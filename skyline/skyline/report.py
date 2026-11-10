"""Write the saved eval and splice the numbers into the README."""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any

from skyline.invariants import MUTATION_PRIMARY, failed_rules
from skyline.mutations import mutate
from skyline.paths import README, REPORTS
from skyline.platform import assemble
from skyline.synth import canonical, digest, read_fixture

START = "<!-- EVAL:START -->"
END = "<!-- EVAL:END -->"


def _money(value: str) -> str:
    number = Decimal(value)
    if number == 0:
        return "$0.00"
    if abs(number) >= 1:
        text = f"{number:,.2f}"
    elif abs(number) >= Decimal("0.01"):
        text = f"{number:.4f}"
    else:
        text = f"{number:.6f}"
    if number < 0:
        return f"-${text[1:]}"
    return f"${text}"


def _check(state: dict[str, Any]) -> list[str]:
    problems: list[str] = []
    if state["violationCount"]:
        problems.append(f"clean synth failed {state['violationCount']} invariant(s)")
    guard = state["guardrail"]
    if not guard["passed"]:
        problems.append(
            f"guardrail stub {guard['enforced_ok']}/{guard['enforced']} enforced, gaps {guard['gaps']}"
        )
    if any(not pillar["ok"] for pillar in state["pillars"]):
        problems.append("a Well-Architected pillar cites a resource the synth does not have")
    if state["synthMs"] > 50:
        problems.append(f"synth took {state['synthMs']} ms, bound is 50")
    if state["bench"]["mean_us"] > 100:
        problems.append(f"guardrail stub mean {state['bench']['mean_us']} µs, bound is 100")
    clean = assemble()
    for name, rule in MUTATION_PRIMARY.items():
        failed = failed_rules(mutate(clean, name))
        if rule not in failed:
            problems.append(f"mutation {name} did not fail {rule} (failed: {failed})")
        if not failed:
            problems.append(f"mutation {name} passed the gate")
    try:
        fixture = read_fixture()
    except FileNotFoundError as exc:
        problems.append(str(exc))
    else:
        if digest(fixture) != state["cleanHash"]:
            problems.append("synth drifted from fixtures/assembly.json")
    return problems


def render_markdown(state: dict[str, Any]) -> str:
    finops = state["finops"]
    guard = state["guardrail"]
    lines = [
        f"Synth `{state['manifest']['synth']}` in {state['region']}. "
        f"Hash `{state['cleanHash'][:16]}`. "
        f"{len(state['accounts'])} accounts, {state['resourceCount']} resources. "
        f"Invariants {sum(1 for row in state['invariants'] if row['ok'])}/{len(state['invariants'])}. "
        f"Guardrail stub {guard['enforced_ok']}/{guard['enforced']} enforced cases, "
        f"{guard['gaps']} known unscored gap.",
        "",
        "Fully loaded USD per 1,000 requests of the mix in `eval/workload.yaml`. "
        "Fixed cost is smeared across the stated requests/day. "
        "Prices are the frozen list in `eval/pricing.yaml`, not an invoice.",
        "",
        "| Requests/day | Skyline | Always Sonnet-class + one NAT | Skyline cheaper by |",
        "|---:|---:|---:|---:|",
    ]
    for preset in state["presets"]:
        delta = Decimal(preset["naive_total"]) - Decimal(preset["skyline_total"])
        lines.append(
            f"| {preset['requests_per_day']:,} | {_money(preset['skyline_total'])} | "
            f"{_money(preset['naive_total'])} | {_money(str(delta))} |"
        )
    crossover = finops["crossover_rpd"]
    endpoint = finops["endpoint_vs_nat_rpd"]
    lines.extend(
        [
            "",
            f"At {finops['requests_per_day']:,} requests/day the lines are:",
            "",
            "| Line | Skyline | Naive |",
            "|---|---:|---:|",
        ]
    )
    for line in finops["lines"]:
        lines.append(f"| {line['label']} | {_money(line['skyline_usd'])} | {_money(line['naive_usd'])} |")
    lines.extend(
        [
            "",
            f"Model routing saves {_money(finops['model_savings_per_1k'])} per 1,000 requests before the platform. "
            f"The guardrail, scanning the user turn and the model output, adds {_money(finops['guardrail_per_1k'])}. "
            f"Scanning the full prompt, retrieved context included, would add "
            f"{_money(finops['guardrail_full_prompt_per_1k'])} and is not what the template does.",
            "",
            f"Skyline's fully loaded unit cost drops below the naive path above "
            f"**{crossover:,} requests/day**."
            if crossover is not None
            else "Skyline's fully loaded unit cost does not drop below the naive path.",
            "",
            (
                f"Interface endpoints are {_money(finops['endpoint_daily'])}/day against "
                f"{_money(finops['nat_daily'])}/day for the single NAT in the counterfactual. "
                + (
                    f"Per-GB savings would not pay that premium back below about {endpoint:,} requests/day."
                    if endpoint
                    else "Per-GB savings do not pay the endpoint premium back."
                )
            ),
            "",
            "Measured bounds. A run that takes longer fails `make eval`. "
            "The exact sample is printed by the command and is not pinned, because it moves with the machine.",
            "",
            "| Measurement | Bound |",
            "|---|---:|",
            "| Synth, including the invariant walk | under 50 ms |",
            "| Guardrail stub, mean | under 100 µs |",
            "",
            "Projections, labeled so they are not read as measurements:",
            "",
            "| Hop | Figure | Why it is not a measurement |",
            "|---|---:|---|",
        ]
    )
    for item in state["projections"]:
        lines.append(f"| {item['hop']} | {item['ms']} ms | {item['basis']} |")
    lines.extend(
        [
            "",
            "Planted breaks. Each one must fail the named rule. A clean synth fails none.",
            "",
            "| Mutation | Rule that must fail |",
            "|---|---|",
        ]
    )
    for item in state["mutations"]:
        lines.append(f"| `{item['id']}` | `{item['rule']}` |")
    lines.extend(
        [
            "",
            "Quantities read off the template, which is what the fixed cost multiplies:",
            "",
            "| Quantity | Count |",
            "|---|---:|",
        ]
    )
    labels = {
        "cmks": "Customer managed keys",
        "guardrails": "Guardrails",
        "interface_az": "Interface endpoint-AZ pairs",
        "interface_endpoints": "Interface endpoints",
        "load_balancers": "Load balancers",
        "task_memory_gb": "Fargate memory, GB running",
        "task_vcpus": "Fargate vCPU running",
        "tgw_attachments": "Transit gateway attachments",
    }
    for key, label in labels.items():
        lines.append(f"| {label} | {finops['quantities'][key]} |")
    lines.append("")
    return "\n".join(lines)


def write_report(state: dict[str, Any]) -> list[str]:
    problems = _check(state)
    REPORTS.mkdir(parents=True, exist_ok=True)
    saved = {key: value for key, value in state.items() if key not in {"bench", "synthMs"}}
    (REPORTS / "summary.json").write_text(
        json.dumps(saved, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    markdown = render_markdown(state)
    (REPORTS / "summary.md").write_text(markdown, encoding="utf-8")
    readme = README.read_text(encoding="utf-8")
    if START not in readme or END not in readme:
        problems.append("README is missing EVAL markers")
    else:
        before, rest = readme.split(START, 1)
        _, after = rest.split(END, 1)
        updated = f"{before}{START}\n{markdown}{END}{after}"
        if not problems:
            README.write_text(updated, encoding="utf-8")
    # Hash in the report is of the clean assembly. Confirm the writer used that digest.
    if digest(canonical(assemble())) != state["cleanHash"]:
        problems.append("clean hash moved while the report was writing")
    return problems
