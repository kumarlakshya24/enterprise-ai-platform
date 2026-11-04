"""PostgreSQL + pgvector storage: schema, pool, and connection helpers.

Tables
  documents         one row per logical document (current version only)
  chunks            current chunks, with denormalised ACL/audience columns so every
                    retrieval query can filter *before* ranking, plus the embedding
  chunk_terms       inverted index (term, chunk, tf) that powers in-database BM25
  chunk_lineage     append-only history: which chunk replaced which, per version
  ingestion_events  every ingest/update/delete/failure, for the status dashboard
  redaction_events  PII redactions (type + count only; values are never stored)
"""
from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

import psycopg
from pgvector.psycopg import register_vector
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

SCHEMA = """
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS documents (
    doc_id         TEXT PRIMARY KEY,
    title          TEXT NOT NULL,
    source_path    TEXT,
    team           TEXT NOT NULL,
    doc_type       TEXT NOT NULL,
    visibility     TEXT NOT NULL CHECK (visibility IN ('public','team','restricted')),
    allowed_roles  TEXT[] NOT NULL DEFAULT '{{}}',
    audience       TEXT[] NOT NULL DEFAULT '{{all}}',
    version        INT NOT NULL,
    version_label  TEXT NOT NULL,
    updated_at     DATE,
    content_hash   TEXT NOT NULL,
    metadata       JSONB NOT NULL DEFAULT '{{}}',
    chunk_count    INT NOT NULL DEFAULT 0,
    indexed_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS chunks (
    chunk_id       TEXT PRIMARY KEY,
    doc_id         TEXT NOT NULL REFERENCES documents(doc_id) ON DELETE CASCADE,
    doc_version    INT NOT NULL,
    chunk_index    INT NOT NULL,
    heading_path   TEXT[] NOT NULL DEFAULT '{{}}',
    context_header TEXT NOT NULL,
    content        TEXT NOT NULL,
    content_hash   TEXT NOT NULL,
    chunk_type     TEXT NOT NULL,
    token_count    INT NOT NULL,
    term_count     INT NOT NULL,
    team           TEXT NOT NULL,
    doc_type       TEXT NOT NULL,
    visibility     TEXT NOT NULL,
    allowed_roles  TEXT[] NOT NULL DEFAULT '{{}}',
    audience       TEXT[] NOT NULL DEFAULT '{{all}}',
    pii_types      TEXT[] NOT NULL DEFAULT '{{}}',
    injection_risk REAL NOT NULL DEFAULT 0,
    embedding      vector({dim}) NOT NULL,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (doc_id, chunk_index)
);
CREATE INDEX IF NOT EXISTS chunks_embedding_hnsw ON chunks USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);
CREATE INDEX IF NOT EXISTS chunks_doc_idx ON chunks (doc_id);
CREATE INDEX IF NOT EXISTS chunks_acl_idx ON chunks (visibility, team);
CREATE INDEX IF NOT EXISTS chunks_audience_idx ON chunks USING gin (audience);

CREATE TABLE IF NOT EXISTS chunk_terms (
    term     TEXT NOT NULL,
    chunk_id TEXT NOT NULL REFERENCES chunks(chunk_id) ON DELETE CASCADE,
    tf       INT NOT NULL,
    PRIMARY KEY (term, chunk_id)
);
CREATE INDEX IF NOT EXISTS chunk_terms_chunk_idx ON chunk_terms (chunk_id);

CREATE TABLE IF NOT EXISTS chunk_lineage (
    id                BIGSERIAL PRIMARY KEY,
    doc_id            TEXT NOT NULL,
    doc_version       INT NOT NULL,
    chunk_id          TEXT,
    previous_chunk_id TEXT,
    change            TEXT NOT NULL CHECK (change IN ('added','unchanged','modified','removed')),
    content_hash      TEXT,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS chunk_lineage_doc_idx ON chunk_lineage (doc_id, doc_version);

CREATE TABLE IF NOT EXISTS ingestion_events (
    id                 BIGSERIAL PRIMARY KEY,
    doc_id             TEXT,
    source             TEXT,
    action             TEXT NOT NULL,  -- created | updated | unchanged | deleted | reindexed | failed
    version            INT,
    chunks_created     INT NOT NULL DEFAULT 0,
    chunks_replaced    INT NOT NULL DEFAULT 0,
    chunks_unchanged   INT NOT NULL DEFAULT 0,
    chunks_removed     INT NOT NULL DEFAULT 0,
    embeddings_computed INT NOT NULL DEFAULT 0,
    error              TEXT,
    duration_ms        REAL,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS redaction_events (
    id         BIGSERIAL PRIMARY KEY,
    request_id TEXT NOT NULL,
    stage      TEXT NOT NULL,   -- query | context
    pii_type   TEXT NOT NULL,
    count      INT NOT NULL,
    chunk_id   TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""


def _configure(conn: psycopg.Connection) -> None:
    register_vector(conn)


class Database:
    def __init__(self, url: str, dim: int, min_size: int = 1, max_size: int = 10):
        self.url, self.dim = url, dim
        # Create the extension before the pool registers the vector type.
        with psycopg.connect(url, autocommit=True) as c:
            c.execute("CREATE EXTENSION IF NOT EXISTS vector")
        self.pool = ConnectionPool(url, min_size=min_size, max_size=max_size, configure=_configure,
                                   kwargs={"row_factory": dict_row}, open=True)

    def migrate(self) -> None:
        with self.conn() as c:
            c.execute(SCHEMA.format(dim=self.dim))

    @contextmanager
    def conn(self) -> Iterator[psycopg.Connection]:
        with self.pool.connection() as c:
            yield c

    def reset(self) -> None:
        """Drop everything (tests / eval re-runs only)."""
        with self.conn() as c:
            c.execute("DROP TABLE IF EXISTS chunk_terms, chunks, documents, chunk_lineage, "
                      "ingestion_events, redaction_events CASCADE")
        self.migrate()

    def ping(self) -> bool:
        with self.conn() as c:
            return c.execute("SELECT 1 AS ok").fetchone()["ok"] == 1

    def close(self) -> None:
        self.pool.close()
