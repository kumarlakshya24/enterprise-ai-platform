"""Cohen's kappa for two raters on a binary label. This is agreement, not accuracy."""

from __future__ import annotations


def confusion(gold: list[bool], pred: list[bool]) -> dict[str, int]:
    if len(gold) != len(pred):
        raise ValueError("gold and pred length mismatch")
    tp = fp = tn = fn = 0
    for left, right in zip(gold, pred, strict=True):
        if left and right:
            tp += 1
        elif right and not left:
            fp += 1
        elif left and not right:
            fn += 1
        else:
            tn += 1
    return {"tp": tp, "fp": fp, "tn": tn, "fn": fn}


def cohen_kappa(gold: list[bool], pred: list[bool]) -> float:
    """κ = (p_o - p_e) / (1 - p_e). Returns 1.0 when both raters are constant and agree."""

    n = len(gold)
    if n == 0:
        raise ValueError("empty rating")
    if len(pred) != n:
        raise ValueError("gold and pred length mismatch")
    observed = sum(1 for left, right in zip(gold, pred, strict=True) if left == right) / n
    gold_pos = sum(1 for value in gold if value) / n
    pred_pos = sum(1 for value in pred if value) / n
    expected = gold_pos * pred_pos + (1 - gold_pos) * (1 - pred_pos)
    if expected == 1.0:
        return 1.0
    return (observed - expected) / (1.0 - expected)
