"""Detector interface. Detectors are pure functions of text; the engine applies policy."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from aegis.types import Finding

# Overlap priority: structured, checksum-validated detectors beat statistical ones.
PRIORITY_STRUCTURED = 100
PRIORITY_SECRET = 95
PRIORITY_OBFUSCATED = 80
PRIORITY_CUE = 60
PRIORITY_NER = 50
PRIORITY_ENTROPY = 40


@runtime_checkable
class Detector(Protocol):
    name: str

    def detect(self, text: str) -> list[Finding]:
        """Return candidate findings with offsets into `text`. No policy decisions here."""
        ...
