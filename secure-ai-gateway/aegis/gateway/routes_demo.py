"""Demo-only routes: UI, sign-in proxy, the unprotected path, and evidence. Off when AEGIS_DEMO_MODE=false."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import httpx
from fastapi import APIRouter, Depends, FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from aegis.agent.unprotected import run_unprotected
from aegis.auth.oidc import Principal
from aegis.demo.scenarios import SCENARIOS
from aegis.gateway.container import Container
from aegis.gateway.deps import get_container, get_principal
from aegis.idp.issuer import DIRECTORY
from aegis.llm.base import ChatMessage, ProviderError
from aegis.llm.providers import MockProvider

router = APIRouter(prefix="/demo", tags=["demo"])


class LoginRequest(BaseModel):
    username: str = Field(pattern=r"^[a-z-]{2,32}$")


class UnprotectedChat(BaseModel):
    message: str = Field(min_length=1, max_length=32_000)


class UnprotectedAgent(BaseModel):
    task: str = Field(min_length=1, max_length=8_000)


def _unprotected_allowed(c: Container) -> None:
    """The unprotected path forwards raw text. Never allow it against a real provider by accident."""
    is_mock = isinstance(c.external_llm, MockProvider) or "mock-llm" in c.settings.llm_base_url
    if c.settings.env == "prod" or not (
        is_mock or os.environ.get("AEGIS_DEMO_ALLOW_UNPROTECTED_REAL") == "true"
    ):
        raise HTTPException(
            403,
            {
                "code": "unprotected_disabled",
                "message": "the unprotected demo path only runs against the mock provider",
            },
        )


@router.get("/scenarios")
def scenarios() -> list[dict[str, Any]]:
    return SCENARIOS


@router.get("/users")
def users() -> list[dict[str, Any]]:
    return [
        {
            "username": u.username,
            "name": u.name,
            "tenant_id": u.tenant_id,
            "roles": list(u.roles),
            "sso": "sso" in u.amr,
            "description": u.description,
        }
        for u in DIRECTORY.values()
    ]


@router.post("/login")
def login(body: LoginRequest, c: Container = Depends(get_container)) -> dict[str, Any]:
    """Demo sign-in proxy to the mock IdP. A real deployment uses the IdP's own login page."""
    issuer = c.extras.get("token_issuer")
    if issuer is not None:
        user = DIRECTORY.get(body.username)
        if user is None:
            raise HTTPException(404, "unknown demo user")
        return {"access_token": issuer.issue(user), "token_type": "Bearer"}
    try:
        r = httpx.post(c.settings.idp_token_url, json={"username": body.username}, timeout=5)
    except httpx.HTTPError as exc:
        raise HTTPException(502, "identity provider unreachable") from exc
    if r.status_code != 200:
        raise HTTPException(r.status_code, "sign-in failed")
    data: dict[str, Any] = r.json()
    return data


@router.get("/whoami")
def whoami(principal: Principal = Depends(get_principal)) -> dict[str, Any]:
    return {**principal.public(), "permissions": sorted(principal.permissions)}


@router.post("/unprotected/chat")
def unprotected_chat(
    body: UnprotectedChat, _: Principal = Depends(get_principal), c: Container = Depends(get_container)
) -> dict[str, Any]:
    """Simulates an employee pasting into a personal ChatGPT tab: raw text, no controls, no audit."""
    _unprotected_allowed(c)
    try:
        llm = c.external_llm.complete([ChatMessage("user", body.message)])
    except ProviderError as exc:
        raise HTTPException(502, str(exc)) from exc
    return {
        "status": "ok",
        "controls": "none",
        "sent_to_llm": {"provider": c.external_llm.name, "prompt": body.message},
        "answer": llm.message.content,
    }


@router.post("/unprotected/agent")
def unprotected_agent(
    body: UnprotectedAgent, _: Principal = Depends(get_principal), c: Container = Depends(get_container)
) -> dict[str, Any]:
    _unprotected_allowed(c)
    try:
        return run_unprotected(body.task, c.external_llm, c.sandbox, c.settings.agent_max_steps)
    except ProviderError as exc:
        raise HTTPException(502, str(exc)) from exc


@router.get("/evidence")
def evidence(_: Principal = Depends(get_principal), c: Container = Depends(get_container)) -> dict[str, Any]:
    """What the third party received, what the local model received, and what the sandbox saw leave."""

    def ev(p: object) -> list[dict[str, Any]]:
        fn = getattr(p, "evidence", None)
        return list(fn(20)) if callable(fn) else []

    return {"external_llm": ev(c.external_llm), "local_llm": ev(c.local_llm), "sandbox": c.sandbox.evidence()}


@router.post("/reset")
def reset(_: Principal = Depends(get_principal), c: Container = Depends(get_container)) -> dict[str, str]:
    """Clears demo evidence only. The audit log is append-only and is never reset."""
    for p in (c.external_llm, c.local_llm):
        fn = getattr(p, "reset", None)
        if callable(fn):
            fn()
    c.sandbox.reset()
    return {"status": "evidence cleared (audit log untouched)"}


def mount_demo(app: FastAPI, static_dir: Path) -> None:
    app.include_router(router)
    if static_dir.exists():
        app.mount("/static", StaticFiles(directory=static_dir), name="static")

        @app.get("/", include_in_schema=False)
        def index() -> FileResponse:
            return FileResponse(static_dir / "index.html")
