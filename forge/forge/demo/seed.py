"""Synthetic workspace files. No customer data, no secrets."""

from __future__ import annotations

from pathlib import Path

SUMMARY = "Northwind Robotics Q3 review\nOwner: Alex Morgan\nStatus: on track\nTickets closed: 42\n"
METRICS = '{"tickets": 42, "sla_pct": 99.1}\n'

SEED_FILES = {
    "notes/summary.txt": SUMMARY,
    "data/metrics.json": METRICS,
}


def seed_workspace(workspace: Path) -> None:
    workspace.mkdir(parents=True, exist_ok=True)
    for relative, text in SEED_FILES.items():
        path = workspace / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            path.write_text(text, encoding="utf-8")
