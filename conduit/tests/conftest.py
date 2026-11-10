from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from conduit.api.app import create_app
from conduit.embedder import FakeEmbedder
from conduit.pipeline import Conduit
from conduit.redact import InProcessRedactor


@pytest.fixture
def conduit(tmp_path: object) -> Iterator[Conduit]:
    from pathlib import Path

    path = Path(str(tmp_path)) / "conduit.db"
    built = Conduit(path, embedder=FakeEmbedder(), redactor=InProcessRedactor())
    built.reset()
    try:
        yield built
    finally:
        built.close()


@pytest.fixture
def client(conduit: Conduit) -> TestClient:
    return TestClient(create_app(conduit))
