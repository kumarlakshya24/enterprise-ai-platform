"""Demo UI and the small JSON API the page calls.

Quality numbers come from the saved report. A slider changes the scenario, then
the same metrics are scored again. It does not resimulate the labeled set.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from arena import __version__
from arena.decide import decide, render_memo, scenario_from_item
from arena.ports import probe_lumen, probe_switchboard
from arena.score import grade
from arena.settings import Settings
from arena.world import World, load_world

STATIC = Path(__file__).resolve().parent / "static"


class DecideIn(BaseModel):
    scenario_id: str | None = None
    monthly_requests: int | None = Field(default=None, ge=1, le=50_000_000)
    change_rate: str | None = None
    citations_required: bool | None = None
    latency_slo_ms: float | None = Field(default=None, gt=0, le=60_000)
    monthly_budget_usd: float | None = Field(default=None, gt=0, le=1_000_000)
    scope: str | None = None


class CompareIn(BaseModel):
    question_id: str = Field(min_length=1, max_length=80)


def create_app(
    settings: Settings | None = None,
    world: World | None = None,
    report: dict[str, Any] | None = None,
) -> FastAPI:
    settings = settings or Settings.from_env()
    world = world or load_world(settings)
    if report is None and settings.report_path.exists():
        report = json.loads(settings.report_path.read_text(encoding="utf-8"))

    app = FastAPI(title="Arena", version=__version__)
    app.state.settings = settings
    app.state.world = world
    app.state.report = report
    if STATIC.exists():
        app.mount("/static", StaticFiles(directory=STATIC), name="static")

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(STATIC / "index.html")

    @app.get("/healthz")
    def healthz() -> dict[str, object]:
        saved = app.state.report
        return {
            "status": "ok",
            "version": __version__,
            "freeze_date": world.meta["freeze_date"],
            "domain": world.meta["domain"],
            "report": saved is not None,
            "report_stale": bool(saved) and saved.get("corpus_sha256") != world.sha,
            "lumen": "http" if settings.lumen_url else "stub",
            "switchboard": "http" if settings.switchboard_url else "stub",
        }

    @app.get("/v1/report")
    def get_report() -> dict[str, object]:
        saved = _report_or_404(app)
        return {
            "source": "saved",
            "stale": saved.get("corpus_sha256") != world.sha,
            "report": saved,
        }

    @app.get("/v1/questions")
    def questions() -> dict[str, object]:
        return {
            "questions": [
                {
                    "id": item.id,
                    "split": item.split,
                    "question": item.question,
                    "fact_ids": list(item.fact_ids),
                    "refuse": item.refuse,
                }
                for item in world.items
                if item.split != "train"
            ]
        }

    @app.post("/v1/decide")
    def decide_route(body: DecideIn) -> dict[str, object]:
        saved = _report_or_404(app)
        scenario, overrides = _merge_scenario(world, body)
        if body.scenario_id and not overrides:
            for existing in saved["scenarios"]:
                if existing["id"] == body.scenario_id:
                    return {"source": "saved", "decision": existing}
        overhead = {
            arm: float(saved["overhead_ms"][arm]["p50"]) for arm in ("prompt", "rag", "lora", "distilled")
        }
        decision = decide(saved["arms"], scenario, world.price, world.policy, overhead)
        decision["memo_md"] = render_memo(
            decision,
            {
                "domain": world.meta["domain"],
                "freeze_date": world.meta["freeze_date"],
                "policy_version": str(world.policy["version"]),
            },
        )
        return {"source": "saved-metrics", "decision": decision}

    @app.post("/v1/compare")
    def compare(body: CompareIn) -> dict[str, object]:
        item = world.by_id.get(body.question_id)
        if item is None or item.split == "train":
            raise HTTPException(status_code=404, detail="unknown question")
        live = {
            "prompt": world.prompt.answer(item.question),
            "rag": world.rag_current.answer(item.question),
            "lora": world.lora.answer(item.question),
            "distilled": world.distilled.answer(item.question),
        }
        arms = {}
        for name, answer in live.items():
            arms[name] = {
                **answer.public(),
                "reason_current": grade(item, answer, world.facts, "current").reason,
                "reason_freeze": grade(item, answer, world.facts, "freeze").reason,
            }
        return {
            "id": item.id,
            "split": item.split,
            "question": item.question,
            "fact_ids": list(item.fact_ids),
            "refuse": item.refuse,
            "arms": arms,
            "note": "RAG is on the current index. The adapter and the student still answer from the freeze.",
        }

    @app.get("/v1/pipeline")
    def pipeline() -> dict[str, object]:
        saved = app.state.report or {}
        return {"pipeline": world.pipeline_public(), "counts": saved.get("counts") or {}}

    @app.get("/v1/ports")
    def ports() -> dict[str, object]:
        return {
            "lumen": probe_lumen(settings.lumen_url),
            "switchboard": probe_switchboard(settings.switchboard_url, world.serving),
        }

    return app


def _report_or_404(app: FastAPI) -> dict[str, Any]:
    saved = app.state.report
    if not saved:
        raise HTTPException(status_code=404, detail="no saved report; run make eval")
    return saved


def _merge_scenario(world: World, body: DecideIn) -> tuple[dict[str, Any], bool]:
    base: dict[str, Any] | None = None
    if body.scenario_id:
        for scenario in world.scenarios:
            if scenario["id"] == body.scenario_id:
                base = dict(scenario)
                break
        if base is None:
            raise HTTPException(status_code=404, detail=f"unknown scenario {body.scenario_id}")
    else:
        base = dict(world.scenarios[0])
        base.pop("id", None)
        base.pop("expect", None)
        base.pop("title", None)
    overrides = False
    for field in (
        "monthly_requests",
        "change_rate",
        "citations_required",
        "latency_slo_ms",
        "monthly_budget_usd",
        "scope",
    ):
        value = getattr(body, field)
        if value is not None:
            base[field] = value
            overrides = True
    if overrides:
        base.pop("expect", None)
        base["id"] = None
        base["title"] = "Custom scenario"
    try:
        return scenario_from_item(base), overrides
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
