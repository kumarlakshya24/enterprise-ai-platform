"""Pure-Python inference for the exported TF-IDF + logistic regression sensitivity classifier.

No pickle, no numpy, no scikit-learn at runtime. The artifact is JSON and its SHA-256 is checked
at load, so a swapped model file cannot execute code and cannot load silently.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections import Counter
from pathlib import Path
from typing import Any

from aegis.classifier.types import Classification
from aegis.types import Label

MODEL_PATH = Path(__file__).with_name("sensitivity_model.json")
TOKEN_PATTERN = r"(?u)\b\w\w+\b"  # noqa: S105 - a regex, not a secret
LABEL_ORDER = [label.name for label in Label]


class ModelIntegrityError(RuntimeError):
    pass


class TfidfLogRegClassifier:
    def __init__(self, model: dict[str, Any], digest: str) -> None:
        if model.get("format") != "aegis-tfidf-lr-v1":
            raise ModelIntegrityError("unknown classifier format")
        self.labels = [Label[name] for name in model["labels"]]
        self.intercept: list[float] = model["intercept"]
        self.vocab: dict[str, tuple[float, list[float]]] = {
            term: (float(v[0]), [float(c) for c in v[1]]) for term, v in model["vocab"].items()
        }
        self.min_n, self.max_n = model["ngram_range"]
        self.sublinear = bool(model["sublinear_tf"])
        self._token = re.compile(model["token_pattern"])
        self.version = f"tfidf-lr-{digest[:12]}"

    @classmethod
    def load(cls, path: Path = MODEL_PATH, expected_sha256: str | None = None) -> TfidfLogRegClassifier:
        raw = path.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        if expected_sha256 is None:
            sha_file = path.with_suffix(".sha256")
            expected_sha256 = sha_file.read_text().strip() if sha_file.exists() else None
        if expected_sha256 is None or digest != expected_sha256:
            raise ModelIntegrityError("classifier artifact hash mismatch; refusing to load")
        return cls(json.loads(raw), digest)

    def _features(self, text: str) -> dict[str, float]:
        tokens = self._token.findall(text.lower())
        grams: list[str] = []
        for n in range(self.min_n, self.max_n + 1):
            grams += [" ".join(tokens[i : i + n]) for i in range(len(tokens) - n + 1)]
        counts = Counter(g for g in grams if g in self.vocab)
        x: dict[str, float] = {}
        for g, c in counts.items():
            tf = 1.0 + math.log(c) if self.sublinear else float(c)
            x[g] = tf * self.vocab[g][0]
        norm = math.sqrt(sum(v * v for v in x.values()))
        if norm > 0:
            x = {g: v / norm for g, v in x.items()}
        return x

    def classify(self, text: str, min_confidence: float = 0.0) -> Classification:
        x = self._features(text)
        scores = list(self.intercept)
        for g, v in x.items():
            coefs = self.vocab[g][1]
            for k in range(len(scores)):
                scores[k] += v * coefs[k]
        m = max(scores)
        exps = [math.exp(s - m) for s in scores]
        total = sum(exps)
        probs = [e / total for e in exps]
        ranked = sorted(range(len(probs)), key=lambda k: probs[k], reverse=True)
        top, second = ranked[0], ranked[1]
        label = self.labels[top]
        escalated_from: Label | None = None
        if probs[top] < min_confidence and self.labels[second] > label:
            escalated_from, label = label, self.labels[second]
            top = second
        contributions = sorted(
            ((g, v * self.vocab[g][1][top]) for g, v in x.items()), key=lambda gv: gv[1], reverse=True
        )
        top_features = [(g, w) for g, w in contributions[:5] if w > 0]
        return Classification(
            label=label,
            confidence=probs[top],
            probabilities={self.labels[k].name: probs[k] for k in range(len(probs))},
            top_features=top_features,
            escalated_from=escalated_from,
            model_version=self.version,
        )


def load_default_classifier() -> TfidfLogRegClassifier:
    return TfidfLogRegClassifier.load(MODEL_PATH)
