"""Agent runs and the approval workflow."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from aegis.auth.oidc import Principal
from aegis.gateway.container import Container
from aegis.gateway.deps import get_container, get_principal, rate_limited, require
from aegis.gateway.pipeline import Pipeline
from aegis.guard.approvals import ApprovalError, ApprovalRecord

router = APIRouter()


class AgentRequest(BaseModel):
    task: str = Field(min_length=1, max_length=8_000)
    session_id: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_-]{8,64}$")


class DecisionRequest(BaseModel):
    note: str = Field(default="", max_length=500)


def _http(exc: ApprovalError) -> HTTPException:
    return HTTPException(exc.status, {"code": exc.code, "message": exc.message})


@router.post("/agent/run", dependencies=[Depends(rate_limited("agent"))])
def agent_run(
    body: AgentRequest,
    principal: Principal = Depends(require("agent:run")),
    c: Container = Depends(get_container),
) -> dict[str, Any]:
    return c.agent.run(body.task, principal, session_id=body.session_id)


@router.get("/agent/runs/{run_id}")
def get_run(
    run_id: str, principal: Principal = Depends(get_principal), c: Container = Depends(get_container)
) -> dict[str, Any]:
    run = c.runs.get(run_id, principal.tenant_id)
    if run is None or (run["user_id"] != principal.sub and not principal.has("approvals:read")):
        raise HTTPException(404, {"code": "not_found", "message": "run not found"})
    return run


@router.get("/approvals")
def list_approvals(
    status: str | None = None,
    principal: Principal = Depends(get_principal),
    c: Container = Depends(get_container),
) -> dict[str, Any]:
    """Approvers see the tenant queue; everyone else sees only their own requests."""
    requester = None if principal.has("approvals:read") else principal.sub
    items = c.approvals.list(principal.tenant_id, status=status, requester_id=requester)
    return {"approvals": items, "count": len(items)}


@router.get("/approvals/{approval_id}")
def get_approval(
    approval_id: str, principal: Principal = Depends(get_principal), c: Container = Depends(get_container)
) -> dict[str, Any]:
    try:
        rec = c.approvals.get(approval_id, principal.tenant_id)
    except ApprovalError as exc:
        raise _http(exc) from None
    if rec.requester_id != principal.sub and not principal.has("approvals:read"):
        raise HTTPException(404, {"code": "not_found", "message": "approval not found"})
    return rec.public()


def _executor(c: Container):  # type: ignore[no-untyped-def]
    def run(rec: ApprovalRecord, payload: dict[str, Any]) -> dict[str, Any]:
        if rec.kind == "tool_call":
            return c.agent.execute_approved(rec, payload)
        return {
            "executed": False,
            "kind": rec.kind,
            "next": "requester resumes with POST /chat/approvals/{id}/resume",
        }

    return run


@router.post("/approvals/{approval_id}/approve")
def approve(
    approval_id: str,
    body: DecisionRequest | None = None,
    principal: Principal = Depends(get_principal),
    c: Container = Depends(get_container),
) -> dict[str, Any]:
    try:
        rec = c.approvals.get(approval_id, principal.tenant_id)
        executor = _executor(c) if rec.kind == "tool_call" else None
        return c.approvals.decide(approval_id, principal, True, executor, note=body.note if body else "")
    except ApprovalError as exc:
        raise _http(exc) from None


@router.post("/approvals/{approval_id}/deny")
def deny(
    approval_id: str,
    body: DecisionRequest | None = None,
    principal: Principal = Depends(get_principal),
    c: Container = Depends(get_container),
) -> dict[str, Any]:
    try:
        result = c.approvals.decide(approval_id, principal, False, None, note=body.note if body else "")
    except ApprovalError as exc:
        raise _http(exc) from None
    rec = c.approvals.get(approval_id, principal.tenant_id)
    if rec.run_id:
        run = c.runs.get(rec.run_id, principal.tenant_id)
        if run is not None:
            run.update(status="denied", final_answer=f"Denied by {principal.sub}. Nothing was sent.")
            c.runs.save(run)
    return result


@router.post("/chat/approvals/{approval_id}/resume")
def resume_chat(
    approval_id: str, principal: Principal = Depends(require("chat")), c: Container = Depends(get_container)
) -> dict[str, Any]:
    try:
        return Pipeline(c).resume_chat(approval_id, principal)
    except ApprovalError as exc:
        raise _http(exc) from None
