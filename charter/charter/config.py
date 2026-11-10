"""Paths and the published demo audit key. Nothing here is a credential."""

from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
POLICIES_DIR = ROOT / "policies"
CANDIDATE_EXCLUDE = frozenset({"002-residency.cedar"})
REGISTRY_PATH = ROOT / "registry" / "models.yaml"
CONTROLS_PATH = ROOT / "catalog" / "controls.yaml"
AUDIT_PATH = ROOT / "fixtures" / "aegis_audit.jsonl"
SLO_PATH = ROOT / "fixtures" / "lens_slo.json"
CASES_PATH = ROOT / "eval" / "cases.yaml"
PRICING_PATH = ROOT / "eval" / "pricing.yaml"
REPORTS_DIR = ROOT / "reports" / "latest"
STATIC_DIR = ROOT / "charter" / "api" / "static"

# The fixture chain is HMAC'd with this published key so a test can recompute it.
# It is not a secret, and it is not Aegis's key. Override only if you regenerate fixtures.
DEMO_AUDIT_KEY = b"charter-demo-not-a-secret"

# Lens eval/slo.yaml targets. Duplicated so Charter runs without that tree.
LENS_SLO_TARGETS: dict[str, float] = {
    "availability": 0.995,
    "latency": 0.99,
    "quality": 0.95,
    "safety": 0.999,
}

WINDOW_START = "2026-10-22T00:00:00Z"
WINDOW_END = "2026-11-04T23:00:00Z"
TENANT = "acme"
PORT = int(os.environ.get("CHARTER_PORT", "8097"))
