"""Canonical JSON for the assembly. The hash is the thing CI pins."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from skyline.paths import BUILD, FIXTURE_ASSEMBLY
from skyline.platform import assemble


def canonical(assembly: dict[str, Any]) -> str:
    return json.dumps(assembly, indent=2, sort_keys=True) + "\n"


def digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def synth_text() -> tuple[dict[str, Any], str, str]:
    assembly = assemble()
    text = canonical(assembly)
    return assembly, text, digest(text)


def read_fixture() -> str:
    if not FIXTURE_ASSEMBLY.exists():
        raise FileNotFoundError(f"missing {FIXTURE_ASSEMBLY}. Run python -m skyline synth --write-fixture")
    return FIXTURE_ASSEMBLY.read_text(encoding="utf-8")


def write_outputs(text: str, *, fixture: bool) -> None:
    BUILD.mkdir(parents=True, exist_ok=True)
    (BUILD / "assembly.json").write_text(text, encoding="utf-8")
    if fixture:
        FIXTURE_ASSEMBLY.parent.mkdir(parents=True, exist_ok=True)
        FIXTURE_ASSEMBLY.write_text(text, encoding="utf-8")
