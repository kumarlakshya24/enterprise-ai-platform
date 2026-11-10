"""Pick an arm from saved slice metrics and a scenario.

The rules are a ceiling. A scenario can demand citations, a change rate, an SLO,
and a budget. It cannot waive the quality floor. Weekly change eliminates both
tune arms even when their frozen-holdout score looks fine: the weights do not
move when the runbook does.
"""

from __future__ import annotations

from collections.abc import Mapping

from arena.arms import ARMS
from arena.corpus import Item
from arena.costing import model_latency_ms, monthly_usd, per_request_usd

SLICE_FOR = {
    ("stable", "full"): "freeze_full",
    ("stable", "common_short"): "freeze_common_short",
    ("monthly", "full"): "current_full",
    ("monthly", "common_short"): "current_common_short",
    ("weekly", "full"): "current_full",
    ("weekly", "common_short"): "current_common_short",
}


def slice_name(change_rate: str, scope: str) -> str:
    try:
        return SLICE_FOR[(change_rate, scope)]
    except KeyError as exc:
        raise ValueError(f"unknown scenario world {change_rate}/{scope}") from exc


def decide(
    metrics: Mapping[str, Mapping[str, Mapping[str, object]]],
    scenario: Mapping[str, object],
    card: Mapping[str, object],
    policy: Mapping[str, object],
    overhead_p50: Mapping[str, float] | None = None,
) -> dict[str, object]:
    # Overhead is reported beside the decision. It is not added to catalog latency:
    # a 0.1 ms measurement must not move an 80 ms SLO.
    overhead_p50 = overhead_p50 or {}
    name = slice_name(str(scenario["change_rate"]), str(scenario["scope"]))
    floor = float(policy["quality_floor"])
    cite_floor = float(policy["citation_floor"])
    stale_floor = float(policy["staleness_floor"])
    tune_raw = policy["tune_arms"]
    if not isinstance(tune_raw, list):
        raise ValueError("policy tune_arms must be a list")
    tune_arms = {str(arm) for arm in tune_raw}
    margin = float(policy["quality_margin_vs_rag"])

    eliminated: dict[str, list[str]] = {arm: [] for arm in ARMS}
    quality: dict[str, float] = {}
    monthly: dict[str, float] = {}
    latency: dict[str, float] = {}
    for arm in ARMS:
        block = metrics[arm][name]
        quality[arm] = float(block["task_success"])
        monthly[arm] = monthly_usd(
            arm,
            int(scenario["monthly_requests"]),
            str(scenario["change_rate"]),
            card,
        )
        latency[arm] = model_latency_ms(arm, card)
        if quality[arm] < floor:
            eliminated[arm].append(
                f"task success {quality[arm]:.2f} is under the {floor:.2f} floor on {name}"
            )
        if bool(scenario["citations_required"]):
            rate = float(block["citation_rate"])
            if rate < cite_floor:
                eliminated[arm].append(f"citation rate {rate:.2f} is under the {cite_floor:.2f} floor")
        if arm in tune_arms and scenario["change_rate"] == "weekly":
            eliminated[arm].append("corpus changes weekly and this arm is frozen at the cutoff")
        if arm in tune_arms and scenario["change_rate"] == "monthly":
            stale_block = metrics[arm]["staleness"]
            stale_success = float(stale_block["task_success"])
            if stale_success < stale_floor:
                eliminated[arm].append(
                    f"monthly change and staleness task success {stale_success:.2f} "
                    f"is under the {stale_floor:.2f} floor"
                )
        slo = float(scenario["latency_slo_ms"])
        if latency[arm] > slo:
            eliminated[arm].append(f"projected latency {latency[arm]:.1f} ms is over the {slo:.0f} ms SLO")
        budget = float(scenario["monthly_budget_usd"])
        if monthly[arm] > budget:
            eliminated[arm].append(
                f"projected monthly cost ${monthly[arm]:.2f} is over the ${budget:.0f} budget"
            )

    survivors = [arm for arm in ARMS if not eliminated[arm]]
    survivors.sort(key=lambda arm: (monthly[arm], -quality[arm], latency[arm], arm))
    winner = survivors[0] if survivors else None

    holdout_lora = float(metrics["lora"]["holdout_freeze"]["task_success"])
    holdout_rag = float(metrics["rag"]["holdout_freeze"]["task_success"])
    gain = round(holdout_lora - holdout_rag, 4)
    checks = _finetune_checks(scenario, metrics, card, policy, gain, margin)

    return {
        "id": scenario.get("id"),
        "title": scenario.get("title"),
        "winner": winner,
        "expect": scenario.get("expect"),
        "do_not_finetune": winner not in tune_arms,
        "slice": name,
        "eliminated": eliminated,
        "survivors": survivors,
        "monthly_usd": monthly,
        "projected_latency_ms": latency,
        "overhead_p50_ms": {arm: overhead_p50.get(arm) for arm in ARMS},
        "per_request_usd": {arm: per_request_usd(arm, card) for arm in ARMS},
        "quality": quality,
        "quality_margin_lora_minus_rag": gain,
        "finetune_checks": checks,
        "inputs": {
            "monthly_requests": int(scenario["monthly_requests"]),
            "change_rate": scenario["change_rate"],
            "citations_required": bool(scenario["citations_required"]),
            "latency_slo_ms": float(scenario["latency_slo_ms"]),
            "monthly_budget_usd": float(scenario["monthly_budget_usd"]),
            "scope": scenario["scope"],
        },
    }


def _finetune_checks(
    scenario: Mapping[str, object],
    metrics: Mapping[str, Mapping[str, Mapping[str, object]]],
    card: Mapping[str, object],
    policy: Mapping[str, object],
    gain: float,
    margin: float,
) -> list[dict[str, object]]:
    volume = int(scenario["monthly_requests"])
    change = str(scenario["change_rate"])
    lora_cost = monthly_usd("lora", volume, change, card)
    rag_cost = monthly_usd("rag", volume, change, card)
    distilled_full = float(metrics["distilled"]["freeze_full"]["task_success"])
    floor = float(policy["quality_floor"])
    stale = float(metrics["lora"]["staleness"]["task_success"])
    stale_floor = float(policy["staleness_floor"])
    citations = bool(scenario["citations_required"])
    weekly = change == "weekly"
    monthly_stale = change == "monthly" and stale < stale_floor
    if lora_cost > rag_cost:
        cost_text = (
            f"At {volume:,} requests a month the LoRA program costs ${lora_cost:,.2f} "
            f"against ${rag_cost:,.2f} for RAG, so the freeze does not pay for itself."
        )
    else:
        cost_text = (
            f"At {volume:,} requests a month the LoRA program costs ${lora_cost:,.2f} "
            f"against ${rag_cost:,.2f} for RAG, so volume covers the program."
        )
    return [
        {
            "id": "citations",
            "fired": citations,
            "text": (
                "Citations are required, and the tune arms do not cite."
                if citations
                else "Citations are not required, so an arm can win without a section pointer."
            ),
        },
        {
            "id": "change",
            "fired": weekly or monthly_stale,
            "text": (
                "The runbook changes weekly, so a frozen adapter is the wrong artifact."
                if weekly
                else "The runbook changes monthly and the adapter misses the staleness floor."
                if monthly_stale
                else "The scenario says the corpus stays put. Staleness stays a risk note, not a veto."
            ),
        },
        {
            "id": "amortization",
            "fired": lora_cost > rag_cost,
            "text": cost_text,
        },
        {
            "id": "quality-margin",
            "fired": gain < margin,
            "text": (
                f"On the frozen holdout, LoRA minus RAG is {gain:+.4f}. "
                f"The margin to justify a freeze on quality alone is {margin:.2f}."
            ),
        },
        {
            "id": "student-coverage",
            "fired": distilled_full < floor,
            "text": (
                f"The student scores {distilled_full:.2f} on the full frozen set, "
                f"under the {floor:.2f} floor, because long procedures and one-off facts were dropped."
            ),
        },
    ]


def render_memo(decision: Mapping[str, object], meta: Mapping[str, str]) -> str:
    winner = decision["winner"]
    inputs = decision["inputs"]
    assert isinstance(inputs, Mapping)
    checks = decision["finetune_checks"]
    assert isinstance(checks, list)
    eliminated = decision["eliminated"]
    assert isinstance(eliminated, Mapping)
    quality = decision["quality"]
    assert isinstance(quality, Mapping)
    monthly = decision["monthly_usd"]
    assert isinstance(monthly, Mapping)
    latency = decision["projected_latency_ms"]
    assert isinstance(latency, Mapping)

    if winner is None:
        headline = "Do not ship any arm. The constraints cannot be met together."
    elif winner == "rag":
        headline = "Do not fine-tune. Ship the RAG arm."
    elif winner == "lora":
        headline = "Ship the adapter. Do not ship it because it is smarter than RAG."
    elif winner == "distilled":
        headline = "Ship the distilled student. Keep the task inside what it was allowed to remember."
    else:
        headline = "Ship prompt-only. The labeled set does not pay for retrieval or a training program."

    lines = [
        f"# Arena decision memo · {meta['domain']}",
        "",
        f"Freeze date {meta['freeze_date']}. Policy {meta['policy_version']}. "
        "Quality numbers are exact-phrase support on the saved eval. "
        "Dollars and model latency are projections from the price card. "
        "Pipeline overhead is measured and is not in the dollar figures.",
        "",
        f"**{headline}**",
        "",
        "## This scenario",
        "",
        (
            f"{int(inputs['monthly_requests']):,} requests / month · change `{inputs['change_rate']}` · "
            f"citations {'required' if inputs['citations_required'] else 'not required'} · "
            f"SLO {float(inputs['latency_slo_ms']):.0f} ms · "
            f"budget ${float(inputs['monthly_budget_usd']):,.0f} · scope `{inputs['scope']}`."
        ),
        "",
        f"Slice `{decision['slice']}`. Winner: `{winner or 'none'}`.",
        "",
        "## The four arms",
        "",
        "| Arm | Task success | $/month | Projected latency | Why it lost, if it lost |",
        "| --- | ---: | ---: | ---: | --- |",
    ]
    for arm in ARMS:
        reasons = eliminated[arm]
        assert isinstance(reasons, list)
        why = "; ".join(str(reason) for reason in reasons) if reasons else "survivor"
        if arm == winner:
            why = "selected: lowest projected monthly cost among arms that cleared the rules"
        lines.append(
            f"| {arm} | {float(quality[arm]):.2f} | {float(monthly[arm]):,.2f} | "
            f"{float(latency[arm]):.0f} ms | {why} |"
        )
    lines.extend(
        [
            "",
            "## When not to fine-tune",
            "",
        ]
    )
    for check in checks:
        assert isinstance(check, Mapping)
        mark = "applies" if check["fired"] else "does not apply"
        lines.append(f"- **{mark}.** {check['text']}")
    lines.extend(
        [
            "",
            "## What would reverse this",
            "",
            _reversal(winner),
            "",
            "Lumen is the retrieval port for the RAG arm (offline stub unless `ARENA_LUMEN_URL` is set). "
            "Switchboard is the serving port: the price card names the catalog model each arm would pin. "
            "That mapping is a stand-in. A live route that disagrees is reported, not overwritten.",
            "",
            "This is not a neural trainer. The adapter stores train-split fact text and the words of the "
            "train questions. The student drops long procedures and facts that appear once. "
            "A GPU fine-tune could paraphrase. It would not change the freeze date, the citation gap, "
            "or the program cost that this memo is about.",
            "",
        ]
    )
    return "\n".join(lines)


def _reversal(winner: object) -> str:
    if winner == "lora":
        return (
            "This flips back to RAG if citations become required, if the runbook starts changing, "
            "or if volume drops far enough that the training program costs more than retrieval."
        )
    if winner == "distilled":
        return (
            "This flips if the contract grows to long procedures or rare policies, or if the SLO "
            "relaxes and the quality floor then prefers a larger arm."
        )
    if winner == "rag":
        return (
            "A fine-tune wins this table only when the corpus is stable, citations are optional, "
            "volume amortizes the program, and the SLO still fits the endpoint. Quality alone does not."
        )
    if winner == "prompt":
        return "Retrieval wins as soon as the questions leave the public subset the base prompt can see."
    return (
        "Loosen one constraint (SLO, citations, or the quality floor) and run the memo again. "
        "Do not skip the floor."
    )


def scenario_from_item(raw: Mapping[str, object]) -> dict[str, object]:
    """Normalize a YAML scenario or an API override into the decide() shape."""
    required = (
        "monthly_requests",
        "change_rate",
        "citations_required",
        "latency_slo_ms",
        "monthly_budget_usd",
        "scope",
    )
    missing = [key for key in required if key not in raw]
    if missing:
        raise ValueError(f"scenario missing {missing}")
    change = str(raw["change_rate"])
    scope = str(raw["scope"])
    if change not in {"stable", "monthly", "weekly"}:
        raise ValueError("change_rate must be stable, monthly, or weekly")
    if scope not in {"full", "common_short"}:
        raise ValueError("scope must be full or common_short")
    out = dict(raw)
    out["monthly_requests"] = int(raw["monthly_requests"])
    out["latency_slo_ms"] = float(raw["latency_slo_ms"])
    out["monthly_budget_usd"] = float(raw["monthly_budget_usd"])
    out["citations_required"] = bool(raw["citations_required"])
    return out


def question_index(items: list[Item]) -> dict[str, Item]:
    return {item.id: item for item in items}
