"""FastAPI app. The pipeline is in-process; nothing here calls a model provider."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from conduit.errors import ConduitError
from conduit.models import Incoming
from conduit.pipeline import Conduit

STATIC = Path(__file__).resolve().parent / "static"


def create_app(conduit: Conduit | None = None) -> FastAPI:
    app = FastAPI(title="Conduit", docs_url=None, redoc_url=None)
    app.state.conduit = conduit if conduit is not None else Conduit()

    @app.exception_handler(ConduitError)
    async def _conduit_error(_request: Request, exc: ConduitError) -> JSONResponse:
        return JSONResponse({"error": str(exc)}, status_code=exc.status)

    @app.get("/healthz")
    def healthz() -> dict[str, bool]:
        return {"ok": True}

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(STATIC / "index.html")

    @app.get("/api/status")
    def status() -> dict[str, object]:
        return _conduit(app).status()

    @app.post("/api/reset")
    def reset() -> dict[str, object]:
        return _conduit(app).reset()

    @app.post("/api/ingest")
    def ingest(body: dict[str, object]) -> dict[str, object]:
        script = body.get("script")
        if script is not None:
            if not isinstance(script, str):
                raise ConduitError("script must be a string")
            return _conduit(app).ingest_script(script)
        raw_events = body.get("events")
        if not isinstance(raw_events, list):
            raise ConduitError("pass script or events")
        return _conduit(app).ingest([_incoming(item) for item in raw_events])

    @app.post("/api/consume")
    def consume(body: dict[str, object] | None = None) -> dict[str, object]:
        return _conduit(app).consume(_optional_int(body, "limit"))

    @app.post("/api/migration/start")
    def start_migration(body: dict[str, object]) -> dict[str, object]:
        version = body.get("model_version")
        if not isinstance(version, str):
            raise ConduitError("model_version is required")
        return _conduit(app).start_migration(version)

    @app.post("/api/migration/step")
    def migration_step(body: dict[str, object] | None = None) -> dict[str, object]:
        limit = _optional_int(body, "limit")
        return _conduit(app).migration_step(20 if limit is None else limit)

    @app.post("/api/swap")
    def swap() -> dict[str, object]:
        return _conduit(app).swap()

    @app.post("/api/rollback")
    def rollback() -> dict[str, object]:
        return _conduit(app).rollback()

    @app.post("/api/replay")
    def replay() -> dict[str, object]:
        return _conduit(app).replay()

    @app.post("/api/forget")
    def forget(body: dict[str, object]) -> dict[str, object]:
        subject_id = body.get("subject_id")
        if not isinstance(subject_id, str) or not subject_id:
            raise ConduitError("subject_id is required")
        proof = _conduit(app).forget(subject_id)
        return {"proof": proof, **_conduit(app).status()}

    @app.post("/api/quarantine/retry")
    def retry_quarantine() -> dict[str, object]:
        return _conduit(app).retry_quarantine()

    @app.get("/api/search")
    def search(q: str = "", k: int = 4) -> dict[str, object]:
        if not q.strip():
            raise ConduitError("q is required")
        return _conduit(app).search(q.strip(), k)

    app.mount("/static", StaticFiles(directory=STATIC), name="static")
    return app


def _conduit(app: FastAPI) -> Conduit:
    conduit = app.state.conduit
    assert isinstance(conduit, Conduit)
    return conduit


def _optional_int(body: dict[str, object] | None, key: str) -> int | None:
    if body is None or body.get(key) is None:
        return None
    return _required_int(body.get(key), key)


def _required_int(value: object, key: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int | str):
        raise ConduitError(f"{key} must be an integer")
    try:
        return int(value)
    except ValueError as exc:
        raise ConduitError(f"{key} must be an integer") from exc


def _incoming(item: object) -> Incoming:
    if not isinstance(item, dict):
        raise ConduitError("each event must be an object")
    subjects = item.get("subject_ids") or []
    if not isinstance(subjects, list):
        raise ConduitError("subject_ids must be a list")
    try:
        return Incoming(
            event_id=str(item["event_id"]),
            op=str(item["op"]),
            doc_id=str(item["doc_id"]),
            doc_version=_required_int(item.get("doc_version"), "doc_version"),
            title=str(item["title"]),
            text=str(item.get("text") or ""),
            subject_ids=tuple(str(subject) for subject in subjects),
            source_ts=str(item.get("source_ts") or "2026-11-02T15:00:00+00:00"),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ConduitError(f"bad event: {exc}") from exc
