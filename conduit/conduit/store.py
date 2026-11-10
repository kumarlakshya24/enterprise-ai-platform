"""SQLite data plane: the log, the generations, the alias, the tombstones.

One writer. Readers follow the `read` alias, which points at exactly one
generation, and that generation has exactly one model version.
"""

from __future__ import annotations

import json
import sqlite3
import struct
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import cast

from conduit.models import Event, Generation, Incoming, Migration

SCHEMA = """
CREATE TABLE IF NOT EXISTS cdc_events (
    seq INTEGER PRIMARY KEY,
    event_id TEXT UNIQUE NOT NULL,
    op TEXT NOT NULL,
    doc_id TEXT NOT NULL,
    doc_version INTEGER NOT NULL,
    title TEXT NOT NULL,
    text TEXT NOT NULL,
    subject_ids TEXT NOT NULL,
    source_ts TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS consumer_offsets (
    consumer TEXT PRIMARY KEY,
    last_seq INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS generations (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    model_id TEXT NOT NULL,
    model_version TEXT NOT NULL,
    dim INTEGER NOT NULL,
    state TEXT NOT NULL,
    high_water INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS alias (
    name TEXT PRIMARY KEY,
    generation_id INTEGER NOT NULL,
    swapped_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS alias_history (
    id INTEGER PRIMARY KEY,
    generation_id INTEGER NOT NULL,
    at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS docs (
    generation_id INTEGER NOT NULL,
    doc_id TEXT NOT NULL,
    doc_version INTEGER NOT NULL,
    title TEXT NOT NULL,
    PRIMARY KEY (generation_id, doc_id)
);
CREATE TABLE IF NOT EXISTS chunks (
    generation_id INTEGER NOT NULL,
    doc_id TEXT NOT NULL,
    chunk_index INTEGER NOT NULL,
    doc_version INTEGER NOT NULL,
    content_hash TEXT NOT NULL,
    text TEXT NOT NULL,
    embed_text TEXT NOT NULL,
    subject_ids TEXT NOT NULL,
    model_version TEXT NOT NULL,
    vector BLOB NOT NULL,
    PRIMARY KEY (generation_id, doc_id, chunk_index)
);
CREATE TABLE IF NOT EXISTS chunk_subjects (
    generation_id INTEGER NOT NULL,
    subject_id TEXT NOT NULL,
    doc_id TEXT NOT NULL,
    chunk_index INTEGER NOT NULL,
    PRIMARY KEY (generation_id, subject_id, doc_id, chunk_index)
);
CREATE INDEX IF NOT EXISTS chunk_subjects_subject ON chunk_subjects (subject_id);
CREATE TABLE IF NOT EXISTS embedding_cache (
    model_version TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    vector BLOB NOT NULL,
    PRIMARY KEY (model_version, content_hash)
);
CREATE TABLE IF NOT EXISTS tombstones (
    subject_id TEXT PRIMARY KEY,
    requested_at TEXT NOT NULL,
    completed_at TEXT,
    chunks_removed INTEGER NOT NULL DEFAULT 0,
    proof_json TEXT
);
CREATE TABLE IF NOT EXISTS quarantine (
    seq INTEGER PRIMARY KEY,
    event_id TEXT NOT NULL,
    reason TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS event_lag (
    seq INTEGER PRIMARY KEY,
    lag_ms REAL NOT NULL,
    outcome TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS apply_stats (
    id INTEGER PRIMARY KEY,
    seq INTEGER NOT NULL,
    generation_id INTEGER NOT NULL,
    embed_calls INTEGER NOT NULL,
    embed_reused INTEGER NOT NULL,
    chunks_written INTEGER NOT NULL,
    outcome TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS migration (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    state TEXT NOT NULL,
    source_id INTEGER,
    target_id INTEGER,
    started_at TEXT
);
"""


def pack_vector(vector: tuple[float, ...]) -> bytes:
    return struct.pack(f"<{len(vector)}f", *vector)


def unpack_vector(blob: bytes) -> tuple[float, ...]:
    count = len(blob) // 4
    return struct.unpack(f"<{count}f", blob)


class Store:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        if str(self.path) != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path, isolation_level=None, timeout=5.0, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.execute("PRAGMA journal_mode = WAL")
        self.conn.executescript(SCHEMA)
        self._ensure_seed()

    def close(self) -> None:
        self.conn.close()

    @contextmanager
    def transaction(self) -> Iterator[None]:
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            yield
        except Exception:
            self.conn.execute("ROLLBACK")
            raise
        else:
            self.conn.execute("COMMIT")

    def reset(self, *, model_version: str, model_id: str, dim: int, at: str) -> None:
        self.conn.executescript(
            """
            DROP TABLE IF EXISTS apply_stats;
            DROP TABLE IF EXISTS event_lag;
            DROP TABLE IF EXISTS quarantine;
            DROP TABLE IF EXISTS tombstones;
            DROP TABLE IF EXISTS embedding_cache;
            DROP TABLE IF EXISTS chunk_subjects;
            DROP TABLE IF EXISTS chunks;
            DROP TABLE IF EXISTS docs;
            DROP TABLE IF EXISTS alias_history;
            DROP TABLE IF EXISTS alias;
            DROP TABLE IF EXISTS migration;
            DROP TABLE IF EXISTS generations;
            DROP TABLE IF EXISTS consumer_offsets;
            DROP TABLE IF EXISTS cdc_events;
            """
        )
        self.conn.executescript(SCHEMA)
        self._seed(model_version=model_version, model_id=model_id, dim=dim, at=at)

    def _ensure_seed(self) -> None:
        row = self.conn.execute("SELECT 1 FROM alias WHERE name = 'read'").fetchone()
        if row is None:
            self._seed(model_version="emb-v1", model_id="fake-hash", dim=256, at="1970-01-01T00:00:00+00:00")

    def _seed(self, *, model_version: str, model_id: str, dim: int, at: str) -> None:
        generation_id = self.insert_generation(
            name="blue",
            model_id=model_id,
            model_version=model_version,
            dim=dim,
            state="active",
            at=at,
        )
        self.conn.execute(
            "INSERT INTO alias (name, generation_id, swapped_at) VALUES ('read', ?, ?)",
            (generation_id, at),
        )
        self.conn.execute(
            "INSERT INTO alias_history (generation_id, at) VALUES (?, ?)",
            (generation_id, at),
        )
        self.conn.execute(
            "INSERT INTO migration (id, state, source_id, target_id, started_at) VALUES (1, 'idle', NULL, NULL, NULL)"
        )
        self.conn.execute(
            "INSERT INTO consumer_offsets (consumer, last_seq) VALUES ('indexer', 0) ON CONFLICT(consumer) DO NOTHING"
        )

    def insert_generation(
        self,
        *,
        name: str,
        model_id: str,
        model_version: str,
        dim: int,
        state: str,
        at: str,
    ) -> int:
        cursor = self.conn.execute(
            """INSERT INTO generations (name, model_id, model_version, dim, state, high_water, created_at)
               VALUES (?, ?, ?, ?, ?, 0, ?)""",
            (name, model_id, model_version, dim, state, at),
        )
        rowid = cursor.lastrowid
        if rowid is None:
            raise RuntimeError("insert did not return a generation id")
        return int(rowid)

    def append(self, event: Incoming) -> int:
        cursor = self.conn.execute(
            """INSERT INTO cdc_events (event_id, op, doc_id, doc_version, title, text, subject_ids, source_ts)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                event.event_id,
                event.op,
                event.doc_id,
                event.doc_version,
                event.title,
                event.text,
                json.dumps(list(event.subject_ids)),
                event.source_ts,
            ),
        )
        rowid = cursor.lastrowid
        if rowid is None:
            raise RuntimeError("insert did not return an event seq")
        return int(rowid)

    def log_head(self) -> int:
        row = self.conn.execute("SELECT COALESCE(MAX(seq), 0) AS head FROM cdc_events").fetchone()
        return int(row["head"])

    def offset(self, consumer: str = "indexer") -> int:
        row = self.conn.execute(
            "SELECT last_seq FROM consumer_offsets WHERE consumer = ?", (consumer,)
        ).fetchone()
        return int(row["last_seq"]) if row is not None else 0

    def set_offset(self, consumer: str, seq: int) -> None:
        self.conn.execute(
            """INSERT INTO consumer_offsets (consumer, last_seq) VALUES (?, ?)
               ON CONFLICT(consumer) DO UPDATE SET last_seq = excluded.last_seq""",
            (consumer, seq),
        )

    def next_event(self, after_seq: int) -> Event | None:
        row = self.conn.execute(
            "SELECT * FROM cdc_events WHERE seq > ? ORDER BY seq ASC LIMIT 1",
            (after_seq,),
        ).fetchone()
        return _event(row) if row is not None else None

    def event_by_seq(self, seq: int) -> Event | None:
        row = self.conn.execute("SELECT * FROM cdc_events WHERE seq = ?", (seq,)).fetchone()
        return _event(row) if row is not None else None

    def events_between(self, after_seq: int, through_seq: int, limit: int) -> list[Event]:
        rows = self.conn.execute(
            """SELECT * FROM cdc_events WHERE seq > ? AND seq <= ? ORDER BY seq ASC LIMIT ?""",
            (after_seq, through_seq, limit),
        ).fetchall()
        return [_event(row) for row in rows]

    def recent_events(self, limit: int = 12) -> list[Event]:
        rows = self.conn.execute("SELECT * FROM cdc_events ORDER BY seq DESC LIMIT ?", (limit,)).fetchall()
        return [_event(row) for row in reversed(rows)]

    def generation(self, generation_id: int) -> Generation:
        row = self.conn.execute("SELECT * FROM generations WHERE id = ?", (generation_id,)).fetchone()
        if row is None:
            raise KeyError(generation_id)
        return _generation(row)

    def generation_by_name(self, name: str) -> Generation | None:
        row = self.conn.execute(
            "SELECT * FROM generations WHERE name = ? ORDER BY id DESC LIMIT 1",
            (name,),
        ).fetchone()
        return _generation(row) if row is not None else None

    def generations(self) -> list[Generation]:
        rows = self.conn.execute("SELECT * FROM generations ORDER BY id ASC").fetchall()
        return [_generation(row) for row in rows]

    def active(self) -> Generation:
        row = self.conn.execute(
            """SELECT g.* FROM generations g
               JOIN alias a ON a.generation_id = g.id
               WHERE a.name = 'read'"""
        ).fetchone()
        if row is None:
            raise RuntimeError("read alias is missing")
        return _generation(row)

    def set_alias(self, generation_id: int, at: str) -> None:
        self.conn.execute(
            "UPDATE alias SET generation_id = ?, swapped_at = ? WHERE name = 'read'", (generation_id, at)
        )
        self.conn.execute("INSERT INTO alias_history (generation_id, at) VALUES (?, ?)", (generation_id, at))

    def history(self) -> list[int]:
        rows = self.conn.execute("SELECT generation_id FROM alias_history ORDER BY id ASC").fetchall()
        return [int(row["generation_id"]) for row in rows]

    def set_state(self, generation_id: int, state: str) -> None:
        self.conn.execute("UPDATE generations SET state = ? WHERE id = ?", (state, generation_id))

    def set_high_water(self, generation_id: int, seq: int) -> None:
        # Checkpoints only move forward. A replay must not rewind a generation
        # that has already applied a later prefix.
        self.conn.execute(
            "UPDATE generations SET high_water = ? WHERE id = ? AND high_water < ?",
            (seq, generation_id, seq),
        )

    def doc_version(self, generation_id: int, doc_id: str) -> int | None:
        row = self.conn.execute(
            "SELECT doc_version FROM docs WHERE generation_id = ? AND doc_id = ?",
            (generation_id, doc_id),
        ).fetchone()
        return int(row["doc_version"]) if row is not None else None

    def delete_doc(self, generation_id: int, doc_id: str) -> None:
        self.conn.execute(
            "DELETE FROM chunk_subjects WHERE generation_id = ? AND doc_id = ?", (generation_id, doc_id)
        )
        self.conn.execute(
            "DELETE FROM chunks WHERE generation_id = ? AND doc_id = ?", (generation_id, doc_id)
        )
        self.conn.execute("DELETE FROM docs WHERE generation_id = ? AND doc_id = ?", (generation_id, doc_id))

    def write_doc(
        self,
        *,
        generation_id: int,
        doc_id: str,
        doc_version: int,
        title: str,
        model_version: str,
        rows: list[tuple[int, str, str, str, tuple[str, ...], tuple[float, ...]]],
    ) -> None:
        self.delete_doc(generation_id, doc_id)
        self.conn.execute(
            """INSERT INTO docs (generation_id, doc_id, doc_version, title) VALUES (?, ?, ?, ?)""",
            (generation_id, doc_id, doc_version, title),
        )
        for index, text, embed_text, content, subjects, vector in rows:
            self.conn.execute(
                """INSERT INTO chunks (generation_id, doc_id, chunk_index, doc_version, content_hash,
                       text, embed_text, subject_ids, model_version, vector)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    generation_id,
                    doc_id,
                    index,
                    doc_version,
                    content,
                    text,
                    embed_text,
                    json.dumps(list(subjects)),
                    model_version,
                    pack_vector(vector),
                ),
            )
            for subject_id in subjects:
                self.conn.execute(
                    """INSERT INTO chunk_subjects (generation_id, subject_id, doc_id, chunk_index)
                       VALUES (?, ?, ?, ?)""",
                    (generation_id, subject_id, doc_id, index),
                )

    def cache_get(self, model_version: str, content: str) -> tuple[float, ...] | None:
        row = self.conn.execute(
            "SELECT vector FROM embedding_cache WHERE model_version = ? AND content_hash = ?",
            (model_version, content),
        ).fetchone()
        return unpack_vector(cast(bytes, row["vector"])) if row is not None else None

    def cache_put(self, model_version: str, content: str, vector: tuple[float, ...]) -> None:
        self.conn.execute(
            """INSERT INTO embedding_cache (model_version, content_hash, vector) VALUES (?, ?, ?)
               ON CONFLICT(model_version, content_hash) DO UPDATE SET vector = excluded.vector""",
            (model_version, content, pack_vector(vector)),
        )

    def drop_unused_hashes(self, hashes: set[str]) -> int:
        dropped = 0
        for content in hashes:
            used = self.conn.execute(
                "SELECT 1 FROM chunks WHERE content_hash = ? LIMIT 1", (content,)
            ).fetchone()
            if used is None:
                cursor = self.conn.execute("DELETE FROM embedding_cache WHERE content_hash = ?", (content,))
                dropped += cursor.rowcount
        return dropped

    def record_lag(self, seq: int, lag_ms: float, outcome: str) -> None:
        self.conn.execute(
            """INSERT INTO event_lag (seq, lag_ms, outcome) VALUES (?, ?, ?)
               ON CONFLICT(seq) DO UPDATE SET lag_ms = excluded.lag_ms, outcome = excluded.outcome""",
            (seq, lag_ms, outcome),
        )

    def record_apply(
        self,
        seq: int,
        generation_id: int,
        embed_calls: int,
        embed_reused: int,
        chunks_written: int,
        outcome: str,
    ) -> None:
        self.conn.execute(
            """INSERT INTO apply_stats (seq, generation_id, embed_calls, embed_reused, chunks_written, outcome)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (seq, generation_id, embed_calls, embed_reused, chunks_written, outcome),
        )

    def quarantine(self, event: Event, reason: str) -> None:
        self.conn.execute(
            "INSERT INTO quarantine (seq, event_id, reason) VALUES (?, ?, ?) ON CONFLICT(seq) DO UPDATE SET reason = excluded.reason",
            (event.seq, event.event_id, reason),
        )

    def clear_quarantine(self, seq: int) -> None:
        self.conn.execute("DELETE FROM quarantine WHERE seq = ?", (seq,))

    def quarantine_rows(self) -> list[sqlite3.Row]:
        return list(self.conn.execute("SELECT * FROM quarantine ORDER BY seq ASC").fetchall())

    def lag_values(self) -> list[float]:
        rows = self.conn.execute("SELECT lag_ms FROM event_lag ORDER BY seq ASC").fetchall()
        return [float(row["lag_ms"]) for row in rows]

    def embed_totals(self) -> tuple[int, int]:
        row = self.conn.execute(
            "SELECT COALESCE(SUM(embed_calls), 0) AS calls, COALESCE(SUM(embed_reused), 0) AS reused FROM apply_stats"
        ).fetchone()
        return int(row["calls"]), int(row["reused"])

    def migration(self) -> Migration:
        row = self.conn.execute("SELECT * FROM migration WHERE id = 1").fetchone()
        if row is None:
            return Migration("idle")
        source = row["source_id"]
        target = row["target_id"]
        return Migration(
            state=str(row["state"]),
            source_id=int(source) if source is not None else None,
            target_id=int(target) if target is not None else None,
            started_at=str(row["started_at"]) if row["started_at"] is not None else None,
        )

    def set_migration(
        self, state: str, source_id: int | None, target_id: int | None, started_at: str | None
    ) -> None:
        self.conn.execute(
            """INSERT INTO migration (id, state, source_id, target_id, started_at) VALUES (1, ?, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET state = excluded.state, source_id = excluded.source_id,
                 target_id = excluded.target_id, started_at = excluded.started_at""",
            (state, source_id, target_id, started_at),
        )

    def tombstone_ids(self) -> set[str]:
        rows = self.conn.execute("SELECT subject_id FROM tombstones").fetchall()
        return {str(row["subject_id"]) for row in rows}

    def add_tombstone(self, subject_id: str, at: str) -> None:
        self.conn.execute(
            """INSERT INTO tombstones (subject_id, requested_at) VALUES (?, ?)
               ON CONFLICT(subject_id) DO NOTHING""",
            (subject_id, at),
        )

    def finish_tombstone(self, subject_id: str, at: str, removed: int, proof: dict[str, object]) -> None:
        self.conn.execute(
            """UPDATE tombstones SET completed_at = ?, chunks_removed = ?, proof_json = ? WHERE subject_id = ?""",
            (at, removed, json.dumps(proof), subject_id),
        )

    def proof_for(self, subject_id: str) -> dict[str, object] | None:
        row = self.conn.execute(
            "SELECT proof_json FROM tombstones WHERE subject_id = ?", (subject_id,)
        ).fetchone()
        if row is None or row["proof_json"] is None:
            return None
        loaded = json.loads(str(row["proof_json"]))
        return loaded if isinstance(loaded, dict) else None

    def latest_proof(self) -> dict[str, object] | None:
        row = self.conn.execute(
            """SELECT proof_json FROM tombstones WHERE proof_json IS NOT NULL
               ORDER BY completed_at DESC LIMIT 1"""
        ).fetchone()
        if row is None:
            return None
        loaded = json.loads(str(row["proof_json"]))
        return loaded if isinstance(loaded, dict) else None

    def chunks_for_subject(self, subject_id: str) -> list[sqlite3.Row]:
        return list(
            self.conn.execute(
                """SELECT c.generation_id, c.doc_id, c.chunk_index, c.content_hash, c.text, c.model_version
                   FROM chunks c
                   JOIN chunk_subjects s
                     ON s.generation_id = c.generation_id AND s.doc_id = c.doc_id AND s.chunk_index = c.chunk_index
                   WHERE s.subject_id = ?""",
                (subject_id,),
            ).fetchall()
        )

    def delete_subject_chunks(self, subject_id: str) -> int:
        rows = self.chunks_for_subject(subject_id)
        removed = 0
        seen: set[tuple[int, str, int]] = set()
        for row in rows:
            key = (int(row["generation_id"]), str(row["doc_id"]), int(row["chunk_index"]))
            if key in seen:
                continue
            seen.add(key)
            self.conn.execute(
                "DELETE FROM chunk_subjects WHERE generation_id = ? AND doc_id = ? AND chunk_index = ?",
                key,
            )
            self.conn.execute(
                "DELETE FROM chunks WHERE generation_id = ? AND doc_id = ? AND chunk_index = ?",
                key,
            )
            removed += 1
        return removed

    def subject_chunk_count(self, subject_id: str, generation_id: int | None = None) -> int:
        if generation_id is None:
            row = self.conn.execute(
                "SELECT COUNT(*) AS n FROM chunk_subjects WHERE subject_id = ?",
                (subject_id,),
            ).fetchone()
        else:
            row = self.conn.execute(
                "SELECT COUNT(*) AS n FROM chunk_subjects WHERE subject_id = ? AND generation_id = ?",
                (subject_id, generation_id),
            ).fetchone()
        return int(row["n"])

    def count_like(self, needle: str) -> dict[str, int]:
        pattern = f"%{needle}%"
        chunks = self.conn.execute(
            "SELECT COUNT(*) AS n FROM chunks WHERE text LIKE ? OR embed_text LIKE ?",
            (pattern, pattern),
        ).fetchone()
        events = self.conn.execute(
            "SELECT COUNT(*) AS n FROM cdc_events WHERE text LIKE ? OR title LIKE ?",
            (pattern, pattern),
        ).fetchone()
        docs = self.conn.execute("SELECT COUNT(*) AS n FROM docs WHERE title LIKE ?", (pattern,)).fetchone()
        return {"chunks": int(chunks["n"]), "events": int(events["n"]), "docs": int(docs["n"])}

    def generation_counts(self, generation_id: int) -> tuple[int, int]:
        chunks = self.conn.execute(
            "SELECT COUNT(*) AS n FROM chunks WHERE generation_id = ?", (generation_id,)
        ).fetchone()
        docs = self.conn.execute(
            "SELECT COUNT(*) AS n FROM docs WHERE generation_id = ?", (generation_id,)
        ).fetchone()
        return int(chunks["n"]), int(docs["n"])

    def model_versions(self, generation_id: int) -> set[str]:
        rows = self.conn.execute(
            "SELECT DISTINCT model_version FROM chunks WHERE generation_id = ?",
            (generation_id,),
        ).fetchall()
        return {str(row["model_version"]) for row in rows}

    def iter_vectors(self, generation_id: int) -> list[tuple[str, str, int, str, tuple[float, ...]]]:
        rows = self.conn.execute(
            "SELECT doc_id, text, chunk_index, embed_text, vector FROM chunks WHERE generation_id = ?",
            (generation_id,),
        ).fetchall()
        return [
            (
                str(row["doc_id"]),
                str(row["text"]),
                int(row["chunk_index"]),
                str(row["embed_text"]),
                unpack_vector(cast(bytes, row["vector"])),
            )
            for row in rows
        ]

    def embedded_chars(self, generation_id: int) -> tuple[int, int]:
        row = self.conn.execute(
            "SELECT COALESCE(SUM(LENGTH(embed_text)), 0) AS chars, COUNT(DISTINCT doc_id) AS docs FROM chunks WHERE generation_id = ?",
            (generation_id,),
        ).fetchone()
        return int(row["chars"]), int(row["docs"])

    def doc_ids(self, generation_id: int) -> set[str]:
        rows = self.conn.execute(
            "SELECT doc_id FROM docs WHERE generation_id = ?", (generation_id,)
        ).fetchall()
        return {str(row["doc_id"]) for row in rows}

    def purge_generation(self, generation_id: int) -> None:
        self.conn.execute("DELETE FROM chunk_subjects WHERE generation_id = ?", (generation_id,))
        self.conn.execute("DELETE FROM chunks WHERE generation_id = ?", (generation_id,))
        self.conn.execute("DELETE FROM docs WHERE generation_id = ?", (generation_id,))
        self.conn.execute("DELETE FROM generations WHERE id = ?", (generation_id,))

    def update_event_text(self, seq: int, text: str, title: str) -> None:
        self.conn.execute("UPDATE cdc_events SET text = ?, title = ? WHERE seq = ?", (text, title, seq))

    def scrub_doc_titles(self, name: str, email: str) -> None:
        rows = self.conn.execute("SELECT generation_id, doc_id, title FROM docs").fetchall()
        for row in rows:
            title = str(row["title"])
            updated = title
            if name and name.lower() in updated.lower():
                updated = "[erased]"
            if email and email.lower() in updated.lower():
                updated = "[erased]"
            if updated != title:
                self.conn.execute(
                    "UPDATE docs SET title = ? WHERE generation_id = ? AND doc_id = ?",
                    (updated, int(row["generation_id"]), str(row["doc_id"])),
                )

    def events_touching(self, subject_id: str, name: str, email: str) -> list[Event]:
        rows = self.conn.execute("SELECT * FROM cdc_events ORDER BY seq ASC").fetchall()
        matched: list[Event] = []
        needle_name = name.lower()
        needle_email = email.lower()
        token = f"[PERSON:{subject_id}]".lower()
        for row in rows:
            event = _event(row)
            blob = f"{event.title}\n{event.text}".lower()
            declared = subject_id in event.subject_ids
            if declared or needle_name in blob or needle_email in blob or token in blob:
                matched.append(event)
        return matched


def _event(row: sqlite3.Row) -> Event:
    subjects = json.loads(str(row["subject_ids"]))
    if not isinstance(subjects, list):
        subjects = []
    return Event(
        seq=int(row["seq"]),
        event_id=str(row["event_id"]),
        op=str(row["op"]),
        doc_id=str(row["doc_id"]),
        doc_version=int(row["doc_version"]),
        title=str(row["title"]),
        text=str(row["text"]),
        subject_ids=tuple(str(item) for item in subjects),
        source_ts=str(row["source_ts"]),
    )


def _generation(row: sqlite3.Row) -> Generation:
    return Generation(
        id=int(row["id"]),
        name=str(row["name"]),
        model_id=str(row["model_id"]),
        model_version=str(row["model_version"]),
        dim=int(row["dim"]),
        state=str(row["state"]),
        high_water=int(row["high_water"]),
    )
