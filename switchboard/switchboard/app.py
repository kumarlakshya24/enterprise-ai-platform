"""HTTP API and the demo UI."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from switchboard import __version__
from switchboard.demo_data import public_scenarios
from switchboard.pipeline import RouteRequest, route
from switchboard.policy import Policy, PolicyError
from switchboard.provider import Fault
from switchboard.runtime import Runtime
from switchboard.settings import Settings, load_settings

STATIC = Path(__file__).resolve().parent / "static"
log = logging.getLogger("switchboard")

TaskName = Literal["chat", "code", "summarize", "extract", "math"]
SensitivityName = Literal["public", "internal", "confidential", "restricted"]
FaultMode = Literal["timeout", "error", "low_quality"]


class FaultIn(BaseModel):
    model: str
    mode: FaultMode


class RouteIn(BaseModel):
    prompt: str = Field(min_length=1, max_length=20000)
    policy: str | None = None
    budget_usd: float | None = Field(default=None, gt=0, le=10)
    latency_slo_ms: float | None = Field(default=None, gt=0, le=120_000)
    sensitivity: SensitivityName | None = None
    task: TaskName | None = None
    fault: FaultIn | None = None
    dry_run: bool = False


class CompareIn(BaseModel):
    prompt: str = Field(min_length=1, max_length=20000)
    policies: list[str] | None = None
    budget_usd: float | None = Field(default=None, gt=0, le=10)
    latency_slo_ms: float | None = Field(default=None, gt=0, le=120_000)
    sensitivity: SensitivityName | None = None
    fault: FaultIn | None = None


class ActiveIn(BaseModel):
    name: str


class DryRunIn(BaseModel):
    prompt: str = Field(min_length=1, max_length=20000)
    name: str | None = None
    yaml: str | None = None
    budget_usd: float | None = Field(default=None, gt=0, le=10)
    latency_slo_ms: float | None = Field(default=None, gt=0, le=120_000)


def create_app(settings: Settings | None = None, runtime: Runtime | None = None) -> FastAPI:
    settings = settings or (runtime.settings if runtime else load_settings())
    logging.basicConfig(level=settings.log_level, format="%(levelname)s %(name)s %(message)s")
    runtime = runtime or Runtime(settings)
    app = FastAPI(title="Switchboard", version=__version__)
    app.state.runtime = runtime
    app.mount("/static", StaticFiles(directory=STATIC), name="static")

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(STATIC / "index.html")

    @app.get("/healthz")
    def healthz() -> dict[str, object]:
        return {
            "status": "ok",
            "version": __version__,
            "policy": runtime.active,
            "models": list(runtime.catalog.order),
            "store": "sqlite",
            "fault_injection": settings.fault_injection,
        }

    @app.get("/v1/catalog")
    def catalog() -> dict[str, object]:
        return runtime.catalog.public()

    @app.get("/v1/policies")
    def policies() -> dict[str, object]:
        return {
            "active": runtime.active,
            "policies": [policy.public() for policy in runtime.policies.values()],
        }

    @app.get("/v1/policies/{name}")
    def policy_detail(name: str) -> dict[str, object]:
        return _policy_or_404(runtime, name).public()

    @app.put("/v1/policies/active")
    def activate(body: ActiveIn) -> dict[str, object]:
        _demo_or_404(runtime)
        try:
            policy = runtime.set_active(body.name)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=f"unknown policy {body.name}") from exc
        log.info("active policy %s", policy.version_id)
        return {"active": policy.name, "version_id": policy.version_id}

    @app.post("/v1/policies/dry-run")
    def dry_run(body: DryRunIn) -> dict[str, object]:
        policy = _resolve_dry_policy(runtime, body)
        return _execute(runtime, body.prompt, policy, body, dry_run=True)

    @app.post("/v1/route")
    def route_request(body: RouteIn) -> dict[str, object]:
        policy = _policy_or_404(runtime, body.policy)
        return _execute(runtime, body.prompt, policy, body, dry_run=body.dry_run)

    @app.post("/v1/compare")
    def compare(body: CompareIn) -> dict[str, object]:
        names = body.policies or ["default", "cost-saver", "latency-first", "quality-first"]
        results = []
        for name in names:
            policy = _policy_or_404(runtime, name)
            results.append(_execute(runtime, body.prompt, policy, body, dry_run=False))
        spend = sum(item["comparison"]["spend_usd"] for item in results)
        premium = sum(item["comparison"]["always_premium_cost_usd"] for item in results)
        return {
            "results": results,
            "totals": {
                "spend_usd": round(spend, 6),
                "always_premium_cost_usd": round(premium, 6),
                "savings_usd": round(premium - spend, 6),
            },
        }

    @app.get("/v1/stats")
    def stats() -> dict[str, object]:
        return runtime.store.stats()

    @app.get("/v1/decisions")
    def decisions(limit: int = 20) -> dict[str, object]:
        return {"decisions": runtime.store.recent(max(1, min(limit, 100)))}

    @app.get("/v1/decisions/{decision_id}")
    def decision(decision_id: str) -> dict[str, object]:
        found = runtime.store.get(decision_id)
        if found is None:
            raise HTTPException(status_code=404, detail="decision not found")
        return found

    @app.get("/v1/scenarios")
    def scenarios() -> dict[str, object]:
        return {"scenarios": public_scenarios()}

    @app.post("/v1/demo/reset")
    def reset() -> dict[str, str]:
        _demo_or_404(runtime)
        runtime.store.reset()
        return {"status": "reset"}

    return app


def _policy_or_404(runtime: Runtime, name: str | None) -> Policy:
    try:
        return runtime.policy(name)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"unknown policy {name}") from exc


def _demo_or_404(runtime: Runtime) -> None:
    if not runtime.settings.demo_controls:
        raise HTTPException(status_code=404, detail="demo controls are disabled")


def _resolve_dry_policy(runtime: Runtime, body: DryRunIn) -> Policy:
    if body.yaml and body.name:
        raise HTTPException(status_code=422, detail="pass a policy name or YAML, not both")
    if body.yaml:
        try:
            return runtime.parse_candidate(body.yaml)
        except PolicyError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _policy_or_404(runtime, body.name)


def _execute(
    runtime: Runtime,
    prompt: str,
    policy: Policy,
    body: object,
    *,
    dry_run: bool,
) -> dict[str, object]:
    fault_body = getattr(body, "fault", None)
    fault = Fault(model=fault_body.model, mode=fault_body.mode) if fault_body else None
    record = route(
        catalog=runtime.catalog,
        policy=policy,
        provider=runtime.provider,
        store=runtime.store,
        fault_injection=runtime.settings.fault_injection,
        request=RouteRequest(
            prompt=prompt,
            budget_usd=getattr(body, "budget_usd", None),
            latency_slo_ms=getattr(body, "latency_slo_ms", None),
            sensitivity=getattr(body, "sensitivity", None),
            task=getattr(body, "task", None),
            fault=fault,
            dry_run=dry_run,
        ),
    )
    log.info(
        "decision %s policy=%s outcome=%s model=%s overhead_ms=%s",
        record["id"],
        policy.version_id,
        record["outcome"],
        record["chosen_model"],
        record["timing"]["router_overhead_ms"],
    )
    return record


def app_factory() -> FastAPI:
    return create_app()
