"""In-process app with a throwaway SQLite file."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from switchboard.app import create_app
from switchboard.runtime import Runtime
from switchboard.settings import Settings


@pytest.fixture()
def runtime(tmp_path: Path) -> Runtime:
    settings = Settings(db_path=str(tmp_path / "switchboard.db"), demo_controls=True, fault_injection=True)
    return Runtime(settings)


@pytest.fixture()
def client(runtime: Runtime) -> Iterator[TestClient]:
    app = create_app(runtime=runtime)
    with TestClient(app) as test_client:
        yield test_client
