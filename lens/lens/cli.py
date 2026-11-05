"""Command line. `python -m lens.cli eval` is what `make eval` runs."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from lens.config import REPORTS_DIR, STATIC_DIR
from lens.dashboard.render import render_html
from lens.pipeline import build_report
from lens.reporting import gate_markdown, write_reports


def _prepare() -> dict[str, object]:
    report = build_report()
    write_reports(report)
    STATIC_DIR.mkdir(parents=True, exist_ok=True)
    (STATIC_DIR / "index.html").write_text(render_html(report))
    return report


def _cmd_eval() -> int:
    report = _prepare()
    clean = bool(report["gate_clean"]["passed"])  # type: ignore[index]
    seeded_blocked = not bool(report["gate_regressed"]["passed"])  # type: ignore[index]
    print(f"clean gate: {'PASS' if clean else 'FAIL'}")
    print(f"seeded regression: {'BLOCKED' if seeded_blocked else 'MISSED'}")
    print(f"wrote {REPORTS_DIR} and {STATIC_DIR / 'index.html'}")
    if clean and seeded_blocked:
        return 0
    return 1


def _cmd_gate(candidate: str) -> int:
    report = build_report()
    gate = report["gate_clean"] if candidate == "clean" else report["gate_regressed"]
    assert isinstance(gate, dict)
    sys.stdout.write(gate_markdown(gate))
    return 0 if gate["passed"] else 1


def _cmd_demo() -> int:
    report = _prepare()
    kappa = report["kappa"]
    assert isinstance(kappa, dict)
    print("Lens demo (offline, no provider calls)")
    print(f"  gold items: {report['gold_n']}")
    print(f"  kappa on pass: {kappa['pass']}")
    print(f"  clean gate: {'PASS' if report['gate_clean']['passed'] else 'FAIL'}")  # type: ignore[index]
    print(f"  seeded gate: {'FAIL (caught)' if not report['gate_regressed']['passed'] else 'PASS (missed)'}")  # type: ignore[index]
    print("  dashboard: lens/dashboard/static/index.html")
    print("  serve it with: make up")
    return 0


def _cmd_serve(port: int) -> int:
    _prepare()
    import uvicorn

    from lens.dashboard.app import create_app

    uvicorn.run(create_app(), host="127.0.0.1", port=port, log_level="info")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="lens")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("eval")
    gate = sub.add_parser("gate")
    gate.add_argument("--candidate", choices=("clean", "regressed"), default="clean")
    sub.add_parser("demo")
    serve = sub.add_parser("serve")
    serve.add_argument("--port", type=int, default=8088)
    args = parser.parse_args(argv)
    if args.cmd == "eval":
        return _cmd_eval()
    if args.cmd == "gate":
        return _cmd_gate(args.candidate)
    if args.cmd == "demo":
        return _cmd_demo()
    if args.cmd == "serve":
        return _cmd_serve(args.port)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
