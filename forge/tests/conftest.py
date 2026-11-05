"""Unit and integration fixtures."""

from __future__ import annotations

from pathlib import Path

import pytest

from forge.audit import AuditLog
from forge.policy.schema import load_default_policy
from forge.service import Session

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def policy():
    return load_default_policy()


@pytest.fixture
def session(tmp_path: Path, policy):
    return Session(tmp_path / "ws", AuditLog(tmp_path / "audit.jsonl", b"test-audit-key"), policy)
