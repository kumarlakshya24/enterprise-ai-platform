"""Project paths and the checked-in eval configuration."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
EVAL_DIR = ROOT / "eval"
REPORTS_DIR = ROOT / "reports" / "latest"
DOCS_DIR = ROOT / "docs"
STATIC_DIR = ROOT / "lens" / "dashboard" / "static"


def load_yaml(name: str) -> dict[str, Any]:
    path = EVAL_DIR / name
    data = yaml.safe_load(path.read_text())
    if not isinstance(data, dict):
        raise ValueError(f"{path} did not contain a mapping")
    return data
