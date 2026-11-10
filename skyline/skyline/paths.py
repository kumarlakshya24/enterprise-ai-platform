"""Filesystem locations. Everything the demo reads lives in the repo."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EVAL = ROOT / "eval"
FIXTURES = ROOT / "fixtures"
FIXTURE_ASSEMBLY = FIXTURES / "assembly.json"
BUILD = ROOT / "build"
REPORTS = ROOT / "reports" / "latest"
README = ROOT / "README.md"
STATIC = Path(__file__).resolve().parent / "dashboard" / "static"
