"""Command line. No subcommand contacts AWS."""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any

from skyline.diffing import diff
from skyline.invariants import evaluate
from skyline.load import load_platform
from skyline.mutations import mutate
from skyline.platform import assemble
from skyline.report import render_markdown, write_report
from skyline.state import build_state
from skyline.synth import read_fixture, synth_text, write_outputs


def _refuse_live() -> None:
    provider = os.environ.get("SKYLINE_PROVIDER", "fixture")
    if provider != "fixture":
        raise SystemExit(f"SKYLINE_PROVIDER={provider!r} is not supported. Skyline only synths fixtures.")
    requested = os.environ.get("SKYLINE_REGION")
    region = load_platform()["region"]
    if requested and requested != region:
        raise SystemExit(
            f"SKYLINE_REGION={requested!r} does not match eval/platform.yaml ({region}). "
            "Refusing to synth a second region quietly."
        )


def _print_rules(assembly: dict[str, Any]) -> int:
    rows = evaluate(assembly)
    for row in rows:
        mark = "ok  " if row["ok"] else "FAIL"
        print(f"{mark} {row['rule']}")
        for finding in row["findings"]:
            print(f"     {finding}")
    failed = sum(1 for row in rows if not row["ok"])
    print(f"{len(rows) - failed}/{len(rows)} passed")
    return 1 if failed else 0


def main(argv: list[str] | None = None) -> int:
    _refuse_live()
    parser = argparse.ArgumentParser(
        prog="skyline", description="Offline platform synth for Aegis, Lumen, and Switchboard."
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    synth = sub.add_parser("synth", help="write build/assembly.json")
    synth.add_argument("--write-fixture", action="store_true", help="also overwrite fixtures/assembly.json")

    sub.add_parser("diff", help="diff the synth against the fixture")

    gate = sub.add_parser("gate", help="run the architecture invariants")
    gate.add_argument("--mutation", default="clean")

    sub.add_parser("eval", help="synth, gate, FinOps, and the README section")
    sub.add_parser("demo", help="print the 60-second walkthrough")

    serve = sub.add_parser("serve", help="serve the console")
    serve.add_argument("--port", type=int, default=int(os.environ.get("SKYLINE_PORT", "8097")))

    args = parser.parse_args(argv)
    if args.cmd == "synth":
        _assembly, text, hashed = synth_text()
        write_outputs(text, fixture=args.write_fixture)
        where = (
            "fixtures/assembly.json and build/assembly.json" if args.write_fixture else "build/assembly.json"
        )
        print(f"wrote {where}")
        print(hashed)
        return 0
    if args.cmd == "diff":
        assembly, text, hashed = synth_text()
        fixture = read_fixture()
        if fixture == text:
            print(f"match {hashed}")
            return 0
        changes = diff(json.loads(fixture), assembly)
        print(f"{len(changes)} change(s); synth {hashed}")
        for change in changes[:40]:
            print(f"{change['op']:7} {change['path']}")
        return 1
    if args.cmd == "gate":
        assembly = mutate(assemble(), args.mutation)
        return _print_rules(assembly)
    if args.cmd == "eval":
        state = build_state()
        problems = write_report(state)
        print(render_markdown(state).split("\n")[0])
        print(f"measured synth {state['synthMs']} ms, stub mean {state['bench']['mean_us']:.2f} µs")
        if problems:
            for problem in problems:
                print(problem, file=sys.stderr)
            return 1
        print(f"clean gate passed; report written; hash {state['cleanHash']}")
        return 0
    if args.cmd == "demo":
        state = build_state()
        finops = state["finops"]
        print("Skyline demo. No AWS account is contacted.")
        print(f"Console: http://127.0.0.1:{os.environ.get('SKYLINE_PORT', '8097')}")
        print(
            f"Hash {state['cleanHash'][:16]}  {state['violationCount']} invariant failures on the clean synth"
        )
        print(
            f"At {finops['requests_per_day']:,} requests/day, "
            f"Skyline is ${finops['skyline_total']} per 1,000 and the naive path is ${finops['naive_total']}."
        )
        print(
            "Then open a security group to 0.0.0.0/0 in the console. The gate should go red and name the rule."
        )
        print("make up    serves the console")
        print("make test   runs the suite")
        print("make eval   rewrites the README numbers")
        return 0
    if args.cmd == "serve":
        import uvicorn

        from skyline.dashboard.app import create_app

        uvicorn.run(create_app(), host="127.0.0.1", port=args.port)
        return 0
    parser.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
