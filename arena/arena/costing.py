"""Projected dollars and catalog latency.

The program cost is the part a single GPU-hour quote leaves out: review, repeats,
eval, and keeping an endpoint up. Inference is list price times the token budget
in the price card. Nothing here is an invoice.
"""

from __future__ import annotations

from collections.abc import Mapping


def per_request_usd(arm: str, card: Mapping[str, object]) -> float:
    spec = _arm(card, arm)
    model = _model(card, str(spec["model"]))
    incoming = int(spec["input_tokens"]) / 1_000_000 * float(model["input_per_mtok"])
    outgoing = int(spec["output_tokens"]) / 1_000_000 * float(model["output_per_mtok"])
    return round(incoming + outgoing, 6)


def model_latency_ms(arm: str, card: Mapping[str, object]) -> float:
    spec = _arm(card, arm)
    model = _model(card, str(spec["model"]))
    base = float(model["base_latency_ms"])
    extra = float(model["per_1k_input_ms"]) * int(spec["input_tokens"]) / 1000
    return round(base + extra, 2)


def monthly_usd(arm: str, volume: int, change_rate: str, card: Mapping[str, object]) -> float:
    spec = _arm(card, arm)
    months = int(card["amortization_months"])
    program = float(spec["program_usd"]) / months
    reindex = 0.0
    if arm == "rag":
        table = spec["reindex_usd_by_change"]
        assert isinstance(table, Mapping)
        reindex = float(table[change_rate])
    return round(per_request_usd(arm, card) * volume + program + reindex, 2)


def serving_stub(card: Mapping[str, object]) -> dict[str, dict[str, str]]:
    """Which Switchboard catalog model would serve the arm. Offline stand-in."""
    reasons = {
        "prompt": (
            "No passages. On the published Switchboard demo prompt, policy default "
            "picks balanced rather than fast-cheap."
        ),
        "rag": (
            "Same generator as prompt. The extra cost is context tokens, not a smarter "
            "model. Retrieval is the Lumen-shaped port, not Switchboard."
        ),
        "lora": (
            "The catalog has no adapter id. The stand-in maps the dedicated endpoint "
            "to premium under quality-first, and says so."
        ),
        "distilled": (
            "The student is the small model. On the same demo prompt, latency-first picks fast-cheap."
        ),
    }
    out: dict[str, dict[str, str]] = {}
    arms = card["arms"]
    assert isinstance(arms, Mapping)
    for arm, spec in arms.items():
        assert isinstance(spec, Mapping)
        model = _model(card, str(spec["model"]))
        out[str(arm)] = {
            "switchboard_model": str(model["switchboard_model"]),
            "policy": str(model["switchboard_policy"]),
            "reason": reasons[str(arm)],
            "source": "switchboard-stub",
        }
    return out


def _arm(card: Mapping[str, object], arm: str) -> Mapping[str, object]:
    arms = card["arms"]
    assert isinstance(arms, Mapping)
    spec = arms[arm]
    assert isinstance(spec, Mapping)
    return spec


def _model(card: Mapping[str, object], name: str) -> Mapping[str, object]:
    models = card["models"]
    assert isinstance(models, Mapping)
    model = models[name]
    assert isinstance(model, Mapping)
    return model
