"""Canonical JSON for hashes and event payloads."""

from __future__ import annotations

import hashlib
import json
from typing import Any


def canon(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)


def digest(obj: Any) -> str:
    return hashlib.sha256(canon(obj).encode()).hexdigest()


def money(value: float) -> float:
    return round(float(value) + 1e-12, 6)
