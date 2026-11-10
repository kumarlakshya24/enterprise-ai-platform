"""One loaded bench for the suite. The report is built with a single timing pass."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from arena.app import create_app
from arena.evaluate import build_report, write_report
from arena.settings import Settings
from arena.world import World, load_world


@pytest.fixture(scope="session")
def world() -> World:
    return load_world(Settings())


@pytest.fixture(scope="session")
def report(world: World, tmp_path_factory: pytest.TempPathFactory) -> dict:
    built = build_report(world, bench_n=1)
    path = tmp_path_factory.mktemp("reports") / "latest.json"
    write_report(built, path)
    built["_path"] = str(path)
    return built


@pytest.fixture()
def client(world: World, report: dict) -> Iterator[TestClient]:
    settings = Settings(report_path=Path(report["_path"]))
    app = create_app(settings=settings, world=world, report={k: v for k, v in report.items() if k != "_path"})
    with TestClient(app) as test_client:
        yield test_client
