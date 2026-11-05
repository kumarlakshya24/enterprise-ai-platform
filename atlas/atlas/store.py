"""SQLite persistence.

Two files, on purpose:

* The workflow store holds the run row, the append-only event log, and checkpoints.
* The effect store is the stand-in for external systems (ledger, email, pager).
  It commits in its own transaction, so a kill between the two files is observable.
"""

from __future__ import annotations

import sqlite3
from typing import Any

from atlas.domain import LeaseHeld, StaleLease
from atlas.jsonutil import canon, digest


def _connect(path: str) -> sqlite3.Connection:
    # FastAPI runs sync endpoints in a worker thread. One connection, explicit transactions.
    conn = sqlite3.connect(path, isolation_level=None, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=FULL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


class EffectStore:
    """External side effects. The unique key is the idempotency key."""

    def __init__(self, path: str) -> None:
        self.path = path
        self.conn = _connect(path)
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS side_effects (
                effect_key TEXT PRIMARY KEY,
                run_id TEXT NOT NULL,
                tool TEXT NOT NULL,
                kind TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                request_hash TEXT NOT NULL,
                created_at REAL NOT NULL
            )
            """
        )
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_side_run ON side_effects(run_id, tool)")

    def close(self) -> None:
        self.conn.close()

    def get(self, key: str) -> dict[str, Any] | None:
        row = self.conn.execute("SELECT * FROM side_effects WHERE effect_key = ?", (key,)).fetchone()
        return _side(row) if row else None

    def commit_effect(
        self,
        *,
        key: str,
        run_id: str,
        tool: str,
        kind: str,
        payload: dict[str, Any],
        created_at: float,
    ) -> tuple[dict[str, Any], bool]:
        """Insert once. Returns (row, created_new). A different payload on the same key conflicts."""
        from atlas.domain import IdempotencyConflict

        request_hash = digest(payload)
        existing = self.get(key)
        if existing is not None:
            if existing["request_hash"] != request_hash:
                raise IdempotencyConflict(key)
            return existing, False
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            again = self.get(key)
            if again is not None:
                self.conn.execute("COMMIT")
                if again["request_hash"] != request_hash:
                    raise IdempotencyConflict(key)
                return again, False
            self.conn.execute(
                """
                INSERT INTO side_effects (effect_key, run_id, tool, kind, payload_json, request_hash, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (key, run_id, tool, kind, canon(payload), request_hash, created_at),
            )
            self.conn.execute("COMMIT")
        except Exception:
            self.conn.execute("ROLLBACK")
            raise
        row = self.get(key)
        assert row is not None
        return row, True

    def counts(self, run_id: str | None = None) -> dict[str, int]:
        if run_id is None:
            rows = self.conn.execute("SELECT tool, COUNT(*) AS n FROM side_effects GROUP BY tool").fetchall()
        else:
            rows = self.conn.execute(
                "SELECT tool, COUNT(*) AS n FROM side_effects WHERE run_id = ? GROUP BY tool",
                (run_id,),
            ).fetchall()
        return {row["tool"]: int(row["n"]) for row in rows}

    def list(self, run_id: str | None = None) -> list[dict[str, Any]]:
        if run_id is None:
            rows = self.conn.execute("SELECT * FROM side_effects ORDER BY created_at, effect_key").fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM side_effects WHERE run_id = ? ORDER BY created_at, effect_key",
                (run_id,),
            ).fetchall()
        return [_side(row) for row in rows]


class Store:
    def __init__(self, path: str) -> None:
        self.path = path
        self.conn = _connect(path)
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS runs (
                id TEXT PRIMARY KEY,
                workflow_id TEXT NOT NULL,
                idempotency_key TEXT NOT NULL UNIQUE,
                status TEXT NOT NULL,
                input_json TEXT NOT NULL,
                output_json TEXT,
                budget_json TEXT NOT NULL,
                cost_usd REAL NOT NULL DEFAULT 0,
                steps INTEGER NOT NULL DEFAULT 0,
                lease_owner TEXT,
                lease_expires_at REAL,
                lease_epoch INTEGER NOT NULL DEFAULT 0,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                error TEXT
            );
            CREATE TABLE IF NOT EXISTS events (
                seq INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL,
                ts REAL NOT NULL,
                type TEXT NOT NULL,
                payload_json TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_events_run_seq ON events(run_id, seq);
            CREATE TABLE IF NOT EXISTS checkpoints (
                run_id TEXT NOT NULL,
                event_seq INTEGER NOT NULL,
                state_json TEXT NOT NULL,
                sha256 TEXT NOT NULL,
                created_at REAL NOT NULL,
                PRIMARY KEY (run_id, event_seq)
            );
            """
        )

    def close(self) -> None:
        self.conn.close()

    def create_run(
        self,
        *,
        run_id: str,
        workflow_id: str,
        idempotency_key: str,
        inputs: dict[str, Any],
        budget: dict[str, Any],
        now: float,
    ) -> None:
        self.conn.execute(
            """
            INSERT INTO runs (
                id, workflow_id, idempotency_key, status, input_json, budget_json,
                cost_usd, steps, lease_epoch, created_at, updated_at
            ) VALUES (?, ?, ?, 'starting', ?, ?, 0, 0, 0, ?, ?)
            """,
            (run_id, workflow_id, idempotency_key, canon(inputs), canon(budget), now, now),
        )

    def find_by_key(self, idempotency_key: str) -> dict[str, Any] | None:
        row = self.conn.execute("SELECT * FROM runs WHERE idempotency_key = ?", (idempotency_key,)).fetchone()
        return _run(row) if row else None

    def get_run(self, run_id: str) -> dict[str, Any]:
        row = self.conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
        if row is None:
            raise KeyError(run_id)
        return _run(row)

    def claim(self, run_id: str, owner: str, now: float, ttl: float) -> int:
        run = self.get_run(run_id)
        expires = run["lease_expires_at"]
        held_by_other = bool(expires and expires > now and run["lease_owner"] not in (None, owner))
        if held_by_other:
            raise LeaseHeld(run_id, str(run["lease_owner"]), float(expires))
        epoch = int(run["lease_epoch"]) + 1
        cur = self.conn.execute(
            """
            UPDATE runs
               SET lease_owner = ?, lease_expires_at = ?, lease_epoch = ?, updated_at = ?
             WHERE id = ? AND lease_epoch = ?
            """,
            (owner, now + ttl, epoch, now, run_id, run["lease_epoch"]),
        )
        if cur.rowcount != 1:
            raise LeaseHeld(run_id, str(run["lease_owner"]), float(expires or 0))
        return epoch

    def expire_lease(self, run_id: str) -> None:
        self.conn.execute("UPDATE runs SET lease_expires_at = 0 WHERE id = ?", (run_id,))

    def append(
        self,
        *,
        run_id: str,
        epoch: int,
        ts: float,
        etype: str,
        payload: dict[str, Any],
        projection: dict[str, Any],
        checkpoint_state: dict[str, Any] | None,
    ) -> int:
        """Append one event and the run projection in a single transaction.

        The write is fenced: it commits only if ``lease_epoch`` is still ``epoch``.
        """
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            row = self.conn.execute("SELECT lease_epoch FROM runs WHERE id = ?", (run_id,)).fetchone()
            if row is None or int(row["lease_epoch"]) != epoch:
                self.conn.execute("ROLLBACK")
                raise StaleLease(run_id, epoch)
            cur = self.conn.execute(
                "INSERT INTO events (run_id, ts, type, payload_json) VALUES (?, ?, ?, ?)",
                (run_id, ts, etype, canon(payload)),
            )
            seq = int(cur.lastrowid)
            cur = self.conn.execute(
                """
                UPDATE runs
                   SET status = ?, cost_usd = ?, steps = ?, output_json = ?, error = ?, updated_at = ?
                 WHERE id = ? AND lease_epoch = ?
                """,
                (
                    projection["status"],
                    projection["cost_usd"],
                    projection["steps"],
                    canon(projection["output"]) if projection.get("output") is not None else None,
                    projection.get("error"),
                    ts,
                    run_id,
                    epoch,
                ),
            )
            if cur.rowcount != 1:
                self.conn.execute("ROLLBACK")
                raise StaleLease(run_id, epoch)
            if checkpoint_state is not None:
                checkpoint_state["last_event_seq"] = seq
                blob = canon(checkpoint_state)
                self.conn.execute(
                    """
                    INSERT OR REPLACE INTO checkpoints (run_id, event_seq, state_json, sha256, created_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (run_id, seq, blob, digest(blob), ts),
                )
            self.conn.execute("COMMIT")
        except StaleLease:
            raise
        except Exception:
            self.conn.execute("ROLLBACK")
            raise
        return seq

    def heartbeat(self, run_id: str, epoch: int, expires_at: float) -> None:
        cur = self.conn.execute(
            "UPDATE runs SET lease_expires_at = ? WHERE id = ? AND lease_epoch = ?",
            (expires_at, run_id, epoch),
        )
        if cur.rowcount != 1:
            raise StaleLease(run_id, epoch)

    def events(self, run_id: str, after_seq: int = 0) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT seq, run_id, ts, type, payload_json FROM events WHERE run_id = ? AND seq > ? ORDER BY seq",
            (run_id, after_seq),
        ).fetchall()
        return [
            {
                "seq": int(row["seq"]),
                "run_id": row["run_id"],
                "ts": row["ts"],
                "type": row["type"],
                "payload": _loads(row["payload_json"]),
            }
            for row in rows
        ]

    def checkpoints(self, run_id: str) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT event_seq, state_json, sha256, created_at FROM checkpoints WHERE run_id = ? ORDER BY event_seq",
            (run_id,),
        ).fetchall()
        return [
            {
                "event_seq": int(row["event_seq"]),
                "state_json": row["state_json"],
                "sha256": row["sha256"],
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    def latest_valid_checkpoint(self, run_id: str) -> dict[str, Any] | None:
        for row in reversed(self.checkpoints(run_id)):
            if digest(row["state_json"]) == row["sha256"]:
                return row
        return None

    def tamper_checkpoint(self, run_id: str, event_seq: int) -> None:
        """Test hook: flip payload bytes and leave the stored hash stale."""
        row = self.conn.execute(
            "SELECT state_json FROM checkpoints WHERE run_id = ? AND event_seq = ?",
            (run_id, event_seq),
        ).fetchone()
        if row is None:
            raise KeyError((run_id, event_seq))
        self.conn.execute(
            "UPDATE checkpoints SET state_json = ? WHERE run_id = ? AND event_seq = ?",
            (row["state_json"] + " ", run_id, event_seq),
        )


def _loads(text: str) -> Any:
    import json

    return json.loads(text)


def _run(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "workflow_id": row["workflow_id"],
        "idempotency_key": row["idempotency_key"],
        "status": row["status"],
        "inputs": _loads(row["input_json"]),
        "output": _loads(row["output_json"]) if row["output_json"] else None,
        "budget": _loads(row["budget_json"]),
        "cost_usd": row["cost_usd"],
        "steps": int(row["steps"]),
        "lease_owner": row["lease_owner"],
        "lease_expires_at": row["lease_expires_at"],
        "lease_epoch": int(row["lease_epoch"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "error": row["error"],
    }


def _side(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "effect_key": row["effect_key"],
        "run_id": row["run_id"],
        "tool": row["tool"],
        "kind": row["kind"],
        "payload": _loads(row["payload_json"]),
        "request_hash": row["request_hash"],
        "created_at": row["created_at"],
    }
