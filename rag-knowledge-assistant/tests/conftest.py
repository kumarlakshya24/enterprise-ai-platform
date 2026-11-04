"""Shared fixtures.

Integration tests use an isolated database (`rag_test`) and a separate Redis key
namespace, with the deterministic hash embedder and no re-ranker, so they are
fast and do not depend on model downloads. They are skipped when the services
are not reachable.
"""
from __future__ import annotations

import os
import sys
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import Settings  # noqa: E402

_PW = os.environ.get("POSTGRES_PASSWORD", "")
BASE_DB = os.environ.get("TEST_DATABASE_URL",
                         os.environ.get("DATABASE_URL", f"postgresql://rag:{_PW}@localhost:5432/rag"))
REDIS_URL = os.environ.get("TEST_REDIS_URL", os.environ.get("REDIS_URL", "redis://localhost:6379/0"))


def _test_db_url() -> str:
    head, _, _ = BASE_DB.rpartition("/")
    return f"{head}/rag_test"


def _services_up() -> bool:
    try:
        import psycopg
        import redis

        with psycopg.connect(BASE_DB, autocommit=True, connect_timeout=2) as c:
            if not c.execute("SELECT 1 FROM pg_database WHERE datname='rag_test'").fetchone():
                c.execute("CREATE DATABASE rag_test")
        redis.Redis.from_url(REDIS_URL, socket_connect_timeout=2).ping()
        return True
    except Exception:  # noqa: BLE001
        return False


SERVICES = _services_up()


@pytest.fixture(scope="session")
def test_settings(tmp_path_factory) -> Settings:
    return Settings(database_url=_test_db_url(), redis_url=REDIS_URL, embedding_provider="hash",
                    reranker_provider="none", llm_provider="extractive", min_vector_score=0.0,
                    docs_dir=tmp_path_factory.mktemp("docs"), _env_file=None)


@pytest.fixture()
def svc(test_settings):
    if not SERVICES:
        pytest.skip("PostgreSQL/Redis not reachable")
    from app.caching.semantic_cache import SemanticCache
    from app.service import RAGService

    cache = SemanticCache(test_settings.redis_url, test_settings.embedding_dim, 0.97, 60, namespace="semcache_test")
    service = RAGService(test_settings, reranker=None, cache=cache)
    service.db.reset()
    cache.clear()
    yield service
    cache.clear()
    service.close()


def write_doc(directory: Path, name: str, front: dict, body: str) -> Path:
    import yaml

    p = directory / name
    p.write_text("---\n" + yaml.safe_dump(front) + "---\n" + textwrap.dedent(body).strip() + "\n")
    return p


@pytest.fixture()
def docdir(tmp_path) -> Path:
    return tmp_path
