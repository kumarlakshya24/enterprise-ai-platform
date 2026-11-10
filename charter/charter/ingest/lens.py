"""Lens-shaped SLO snapshot.

Targets match Lens `eval/slo.yaml` (availability 0.995, latency 0.99, quality 0.95,
safety 0.999). Status strings are the ones Lens shows on the dashboard: within_budget,
ticket, page. Charter does not recompute burn and does not import Lens.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from charter.config import LENS_SLO_TARGETS


class SloError(Exception):
    pass


@dataclass(frozen=True)
class Objective:
    id: str
    app: str
    target: float
    sli: float
    status: str
    burn_6h: float

    def as_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "app": self.app,
            "target": self.target,
            "sli": self.sli,
            "status": self.status,
            "burn_6h": self.burn_6h,
        }


@dataclass(frozen=True)
class SloSnapshot:
    source: str
    note: str
    window_days: int
    observed_start: str
    observed_end: str
    objectives: tuple[Objective, ...]

    def status(self, objective_id: str) -> str:
        for objective in self.objectives:
            if objective.id == objective_id:
                return objective.status
        return "missing"

    def get(self, objective_id: str) -> Objective | None:
        for objective in self.objectives:
            if objective.id == objective_id:
                return objective
        return None

    def as_dict(self) -> dict[str, object]:
        return {
            "source": self.source,
            "note": self.note,
            "window_days": self.window_days,
            "observed_start": self.observed_start,
            "observed_end": self.observed_end,
            "objectives": [item.as_dict() for item in self.objectives],
        }


def load_slo(path: Path) -> SloSnapshot:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or not isinstance(raw.get("objectives"), list):
        raise SloError("slo snapshot needs an objectives list")
    objectives: list[Objective] = []
    for item in raw["objectives"]:
        if not isinstance(item, dict):
            raise SloError("objective must be an object")
        objective_id = str(item.get("id") or "")
        target = item.get("target")
        sli = item.get("sli")
        status = str(item.get("status") or "")
        if objective_id not in LENS_SLO_TARGETS:
            raise SloError(f"unknown objective {objective_id}")
        if not isinstance(target, int | float) or float(target) != LENS_SLO_TARGETS[objective_id]:
            raise SloError(f"{objective_id} target does not match the Lens contract")
        if not isinstance(sli, int | float):
            raise SloError(f"{objective_id} sli must be a number")
        if status not in ("within_budget", "ticket", "page"):
            raise SloError(f"{objective_id} status {status!r} is not a Lens status")
        burn = item.get("burn_6h", 0)
        if not isinstance(burn, int | float):
            raise SloError(f"{objective_id} burn_6h must be a number")
        objectives.append(
            Objective(
                id=objective_id,
                app=str(item.get("app") or "all"),
                target=float(target),
                sli=float(sli),
                status=status,
                burn_6h=float(burn),
            )
        )
    found = {item.id for item in objectives}
    if found != set(LENS_SLO_TARGETS):
        raise SloError(f"snapshot is missing {sorted(set(LENS_SLO_TARGETS) - found)}")
    return SloSnapshot(
        source=str(raw.get("source") or "lens"),
        note=str(raw.get("note") or ""),
        window_days=int(raw.get("window_days") or 30),
        observed_start=str(raw.get("observed_start") or ""),
        observed_end=str(raw.get("observed_end") or ""),
        objectives=tuple(objectives),
    )


def snapshot_dict(snapshot: SloSnapshot) -> dict[str, Any]:
    return snapshot.as_dict()
