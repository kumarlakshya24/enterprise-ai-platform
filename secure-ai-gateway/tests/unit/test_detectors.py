"""Unit tests for each DLP detector and the engine's policy application."""

from __future__ import annotations

import pytest

from aegis.demo import fakes
from aegis.dlp.engine import DLPEngine
from aegis.dlp.ner import load_first_names
from aegis.dlp.normalize import normalize
from aegis.dlp.regex_detectors import (
    CreditCardDetector,
    EmailDetector,
    NameCueDetector,
    ObfuscatedEmailDetector,
    PhoneDetector,
    SecretDetector,
    SSNDetector,
    luhn_valid,
)
from aegis.policy.schema import Policy
from aegis.types import EntityAction, EntityType, FindingStatus


def types_of(findings: list) -> list[str]:
    return [f.entity_type.value for f in findings]


# ----------------------------------------------------------------- email


def test_email_basic_and_trailing_punctuation() -> None:
    f = EmailDetector().detect("write to dana.holloway@example.com.")
    assert len(f) == 1 and f[0].confidence == 0.99
    assert "write to dana.holloway@example.com."[f[0].start : f[0].end] == "dana.holloway@example.com"


@pytest.mark.parametrize(
    "text",
    [
        "dana dot holloway at example dot com",
        "dana[at]example[dot]com",
        "dana (at) example (dot) com",
        "dana @ example . com",
    ],
)
def test_obfuscated_email(text: str) -> None:
    f = ObfuscatedEmailDetector().detect(f"contact {text} today")
    assert types_of(f) == ["EMAIL"], text


@pytest.mark.parametrize(
    "text", ["Let's meet at noon. Then lunch.", "email me at work dot com", "I am at home."]
)
def test_obfuscated_email_ignores_prose(text: str) -> None:
    assert ObfuscatedEmailDetector().detect(text) == []


# ----------------------------------------------------------------- phone


def test_phone_formatted_and_context() -> None:
    f = PhoneDetector().detect("call me on (312) 555-0142 please")
    assert types_of(f) == ["PHONE"] and f[0].confidence >= 0.9


def test_phone_bare_digits_low_confidence_without_context() -> None:
    f = PhoneDetector().detect("order 3125550142 shipped")
    assert f and f[0].confidence < 0.6  # below the default PHONE threshold


def test_phone_international() -> None:
    assert types_of(PhoneDetector().detect("UK office +44 20 7946 0958")) == ["PHONE"]


# ----------------------------------------------------------------- cards


def test_luhn() -> None:
    assert luhn_valid("4111111111111111")
    assert not luhn_valid("4111111111111112")


@pytest.mark.parametrize(
    "text",
    [
        "4111 1111 1111 1111",
        "4111-1111-1111-1111",
        "4111111111111111",
        "5555 5555 5555 4444",
        "3782 822463 10005",
        "4 1 1 1 1 1 1 1 1 1 1 1 1 1 1 1",
    ],
)
def test_card_formats(text: str) -> None:
    f = CreditCardDetector().detect(f"card: {text}.")
    assert types_of(f) == ["CREDIT_CARD"] and f[0].confidence >= 0.8, text


def test_card_rejects_luhn_failures_and_repeated_digits() -> None:
    assert CreditCardDetector().detect("4111 1111 1111 1112") == []
    assert CreditCardDetector().detect("0000 0000 0000 0000") == []


def test_card_fullwidth_digits_via_normalization(dlp_engine: DLPEngine, default_policy: Policy) -> None:
    text = "card ４１１１ １１１１ １１１１ １１１１ ok"
    r = dlp_engine.scan(text, default_policy)
    cards = [f for f in r.applied if f.entity_type is EntityType.CREDIT_CARD]
    assert len(cards) == 1
    assert text[cards[0].start : cards[0].end] == "４１１１ １１１１ １１１１ １１１１"
    assert cards[0].canonical == "4111111111111111"


# ----------------------------------------------------------------- SSN


def test_ssn_valid_and_invalid_areas() -> None:
    d = SSNDetector()
    assert types_of(d.detect("SSN 987-65-4321")) == ["SSN"]
    assert d.detect("id 000-12-3456") == []
    assert d.detect("id 666-12-3456") == []
    assert d.detect("no context 987654321") == []
    assert types_of(d.detect("my social security number is 987654321")) == ["SSN"]


# ----------------------------------------------------------------- secrets


@pytest.mark.parametrize(
    ("value", "etype"),
    [
        (fakes.fake_openai_key(), EntityType.API_KEY),
        (fakes.fake_aws_key_id(), EntityType.API_KEY),
        (fakes.fake_github_token(), EntityType.API_KEY),
        (fakes.fake_jwt(), EntityType.API_KEY),
        (fakes.fake_private_key(), EntityType.PRIVATE_KEY),
    ],
)
def test_known_secret_formats(value: str, etype: EntityType) -> None:
    f = SecretDetector().detect(f"here: {value} end")
    assert etype.value in types_of(f)


def test_password_assignments_and_url_credentials() -> None:
    f = SecretDetector().detect("password: hunter22 and postgres://admin:S3cr3tPw@db.internal/app")
    values = sorted(
        "password: hunter22 and postgres://admin:S3cr3tPw@db.internal/app"[x.start : x.end] for x in f
    )
    assert values == ["S3cr3tPw", "hunter22"]


@pytest.mark.parametrize(
    "text",
    [
        "password: ${DB_PASSWORD}",
        "token=<redacted>",
        "password: required",
        "commit 3f2a9c1e8b7d6a5f4e3d2c1b0a9f8e7d6c5b4a3f",
        "id 123e4567-e89b-12d3-a456-426614174000",
    ],
)
def test_secret_negatives(text: str) -> None:
    assert [f for f in SecretDetector().detect(text) if f.confidence >= 0.6] == []


def test_high_entropy_token() -> None:
    assert "API_KEY" in types_of(SecretDetector().detect(f"use {fakes.fake_high_entropy()} for auth"))


# ----------------------------------------------------------------- names


def test_name_cue_catches_lowercase_names() -> None:
    d = NameCueDetector(load_first_names())
    f = d.detect("hello, my name is dana holloway and I need help")
    assert (
        len(f) == 1
        and "hello, my name is dana holloway and I need help"[f[0].start : f[0].end] == "dana holloway"
    )


@pytest.mark.parametrize(
    "text", ["I am Concerned about this", "Dear Hiring Manager,", "Thanks for your help"]
)
def test_name_cue_negatives(text: str) -> None:
    assert NameCueDetector(load_first_names()).detect(text) == []


def test_ner_person_and_org(dlp_engine: DLPEngine, default_policy: Policy) -> None:
    r = dlp_engine.scan(
        "Customer Victor Okafor from Northwind Traders reported a duplicate charge.", default_policy
    )
    assert sorted(types_of(r.applied)) == ["ORG", "PERSON_NAME"]


@pytest.mark.parametrize(
    "text",
    [
        "Explain the difference between AWS Lambda and Google Cloud Run for a small API.",
        "Can Kubernetes autoscale pods based on Kafka consumer lag?",
        "Write a SQL query that returns the top 5 products by revenue in Q3.",
        "How do I configure retries with exponential backoff in a Python requests session?",
    ],
)
def test_no_false_redaction_on_technical_questions(
    dlp_engine: DLPEngine, default_policy: Policy, text: str
) -> None:
    r = dlp_engine.scan(text, default_policy)
    assert r.applied == [], [f.public_dict() for f in r.applied]
    # The raw NER hits are kept for explainability as allowlisted or below threshold.
    assert all(f.status in (FindingStatus.ALLOWLISTED, FindingStatus.BELOW_THRESHOLD) for f in r.discarded)


# ----------------------------------------------------------------- engine


def test_normalization_maps_offsets_through_zero_width_chars() -> None:
    n = normalize("da\u200bna@example.com")
    assert n.text == "dana@example.com"
    assert n.to_original_span(0, len(n.text)) == (0, 17)


def test_engine_zero_width_email_is_fully_covered(dlp_engine: DLPEngine, default_policy: Policy) -> None:
    text = "mail da\u200bna@example.com now"
    r = dlp_engine.scan(text, default_policy)
    emails = [f for f in r.applied if f.entity_type is EntityType.EMAIL]
    assert len(emails) == 1 and text[emails[0].start : emails[0].end] == "da\u200bna@example.com"


def test_engine_overlap_prefers_structured_detectors(dlp_engine: DLPEngine, default_policy: Policy) -> None:
    r = dlp_engine.scan("Hi, my name is Dana Holloway, email dana.holloway@example.com", default_policy)
    assert sorted(types_of(r.applied)) == ["EMAIL", "PERSON_NAME"]
    assert all(not (a.start < b.end and b.start < a.end) for a in r.applied for b in r.applied if a is not b)


def test_engine_applies_policy_actions(dlp_engine: DLPEngine, default_policy: Policy) -> None:
    r = dlp_engine.scan(f"key {fakes.fake_openai_key()} and {fakes.fake_private_key()}", default_policy)
    actions = {f.entity_type: f.action for f in r.applied}
    assert actions[EntityType.API_KEY] is EntityAction.REDACT
    assert actions[EntityType.PRIVATE_KEY] is EntityAction.BLOCK
    assert r.blocking


def test_engine_threshold_from_policy(dlp_engine: DLPEngine, default_policy: Policy) -> None:
    strict = default_policy.model_copy(deep=True)
    strict.entities[EntityType.PHONE].min_confidence = 0.99
    r = dlp_engine.scan("call (312) 555-0142", strict)
    assert r.applied == [] and r.discarded[0].status is FindingStatus.BELOW_THRESHOLD


def test_detector_failure_fails_closed(default_policy: Policy) -> None:
    from aegis.dlp.engine import DetectorFailure

    class Boom:
        name = "boom"

        def detect(self, text: str) -> list:
            raise ValueError("nope")

    with pytest.raises(DetectorFailure):
        DLPEngine([Boom()]).scan("anything", default_policy)
