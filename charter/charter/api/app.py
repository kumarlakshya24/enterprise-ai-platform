"""Local UI and JSON API. Bound to 127.0.0.1 by the CLI. No auth, by design, for the demo."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from charter.config import CANDIDATE_EXCLUDE, POLICIES_DIR, STATIC_DIR
from charter.evidence.pack import Report, build_report, report_dict
from charter.policy.engine import evaluate, load_policies

_REPORT: Report | None = None


def get_report() -> Report:
    global _REPORT
    if _REPORT is None:
        _REPORT = build_report()
    return _REPORT


def create_app() -> FastAPI:
    app = FastAPI(title="Charter", docs_url=None, redoc_url=None)
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/api/snapshot")
    def snapshot() -> dict[str, Any]:
        return report_dict(get_report())

    @app.post("/api/decide")
    def decide(body: dict[str, Any]) -> dict[str, Any]:
        case_id = str(body.get("case_id") or "")
        policy = str(body.get("policy") or "shipped")
        if policy not in ("shipped", "no-residency"):
            raise HTTPException(status_code=400, detail="policy must be shipped or no-residency")
        report = get_report()
        try:
            item = report.decision_for(case_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="unknown case") from exc
        exclude = CANDIDATE_EXCLUDE if policy == "no-residency" else frozenset()
        bundle = load_policies(POLICIES_DIR, exclude=exclude)
        card = report.registry.get(item.case.request.model_id)
        resource = None if card is None else card.resource()
        decision = evaluate(bundle, item.case.request, resource)
        excerpt = ""
        for statement in bundle.statements:
            if statement.rule_id == decision.primary_rule:
                excerpt = statement.excerpt
                break
        passed = decision.effect == item.case.effect and all(
            rule in decision.rule_ids for rule in item.case.includes
        )
        return {
            "case_id": case_id,
            "policy": policy,
            "decision": decision.as_dict(),
            "expect": {"effect": item.case.effect, "includes": list(item.case.includes)},
            "matches_locked_case": passed,
            "excerpt": excerpt,
            "model": None if card is None else card.as_dict(),
        }

    return app


app = create_app()
