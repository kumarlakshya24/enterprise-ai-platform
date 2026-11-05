"""Core routes: chat, policies (read), audit, vault de-tokenization, health."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from aegis.auth.oidc import Principal
from aegis.gateway.container import Container
from aegis.gateway.deps import get_container, rate_limited, require
from aegis.gateway.pipeline import Pipeline
from aegis.vault.vault import SessionOwnershipError, VaultContext

router = APIRouter()


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=32_000)
    session_id: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_-]{8,64}$")
    purpose: str = Field(default="chat", pattern=r"^[a-z_]{3,24}$")


class DetokenizeRequest(BaseModel):
    session_id: str = Field(pattern=r"^[A-Za-z0-9_-]{8,64}$")
    text: str = Field(min_length=1, max_length=32_000)
    purpose: str = Field(default="chat", pattern=r"^[a-z_]{3,24}$")


@router.get("/healthz")
def healthz(c: Container = Depends(get_container)) -> dict[str, Any]:
    return c.health()


@router.post("/chat", dependencies=[Depends(rate_limited("chat"))])
def chat(
    body: ChatRequest, principal: Principal = Depends(require("chat")), c: Container = Depends(get_container)
) -> dict[str, Any]:
    return Pipeline(c).chat(body.message, principal, session_id=body.session_id, purpose=body.purpose)


@router.get("/policies")
def get_policies(
    principal: Principal = Depends(require("policy:read")), c: Container = Depends(get_container)
) -> dict[str, Any]:
    """The effective policy for the caller (tenant + user overrides applied). Transparency for users."""
    policy, version = c.policies.effective(principal.tenant_id, principal.sub)
    return {"policy_version": version, "policy": policy.model_dump(mode="json")}


@router.get("/audit")
def get_audit(
    principal: Principal = Depends(require("audit:read")),
    c: Container = Depends(get_container),
    user_id: str | None = None,
    event_type: str | None = None,
    session_id: str | None = None,
    after_seq: int | None = None,
    limit: int = Query(default=100, ge=1, le=1000),
    include_auth_failures: bool = True,
) -> dict[str, Any]:
    events = c.audit.query(
        principal.tenant_id,
        user_id=user_id,
        event_type=event_type,
        session_id=session_id,
        after_seq=after_seq,
        limit=limit,
    )
    if include_auth_failures and not (user_id or session_id) and event_type in (None, "auth_failed"):
        events += c.audit.query("_auth", event_type="auth_failed", after_seq=after_seq, limit=limit)
        events.sort(key=lambda e: e["seq"], reverse=True)
        events = events[:limit]
    return {"events": events, "count": len(events)}


@router.get("/audit/verify")
def verify_audit(
    principal: Principal = Depends(require("audit:read")), c: Container = Depends(get_container)
) -> dict[str, Any]:
    return c.audit.verify()


@router.post("/vault/detokenize")
def detokenize(
    body: DetokenizeRequest,
    principal: Principal = Depends(require("vault:detokenize:own")),
    c: Container = Depends(get_container),
) -> dict[str, Any]:
    """Restore placeholders for the session owner only, scoped by role."""
    ctx = VaultContext(principal.tenant_id, principal.sub, body.session_id, body.purpose)
    try:
        owner = c.vault.session_owner(principal.tenant_id, body.session_id)
        if owner is None:
            raise HTTPException(404, {"code": "session_expired", "message": "session unknown or expired"})
        result = c.vault.restore_text(body.text, ctx, principal.restore_scopes)
    except SessionOwnershipError:
        c.audit.append(
            "detokenize_denied",
            tenant_id=principal.tenant_id,
            user_id=principal.sub,
            session_id=body.session_id,
            outcome="denied",
            details={"reason": "session not owned by caller"},
        )
        raise HTTPException(
            403, {"code": "session_not_owned", "message": "you can only de-tokenize your own sessions"}
        ) from None
    c.audit.append(
        "detokenize",
        tenant_id=principal.tenant_id,
        user_id=principal.sub,
        session_id=body.session_id,
        outcome="ok",
        details={"restored": result.restored, "missing": result.missing},
    )
    return {"text": result.text, "restored": result.restored, "missing": result.missing}
