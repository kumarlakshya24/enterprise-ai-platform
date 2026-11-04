"""SQLAlchemy Core schema. Postgres in deployments, SQLite in tests and single-process dev."""

from __future__ import annotations

import logging

from sqlalchemy import (
    Boolean,
    Column,
    Engine,
    Float,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    create_engine,
    insert,
    select,
    text,
)
from sqlalchemy.pool import StaticPool

log = logging.getLogger("aegis.db")
metadata = MetaData()

GENESIS_HASH = "0" * 64

audit_events = Table(
    "audit_events",
    metadata,
    Column("seq", Integer, primary_key=True, autoincrement=True),
    Column("event_id", String(36), nullable=False, unique=True),
    Column("ts", String(40), nullable=False),
    Column("tenant_id", String(64), nullable=False, index=True),
    Column("user_id", String(128), nullable=False, index=True),
    Column("session_id", String(64), nullable=True, index=True),
    Column("request_id", String(64), nullable=True),
    Column("event_type", String(64), nullable=False, index=True),
    Column("policy_version", String(64), nullable=True),
    Column("route", String(32), nullable=True),
    Column("outcome", String(32), nullable=True),
    Column("details", Text, nullable=False),
    Column("prev_hash", String(64), nullable=False),
    Column("hash", String(64), nullable=False),
)

audit_head = Table(
    "audit_head",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("seq", Integer, nullable=False),
    Column("hash", String(64), nullable=False),
)

policy_versions = Table(
    "policy_versions",
    metadata,
    Column("revision", Integer, primary_key=True, autoincrement=True),
    Column("digest", String(32), nullable=False),
    Column("created_at", String(40), nullable=False),
    Column("created_by", String(128), nullable=False),
    Column("note", Text, nullable=False, default=""),
    Column("bundle", Text, nullable=False),
    Column("active", Boolean, nullable=False, default=False),
)

approvals = Table(
    "approvals",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("tenant_id", String(64), nullable=False, index=True),
    Column("requester_id", String(128), nullable=False),
    Column("kind", String(32), nullable=False),
    Column("status", String(16), nullable=False, index=True),
    Column("created_at", Float, nullable=False),
    Column("expires_at", Float, nullable=False),
    Column("decided_by", String(128), nullable=True),
    Column("decided_at", Float, nullable=True),
    Column("summary", Text, nullable=False),
    Column("payload_enc", Text, nullable=False),
    Column("run_id", String(36), nullable=True),
    Column("result", Text, nullable=True),
)

agent_runs = Table(
    "agent_runs",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("tenant_id", String(64), nullable=False, index=True),
    Column("user_id", String(128), nullable=False),
    Column("status", String(32), nullable=False),
    Column("created_at", Float, nullable=False),
    Column("updated_at", Float, nullable=False),
    Column("data", Text, nullable=False),
)

_SQLITE_TRIGGERS = [
    """CREATE TRIGGER IF NOT EXISTS audit_no_update BEFORE UPDATE ON audit_events
       BEGIN SELECT RAISE(ABORT, 'audit_events is append-only'); END""",
    """CREATE TRIGGER IF NOT EXISTS audit_no_delete BEFORE DELETE ON audit_events
       BEGIN SELECT RAISE(ABORT, 'audit_events is append-only'); END""",
]

_PG_TRIGGERS = [
    """CREATE OR REPLACE FUNCTION aegis_audit_append_only() RETURNS trigger AS $$
       BEGIN RAISE EXCEPTION 'audit_events is append-only'; END; $$ LANGUAGE plpgsql""",
    "DROP TRIGGER IF EXISTS audit_no_update_delete ON audit_events",
    """CREATE TRIGGER audit_no_update_delete BEFORE UPDATE OR DELETE ON audit_events
       FOR EACH ROW EXECUTE FUNCTION aegis_audit_append_only()""",
    "DROP TRIGGER IF EXISTS audit_no_truncate ON audit_events",
    """CREATE TRIGGER audit_no_truncate BEFORE TRUNCATE ON audit_events
       FOR EACH STATEMENT EXECUTE FUNCTION aegis_audit_append_only()""",
]


def make_engine(url: str) -> Engine:
    if url.startswith("sqlite"):
        if url in ("sqlite://", "sqlite:///:memory:"):
            return create_engine(url, connect_args={"check_same_thread": False}, poolclass=StaticPool)
        return create_engine(url, connect_args={"check_same_thread": False})
    return create_engine(url, pool_pre_ping=True, pool_size=10, max_overflow=10)


def init_db(engine: Engine) -> None:
    """Create tables and append-only triggers. Idempotent; serialized across replicas on Postgres."""
    with engine.begin() as conn:
        if engine.dialect.name == "postgresql":
            conn.execute(text("SELECT pg_advisory_xact_lock(424242)"))
        metadata.create_all(conn)
        for stmt in _PG_TRIGGERS if engine.dialect.name == "postgresql" else _SQLITE_TRIGGERS:
            conn.execute(text(stmt))
        if conn.execute(select(audit_head.c.id).where(audit_head.c.id == 1)).first() is None:
            conn.execute(insert(audit_head).values(id=1, seq=0, hash=GENESIS_HASH))
