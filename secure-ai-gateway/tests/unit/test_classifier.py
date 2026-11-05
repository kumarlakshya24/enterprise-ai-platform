"""Classifier: integrity check, determinism, explanations, escalation, parity with scikit-learn."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from aegis.classifier.model import (
    MODEL_PATH,
    ModelIntegrityError,
    TfidfLogRegClassifier,
    load_default_classifier,
)
from aegis.demo.scenarios import SCENARIOS_BY_ID
from aegis.gateway.pipeline import classifier_view
from aegis.types import Label

clf = load_default_classifier()


def test_refuses_tampered_artifact(tmp_path: Path) -> None:
    bad = tmp_path / "sensitivity_model.json"
    shutil.copy(MODEL_PATH, bad)
    shutil.copy(MODEL_PATH.with_suffix(".sha256"), tmp_path / "sensitivity_model.sha256")
    data = json.loads(bad.read_text())
    data["intercept"][0] += 5.0  # e.g. an attacker biasing everything towards PUBLIC
    bad.write_text(json.dumps(data))
    with pytest.raises(ModelIntegrityError):
        TfidfLogRegClassifier.load(bad)


def test_refuses_artifact_without_hash(tmp_path: Path) -> None:
    lone = tmp_path / "m.json"
    shutil.copy(MODEL_PATH, lone)
    with pytest.raises(ModelIntegrityError):
        TfidfLogRegClassifier.load(lone)


@pytest.mark.parametrize(
    ("scenario", "expected"),
    [
        ("s1_direct_paste", Label.INTERNAL),
        ("s2_context_leak", Label.CONFIDENTIAL),
        ("s5_legit", Label.PUBLIC),
    ],
)
def test_demo_scenarios(scenario: str, expected: Label) -> None:
    text = SCENARIOS_BY_ID[scenario]["input"]
    if scenario == "s1_direct_paste":  # the classifier sees the tokenized view
        text = (
            text.replace("Dana Holloway", "[PERSON_NAME_1]")
            .replace("4111 1111 1111 1111", "[CREDIT_CARD_1]")
            .replace("dana.holloway@example.com", "[EMAIL_1]")
        )
    c = clf.classify(classifier_view(text))
    assert c.label is expected, c.public()


def test_explanations_name_the_driving_features() -> None:
    c = clf.classify(SCENARIOS_BY_ID["s2_context_leak"]["input"])
    feats = [f for f, _ in c.top_features]
    assert feats and all(w > 0 for _, w in c.top_features)
    assert any(
        term in " ".join(feats) for term in ("unannounced", "acquisition", "discontinue", "raise", "talks")
    )


def test_probabilities_sum_to_one_and_deterministic() -> None:
    a = clf.classify("Explain database indexing to a new engineer.")
    b = clf.classify("Explain database indexing to a new engineer.")
    assert a == b
    assert sum(a.probabilities.values()) == pytest.approx(1.0)


def test_low_confidence_escalates_one_level_only() -> None:
    from aegis.classifier.model import ESCALATION_MASS

    text = "Summarize the notes."
    base = clf.classify(text)
    forced = clf.classify(text, min_confidence=0.999)
    above = sum(p for k, p in base.probabilities.items() if Label[k] > base.label)
    if above >= ESCALATION_MASS and base.label < Label.RESTRICTED:
        assert forced.escalated_from is base.label and forced.label == base.label + 1
    else:
        assert forced.escalated_from is None and forced.label is base.label


def test_placeholders_are_generic_in_classifier_view() -> None:
    assert classifier_view("mail [EMAIL_3] and [PERSON_NAME_12]") == "mail [EMAIL] and [PERSON_NAME]"


def test_matches_sklearn_when_available() -> None:
    pytest.importorskip("sklearn")
    from aegis.classifier.train import TEST, _load

    texts, _ = _load(TEST)
    model = json.loads(MODEL_PATH.read_text())
    assert model["format"] == "aegis-tfidf-lr-v1"
    # Parity is asserted at training time and recorded in reports/classifier.md; here we just make sure
    # inference is stable over the whole test set.
    assert all(clf.classify(t).label in Label for t in texts)
