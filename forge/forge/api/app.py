"""Local FastAPI UI and JSON API. No network calls."""

from __future__ import annotations

import tempfile
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from forge import __version__
from forge.audit import AuditLog
from forge.config import audit_key
from forge.demo.runner import _judge_step, _request, regression_checks
from forge.demo.scenarios import by_id, public_scenarios
from forge.policy.schema import load_default_policy
from forge.service import Session
from forge.types import ToolRequest

STATIC = Path(__file__).resolve().parent / "static"


class RunBody(BaseModel):
    scenario_id: str | None = None
    tool: str | None = None
    code: str | None = None
    path: str | None = None
    content: str | None = None
    timeout_ms: int | None = Field(default=None, ge=100, le=5000)


def _step_payload(result: object, ok: bool) -> dict[str, object]:
    preview = result.preview  # type: ignore[attr-defined]
    return {
        "tool": result.tool,  # type: ignore[attr-defined]
        "outcome": result.outcome,  # type: ignore[attr-defined]
        "rule": result.rule,  # type: ignore[attr-defined]
        "reasons": result.reasons,  # type: ignore[attr-defined]
        "stdout": result.stdout,  # type: ignore[attr-defined]
        "spawned": result.spawned,  # type: ignore[attr-defined]
        "duration_ms": round(result.duration_ms, 1),  # type: ignore[attr-defined]
        "error": result.error,  # type: ignore[attr-defined]
        "audit_seq": result.audit_seq,  # type: ignore[attr-defined]
        "ok": ok,
        "preview": {
            "would_allow": preview.would_allow,
            "executed": preview.executed,
            "risk": preview.risk,
            "note": preview.note,
        },
    }


def create_app(workspace: Path | None = None, audit_path: Path | None = None) -> FastAPI:
    root = workspace or (Path.cwd() / "var" / "workspace")
    log_path = audit_path or (Path.cwd() / "var" / "audit.jsonl")
    session = Session(root, AuditLog(log_path, audit_key()), load_default_policy())
    app = FastAPI(title="Forge", version=__version__)
    app.state.session = session

    @app.get("/healthz")
    def healthz() -> dict[str, object]:
        verify = session.audit.verify()
        return {
            "status": "ok",
            "version": __version__,
            "policy": session.policy.version,
            "audit_ok": verify["ok"],
            "audit_events": verify["events"],
        }

    @app.get("/scenarios")
    def scenarios() -> dict[str, object]:
        return {"scenarios": public_scenarios()}

    @app.post("/run")
    def run(body: RunBody) -> dict[str, object]:
        if body.scenario_id:
            try:
                scenario = by_id(body.scenario_id)
            except KeyError as exc:
                raise HTTPException(status_code=404, detail="unknown scenario") from exc
            if scenario.kind == "regression":
                with tempfile.TemporaryDirectory(prefix="forge-gate-") as tmp:
                    checks = regression_checks(Path(tmp), session.policy)
                return {
                    "id": scenario.id,
                    "title": scenario.title,
                    "say": scenario.say,
                    "kind": "regression",
                    "demo_pass": all(item.ok for item in checks),
                    "steps": [],
                    "checks": [{"id": item.id, "ok": item.ok, "detail": item.detail} for item in checks],
                }
            steps = []
            demo_pass = True
            for step in scenario.steps:
                result = session.execute(_request(step))
                ok, _detail = _judge_step(step, result)
                demo_pass = demo_pass and ok
                payload = _step_payload(result, ok)
                payload["code"] = step.code
                payload["path"] = step.path
                steps.append(payload)
            return {
                "id": scenario.id,
                "title": scenario.title,
                "say": scenario.say,
                "kind": "tool",
                "demo_pass": demo_pass,
                "steps": steps,
            }
        if not body.tool:
            raise HTTPException(status_code=400, detail="scenario_id or tool is required")
        result = session.execute(
            ToolRequest(
                tool=body.tool,
                code=body.code,
                path=body.path,
                content=body.content,
                timeout_ms=body.timeout_ms,
                actor="ui",
            )
        )
        return {"kind": "custom", "demo_pass": None, "steps": [_step_payload(result, result.outcome != "error")]}

    @app.get("/audit")
    def audit(limit: int = 20) -> dict[str, object]:
        rows = session.audit.records()[-max(1, min(limit, 100)) :]
        return {"events": rows}

    @app.get("/audit/verify")
    def verify() -> dict[str, object]:
        return session.audit.verify()

    @app.post("/session/reset")
    def reset() -> dict[str, str]:
        session.reset()
        return {"status": "reset"}

    if STATIC.exists():
        app.mount("/static", StaticFiles(directory=STATIC), name="static")

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(STATIC / "index.html")

    return app


app = create_app()
