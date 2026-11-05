"""Local dashboard. `make up` serves the report that `make eval` already rendered."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from lens.config import REPORTS_DIR, STATIC_DIR


def create_app() -> Any:
    from fastapi import FastAPI
    from fastapi.responses import HTMLResponse, JSONResponse

    app = FastAPI(title="Lens", docs_url=None, redoc_url=None)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/", response_class=HTMLResponse)
    def index() -> HTMLResponse:
        page = STATIC_DIR / "index.html"
        if not page.exists():
            from lens.cli import _prepare

            _prepare()
        return HTMLResponse((STATIC_DIR / "index.html").read_text())

    @app.get("/api/summary")
    def summary() -> JSONResponse:
        path = Path(REPORTS_DIR / "summary.json")
        return JSONResponse(json.loads(path.read_text()))

    return app
