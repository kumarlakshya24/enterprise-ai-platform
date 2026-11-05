"""Train the sensitivity classifier and export it to JSON (no pickle). Dev dependency: scikit-learn.

python -m aegis.classifier.train
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from aegis.classifier.model import LABEL_ORDER, MODEL_PATH, TOKEN_PATTERN, TfidfLogRegClassifier

ROOT = Path(__file__).resolve().parents[2]
TRAIN = ROOT / "data" / "classifier" / "train.jsonl"
TEST = ROOT / "data" / "classifier" / "test.jsonl"
REPORT = ROOT / "reports" / "classifier.md"


def _load(path: Path) -> tuple[list[str], list[str]]:
    rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    return [r["text"] for r in rows], [r["label"] for r in rows]


def _metrics(y_true: list[str], y_pred: list[str]) -> dict[str, Any]:
    out: dict[str, Any] = {"accuracy": sum(a == b for a, b in zip(y_true, y_pred, strict=True)) / len(y_true)}
    per: dict[str, dict[str, float]] = {}
    for lab in LABEL_ORDER:
        tp = sum(1 for a, b in zip(y_true, y_pred, strict=True) if a == lab and b == lab)
        fp = sum(1 for a, b in zip(y_true, y_pred, strict=True) if a != lab and b == lab)
        fn = sum(1 for a, b in zip(y_true, y_pred, strict=True) if a == lab and b != lab)
        p = tp / (tp + fp) if tp + fp else 0.0
        r = tp / (tp + fn) if tp + fn else 0.0
        per[lab] = {
            "precision": p,
            "recall": r,
            "f1": 2 * p * r / (p + r) if p + r else 0.0,
            "support": tp + fn,
        }
    out["per_label"] = per
    # The security question: is sensitive (CONFIDENTIAL+) context kept away from the external route?
    sens = {"CONFIDENTIAL", "RESTRICTED"}
    tp = sum(1 for a, b in zip(y_true, y_pred, strict=True) if a in sens and b in sens)
    fn = sum(1 for a, b in zip(y_true, y_pred, strict=True) if a in sens and b not in sens)
    fp = sum(1 for a, b in zip(y_true, y_pred, strict=True) if a not in sens and b in sens)
    out["sensitive_vs_not"] = {
        "recall": tp / (tp + fn) if tp + fn else 0.0,
        "precision": tp / (tp + fp) if tp + fp else 0.0,
        "false_negatives": fn,
        "false_positives": fp,
    }
    conf = {a: dict.fromkeys(LABEL_ORDER, 0) for a in LABEL_ORDER}
    for a, b in zip(y_true, y_pred, strict=True):
        conf[a][b] += 1
    out["confusion"] = conf
    return out


def train(c_values: tuple[float, ...] = (1.0, 3.0, 10.0, 30.0)) -> dict[str, Any]:
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.linear_model import LogisticRegression
    from sklearn.model_selection import cross_val_score
    from sklearn.pipeline import make_pipeline

    x_train, y_train = _load(TRAIN)
    x_test, y_test = _load(TEST)

    def make(c: float) -> Any:
        return make_pipeline(
            TfidfVectorizer(
                lowercase=True, ngram_range=(1, 2), sublinear_tf=True, token_pattern=TOKEN_PATTERN
            ),
            LogisticRegression(C=c, max_iter=5000, class_weight="balanced"),
        )

    cv = {c: float(cross_val_score(make(c), x_train, y_train, cv=5).mean()) for c in c_values}
    best_c = max(cv, key=lambda c: cv[c])
    pipe = make(best_c).fit(x_train, y_train)
    vec, clf = pipe.steps[0][1], pipe.steps[1][1]

    classes = list(clf.classes_)
    order = [classes.index(lab) for lab in LABEL_ORDER]
    vocab: dict[str, list[Any]] = {}
    for term, j in vec.vocabulary_.items():
        vocab[term] = [round(float(vec.idf_[j]), 6), [round(float(clf.coef_[k][j]), 6) for k in order]]
    model = {
        "format": "aegis-tfidf-lr-v1",
        "labels": LABEL_ORDER,
        "ngram_range": [1, 2],
        "sublinear_tf": True,
        "token_pattern": TOKEN_PATTERN,
        "intercept": [round(float(clf.intercept_[k]), 6) for k in order],
        "vocab": dict(sorted(vocab.items())),
        "trained_at": datetime.now(UTC).date().isoformat(),
        "train_rows": len(x_train),
        "train_sha256": hashlib.sha256(TRAIN.read_bytes()).hexdigest(),
        "C": best_c,
    }
    raw = json.dumps(model, separators=(",", ":"), sort_keys=True).encode()
    MODEL_PATH.write_bytes(raw)
    MODEL_PATH.with_suffix(".sha256").write_text(hashlib.sha256(raw).hexdigest() + "\n")

    exported = TfidfLogRegClassifier.load(MODEL_PATH)
    y_pred_sklearn = list(pipe.predict(x_test))
    y_pred = [exported.classify(t).label.name for t in x_test]
    parity = sum(a == b for a, b in zip(y_pred, y_pred_sklearn, strict=True)) / len(y_pred)
    test_metrics = _metrics(y_test, y_pred)
    train_metrics = _metrics(y_train, [exported.classify(t).label.name for t in x_train])
    misses = [
        {"text": t, "expected": a, "predicted": b}
        for t, a, b in zip(x_test, y_test, y_pred, strict=True)
        if a != b
    ]
    result = {
        "cv_accuracy_by_C": cv,
        "best_C": best_c,
        "vocab_size": len(vocab),
        "train": train_metrics,
        "test": test_metrics,
        "sklearn_parity": parity,
        "misses": misses,
        "model_sha256": hashlib.sha256(raw).hexdigest(),
    }
    _write_report(result, len(x_train), len(x_test))
    return result


def _write_report(r: dict[str, Any], n_train: int, n_test: int) -> None:
    t = r["test"]
    lines = [
        "# Sensitivity classifier report",
        "",
        "Generated by `make train` (`python -m aegis.classifier.train`). Do not edit by hand.",
        "",
        f"* Model: TF-IDF (1-2 grams, sublinear tf) + multinomial logistic regression, C={r['best_C']}",
        f"* Training rows: {n_train} (synthetic, template-generated, seeded)",
        f"* Held-out test rows: {n_test} (hand-written, different phrasing from the templates)",
        f"* Vocabulary: {r['vocab_size']} n-grams. Exported to JSON, SHA-256 `{r['model_sha256'][:16]}...`",
        f"* Pure-Python inference agrees with scikit-learn on {r['sklearn_parity'] * 100:.1f}% of test rows",
        "",
        "## Held-out test set",
        "",
        f"Accuracy: **{t['accuracy'] * 100:.1f}%** (train accuracy {r['train']['accuracy'] * 100:.1f}%, "
        f"5-fold CV on train {max(r['cv_accuracy_by_C'].values()) * 100:.1f}%)",
        "",
        "| Label | Precision | Recall | F1 | Support |",
        "|-------|-----------|--------|----|---------|",
    ]
    for lab, m in t["per_label"].items():
        lines.append(
            f"| {lab} | {m['precision']:.2f} | {m['recall']:.2f} | {m['f1']:.2f} | {int(m['support'])} |"
        )
    s = t["sensitive_vs_not"]
    lines += [
        "",
        "### The number that matters for leakage",
        "",
        "Binary view: is CONFIDENTIAL or RESTRICTED context kept off the external route?",
        "",
        f"* Recall on sensitive context: **{s['recall'] * 100:.1f}%** "
        f"({s['false_negatives']} sensitive prompts labelled PUBLIC/INTERNAL)",
        f"* Precision: {s['precision'] * 100:.1f}% ({s['false_positives']} non-sensitive prompts over-protected)",
        "",
        "Note: the gateway does not rely on the classifier alone. Deterministic context markers and the",
        "low-confidence escalation rule add protection on top of these raw model numbers; the red-team",
        "report (`reports/redteam.md`) measures the full pipeline.",
        "",
        "### Confusion matrix (rows = expected, columns = predicted)",
        "",
        "| | " + " | ".join(LABEL_ORDER) + " |",
        "|---|" + "---|" * len(LABEL_ORDER),
    ]
    for a in LABEL_ORDER:
        lines.append(f"| {a} | " + " | ".join(str(t["confusion"][a][b]) for b in LABEL_ORDER) + " |")
    lines += ["", "### Misclassified test rows", ""]
    if not r["misses"]:
        lines.append("None.")
    for m in r["misses"]:
        lines.append(f"* expected **{m['expected']}**, got **{m['predicted']}**: {m['text']}")
    lines += [
        "",
        "## Limitations",
        "",
        "* Synthetic training data encodes one person's idea of what is confidential. A real deployment",
        "  needs labelled samples from the company's own documents and a feedback loop from overrides.",
        '* A bag-of-words model does not understand negation ("this is not confidential").',
        "* The held-out set is small (100 rows), so each miss moves accuracy by a full point.",
    ]
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
    res = train()
    print(json.dumps({k: res[k] for k in ("best_C", "vocab_size", "sklearn_parity")}, indent=2))
    print(
        "test accuracy",
        round(res["test"]["accuracy"], 3),
        "sensitive recall",
        round(res["test"]["sensitive_vs_not"]["recall"], 3),
    )
    for m in res["misses"]:
        print("MISS", m["expected"], "->", m["predicted"], "|", m["text"][:100])
