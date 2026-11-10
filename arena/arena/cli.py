"""Command line. `python -m arena.cli eval` writes reports/latest.json."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from arena.evaluate import SLICES, build_report, fingerprint, write_report
from arena.score import grade
from arena.settings import Settings
from arena.world import load_world


def _settings(args: argparse.Namespace) -> Settings:
    settings = Settings.from_env()
    if args.report:
        return Settings(
            host=settings.host,
            port=settings.port,
            lumen_url=settings.lumen_url,
            switchboard_url=settings.switchboard_url,
            report_path=Path(args.report),
            data_dir=settings.data_dir,
            static_dir=settings.static_dir,
        )
    return settings


def cmd_eval(args: argparse.Namespace) -> int:
    settings = _settings(args)
    world = load_world(settings)
    report = build_report(world, bench_n=args.bench_n)
    write_report(report, settings.report_path)
    print(f"wrote {settings.report_path}")
    for scenario in report["scenarios"]:
        mark = "ok" if scenario["winner"] == scenario["expect"] else "DRIFT"
        print(f"  {mark}  {scenario['id']}: {scenario['winner']} (expect {scenario['expect']})")
    drifted = [s for s in report["scenarios"] if s["winner"] != s["expect"]]
    return 1 if drifted else 0


def cmd_explain(args: argparse.Namespace) -> int:
    world = load_world(_settings(args))
    slice_name = args.slice
    as_of, scope, splits = SLICES[slice_name]
    from arena.evaluate import select_items

    rows = select_items(world.items, world.facts, world.train_counts, splits, scope)
    answerers = {
        "prompt": world.prompt.answer,
        "rag": world.rag_freeze.answer if as_of == "freeze" else world.rag_current.answer,
        "lora": world.lora.answer,
        "distilled": world.distilled.answer,
    }
    misses = 0
    for item in rows:
        for arm, answer_fn in answerers.items():
            answer = answer_fn(item.question)
            result = grade(item, answer, world.facts, as_of)
            if result.ok:
                continue
            misses += 1
            print(f"{slice_name} {arm:10} {item.id:22} {result.reason:12} {answer.text[:90]!r}")
    print(f"{misses} misses")
    return 0


def cmd_demo(args: argparse.Namespace) -> int:
    settings = _settings(args)
    world = load_world(settings)
    report = build_report(world, bench_n=5)
    checks: list[tuple[str, bool]] = []
    for scenario in report["scenarios"]:
        checks.append(
            (
                f"scenario {scenario['id']} -> {scenario['expect']}",
                scenario["winner"] == scenario["expect"],
            )
        )

    credit = world.by_id["ho-credit"]
    rag = world.rag_current.answer(credit.question)
    lora = world.lora.answer(credit.question)
    checks.append(("RAG finds the 50 USD cap on a reworded credit question", "50 USD" in rag.text))
    checks.append(("adapter misses that rewording", lora.refused and "50 USD" not in lora.text))

    window = world.by_id["st-refund-window"]
    rag_w = world.rag_current.answer(window.question)
    lora_w = world.lora.answer(window.question)
    checks.append(("RAG cites the current 30 day window", "30 days" in rag_w.text and not rag_w.refused))
    cited = any(row["doc_id"] == "billing-refunds" for row in rag_w.citations)
    checks.append(("RAG citation is the refunds runbook", cited))
    checks.append(("adapter still says 14 days", "14 days" in lora_w.text and "30 days" not in lora_w.text))

    tea = world.by_id["un-tea"]
    tea_answers = [
        world.prompt.answer(tea.question),
        world.rag_current.answer(tea.question),
        world.lora.answer(tea.question),
        world.distilled.answer(tea.question),
    ]
    checks.append(("every arm refuses the tea question", all(answer.refused for answer in tea_answers)))

    public = world.by_id["ho-product-what"]
    prompt_public = world.prompt.answer(public.question)
    checks.append(("prompt answers the public product question", not prompt_public.refused))
    prompt_refund = world.prompt.answer(window.question)
    checks.append(("prompt refuses an internal refund question", prompt_refund.refused))

    bridge = world.by_id["ho-bridge"]
    student_bridge = world.distilled.answer(bridge.question)
    checks.append(("student drops the long bridge procedure", student_bridge.refused))
    adapter_bridge = world.lora.answer(bridge.question)
    checks.append(("adapter still has the bridge procedure", "every 30 minutes" in adapter_bridge.text))

    overhead = report["overhead_ms"]["rag"]
    checks.append(("RAG overhead p95 stays under 20 ms", float(overhead["p95"]) < 20))

    failed = 0
    for label, ok in checks:
        print(("PASS  " if ok else "FAIL  ") + label)
        failed += not ok
    print(f"{len(checks) - failed}/{len(checks)} passed")
    return 1 if failed else 0


def cmd_gate(args: argparse.Namespace) -> int:
    settings = _settings(args)
    if not settings.report_path.exists():
        print(f"missing {settings.report_path}; run make eval", file=sys.stderr)
        return 1
    saved = json.loads(settings.report_path.read_text(encoding="utf-8"))
    world = load_world(settings)
    # Quality does not depend on the bench size. Keep the gate fast and stable.
    live = build_report(world, bench_n=1)
    if fingerprint(saved) != fingerprint(live):
        print("committed report does not match a fresh eval", file=sys.stderr)
        return 1
    if saved.get("corpus_sha256") != world.sha:
        print("report hash does not match the corpus", file=sys.stderr)
        return 1
    print("gate passed")
    return 0


def cmd_memo(args: argparse.Namespace) -> int:
    settings = _settings(args)
    report = json.loads(settings.report_path.read_text(encoding="utf-8"))
    for scenario in report["scenarios"]:
        if scenario["id"] == args.scenario:
            print(scenario["memo_md"])
            return 0
    print(f"unknown scenario {args.scenario}", file=sys.stderr)
    return 1


def cmd_serve(args: argparse.Namespace) -> int:
    import uvicorn

    from arena.app import create_app

    settings = _settings(args)
    uvicorn.run(create_app(settings), host=settings.host, port=settings.port)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="arena")
    parser.add_argument("--report", default="")
    sub = parser.add_subparsers(dest="command", required=True)
    eval_parser = sub.add_parser("eval", help="write reports/latest.json")
    eval_parser.add_argument("--bench-n", type=int, default=20)
    eval_parser.set_defaults(func=cmd_eval)
    explain = sub.add_parser("explain", help="print misses for one slice")
    explain.add_argument("--slice", default="current_full", choices=sorted(SLICES))
    explain.set_defaults(func=cmd_explain)
    demo = sub.add_parser("demo", help="locked checks")
    demo.set_defaults(func=cmd_demo)
    gate = sub.add_parser("gate", help="fresh eval must match the committed report")
    gate.set_defaults(func=cmd_gate)
    memo = sub.add_parser("memo", help="print one saved memo")
    memo.add_argument("--scenario", default="weekly-cited")
    memo.set_defaults(func=cmd_memo)
    serve = sub.add_parser("serve", help="demo UI")
    serve.set_defaults(func=cmd_serve)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
