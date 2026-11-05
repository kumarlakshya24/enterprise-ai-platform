"""Demo API and single-page UI. SQLite only. No API keys."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from atlas.baseline import BaselineAgent
from atlas.clock import SystemClock
from atlas.config import Settings
from atlas.domain import CrashInjected, LeaseHeld
from atlas.engine import CrashSpec, Engine
from atlas.guard import build_guard
from atlas.knowledge import build_knowledge
from atlas.llm import MockLLM
from atlas.store import EffectStore, Store

STATIC = Path(__file__).parent / "static" / "index.html"


class RunRequest(BaseModel):
    workflow_id: str
    inputs: dict[str, Any] = Field(default_factory=dict)
    idempotency_key: str | None = None
    crash_after: str | None = None
    auto_approve: bool = False
    budget: dict[str, Any] | None = None


class DecisionRequest(BaseModel):
    decision: str
    actor: str = "morgan"
    crash_after: str | None = None


class BudgetRequest(BaseModel):
    max_steps: int = 20
    max_cost_usd: float = 1.0
    on_exceeded: str = "pause"


class BaselineRequest(BaseModel):
    workflow_id: str = "refund"
    inputs: dict[str, Any] = Field(default_factory=dict)
    crash_after: str | None = "post_ledger:after_remote"


def create_app(db_path: str, effects_path: str, settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    Path(effects_path).parent.mkdir(parents=True, exist_ok=True)
    engine = Engine(
        Store(db_path),
        EffectStore(effects_path),
        llm=MockLLM(),
        guard=build_guard(settings.guard, settings.aegis_base_url),
        knowledge=build_knowledge(settings.knowledge, settings.lumen_base_url, settings.lumen_user_id),
        clock=SystemClock(),
        lease_ttl=settings.lease_seconds,
    )
    app = FastAPI(title="Atlas", version="0.1.0")
    app.state.engine = engine
    app.state.settings = settings

    @app.get("/", response_class=HTMLResponse)
    def index() -> str:
        return STATIC.read_text()

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "guard": settings.guard, "knowledge": settings.knowledge}

    @app.get("/api/workflows")
    def workflows() -> list[dict[str, str]]:
        from atlas.catalog import list_workflows

        return list_workflows()

    @app.post("/api/runs")
    def start_run(body: RunRequest) -> dict[str, Any]:
        key = body.idempotency_key or f"{body.workflow_id}:{_stable(body.inputs)}"
        return _call(
            engine.start,
            body.workflow_id,
            body.inputs,
            idempotency_key=key,
            budget=body.budget,
            crash=CrashSpec.parse(body.crash_after),
            auto_approve=body.auto_approve,
            owner="ui",
        )

    @app.get("/api/runs/{run_id}")
    def get_run(run_id: str) -> dict[str, Any]:
        try:
            return engine.snapshot(run_id)
        except KeyError as exc:
            raise HTTPException(404, "run not found") from exc

    @app.post("/api/runs/{run_id}/decision")
    def decide(run_id: str, body: DecisionRequest) -> dict[str, Any]:
        return _call(
            engine.decide,
            run_id,
            body.decision,
            body.actor,
            crash=CrashSpec.parse(body.crash_after),
            owner="ui",
        )

    @app.post("/api/runs/{run_id}/resume")
    def resume(run_id: str) -> dict[str, Any]:
        return _call(engine.resume, run_id, owner="ui", because_crash=True)

    @app.post("/api/runs/{run_id}/budget")
    def budget(run_id: str, body: BudgetRequest) -> dict[str, Any]:
        return _call(
            engine.raise_budget,
            run_id,
            {"max_steps": body.max_steps, "max_cost_usd": body.max_cost_usd, "on_exceeded": body.on_exceeded},
            owner="ui",
        )

    @app.post("/api/baseline")
    def baseline(body: BaselineRequest) -> dict[str, Any]:
        agent = BaselineAgent(engine.effects, MockLLM(), engine.knowledge)
        crash = CrashSpec.parse(body.crash_after)
        try:
            report = agent.run(body.workflow_id, body.inputs, crash=crash)
        except CrashInjected:
            report = agent.run(body.workflow_id, body.inputs)
        return {
            "engine": "baseline",
            "status": report["status"],
            "effect_counts": report["effect_counts"],
            "steps": report["steps"],
            "recovery": report["recovery"],
            "note": "Single agent, no effect key. A crash replays the whole plan.",
        }

    return app


def _call(fn: Any, *args: Any, **kwargs: Any) -> dict[str, Any]:
    try:
        snap = fn(*args, **kwargs)
    except CrashInjected as exc:
        engine: Engine = fn.__self__
        engine.store.expire_lease(exc.run_id)
        snap = engine.snapshot(exc.run_id)
        snap["crashed"] = True
        snap["crash"] = {"activity_id": exc.activity_id, "phase": exc.phase}
        return snap
    except LeaseHeld as exc:
        raise HTTPException(409, f"run is leased to {exc.owner}") from exc
    except (KeyError, ValueError) as exc:
        raise HTTPException(400, str(exc)) from exc
    snap["crashed"] = False
    return snap


def _stable(payload: dict[str, Any]) -> str:
    import hashlib
    import json

    raw = json.dumps(payload, sort_keys=True, default=str).encode()
    return hashlib.sha256(raw).hexdigest()[:16]


def serve() -> None:
    import uvicorn

    settings = Settings.from_env()
    app = create_app(settings.db_path, settings.effects_path, settings)
    uvicorn.run(app, host=settings.host, port=settings.port)


app = create_app(
    Settings.from_env().db_path,
    Settings.from_env().effects_path,
)
