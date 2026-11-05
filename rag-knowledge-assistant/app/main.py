"""FastAPI application: ingest, ask, re-index, delete, eval, status, health."""

from __future__ import annotations

import json
import logging
import math
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app.config import ROOT, get_settings
from app.ingestion.parsers import SUPPORTED_SUFFIXES
from app.ingestion.pipeline import ingestion_status
from app.models import Principal
from app.retrieval.filters import QueryFilters
from app.security.acl import UnknownUser, get_principal, list_users
from app.service import PROFILES, UNSAFE_PROFILES, RAGService

settings = get_settings()
logging.basicConfig(level=settings.log_level, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("api")
MAX_UPLOAD_BYTES = 20 * 1024 * 1024


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.svc = RAGService(settings)
    # Index the bundled sample corpus on first start so the demo works out of the box.
    if settings.docs_dir.exists():
        with app.state.svc.db.conn() as c:
            empty = c.execute("SELECT count(*) AS n FROM documents").fetchone()["n"] == 0
        if empty:
            app.state.svc.indexer.ingest_directory(settings.docs_dir)
    yield
    app.state.svc.close()


app = FastAPI(
    title="Lumen Knowledge Assistant",
    version="1.0.0",
    lifespan=lifespan,
    description="Production-style RAG: hybrid retrieval, re-ranking, RBAC, semantic cache, evals.",
)


def svc() -> RAGService:
    return app.state.svc


def principal(x_user_id: Annotated[str | None, Header()] = None) -> Principal:
    """Demo authentication: the X-User-Id header selects a user from config/users.yaml.

    In production this dependency validates an OIDC/JWT bearer token and maps
    IdP group claims to team/roles; nothing downstream changes.
    """
    if not x_user_id:
        raise HTTPException(401, "X-User-Id header required")
    try:
        return get_principal(x_user_id, settings.users_file)
    except UnknownUser:
        raise HTTPException(401, f"unknown user {x_user_id!r}") from None


def admin(p: Annotated[Principal, Depends(principal)]) -> Principal:
    if settings.admin_role not in p.roles:
        raise HTTPException(403, f"role '{settings.admin_role}' required")
    return p


def _clean(o):
    """JSON-safe: NaN -> None."""
    if isinstance(o, float) and math.isnan(o):
        return None
    if isinstance(o, dict):
        return {k: _clean(v) for k, v in o.items()}
    if isinstance(o, list):
        return [_clean(v) for v in o]
    return o


class AskRequest(BaseModel):
    question: str = Field(min_length=2, max_length=2000)
    profile: str = Field(default=settings.default_profile)
    teams: list[str] | None = Field(default=None, description="restrict to documents owned by these teams")
    doc_types: list[str] | None = None
    audience_teams: list[str] | None = Field(default=None, description="answer as if for these teams")
    debug: bool = False


class ReindexRequest(BaseModel):
    doc_id: str | None = None


class EvalRequest(BaseModel):
    profiles: list[str] | None = None
    with_cache: bool = False


@app.get("/health")
def health() -> dict:
    return svc().health()


@app.post("/ask")
def ask(req: AskRequest, p: Annotated[Principal, Depends(principal)]) -> dict:
    if req.profile not in PROFILES:
        raise HTTPException(400, f"unknown profile; choose from {list(PROFILES)}")
    if req.profile in UNSAFE_PROFILES and settings.admin_role not in p.roles:
        raise HTTPException(403, f"profile '{req.profile}' disables access control and is admin-only")
    filters = None
    if req.teams or req.doc_types or req.audience_teams:
        filters = QueryFilters(teams=req.teams, doc_types=req.doc_types, audience_teams=req.audience_teams)
    res = svc().ask(req.question, p, req.profile, filters=filters, debug=req.debug)
    out = res.to_dict()
    if not req.debug:
        out.pop("candidates", None)
    return out


@app.post("/ingest")
async def ingest(
    admin_p: Annotated[Principal, Depends(admin)],
    file: UploadFile = File(...),
    metadata: str | None = Form(default=None, description="JSON: team, visibility, allowed_roles, ..."),
) -> dict:
    name = Path(file.filename or "upload.txt").name
    if Path(name).suffix.lower() not in SUPPORTED_SUFFIXES:
        raise HTTPException(415, f"supported types: {sorted(SUPPORTED_SUFFIXES)}")
    data = await file.read()
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "file too large")
    try:
        meta = json.loads(metadata) if metadata else None
    except json.JSONDecodeError:
        raise HTTPException(400, "metadata must be JSON") from None
    res = svc().indexer.ingest_bytes(name, data, meta)
    if res.action == "failed":
        return JSONResponse(status_code=422, content=res.__dict__)
    return res.__dict__


@app.post("/ingest/directory")
def ingest_directory(admin_p: Annotated[Principal, Depends(admin)], force: bool = False) -> dict:
    results = svc().indexer.ingest_directory(settings.docs_dir, force=force)
    return {"results": [r.__dict__ for r in results]}


@app.post("/reindex")
def reindex(req: ReindexRequest, admin_p: Annotated[Principal, Depends(admin)]) -> dict:
    return {"results": [r.__dict__ for r in svc().indexer.reindex(req.doc_id)]}


@app.delete("/documents/{doc_id}")
def delete_document(doc_id: str, admin_p: Annotated[Principal, Depends(admin)]) -> dict:
    res = svc().indexer.delete(doc_id)
    if res.action == "not_found":
        raise HTTPException(404, "document not found")
    return res.__dict__


@app.get("/documents")
def documents(p: Annotated[Principal, Depends(principal)]) -> list[dict]:
    from app.security.acl import can_read

    with svc().db.conn() as c:
        rows = c.execute("""SELECT doc_id, title, team, doc_type, visibility, allowed_roles, audience, version,
                                   version_label, updated_at, chunk_count, indexed_at
                            FROM documents ORDER BY team, title""").fetchall()
    return [r for r in rows if can_read(p, r["visibility"], r["team"], r["allowed_roles"])]


@app.get("/documents/{doc_id}/lineage")
def lineage(doc_id: str, admin_p: Annotated[Principal, Depends(admin)]) -> list[dict]:
    with svc().db.conn() as c:
        return c.execute("SELECT * FROM chunk_lineage WHERE doc_id=%s ORDER BY doc_version, id", (doc_id,)).fetchall()


@app.get("/ingestion/status")
def status(admin_p: Annotated[Principal, Depends(admin)]) -> dict:
    return ingestion_status(svc().db)


@app.get("/cache/stats")
def cache_stats(p: Annotated[Principal, Depends(principal)]) -> dict:
    return svc().cache.stats() if svc().cache else {"enabled": False}


@app.post("/cache/clear")
def cache_clear(admin_p: Annotated[Principal, Depends(admin)]) -> dict:
    if svc().cache:
        svc().cache.clear()
    return {"cleared": True}


@app.post("/eval")
def run_eval(req: EvalRequest, admin_p: Annotated[Principal, Depends(admin)]) -> dict:
    """Run the eval suite against the *current* index (no reindex). Synchronous; takes minutes."""
    from app.evaluation.runner import run

    bad = [x for x in (req.profiles or []) if x not in PROFILES or x == "full_cached"]
    if bad:
        raise HTTPException(400, f"unknown profiles {bad}")
    return _clean(run(req.profiles, reindex=False, with_cache=req.with_cache, tag="api"))


@app.get("/eval/results")
def eval_results() -> dict:
    f = ROOT / "eval_results" / "latest" / "summary.json"
    if not f.exists():
        raise HTTPException(404, "no eval results yet; run python -m app.evaluation.runner")
    return _clean(json.loads(f.read_text()))


@app.get("/users")
def users() -> dict:
    return {
        k: {"display_name": v.get("display_name"), "team": v["team"], "roles": v["roles"]}
        for k, v in list_users(settings.users_file).items()
    }


@app.get("/profiles")
def profiles() -> dict:
    return {k: v.__dict__ for k, v in PROFILES.items()}


app.mount("/static", StaticFiles(directory=ROOT / "web"), name="static")


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(ROOT / "web" / "index.html")
