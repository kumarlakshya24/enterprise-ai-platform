"""HTTP console. The numbers are the synth, not a static mock."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from skyline.mutations import mutation_names
from skyline.paths import STATIC
from skyline.state import build_state

_KNOWN = {"clean", *mutation_names()}


def create_app() -> FastAPI:
    app = FastAPI(title="Skyline", docs_url=None, redoc_url=None)

    @app.get("/healthz")
    def health() -> dict[str, bool]:
        return {"ok": True}

    @app.get("/api/state")
    def state(mutation: str = "clean", rpd: int = 100_000) -> dict[str, Any]:
        if mutation not in _KNOWN:
            raise HTTPException(status_code=400, detail=f"unknown mutation {mutation}")
        if not 1 <= rpd <= 100_000_000:
            raise HTTPException(status_code=400, detail="rpd out of range")
        return build_state(mutation, rpd)

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(STATIC / "index.html")

    app.mount("/static", StaticFiles(directory=STATIC), name="static")
    return app
