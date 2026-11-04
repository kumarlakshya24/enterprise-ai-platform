"""FastAPI application factory for the Aegis gateway."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from aegis.audit.store import AuditWriteError
from aegis.config import Settings
from aegis.dlp.engine import DetectorFailure
from aegis.gateway.container import Container, build_container, build_embedded_demo_container
from aegis.gateway.routes_admin import router as admin_router
from aegis.gateway.routes_agent import router as agent_router
from aegis.gateway.routes_core import router as core_router
from aegis.gateway.routes_demo import mount_demo
from aegis.vault.backends import BackendUnavailable
from aegis.vault.vault import SessionOwnershipError

log = logging.getLogger("aegis.gateway")
STATIC_DIR = Path(__file__).parent / "static"


class BodyLimitMiddleware:
    """Reject request bodies above a size limit, including chunked bodies without Content-Length."""

    def __init__(self, app: ASGIApp, max_bytes: int) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        for name, value in scope.get("headers", []):
            if name == b"content-length" and value.isdigit() and int(value) > self.max_bytes:
                await _too_large(send)
                return
        received = 0

        async def limited_receive() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_bytes:
                    raise _BodyTooLarge
            return message

        try:
            await self.app(scope, limited_receive, send)
        except _BodyTooLarge:
            await _too_large(send)


class _BodyTooLarge(Exception):
    pass


async def _too_large(send: Send) -> None:
    await send(
        {"type": "http.response.start", "status": 413, "headers": [(b"content-type", b"application/json")]}
    )
    await send({"type": "http.response.body", "body": b'{"detail":{"code":"payload_too_large"}}'})


SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Cache-Control": "no-store",
    # The demo UI loads nothing external and never renders model output as HTML.
    "Content-Security-Policy": "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; "
    "connect-src 'self'; frame-ancestors 'none'",
}


def create_app(container: Container | None = None, settings: Settings | None = None) -> FastAPI:
    if container is None:
        settings = settings or Settings.from_env()
        logging.basicConfig(level=settings.log_level, format="%(asctime)s %(levelname)s %(name)s %(message)s")
        container = (
            build_embedded_demo_container(settings) if settings.embedded_demo else build_container(settings)
        )
    app = FastAPI(
        title="Aegis Secure AI Gateway",
        version="0.1.0",
        description="DLP, tokenization, private classification, tool guardrails, and tamper-evident audit.",
    )
    app.state.container = container

    @app.middleware("http")
    async def security_headers(request: Request, call_next: Any) -> Any:
        response = await call_next(request)
        for k, v in SECURITY_HEADERS.items():
            response.headers.setdefault(k, v)
        return response

    app.add_middleware(BodyLimitMiddleware, max_bytes=container.settings.max_body_bytes)

    @app.exception_handler(SessionOwnershipError)
    async def _session(_: Request, exc: SessionOwnershipError) -> JSONResponse:
        return JSONResponse({"detail": {"code": "session_not_owned", "message": str(exc)}}, status_code=403)

    @app.exception_handler(BackendUnavailable)
    async def _vault_down(_: Request, __: BackendUnavailable) -> JSONResponse:
        return JSONResponse(
            {
                "detail": {
                    "code": "vault_unavailable",
                    "message": "token vault unavailable; request refused rather than sent unprotected",
                }
            },
            status_code=503,
        )

    @app.exception_handler(AuditWriteError)
    async def _audit_down(_: Request, __: AuditWriteError) -> JSONResponse:
        return JSONResponse(
            {"detail": {"code": "audit_unavailable", "message": "audit log unavailable; request refused"}},
            status_code=503,
        )

    @app.exception_handler(DetectorFailure)
    async def _detector(_: Request, __: DetectorFailure) -> JSONResponse:
        return JSONResponse(
            {"detail": {"code": "dlp_failure", "message": "DLP engine error; request blocked"}},
            status_code=503,
        )

    app.include_router(core_router)
    app.include_router(agent_router)
    app.include_router(admin_router)
    if container.settings.demo_mode:
        mount_demo(app, STATIC_DIR)
    return app


def app_factory() -> FastAPI:
    """Entry point for `uvicorn --factory aegis.gateway.app:app_factory`."""
    return create_app()
