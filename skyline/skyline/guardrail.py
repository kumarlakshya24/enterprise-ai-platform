"""Offline stand-in for the guardrail the template declares.

The stub scores what a regex and a phrase list can score: PII shapes, a few
denied-topic phrases, and prompt-attack phrases. Content filters (hate,
insults, misconduct) are configured on the resource and deliberately not
scored here. A case tagged as that gap must stay ALLOW.
"""

from __future__ import annotations

import re
import time
from typing import Any

PII_TYPES = ("EMAIL", "PHONE", "CREDIT_DEBIT_CARD_NUMBER", "AWS_ACCESS_KEY")
BLIND_FILTERS = ("HATE", "INSULTS", "MISCONDUCT")
PROMPT_PHRASES = (
    "ignore previous instructions",
    "reveal the system prompt",
    "you are now",
)
TOPIC_KEYWORDS: dict[str, tuple[str, ...]] = {
    "financial-advice": ("buy the stock", "price target", "guaranteed return"),
    "credential-request": ("password is", "api key is"),
}

_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_PHONE = re.compile(r"(?:\+?1[-.\s]?)?(?:\(\d{3}\)|\d{3})[-.\s]\d{3}[-.\s]\d{4}")
_AWS_KEY = re.compile(r"\bAKIA[0-9A-Z]{16}\b")
_CARD_RUN = re.compile(r"\b(?:\d[ -]*?){13,19}\b")


def luhn_ok(raw: str) -> bool:
    digits = [int(char) for char in raw if char.isdigit()]
    if not 13 <= len(digits) <= 19:
        return False
    total = 0
    alt = False
    for digit in reversed(digits):
        if alt:
            digit *= 2
            if digit > 9:
                digit -= 9
        total += digit
        alt = not alt
    return total % 10 == 0


def guardrail_properties(region: str) -> dict[str, Any]:
    """CloudFormation properties for AWS::Bedrock::Guardrail, fixture-shaped."""
    return {
        "Name": "skyline-platform",
        "Description": "Platform guardrail. User turn and model output, not retrieved context.",
        "BlockedInputMessaging": "Blocked by the Skyline guardrail.",
        "BlockedOutputsMessaging": "Blocked by the Skyline guardrail.",
        "ContentPolicyConfig": {
            "FiltersConfig": [
                {"Type": "HATE", "InputStrength": "HIGH", "OutputStrength": "HIGH"},
                {"Type": "INSULTS", "InputStrength": "HIGH", "OutputStrength": "HIGH"},
                {"Type": "MISCONDUCT", "InputStrength": "HIGH", "OutputStrength": "HIGH"},
                {"Type": "PROMPT_ATTACK", "InputStrength": "HIGH", "OutputStrength": "NONE"},
            ]
        },
        "TopicPolicyConfig": {
            "TopicsConfig": [
                {
                    "Name": "financial-advice",
                    "Definition": "Telling someone to buy or sell a security, or promising a return.",
                    "Examples": ["you should buy the stock today"],
                    "Type": "DENY",
                },
                {
                    "Name": "credential-request",
                    "Definition": "Asking for or repeating a password or an API key.",
                    "Examples": ["the password is swordfish"],
                    "Type": "DENY",
                },
            ]
        },
        "SensitiveInformationPolicyConfig": {
            "PiiEntitiesConfig": [{"Type": name, "Action": "BLOCK"} for name in PII_TYPES]
        },
        "Tags": [{"Key": "Project", "Value": "skyline"}, {"Key": "RegionNote", "Value": region}],
    }


def guardrail_meta() -> dict[str, Any]:
    return {
        "kind": "guardrail",
        "scans": ["user-turn", "model-output"],
        "doesNotScan": ["retrieved-context"],
        "stubBlindFilters": list(BLIND_FILTERS),
        "stubKeywords": {name: list(phrases) for name, phrases in TOPIC_KEYWORDS.items()},
        "promptAttackPhrases": list(PROMPT_PHRASES),
    }


def _card_hit(text: str) -> str | None:
    for match in _CARD_RUN.finditer(text):
        if luhn_ok(match.group(0)):
            return "CREDIT_DEBIT_CARD_NUMBER"
    return None


def evaluate(text: str) -> dict[str, Any]:
    """Return the stub verdict. First matching class is the headline; all hits are kept."""
    hits: list[dict[str, str]] = []
    if _EMAIL.search(text):
        hits.append({"filter": "pii", "detail": "EMAIL"})
    if _PHONE.search(text):
        hits.append({"filter": "pii", "detail": "PHONE"})
    card = _card_hit(text)
    if card:
        hits.append({"filter": "pii", "detail": card})
    if _AWS_KEY.search(text):
        hits.append({"filter": "pii", "detail": "AWS_ACCESS_KEY"})
    lowered = text.lower()
    for phrase in PROMPT_PHRASES:
        if phrase in lowered:
            hits.append({"filter": "prompt-attack", "detail": phrase})
            break
    for topic, phrases in TOPIC_KEYWORDS.items():
        for phrase in phrases:
            if phrase in lowered:
                hits.append({"filter": "topic", "detail": topic})
                break
    action = "INTERVENE" if hits else "ALLOW"
    headline = hits[0]["filter"] if hits else ""
    return {"action": action, "filter": headline, "hits": hits}


def score_cases(cases: list[dict[str, Any]]) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    enforced_ok = 0
    enforced = 0
    gaps = 0
    for case in cases:
        verdict = evaluate(str(case["text"]))
        ok = verdict["action"] == case["expect"]
        if case["expect"] == "INTERVENE" and case.get("filter"):
            ok = ok and verdict["filter"] == case["filter"]
        gap = str(case.get("gap") or "")
        if gap:
            gaps += 1
            # A gap case is only honest if the stub still allows it.
            ok = verdict["action"] == "ALLOW" and case["expect"] == "ALLOW"
        else:
            enforced += 1
            enforced_ok += int(ok)
        rows.append(
            {
                "id": case["id"],
                "text": case["text"],
                "expect": case["expect"],
                "action": verdict["action"],
                "filter": verdict["filter"],
                "hits": verdict["hits"],
                "gap": gap,
                "ok": ok,
            }
        )
    return {
        "rows": rows,
        "enforced": enforced,
        "enforced_ok": enforced_ok,
        "gaps": gaps,
        "blind_filters": list(BLIND_FILTERS),
        "passed": enforced_ok == enforced and gaps > 0 and all(row["ok"] for row in rows),
    }


def bench(cases: list[dict[str, Any]], rounds: int = 50) -> dict[str, float]:
    """Mean microseconds per evaluation. This is the stub, not Bedrock."""
    start = time.perf_counter()
    for _ in range(rounds):
        for case in cases:
            evaluate(str(case["text"]))
    elapsed = time.perf_counter() - start
    count = rounds * len(cases)
    return {"evaluations": float(count), "mean_us": (elapsed / count) * 1_000_000, "rounds": float(rounds)}
