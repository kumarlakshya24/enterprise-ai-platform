"""Offline commands. No network. No API key."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence

from charter.config import POLICIES_DIR, PORT, REGISTRY_PATH, REPORTS_DIR
from charter.evidence.pack import (
    build_report,
    decide_all,
    evidence_markdown,
    gate,
    load_cases,
    summary_markdown,
    write_reports,
)
from charter.policy.engine import load_policies
from charter.registry.cards import load_registry


def _cmd_eval(_: argparse.Namespace) -> int:
    report = build_report()
    write_reports(report)
    print(summary_markdown(report), end="")
    counts = report.matrix.counts()
    if counts.get("unmapped"):
        print("unmapped controls; the catalog and the rules have drifted")
        return 1
    if not report.gate.ok:
        print("shipped policy failed the locked cases")
        return 1
    if report.weakened.ok:
        print("removing 002-residency.cedar still passed the gate; it must not")
        return 1
    if not report.audit.chain_ok or len(report.audit.violations) != 1:
        print("audit stub is not the planted one-violation log")
        return 1
    print(f"wrote {REPORTS_DIR}")
    return 0


def _cmd_gate(args: argparse.Namespace) -> int:
    exclude = frozenset({"002-residency.cedar"}) if args.weakened else frozenset()
    bundle = load_policies(POLICIES_DIR, exclude=exclude)
    decisions = decide_all(bundle, load_registry(REGISTRY_PATH), load_cases())
    result = gate(decisions)
    for failure in result.failures:
        print(failure)
    label = "weakened" if args.weakened else "shipped"
    print(f"{label} gate: {'pass' if result.ok else 'fail'} ({len(result.failures)} mismatched)")
    return 0 if result.ok else 1


def _cmd_demo(_: argparse.Namespace) -> int:
    report = build_report(measure=False)
    denied = report.decision_for("eu-support-us")
    allowed = report.decision_for("eu-support-local")
    counts = report.matrix.counts()
    print("Charter demo (offline, synthetic)")
    print(f"  allow  eu-support-local  {allowed.decision.primary_rule}")
    print(f"  deny   eu-support-us     {denied.decision.primary_rule}  {denied.decision.reason}")
    print(f"  matrix {counts['met']} met, {counts['partial']} partial, {counts['gap']} gap")
    violation = report.audit.violations[0]
    print(f"  audit  {violation.request_id} {violation.label} route {violation.route} → {violation.region}")
    print(f"  weakened gate blocked: {not report.weakened.ok}")
    print(f"  ui     make up  →  http://127.0.0.1:{PORT}")
    return 0


def _cmd_decide(args: argparse.Namespace) -> int:
    report = build_report(measure=False)
    item = report.decision_for(args.case)
    print(json.dumps(item.as_dict(), indent=2))
    return 0 if item.decision.effect == item.case.effect else 1


def _cmd_evidence(_: argparse.Namespace) -> int:
    report = build_report(measure=False)
    print(evidence_markdown(report), end="")
    return 0


def _cmd_serve(args: argparse.Namespace) -> int:
    import uvicorn

    uvicorn.run("charter.api.app:app", host="127.0.0.1", port=args.port, log_level="info")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="charter", description="AI governance control plane")
    sub = parser.add_subparsers(dest="cmd", required=True)

    eval_cmd = sub.add_parser("eval", help="run the pack, write reports, fail if the story breaks")
    eval_cmd.set_defaults(func=_cmd_eval)

    gate_cmd = sub.add_parser("gate", help="compare decisions to eval/cases.yaml")
    gate_cmd.add_argument("--weakened", action="store_true", help="drop 002-residency.cedar")
    gate_cmd.set_defaults(func=_cmd_gate)

    demo = sub.add_parser("demo", help="print the allow, the deny, and the gap")
    demo.set_defaults(func=_cmd_demo)

    decide = sub.add_parser("decide", help="print one locked case")
    decide.add_argument("--case", default="eu-support-us")
    decide.set_defaults(func=_cmd_decide)

    evidence = sub.add_parser("evidence", help="print the evidence pack")
    evidence.set_defaults(func=_cmd_evidence)

    serve = sub.add_parser("serve", help="serve the local UI")
    serve.add_argument("--port", type=int, default=PORT)
    serve.set_defaults(func=_cmd_serve)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
