"""Named-entity detection for PERSON and ORG.

spaCy's small English model does not expose calibrated probabilities, and on technical text
it over-fires (`Kafka` as PERSON, `SQL` as ORG). We turn its raw labels into a confidence with
simple, explainable heuristics, and let the policy's public-term allowlist remove the rest.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterable
from importlib import resources
from typing import Any

from aegis.dlp.base import PRIORITY_NER
from aegis.types import EntityType, Finding

log = logging.getLogger("aegis.dlp.ner")

_CORP_SUFFIX = re.compile(
    r"\b(inc|llc|ltd|corp|corporation|co|company|gmbh|plc|ag|sa|bank|traders|industries|group|holdings"
    r"|labs|partners|capital|systems|solutions|technologies|enterprises|associates|foundation|university)\.?$",
    re.IGNORECASE,
)
_CUES_BEFORE = re.compile(
    r"(my name is|i am|i'm|this is|dear|hi|hello|customer|client|from|mr\.?|ms\.?|mrs\.?|dr\.?|ask|cc|"
    r"contact|employee|manager|signed|regards|thanks)\W*$",
    re.IGNORECASE,
)


def load_first_names() -> list[str]:
    text = resources.files("aegis.dlp.data").joinpath("first_names.txt").read_text()
    return [ln.strip() for ln in text.splitlines() if ln.strip() and not ln.startswith("#")]


def _person_confidence(ent_text: str, before: str, first_names: frozenset[str]) -> tuple[float, str]:
    tokens = ent_text.split()
    reasons: list[str] = []
    if len(tokens) >= 2:
        conf = 0.7
        reasons.append("multi-token")
    else:
        conf = 0.45
        reasons.append("single token")
    if tokens and tokens[0].lower().strip(".,") in first_names:
        conf += 0.15
        reasons.append("known first name")
    elif len(tokens) >= 2:
        conf -= 0.15
        reasons.append("unknown first name")
    if ent_text.islower():
        conf -= 0.05
        reasons.append("lowercase")
    if any(ch.isdigit() for ch in ent_text):
        conf -= 0.3
        reasons.append("contains digits")
    if _CUES_BEFORE.search(before):
        conf += 0.1
        reasons.append("introduced by cue")
    return max(0.0, min(conf, 0.97)), ", ".join(reasons)


def _org_confidence(ent_text: str, before: str) -> tuple[float, str]:
    tokens = ent_text.split()
    reasons: list[str] = []
    if len(tokens) == 1 and ent_text.isupper() and len(ent_text) <= 5:
        return 0.3, "short acronym"
    conf = 0.72 if len(tokens) >= 2 else 0.5
    reasons.append("multi-token" if len(tokens) >= 2 else "single token")
    if _CORP_SUFFIX.search(ent_text):
        conf += 0.18
        reasons.append("corporate suffix")
    if _CUES_BEFORE.search(before):
        conf += 0.05
        reasons.append("introduced by cue")
    return min(conf, 0.95), ", ".join(reasons)


class SpacyNERDetector:
    name = "ner.spacy"

    def __init__(self, first_names: Iterable[str], model: str = "en_core_web_sm") -> None:
        import spacy  # imported lazily: heavy

        # Only the NER component is needed; its tok2vec is internal in the sm pipeline.
        self._nlp: Any = spacy.load(
            model, disable=["tok2vec", "tagger", "parser", "attribute_ruler", "lemmatizer", "senter"]
        )
        self.first_names = frozenset(n.lower() for n in first_names)
        self.model = model

    def detect(self, text: str) -> list[Finding]:
        doc = self._nlp(text)
        out: list[Finding] = []
        for ent in doc.ents:
            if ent.label_ not in ("PERSON", "ORG"):
                continue
            ent_text = ent.text.strip()
            if not ent_text or ent_text.startswith("[") or "@" in ent_text:
                continue  # our own placeholders, or emails handled by regex
            before = text[max(0, ent.start_char - 20) : ent.start_char]
            label = ent.label_
            tokens = ent_text.split()
            # spaCy sometimes tags "Morgan Vale" as ORG. A known first name + no corporate suffix
            # is much more likely a person.
            if (
                label == "ORG"
                and 2 <= len(tokens) <= 3
                and tokens[0].lower() in self.first_names
                and not _CORP_SUFFIX.search(ent_text)
            ):
                label = "PERSON"
            if label == "PERSON":
                conf, why = _person_confidence(ent_text, before, self.first_names)
                etype = EntityType.PERSON_NAME
            else:
                conf, why = _org_confidence(ent_text, before)
                etype = EntityType.ORG
            out.append(
                Finding(
                    etype,
                    ent.start_char,
                    ent.start_char + len(ent.text.rstrip()),
                    conf,
                    self.name,
                    f"spaCy {ent.label_} ({why})",
                    priority=PRIORITY_NER,
                )
            )
        return out


class HeuristicNameDetector:
    """Fallback when spaCy is unavailable: Title-case bigrams starting with a known first name."""

    name = "ner.heuristic"
    _re = re.compile(r"\b([A-Z][a-z]+)\s+([A-Z][a-z'’-]+)(?:\s+([A-Z][a-z'’-]+))?\b")

    def __init__(self, first_names: Iterable[str]) -> None:
        self.first_names = frozenset(n.lower() for n in first_names)

    def detect(self, text: str) -> list[Finding]:
        out: list[Finding] = []
        for m in self._re.finditer(text):
            if m.group(1).lower() not in self.first_names:
                continue
            out.append(
                Finding(
                    EntityType.PERSON_NAME,
                    m.start(),
                    m.end(),
                    0.75,
                    self.name,
                    "Title-case name starting with a known first name (heuristic fallback)",
                    priority=PRIORITY_NER,
                )
            )
        return out


def build_ner_detector(
    backend: str, first_names: list[str]
) -> SpacyNERDetector | HeuristicNameDetector | None:
    if backend == "off":
        return None
    if backend == "spacy":
        try:
            return SpacyNERDetector(first_names)
        except Exception as exc:  # model missing, import error
            log.warning(
                "spaCy NER unavailable (%s); falling back to heuristic name detector", type(exc).__name__
            )
    return HeuristicNameDetector(first_names)
