"""Decision log. SQLite, one file, redacted preview only. No raw prompt."""

from __future__ import annotations

import json
import sqlite3
import threading
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS decisions (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    policy_version TEXT NOT NULL,
    task TEXT NOT NULL,
    complexity REAL NOT NULL,
    sensitivity TEXT NOT NULL,
    prompt_sha256 TEXT NOT NULL,
    prompt_preview TEXT NOT NULL,
    chosen_model TEXT,
    outcome TEXT NOT NULL,
    cost_usd REAL NOT NULL,
    premium_cost_usd REAL NOT NULL,
    simulated_latency_ms REAL NOT NULL,
    router_overhead_ms REAL NOT NULL,
    degraded INTEGER NOT NULL,
    dry_run INTEGER NOT NULL,
    payload_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_decisions_created ON decisions(created_at);
"""


class Store:
    def __init__(self, path: str) -> None:
        self.path = path
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def save(self, record: dict[str, Any]) -> None:
        features = record["features"]
        timing = record["timing"]
        comparison = record["comparison"]
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO decisions (
                    id, created_at, policy_version, task, complexity, sensitivity,
                    prompt_sha256, prompt_preview, chosen_model, outcome, cost_usd,
                    premium_cost_usd, simulated_latency_ms, router_overhead_ms,
                    degraded, dry_run, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record["id"],
                    record["created_at"],
                    record["policy"]["version_id"],
                    features["task"],
                    features["complexity"],
                    features["sensitivity"],
                    record["prompt_sha256"],
                    record["prompt_preview"],
                    record["chosen_model"],
                    record["outcome"],
                    comparison["spend_usd"],
                    comparison["always_premium_cost_usd"],
                    timing["simulated_latency_ms"],
                    timing["router_overhead_ms"],
                    1 if record["degraded"] else 0,
                    1 if record["dry_run"] else 0,
                    json.dumps(record, separators=(",", ":")),
                ),
            )
            self._conn.commit()

    def get(self, decision_id: str) -> dict[str, Any] | None:
        row = self._conn.execute("SELECT payload_json FROM decisions WHERE id = ?", (decision_id,)).fetchone()
        if row is None:
            return None
        return json.loads(row["payload_json"])

    def recent(self, limit: int = 20) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            """
            SELECT id, created_at, policy_version, task, sensitivity, chosen_model,
                   outcome, cost_usd, simulated_latency_ms, router_overhead_ms,
                   degraded, dry_run, prompt_preview
            FROM decisions
            ORDER BY created_at DESC, rowid DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [dict(row) for row in rows]

    def stats(self) -> dict[str, Any]:
        rows = self._conn.execute(
            """
            SELECT chosen_model, outcome, cost_usd, premium_cost_usd,
                   simulated_latency_ms, router_overhead_ms, degraded
            FROM decisions
            WHERE dry_run = 0
            """
        ).fetchall()
        if not rows:
            return empty_stats()
        by_model: dict[str, int] = {}
        by_outcome: dict[str, int] = {}
        spend = 0.0
        premium = 0.0
        simulated: list[float] = []
        overhead: list[float] = []
        fallbacks = 0
        degraded = 0
        for row in rows:
            model = row["chosen_model"] or "(none)"
            by_model[model] = by_model.get(model, 0) + 1
            by_outcome[row["outcome"]] = by_outcome.get(row["outcome"], 0) + 1
            spend += row["cost_usd"]
            premium += row["premium_cost_usd"]
            simulated.append(row["simulated_latency_ms"])
            overhead.append(row["router_overhead_ms"])
            if row["outcome"] == "fallback":
                fallbacks += 1
            if row["degraded"]:
                degraded += 1
        savings = premium - spend
        count = len(rows)
        return {
            "requests": count,
            "dry_runs_excluded": True,
            "by_model": by_model,
            "by_outcome": by_outcome,
            "fallback_rate": round(fallbacks / count, 4),
            "degraded": degraded,
            "spend_usd": round(spend, 6),
            "always_premium_cost_usd": round(premium, 6),
            "savings_usd": round(savings, 6),
            "savings_pct": round(100 * savings / premium, 2) if premium else 0.0,
            "simulated_latency_ms": _pcts(simulated),
            "router_overhead_ms": _pcts(overhead),
            "note": (
                "Spend and latency use the catalog. Router overhead is wall clock "
                "for classify, score, mock, and the SQLite append. Dry-runs are excluded."
            ),
        }

    def reset(self) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM decisions")
            self._conn.commit()


def empty_stats() -> dict[str, Any]:
    return {
        "requests": 0,
        "dry_runs_excluded": True,
        "by_model": {},
        "by_outcome": {},
        "fallback_rate": 0.0,
        "degraded": 0,
        "spend_usd": 0.0,
        "always_premium_cost_usd": 0.0,
        "savings_usd": 0.0,
        "savings_pct": 0.0,
        "simulated_latency_ms": {"p50": 0.0, "p95": 0.0},
        "router_overhead_ms": {"p50": 0.0, "p95": 0.0},
        "note": (
            "Spend and latency use the catalog. Router overhead is wall clock "
            "for classify, score, mock, and the SQLite append. Dry-runs are excluded."
        ),
    }


def percentile(values: list[float], pct: float) -> float:
    """Linear interpolation between nearest ranks. pct is 0-100."""
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return float(ordered[0])
    rank = (len(ordered) - 1) * (pct / 100)
    low = int(rank)
    high = min(low + 1, len(ordered) - 1)
    weight = rank - low
    return float(ordered[low] * (1 - weight) + ordered[high] * weight)


def _pcts(values: list[float]) -> dict[str, float]:
    return {
        "p50": round(percentile(values, 50), 3),
        "p95": round(percentile(values, 95), 3),
    }
