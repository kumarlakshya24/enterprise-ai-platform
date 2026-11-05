"""Paths and the demo audit key.

The demo key is a public placeholder so `make demo` works with no setup.
Set FORGE_AUDIT_KEY to override it. It is not a credential for any external service.
"""

from __future__ import annotations

import os
from pathlib import Path

DEMO_AUDIT_KEY = "forge-demo-audit-key-not-a-secret"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8095

PACKAGE_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = PACKAGE_ROOT.parent
DEFAULT_POLICY_PATH = PACKAGE_ROOT / "policy" / "default_policy.yaml"


def audit_key() -> bytes:
    return os.environ.get("FORGE_AUDIT_KEY", DEMO_AUDIT_KEY).encode()


def listen_host() -> str:
    return os.environ.get("FORGE_HOST", DEFAULT_HOST)


def listen_port() -> int:
    raw = os.environ.get("FORGE_PORT", str(DEFAULT_PORT))
    return int(raw)
