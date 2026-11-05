"""Write the eval artifacts and copy the markdown summary into the README."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from lens.config import REPORTS_DIR, ROOT
from lens.evalset.cases import CASES


def _round(value: Any) -> Any:
    if isinstance(value, float):
        return round(value, 4)
    if isinstance(value, dict):
        return {key: _round(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_round(item) for item in value]
    return value


def summary_markdown(report: dict[str, Any]) -> str:
    kappa = report["kappa"]
    clean = report["gate_clean"]
    bad = report["gate_regressed"]
    cost = report["cost"]
    latency = report["latency_synthetic_ms"]
    lines = [
        f"Seed `{report['seed']}`, judge `{report['judge']}`, gold set n={report['gold_n']}.",
        f"Window {report['window']['start']} → {report['window']['end']} ({report['window']['hours']} hourly buckets).",
        "",
        "Cohen's kappa, heuristic against the hand labels on the **baseline** outputs:",
        "",
        "| Label | kappa | tp | fp | tn | fn |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for name in ("pass", "faithful", "relevant", "safe", "refusal_correct"):
        matrix = kappa[f"{name}_confusion"]
        lines.append(
            f"| {name} | {kappa[name]:.4f} | {matrix['tp']} | {matrix['fp']} | {matrix['tn']} | {matrix['fn']} |"
        )
    lines += [
        "",
        "Disagreements (the known gaps, not hidden):",
        "",
        "| id | gap | gold pass | heuristic pass |",
        "|---|---|---:|---:|",
    ]
    for gap in kappa["disagreements"]:
        lines.append(
            f"| `{gap['id']}` | {gap['gap']} | {str(gap['gold_pass']).lower()} | {str(gap['pred_pass']).lower()} |"
        )
    lines += [
        "",
        "CI gate on the frozen gold set. Clean is the locked baseline judged again. Regressed is the seeded prompt.",
        "",
        "| Rule | Clean | Seeded regression |",
        "|---|---|---|",
    ]
    bad_by_id = {rule["rule_id"]: rule for rule in bad["rules"]}
    for rule in clean["rules"]:
        other = bad_by_id[rule["rule_id"]]
        lines.append(
            f"| `{rule['rule_id']}` | {'pass' if rule['passed'] else 'FAIL'} | {'pass' if other['passed'] else 'FAIL'} |"
        )
    lines += [
        "",
        f"Clean gate: **{'PASS' if clean['passed'] else 'FAIL'}**. "
        f"Seeded gate: **{'PASS' if bad['passed'] else 'FAIL'}**.",
        "",
        "Seeded safety regressions (baseline safe, candidate unsafe): "
        + ", ".join(f"`{item}`" for item in bad["safety_regressions"])
        + ".",
        "",
        "| Metric | Baseline | Seeded |",
        "|---|---:|---:|",
    ]
    for key in ("pass_rate", "faithfulness_rate", "safety_rate", "latency_p95_ms"):
        lines.append(f"| {key} | {clean['metrics'][key]:.4f} | {bad['metrics'][key]:.4f} |")
    lines += [
        "",
        "Synthetic workload latency (not a live Aegis or Lumen measurement): "
        f"p50 {latency['p50']:.0f} ms, p95 {latency['p95']:.0f} ms.",
        "",
        "SLOs over the 14-day log. Remaining budget is against a 30-day window.",
        "",
        "| Objective | SLI | Target | 30-day budget left | Status | Burn 1h | Burn 6h | Burn 72h |",
        "|---|---:|---:|---:|---|---:|---:|---:|",
    ]
    for row in report["slo"]["objectives"]:
        lines.append(
            f"| {row['id']} | {row['sli']:.2%} | {row['target']:.2%} | {row['remaining']:.0%} | {row['status']} | "
            f"{row['burn']['1h']:.2f}x | {row['burn']['6h']:.2f}x | {row['burn']['72h']:.2f}x |"
        )
    lines += [
        "",
        "Drift, first 7 days versus the last 48 hours. Alert at PSI ≥ 0.25.",
        "",
        "| Signal | PSI | Level |",
        "|---|---:|---|",
    ]
    for signal in report["drift"]["signals"]:
        lines.append(f"| {signal['name']} | {signal['psi']:.4f} | {signal['level']} |")
    cusum = report["drift"]["cusum"]
    lines += [
        "",
        f"CUSUM on the Lumen eval-sample fail rate (6-hour blocks, μ={cusum['mu']:.4f}, "
        f"k={cusum['k']}, h={cusum['h']}) first alarms at `{cusum['first_alarm']}`.",
        "",
        "Cost. Heuristic judge: **$0**. Projections use `eval/pricing.yaml` and are not invoices.",
        "",
        "| Judge | Sampled (5% of 50k req/day) | If you judged every request |",
        "|---|---:|---:|",
        "| Heuristic | $0 | $0 |",
        f"| Small-model stand-in | ${cost['stand_in_usd_per_day']:.2f}/day | ${cost['stand_in_usd_per_day_if_unsampled']:.2f}/day |",
        f"| Premium stand-in | ${cost['premium_usd_per_day']:.2f}/day | ${cost['premium_usd_per_day_if_unsampled']:.2f}/day |",
        "",
    ]
    return "\n".join(lines)


def gate_markdown(gate: dict[str, Any]) -> str:
    lines = [f"# Gate `{gate['name']}`: {'PASS' if gate['passed'] else 'FAIL'}", ""]
    for rule in gate["rules"]:
        mark = "PASS" if rule["passed"] else "FAIL"
        lines.append(f"- **{mark}** `{rule['rule_id']}` — {rule['detail']}")
    if gate["safety_regressions"]:
        lines += ["", "New unsafe ids: " + ", ".join(gate["safety_regressions"])]
    if gate["flips"]:
        lines += ["", "Items the candidate newly fails:"]
        for flip in gate["flips"]:
            lines.append(f"- `{flip['id']}` ({flip['kind']}) {flip['reasons']}")
    lines.append("")
    return "\n".join(lines)


def write_reports(report: dict[str, Any]) -> None:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    payload = _round(report)
    # The OTLP blob is for the trace test and the dashboard, not the summary table.
    summary = {key: value for key, value in payload.items() if key not in {"otlp", "series", "safety_series"}}
    (REPORTS_DIR / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    (REPORTS_DIR / "summary.md").write_text(summary_markdown(report))
    (REPORTS_DIR / "dashboard.json").write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    (REPORTS_DIR / "gate_clean.md").write_text(gate_markdown(report["gate_clean"]))
    (REPORTS_DIR / "gate_regressed.md").write_text(gate_markdown(report["gate_regressed"]))
    (REPORTS_DIR / "gate_clean.json").write_text(
        json.dumps(_round(report["gate_clean"]), indent=2, sort_keys=True) + "\n"
    )
    (REPORTS_DIR / "gate_regressed.json").write_text(
        json.dumps(_round(report["gate_regressed"]), indent=2, sort_keys=True) + "\n"
    )
    _write_gold_jsonl(REPORTS_DIR / "gold.jsonl")
    update_readme(summary_markdown(report))


def _write_gold_jsonl(path: Path) -> None:
    rows = []
    for case in CASES:
        rows.append(
            {
                "id": case.id,
                "app": case.app,
                "category": case.category,
                "safety_critical": case.safety_critical,
                "question": case.question,
                "context": list(case.context),
                "output_baseline": case.output_baseline,
                "output_regressed": case.output_regressed,
                "gold_faithful": case.gold_faithful,
                "gold_relevant": case.gold_relevant,
                "gold_safe": case.gold_safe,
                "gold_refusal_correct": case.gold_refusal_correct,
                "gold_pass": case.gold_pass,
                "regressed_defect": case.regressed_defect,
                "known_heuristic_gap": case.known_heuristic_gap,
                "note": case.note,
            }
        )
    path.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in rows))


def update_readme(summary_md: str) -> None:
    path = ROOT / "README.md"
    text = path.read_text()
    pattern = r"<!-- EVAL:START -->\n.*?<!-- EVAL:END -->"
    replacement = "<!-- EVAL:START -->\n" + summary_md.rstrip() + "\n<!-- EVAL:END -->"
    updated, count = re.subn(pattern, replacement, text, count=1, flags=re.S)
    if count != 1:
        raise RuntimeError("README is missing the EVAL markers")
    path.write_text(updated)
