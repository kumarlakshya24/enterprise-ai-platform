"""DLP engine: normalize, run detectors, apply policy thresholds and allowlist, resolve overlaps."""

from __future__ import annotations

import logging
import re
import time
from collections.abc import Sequence
from dataclasses import dataclass, field

from aegis.dlp.base import Detector
from aegis.dlp.ner import build_ner_detector, load_first_names
from aegis.dlp.normalize import normalize
from aegis.dlp.regex_detectors import default_regex_detectors
from aegis.policy.schema import Policy
from aegis.types import EntityAction, EntityType, Finding, FindingStatus

log = logging.getLogger("aegis.dlp")


class DetectorFailure(RuntimeError):
    """A detector crashed. The pipeline treats this as fail-closed."""


@dataclass
class ScanResult:
    text: str
    findings: list[Finding]  # accepted, non-overlapping, sorted by start
    discarded: list[Finding]  # below threshold, allowlisted, or overlapped
    timings_ms: dict[str, float] = field(default_factory=dict)
    normalized_changed: bool = False

    @property
    def applied(self) -> list[Finding]:
        return [
            f
            for f in self.findings
            if f.status is FindingStatus.APPLIED and f.action is not EntityAction.ALLOW
        ]

    @property
    def blocking(self) -> list[Finding]:
        return [f for f in self.applied if f.action is EntityAction.BLOCK]

    def detectors_fired(self) -> list[str]:
        return sorted({f.detector for f in self.applied})

    def entity_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for f in self.applied:
            counts[f.entity_type.value] = counts.get(f.entity_type.value, 0) + 1
        return counts

    def explain(self) -> list[dict[str, object]]:
        return [f.public_dict() for f in self.findings + self.discarded]


def canonical_value(etype: EntityType, normalized_value: str) -> str:
    """Canonical form used to give the same value the same placeholder."""
    if etype in (EntityType.CREDIT_CARD, EntityType.PHONE, EntityType.SSN):
        return re.sub(r"\D", "", normalized_value)
    if etype is EntityType.EMAIL:
        v = normalized_value.lower()
        v = re.sub(r"\s*(?:\[\s*at\s*\]|\(\s*at\s*\)|\{\s*at\s*\}|\s+at\s+)\s*", "@", v)
        v = re.sub(r"\s*(?:\[\s*dot\s*\]|\(\s*dot\s*\)|\{\s*dot\s*\}|\s+dot\s+)\s*", ".", v)
        return re.sub(r"\s+", "", v)
    return " ".join(normalized_value.lower().split())


class DLPEngine:
    def __init__(self, detectors: Sequence[Detector], ner_backend: str = "none") -> None:
        self.detectors = list(detectors)
        self.ner_backend = ner_backend

    @classmethod
    def default(cls, ner_backend: str = "spacy") -> DLPEngine:
        first_names = load_first_names()
        detectors: list[Detector] = list(default_regex_detectors(first_names))  # type: ignore[arg-type]
        ner = build_ner_detector(ner_backend, first_names)
        actual = "off"
        if ner is not None:
            detectors.append(ner)
            actual = ner.name.split(".", 1)[1]
        return cls(detectors, ner_backend=actual)

    def scan(self, text: str, policy: Policy, *, use_ner: bool = True) -> ScanResult:
        norm = normalize(text)
        candidates: list[Finding] = []
        timings: dict[str, float] = {}
        for det in self.detectors:
            if not use_ner and det.name.startswith("ner."):
                continue
            t0 = time.perf_counter()
            try:
                found = det.detect(norm.text)
            except Exception as exc:
                raise DetectorFailure(f"detector {det.name} failed: {type(exc).__name__}") from exc
            timings[det.name] = (time.perf_counter() - t0) * 1000
            for f in found:
                n_start, n_end = f.start, f.end
                f.canonical = canonical_value(f.entity_type, norm.text[n_start:n_end])
                f.start, f.end = norm.to_original_span(n_start, n_end)
                f.value = text[f.start : f.end]
                candidates.append(f)

        eligible: list[Finding] = []
        discarded: list[Finding] = []
        for f in candidates:
            rule = policy.rule(f.entity_type)
            if f.entity_type in (EntityType.PERSON_NAME, EntityType.ORG) and policy.is_allowlisted(f.value):
                f.status, f.action = FindingStatus.ALLOWLISTED, EntityAction.ALLOW
                discarded.append(f)
            elif f.confidence < rule.min_confidence:
                f.status, f.action = FindingStatus.BELOW_THRESHOLD, EntityAction.ALLOW
                discarded.append(f)
            else:
                f.status, f.action = FindingStatus.APPLIED, rule.action
                eligible.append(f)

        accepted: list[Finding] = []
        for f in sorted(eligible, key=lambda x: (-x.priority, -x.confidence, -(x.end - x.start), x.start)):
            if any(f.start < a.end and a.start < f.end for a in accepted):
                f.status = FindingStatus.OVERLAPPED
                discarded.append(f)
                continue
            accepted.append(f)
        accepted.sort(key=lambda x: x.start)
        return ScanResult(text, accepted, discarded, timings, norm.changed)
