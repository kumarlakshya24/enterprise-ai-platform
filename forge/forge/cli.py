"""Command line entry points for demo, eval, interview, and the local UI."""

from __future__ import annotations

import argparse
from pathlib import Path

from forge import __version__
from forge.audit import AuditLog
from forge.config import listen_host, listen_port


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="forge")
    parser.add_argument("--version", action="version", version=f"forge {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("demo", help="run PASS/FAIL scenarios")
    sub.add_parser("interview", help="run the interview beats")
    sub.add_parser("eval", help="run the corpus and write reports")
    sub.add_parser("serve", help="serve the local UI")
    verify = sub.add_parser("verify", help="verify an audit log")
    verify.add_argument("path")
    args = parser.parse_args(argv)
    if args.command == "demo":
        from forge.demo.runner import run_demo

        return _print(run_demo())
    if args.command == "interview":
        from forge.demo.runner import run_interview

        return _print(run_interview())
    if args.command == "eval":
        from forge.reporting import run_eval

        return run_eval()
    if args.command == "verify":
        from forge.config import audit_key

        report = AuditLog(Path(args.path), audit_key()).verify()
        print(report)
        return 0 if report["ok"] else 1
    if args.command == "serve":
        import uvicorn

        uvicorn.run("forge.api.app:app", host=listen_host(), port=listen_port(), log_level="info")
        return 0
    return 2


def _print(checks: list[object]) -> int:
    failed = 0
    for check in checks:
        mark = "PASS" if check.ok else "FAIL"  # type: ignore[attr-defined]
        if not check.ok:  # type: ignore[attr-defined]
            failed += 1
        print(f"{mark}  {check.id:<32} {check.detail}")  # type: ignore[attr-defined]
    passed = len(checks) - failed
    print(f"\n{passed}/{len(checks)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
