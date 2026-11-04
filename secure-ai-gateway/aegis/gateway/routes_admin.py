"""Admin API: policy bundle management behind the regression gate."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, ValidationError

from aegis.auth.oidc import Principal
from aegis.gateway.container import Container
from aegis.gateway.deps import get_container, require
from aegis.gateway.pipeline import classifier_view
from aegis.policy.engine import decide
from aegis.policy.regression import BASELINE, CASES_DIR, Evaluator, gate, load_baseline, load_cases
from aegis.policy.schema import PolicyBundle
from aegis.vault.backends import MemoryBackend
from aegis.vault.crypto import VaultCipher
from aegis.vault.vault import TokenVault, VaultContext

router = APIRouter(prefix="/admin", tags=["admin"])


class PolicyUpdate(BaseModel):
    bundle: dict[str, Any]
    note: str = Field(default="", max_length=500)


class DryRun(BaseModel):
    bundle: dict[str, Any] | None = None
    message: str = Field(min_length=1, max_length=32_000)


def _evaluator(c: Container) -> tuple[Evaluator, list[dict[str, Any]], dict[str, list[str]]]:
    if "evaluator" not in c.extras:
        cases_dir = Path(os.environ.get("AEGIS_EVAL_DIR", str(CASES_DIR.parent))) / "cases"
        baseline_path = (
            Path(os.environ.get("AEGIS_EVAL_DIR", str(BASELINE.parents[1]))) / "regression" / "baseline.json"
        )
        if not cases_dir.exists() or not baseline_path.exists():
            raise HTTPException(
                503,
                {
                    "code": "regression_corpus_missing",
                    "message": "regression corpus unavailable; policy changes are refused",
                },
            )
        c.extras["evaluator"] = (
            Evaluator(c.dlp, c.classifier, c.injection),
            load_cases(sorted(cases_dir.glob("*.jsonl"))),
            load_baseline(baseline_path),
        )
    result: tuple[Evaluator, list[dict[str, Any]], dict[str, list[str]]] = c.extras["evaluator"]
    return result


def _parse(raw: dict[str, Any]) -> PolicyBundle:
    try:
        bundle = PolicyBundle.model_validate(raw)
        bundle.validate_all()
    except (ValidationError, ValueError) as exc:
        raise HTTPException(422, {"code": "invalid_policy", "message": str(exc)[:2000]}) from None
    return bundle


@router.get("/policies")
def get_bundle(
    principal: Principal = Depends(require("policy:write")), c: Container = Depends(get_container)
) -> dict[str, Any]:
    active = c.policies.active()
    return {
        "policy_version": active.version,
        "bundle": active.bundle.model_dump(mode="json"),
        "history": c.policies.history(),
    }


@router.put("/policies")
def put_bundle(
    body: PolicyUpdate,
    principal: Principal = Depends(require("policy:write")),
    c: Container = Depends(get_container),
) -> dict[str, Any]:
    bundle = _parse(body.bundle)
    ev, cases, baseline = _evaluator(c)
    report = gate(bundle, ev, baseline, cases)
    current = c.policies.active()
    if not report.ok:
        c.audit.append(
            "policy_update_rejected",
            tenant_id=principal.tenant_id,
            user_id=principal.sub,
            policy_version=current.version,
            outcome="rejected",
            details={
                "candidate_digest": bundle.digest(),
                "regressions": report.protection_regressions[:50],
                "note": body.note,
            },
        )
        raise HTTPException(
            409,
            {
                "code": "regression_gate_failed",
                "message": f"{len(report.protection_regressions)} protected cases would regress; "
                "the current policy stays active",
                "report": report.public(),
            },
        )
    active = c.policies.activate(bundle, principal.sub, body.note)
    c.audit.append(
        "policy_updated",
        tenant_id=principal.tenant_id,
        user_id=principal.sub,
        policy_version=active.version,
        outcome="activated",
        details={
            "previous_version": current.version,
            "note": body.note,
            "utility_regressions": len(report.utility_regressions),
            "scopes": report.scopes_checked,
        },
    )
    return {"status": "activated", "policy_version": active.version, "gate": report.public()}


@router.post("/policies/dry-run")
def dry_run(
    body: DryRun,
    principal: Principal = Depends(require("policy:write")),
    c: Container = Depends(get_container),
) -> dict[str, Any]:
    """Preview a decision under a candidate policy. Nothing is sent to any model; nothing is stored."""
    bundle = _parse(body.bundle) if body.bundle else c.policies.active().bundle
    policy = bundle.effective(principal.tenant_id, principal.sub)
    scan = c.dlp.scan(body.message, policy)
    vault = TokenVault(MemoryBackend(), VaultCipher({"dry": os.urandom(32)}, "dry"))
    tokenized = vault.apply(scan, VaultContext(principal.tenant_id, principal.sub, "dry-run-0001", "dry"))
    clf = (
        c.classifier.classify(classifier_view(tokenized), policy.classifier.min_confidence)
        if c.classifier
        else None
    )
    d = decide(text=body.message, scan=scan, classification=clf, policy=policy, policy_version="dry-run")
    return {
        "decision": d.public(),
        "entities": [f.public_dict() for f in scan.applied],
        "would_send": tokenized if d.route.sends_external else None,
    }


@router.get("/regression")
def regression_status(
    principal: Principal = Depends(require("policy:write")), c: Container = Depends(get_container)
) -> dict[str, Any]:
    ev, cases, baseline = _evaluator(c)
    return gate(c.policies.active().bundle, ev, baseline, cases).public()
