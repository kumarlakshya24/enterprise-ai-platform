"""FastAPI dependencies: container, authenticated principal, permission checks, rate limit."""

from __future__ import annotations

from collections.abc import Callable

import jwt
from fastapi import Depends, HTTPException, Request

from aegis.auth.oidc import AuthError, Principal
from aegis.gateway.container import Container


def get_container(request: Request) -> Container:
    c: Container = request.app.state.container
    return c


def _unverified_tenant(token: str) -> str:
    try:
        tid = str(jwt.decode(token, options={"verify_signature": False}).get("tid", ""))
    except jwt.PyJWTError:
        return "_auth"
    return tid if tid else "_auth"


def get_principal(request: Request, c: Container = Depends(get_container)) -> Principal:
    header = request.headers.get("authorization", "")
    if not header.lower().startswith("bearer "):
        raise HTTPException(
            401,
            {"code": "missing_token", "message": "Bearer token required"},
            headers={"WWW-Authenticate": "Bearer"},
        )
    token = header[7:].strip()
    try:
        return c.verifier.verify(token)
    except AuthError as exc:
        claimed = _unverified_tenant(token)
        tenant = claimed if claimed in c.settings.allowed_tenants else "_auth"
        c.audit.append(
            "auth_failed",
            tenant_id=tenant,
            user_id="anonymous",
            outcome="denied",
            details={"code": exc.code, "claimed_tenant_unverified": claimed[:64], "path": request.url.path},
        )
        raise HTTPException(
            exc.status,
            {"code": exc.code, "message": exc.message},
            headers={"WWW-Authenticate": "Bearer"} if exc.status == 401 else None,
        ) from None


def require(permission: str) -> Callable[..., Principal]:
    def dep(
        request: Request, principal: Principal = Depends(get_principal), c: Container = Depends(get_container)
    ) -> Principal:
        if not principal.has(permission):
            c.audit.append(
                "access_denied",
                tenant_id=principal.tenant_id,
                user_id=principal.sub,
                outcome="denied",
                details={"permission": permission, "path": request.url.path},
            )
            raise HTTPException(403, {"code": "forbidden", "message": f"missing permission {permission}"})
        return principal

    return dep


def rate_limited(bucket: str) -> Callable[..., None]:
    def dep(principal: Principal = Depends(get_principal), c: Container = Depends(get_container)) -> None:
        decision = c.rate_limiter.check(principal.tenant_id, principal.sub, bucket)
        if not decision.allowed:
            c.audit.append(
                "rate_limited",
                tenant_id=principal.tenant_id,
                user_id=principal.sub,
                outcome="denied",
                details={"bucket": bucket},
            )
            raise HTTPException(
                429,
                {"code": "rate_limited", "message": "too many requests"},
                headers={"Retry-After": str(decision.retry_after)},
            )

    return dep
