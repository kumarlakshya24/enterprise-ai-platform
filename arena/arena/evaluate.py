"""Run every arm on every slice and write the saved report.

Decisions read this report. They do not rescore the labeled set, so a slider in the
UI cannot quietly change a quality number.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from arena.arms import ARMS, Answer
from arena.bench import measure
from arena.corpus import Fact, Item
from arena.decide import decide, render_memo
from arena.score import aggregate_with_facts, grade
from arena.world import World

SLICES: dict[str, tuple[str, str, tuple[str, ...]]] = {
    "freeze_full": ("freeze", "full", ("holdout", "unanswerable")),
    "freeze_common_short": ("freeze", "common_short", ("holdout", "unanswerable")),
    "current_full": ("current", "full", ("holdout", "staleness", "unanswerable")),
    "current_common_short": ("current", "common_short", ("holdout", "staleness", "unanswerable")),
    "staleness": ("current", "full", ("staleness",)),
    "holdout_freeze": ("freeze", "full", ("holdout",)),
}

SHOWCASE_ID = "st-refund-window"


def select_items(
    items: list[Item],
    facts: dict[str, Fact],
    counts: dict[str, int],
    splits: tuple[str, ...],
    scope: str,
) -> list[Item]:
    chosen: list[Item] = []
    for item in items:
        if item.split not in splits:
            continue
        if scope == "common_short" and not item.refuse:
            covered = all(
                facts[fact_id].length == "short" and counts.get(fact_id, 0) >= 2 for fact_id in item.fact_ids
            )
            if not covered:
                continue
        chosen.append(item)
    return chosen


def _answerer(world: World, arm: str, as_of: str) -> Callable[[str], Answer]:
    if arm == "prompt":
        return world.prompt.answer
    if arm == "lora":
        return world.lora.answer
    if arm == "distilled":
        return world.distilled.answer
    if as_of == "freeze":
        return world.rag_freeze.answer
    return world.rag_current.answer


def build_report(world: World, bench_n: int = 20) -> dict[str, Any]:
    metrics: dict[str, dict[str, dict[str, object]]] = {arm: {} for arm in ARMS}
    grades: dict[str, dict[str, dict[str, str]]] = {name: {} for name in SLICES}
    for slice_name, (as_of, scope, splits) in SLICES.items():
        rows = select_items(world.items, world.facts, world.train_counts, splits, scope)
        for arm in ARMS:
            answer = _answerer(world, arm, as_of)
            graded = [(item, grade(item, answer(item.question), world.facts, as_of)) for item in rows]
            metrics[arm][slice_name] = aggregate_with_facts(graded, world.facts)
            for item, result in graded:
                grades[slice_name].setdefault(item.id, {})[arm] = result.reason

    questions = [item.question for item in world.items if item.split != "train"]
    overhead = {
        "prompt": measure(world.prompt.answer, questions, bench_n),
        "rag": measure(world.rag_current.answer, questions, bench_n),
        "lora": measure(world.lora.answer, questions, bench_n),
        "distilled": measure(world.distilled.answer, questions, bench_n),
        "note": "In-process wall clock. Catalog model latency is not slept.",
        "train_adapter_ms": world.train_adapter_ms,
        "train_student_ms": world.train_student_ms,
    }
    overhead_p50 = {arm: float(overhead[arm]["p50"]) for arm in ARMS}

    decisions = []
    meta = {
        "domain": world.meta["domain"],
        "freeze_date": world.meta["freeze_date"],
        "policy_version": str(world.policy["version"]),
    }
    for scenario in world.scenarios:
        decision = decide(metrics, scenario, world.price, world.policy, overhead_p50)
        decision["memo_md"] = render_memo(decision, meta)
        decisions.append(decision)

    counts = {item.split: 0 for item in world.items}
    for item in world.items:
        counts[item.split] = counts.get(item.split, 0) + 1

    report: dict[str, Any] = {
        "version": world.meta["version"],
        "freeze_date": world.meta["freeze_date"],
        "domain": world.meta["domain"],
        "policy_version": world.policy["version"],
        "price_version": world.price["version"],
        "price_label": world.price["label"],
        "corpus_sha256": world.sha,
        "counts": {
            "docs": world.doc_count,
            "facts": len(world.facts),
            "questions": len(world.items),
            "train": counts.get("train", 0),
            "holdout": counts.get("holdout", 0),
            "staleness": counts.get("staleness", 0),
            "unanswerable": counts.get("unanswerable", 0),
            "adapter_facts": len(world.lora.facts),
            "student_facts": len(world.distilled.facts),
        },
        "pipeline": world.pipeline_public(),
        "arms": metrics,
        "grades": grades,
        "overhead_ms": overhead,
        "cost": {
            "label": "projection",
            "amortization_months": world.price["amortization_months"],
            "per_request_usd": world.per_request,
            "model_latency_ms": world.model_latency,
            "program_usd": {arm: world.price["arms"][arm]["program_usd"] for arm in ARMS},
        },
        "serving": world.serving,
        "scenarios": decisions,
        "questions": [
            {
                "id": item.id,
                "split": item.split,
                "question": item.question,
                "fact_ids": list(item.fact_ids),
                "refuse": item.refuse,
            }
            for item in world.items
            if item.split != "train"
        ],
        "showcase": _showcase(world),
    }
    return report


def _showcase(world: World) -> dict[str, Any]:
    item = world.by_id[SHOWCASE_ID]
    arms = {
        "prompt": world.prompt.answer(item.question),
        "rag": world.rag_current.answer(item.question),
        "lora": world.lora.answer(item.question),
        "distilled": world.distilled.answer(item.question),
    }
    return {
        "question_id": item.id,
        "question": item.question,
        "note": "Current index for RAG. Adapter and student still speak the freeze text.",
        "arms": {
            name: {
                **answer.public(),
                "reason": grade(item, answer, world.facts, "current").reason,
            }
            for name, answer in arms.items()
        },
    }


def write_report(report: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    md = path.with_suffix(".md")
    md.write_text(render_eval_md(report), encoding="utf-8")


def render_eval_md(report: dict[str, Any]) -> str:
    lines = [
        "# Arena eval",
        "",
        f"Domain: {report['domain']}. Freeze {report['freeze_date']}. "
        f"Corpus `{report['corpus_sha256'][:12]}`.",
        "",
        "Task success is exact-phrase support. Cost and model latency are projections. "
        "Overhead is measured wall clock and is not added into the dollars.",
        "",
        "## Counts",
        "",
        "| | |",
        "| --- | ---: |",
    ]
    for key, value in report["counts"].items():
        lines.append(f"| {key} | {value} |")
    lines.extend(["", "## Quality", ""])
    header = "| Slice | " + " | ".join(ARMS) + " |"
    lines.append(header)
    lines.append("| --- | " + " | ".join("---:" for _ in ARMS) + " |")
    for slice_name in SLICES:
        cells = []
        for arm in ARMS:
            block = report["arms"][arm][slice_name]
            cells.append(f"{block['correct']}/{block['n']} ({block['task_success']:.2f})")
        lines.append(f"| {slice_name} | " + " | ".join(cells) + " |")
    lines.extend(["", "## Scenarios", ""])
    lines.append("| Scenario | Winner | Do not fine-tune | Slice |")
    lines.append("| --- | --- | --- | --- |")
    for scenario in report["scenarios"]:
        lines.append(
            f"| {scenario['id']} | {scenario['winner']} | "
            f"{scenario['do_not_finetune']} | {scenario['slice']} |"
        )
    lines.extend(["", "## Overhead (measured)", ""])
    lines.append("| Arm | p50 ms | p95 ms | n |")
    lines.append("| --- | ---: | ---: | ---: |")
    for arm in ARMS:
        block = report["overhead_ms"][arm]
        lines.append(f"| {arm} | {block['p50']} | {block['p95']} | {block['n']} |")
    lines.append("")
    lines.append(report["overhead_ms"]["note"])
    lines.append("")
    return "\n".join(lines) + "\n"


def fingerprint(report: dict[str, Any]) -> dict[str, Any]:
    """The part that must match across machines. Wall clock is not in here."""
    return {
        "corpus_sha256": report["corpus_sha256"],
        "counts": report["counts"],
        "arms": report["arms"],
        "grades": report["grades"],
        "cost": report["cost"],
        "scenarios": [
            {
                "id": scenario["id"],
                "winner": scenario["winner"],
                "do_not_finetune": scenario["do_not_finetune"],
                "slice": scenario["slice"],
                "monthly_usd": scenario["monthly_usd"],
                "quality": scenario["quality"],
                "eliminated": scenario["eliminated"],
                "finetune_checks": scenario["finetune_checks"],
                "memo_md": scenario["memo_md"],
            }
            for scenario in report["scenarios"]
        ],
        "showcase": {
            "question_id": report["showcase"]["question_id"],
            "arms": {
                arm: {
                    "reason": payload["reason"],
                    "refused": payload["refused"],
                    "text": payload["text"],
                    "fact_ids": payload["fact_ids"],
                }
                for arm, payload in report["showcase"]["arms"].items()
            },
        },
    }
