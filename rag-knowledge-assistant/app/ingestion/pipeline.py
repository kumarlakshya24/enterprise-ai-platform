"""Incremental indexing.

Update semantics (per document):
  * content hash unchanged            -> no-op ("unchanged" event), nothing re-embedded
  * changed                           -> new version; old chunks are replaced *in the
                                         same transaction* (readers never see both versions)
  * chunk with identical content hash -> embedding reused, lineage 'unchanged'
  * chunk at same heading path        -> lineage 'modified' (previous_chunk_id kept)
  * old chunk with no successor       -> lineage 'removed'
  * delete                            -> rows removed, lineage + event recorded
After commit, `on_change(doc_ids)` fires so the semantic cache can drop dependent answers.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np

from app.db import Database
from app.ingestion.chunker import chunk_document
from app.ingestion.parsers import SUPPORTED_SUFFIXES, ParseError, parse_file
from app.models import ParsedDocument
from app.providers.embeddings import Embedder
from app.security import injection, pii
from app.textproc import term_freqs

log = logging.getLogger(__name__)


@dataclass
class IngestResult:
    doc_id: str | None
    source: str
    action: str
    version: int | None = None
    chunks_created: int = 0
    chunks_replaced: int = 0
    chunks_unchanged: int = 0
    chunks_removed: int = 0
    embeddings_computed: int = 0
    error: str | None = None
    duration_ms: float = 0.0
    warnings: list[str] = field(default_factory=list)


def _doc_hash(doc: ParsedDocument) -> str:
    m = doc.meta
    payload = json.dumps(
        {
            "text": [(b.kind, b.text, b.heading_path) for b in doc.blocks],
            "meta": [
                m.title,
                m.team,
                m.doc_type,
                m.version_label,
                str(m.updated),
                m.visibility,
                sorted(m.allowed_roles),
                sorted(m.audience),
            ],
        },
        sort_keys=True,
        default=str,
    )
    return hashlib.sha256(payload.encode()).hexdigest()


class Indexer:
    def __init__(
        self,
        db: Database,
        embedder: Embedder,
        max_tokens: int = 200,
        min_tokens: int = 40,
        on_change: Callable[[list[str]], None] | None = None,
    ):
        self.db, self.embedder = db, embedder
        self.max_tokens, self.min_tokens = max_tokens, min_tokens
        self.on_change = on_change

    # ------------------------------------------------------------------ public API
    def ingest_path(self, path: Path, force: bool = False, meta_override: dict | None = None) -> IngestResult:
        return self._ingest(path, None, force, meta_override)

    def ingest_bytes(
        self, filename: str, data: bytes, meta_override: dict | None = None, force: bool = False
    ) -> IngestResult:
        return self._ingest(Path(filename), data, force, meta_override)

    def ingest_directory(self, root: Path, force: bool = False) -> list[IngestResult]:
        files = sorted(p for p in root.rglob("*") if p.is_file() and p.suffix.lower() in SUPPORTED_SUFFIXES)
        return [self.ingest_path(p, force=force) for p in files]

    def delete(self, doc_id: str) -> IngestResult:
        t0 = time.perf_counter()
        with self.db.conn() as c, c.transaction():
            row = c.execute("SELECT version FROM documents WHERE doc_id=%s", (doc_id,)).fetchone()
            if not row:
                return IngestResult(doc_id, "api", "not_found")
            old = c.execute("SELECT chunk_id, content_hash FROM chunks WHERE doc_id=%s", (doc_id,)).fetchall()
            for o in old:
                c.execute(
                    "INSERT INTO chunk_lineage (doc_id, doc_version, chunk_id, previous_chunk_id, change, content_hash)"
                    " VALUES (%s,%s,NULL,%s,'removed',%s)",
                    (doc_id, row["version"], o["chunk_id"], o["content_hash"]),
                )
            c.execute("DELETE FROM documents WHERE doc_id=%s", (doc_id,))
            res = IngestResult(
                doc_id,
                "api",
                "deleted",
                row["version"],
                chunks_removed=len(old),
                duration_ms=(time.perf_counter() - t0) * 1000,
            )
            self._event(c, res)
        self._notify([doc_id])
        return res

    def reindex(self, doc_id: str | None = None) -> list[IngestResult]:
        """Re-parse and re-embed from the stored source path (one doc or all), without a full rebuild."""
        with self.db.conn() as c:
            q = "SELECT doc_id, source_path, metadata FROM documents" + (" WHERE doc_id=%s" if doc_id else "")
            rows = c.execute(q, (doc_id,) if doc_id else ()).fetchall()
        out = []
        for r in rows:
            if not r["source_path"]:
                res = IngestResult(
                    r["doc_id"],
                    "upload",
                    "failed",
                    error="uploaded via API and raw bytes are not retained; re-upload to re-index",
                )
                with self.db.conn() as c:
                    self._event(c, res)
                out.append(res)
                continue
            src = Path(r["source_path"])
            if not src.is_file():
                res = IngestResult(r["doc_id"], str(src), "failed", error="source file no longer exists")
                with self.db.conn() as c:
                    self._event(c, res)
                out.append(res)
                continue
            override = (r["metadata"] or {}).get("api_override")
            res = self._ingest(src, None, True, override)
            if res.action in ("updated", "created"):
                res.action = "reindexed"
            out.append(res)
        return out

    # ------------------------------------------------------------------ internals
    def _ingest(self, path: Path, data: bytes | None, force: bool, meta_override: dict | None) -> IngestResult:
        t0 = time.perf_counter()
        source = str(path)
        try:
            doc = parse_file(path, data=data, meta_override=meta_override)
            if data is not None:
                doc.source_path = None
            res = self._index(doc, force, meta_override, t0)
        except (ParseError, ValueError, OSError) as e:
            res = IngestResult(None, source, "failed", error=f"{type(e).__name__}: {e}")
        except Exception as e:  # noqa: BLE001 - one bad file must not stop a batch
            log.exception("ingest failed for %s", source)
            res = IngestResult(None, source, "failed", error=f"{type(e).__name__}: {e}")
        res.source = source
        res.duration_ms = round((time.perf_counter() - t0) * 1000, 1)
        if res.action == "failed":
            with self.db.conn() as c:
                self._event(c, res)
        log.info("ingest %s", json.dumps({k: v for k, v in asdict(res).items() if v not in (None, [], 0)}))
        return res

    def _index(self, doc: ParsedDocument, force: bool, meta_override: dict | None, t0: float) -> IngestResult:
        m = doc.meta
        dhash = _doc_hash(doc)
        chunks = chunk_document(doc, embed=self.embedder.embed, max_tokens=self.max_tokens, min_tokens=self.min_tokens)
        if not chunks:
            raise ParseError("no chunks produced")

        with self.db.conn() as c, c.transaction():
            cur = c.execute(
                "SELECT version, content_hash FROM documents WHERE doc_id=%s FOR UPDATE", (m.doc_id,)
            ).fetchone()
            if cur and cur["content_hash"] == dhash and not force:
                res = IngestResult(
                    m.doc_id,
                    doc.source_path or "upload",
                    "unchanged",
                    cur["version"],
                    chunks_unchanged=len(chunks),
                    duration_ms=round((time.perf_counter() - t0) * 1000, 1),
                )
                self._event(c, res)
                return res
            version = (cur["version"] + 1) if cur else 1
            old = (
                c.execute(
                    "SELECT chunk_id, chunk_index, heading_path, content_hash, embedding FROM chunks "
                    "WHERE doc_id=%s ORDER BY chunk_index",
                    (m.doc_id,),
                ).fetchall()
                if cur
                else []
            )
            by_hash = {o["content_hash"]: o for o in old}
            by_path = {tuple(o["heading_path"]): o for o in old}

            # Reuse embeddings for unchanged chunks (unless forced), embed the rest in one batch.
            need = [ch for ch in chunks if force or ch.content_hash not in by_hash]
            vecs = self.embedder.embed([ch.embed_text for ch in need]) if need else np.zeros((0, self.embedder.dim))
            new_vecs = {ch.content_hash: v for ch, v in zip(need, vecs, strict=True)}

            meta_json = {**m.extra, "api_override": meta_override} if meta_override else dict(m.extra)
            c.execute(
                """INSERT INTO documents (doc_id, title, source_path, team, doc_type, visibility,
                       allowed_roles, audience,
                       version, version_label, updated_at, content_hash, metadata, chunk_count, indexed_at)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s, now())
                   ON CONFLICT (doc_id) DO UPDATE SET title=EXCLUDED.title, source_path=EXCLUDED.source_path,
                       team=EXCLUDED.team, doc_type=EXCLUDED.doc_type, visibility=EXCLUDED.visibility,
                       allowed_roles=EXCLUDED.allowed_roles, audience=EXCLUDED.audience, version=EXCLUDED.version,
                       version_label=EXCLUDED.version_label, updated_at=EXCLUDED.updated_at,
                       content_hash=EXCLUDED.content_hash, metadata=EXCLUDED.metadata,
                       chunk_count=EXCLUDED.chunk_count, indexed_at=now()""",
                (
                    m.doc_id,
                    m.title,
                    doc.source_path,
                    m.team,
                    m.doc_type,
                    m.visibility,
                    m.allowed_roles,
                    m.audience,
                    version,
                    m.version_label,
                    m.updated,
                    dhash,
                    json.dumps(meta_json, default=str),
                    len(chunks),
                ),
            )
            # Atomic swap: old chunks (and their BM25 postings via cascade) go, new ones arrive.
            c.execute("DELETE FROM chunks WHERE doc_id=%s", (m.doc_id,))

            created = replaced = unchanged = 0
            used_old: set[str] = set()
            for ch in chunks:
                cid = f"{m.doc_id}::v{version}::c{ch.index}"
                prev = by_hash.get(ch.content_hash)
                if prev is not None and prev["chunk_id"] not in used_old:
                    change = "unchanged"
                    vec = new_vecs.get(ch.content_hash, prev["embedding"])
                    unchanged += 1
                else:
                    vec = new_vecs[ch.content_hash] if ch.content_hash in new_vecs else prev["embedding"]
                    prev = by_path.get(tuple(ch.heading_path))
                    if prev is not None and prev["chunk_id"] not in used_old:
                        change = "modified"
                        replaced += 1
                    else:
                        change, prev = "added", None
                        created += 1
                if prev is not None:
                    used_old.add(prev["chunk_id"])
                ch.pii_types = sorted(pii.detect(ch.content).keys())
                ch.injection_risk = injection.score(ch.content)
                tfs = term_freqs(ch.embed_text)
                c.execute(
                    """INSERT INTO chunks (chunk_id, doc_id, doc_version, chunk_index, heading_path,
                           context_header, content,
                           content_hash, chunk_type, token_count, term_count, team, doc_type, visibility, allowed_roles,
                           audience, pii_types, injection_risk, embedding)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (
                        cid,
                        m.doc_id,
                        version,
                        ch.index,
                        list(ch.heading_path),
                        ch.context_header,
                        ch.content,
                        ch.content_hash,
                        ch.chunk_type,
                        ch.token_count,
                        sum(tfs.values()),
                        m.team,
                        m.doc_type,
                        m.visibility,
                        m.allowed_roles,
                        m.audience,
                        ch.pii_types,
                        ch.injection_risk,
                        np.asarray(vec),
                    ),
                )
                with c.cursor() as cur2:
                    cur2.executemany(
                        "INSERT INTO chunk_terms (term, chunk_id, tf) VALUES (%s,%s,%s)",
                        [(t, cid, n) for t, n in tfs.items()],
                    )
                c.execute(
                    "INSERT INTO chunk_lineage (doc_id, doc_version, chunk_id, previous_chunk_id, change, content_hash)"
                    " VALUES (%s,%s,%s,%s,%s,%s)",
                    (m.doc_id, version, cid, prev["chunk_id"] if prev else None, change, ch.content_hash),
                )
            removed = [o for o in old if o["chunk_id"] not in used_old]
            for o in removed:
                c.execute(
                    "INSERT INTO chunk_lineage (doc_id, doc_version, chunk_id, previous_chunk_id, change, content_hash)"
                    " VALUES (%s,%s,NULL,%s,'removed',%s)",
                    (m.doc_id, version, o["chunk_id"], o["content_hash"]),
                )
            res = IngestResult(
                m.doc_id,
                doc.source_path or "upload",
                "updated" if cur else "created",
                version,
                chunks_created=created,
                chunks_replaced=replaced,
                chunks_unchanged=unchanged,
                chunks_removed=len(removed),
                embeddings_computed=len(need),
                duration_ms=round((time.perf_counter() - t0) * 1000, 1),
            )
            if any(ch.injection_risk >= 0.6 for ch in chunks):
                res.warnings.append("prompt-injection patterns detected; chunk flagged")
            self._event(c, res)
        self._notify([m.doc_id])
        return res

    def _event(self, c, r: IngestResult) -> None:
        c.execute(
            """INSERT INTO ingestion_events (doc_id, source, action, version, chunks_created, chunks_replaced,
                     chunks_unchanged, chunks_removed, embeddings_computed, error, duration_ms)
                     VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (
                r.doc_id,
                r.source,
                r.action,
                r.version,
                r.chunks_created,
                r.chunks_replaced,
                r.chunks_unchanged,
                r.chunks_removed,
                r.embeddings_computed,
                r.error,
                r.duration_ms,
            ),
        )

    def _notify(self, doc_ids: Iterable[str]) -> None:
        if self.on_change:
            try:
                self.on_change(list(doc_ids))
            except Exception:  # noqa: BLE001 - cache outage must not fail ingestion; TTL bounds staleness
                log.exception("cache invalidation failed")


def ingestion_status(db: Database, recent: int = 25) -> dict:
    with db.conn() as c:
        docs = c.execute("SELECT count(*) AS n, coalesce(sum(chunk_count),0) AS chunks FROM documents").fetchone()
        totals = c.execute("""SELECT action, count(*) AS n, sum(chunks_created) AS created,
                                     sum(chunks_replaced) AS replaced,
                                     sum(chunks_unchanged) AS unchanged, sum(chunks_removed) AS removed,
                                     sum(embeddings_computed) AS embedded
                              FROM ingestion_events GROUP BY action""").fetchall()
        failed = c.execute("""SELECT DISTINCT ON (source) source, error, created_at FROM ingestion_events
                              WHERE action='failed' ORDER BY source, created_at DESC""").fetchall()
        recent_rows = c.execute("SELECT * FROM ingestion_events ORDER BY id DESC LIMIT %s", (recent,)).fetchall()
        by_team = c.execute("""SELECT team, visibility, count(*) AS docs, sum(chunk_count) AS chunks FROM documents
                               GROUP BY team, visibility ORDER BY team""").fetchall()
        flagged = c.execute("""SELECT count(*) FILTER (WHERE injection_risk >= 0.6) AS injection_flagged,
                                      count(*) FILTER (WHERE cardinality(pii_types) > 0) AS pii_chunks
                               FROM chunks""").fetchone()
    agg = {r["action"]: r for r in totals}
    s = lambda k: int(sum((r[k] or 0) for r in totals))  # noqa: E731
    return {
        "documents_indexed": docs["n"],
        "chunks_current": int(docs["chunks"]),
        "chunks_created_total": s("created"),
        "chunks_replaced_total": s("replaced"),
        "chunks_unchanged_reused_total": s("unchanged"),
        "chunks_removed_total": s("removed"),
        "embeddings_computed_total": s("embedded"),
        "events_by_action": {k: v["n"] for k, v in agg.items()},
        "failed_files": [
            {"source": f["source"], "error": f["error"], "at": f["created_at"].isoformat()} for f in failed
        ],
        "by_team": by_team,
        "flagged_chunks": flagged,
        "recent_events": [{**r, "created_at": r["created_at"].isoformat()} for r in recent_rows],
    }
