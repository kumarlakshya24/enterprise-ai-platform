"""CLI entrypoints: `python -m atlas <command>`."""

from __future__ import annotations

import argparse
import sys


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="atlas")
    parser.add_argument("command", choices=["serve", "eval", "demo", "kill-resume", "interview"])
    args = parser.parse_args(argv)
    if args.command == "serve":
        from atlas.api.app import serve

        serve()
    elif args.command == "eval":
        from atlas.evaluation.runner import main as eval_main

        eval_main()
    elif args.command == "demo":
        from atlas.demo.trace import main as demo_main

        demo_main()
    elif args.command == "kill-resume":
        from atlas.demo.kill_resume import main as kill_main

        kill_main()
    elif args.command == "interview":
        import pathlib

        path = pathlib.Path(__file__).resolve().parents[1] / "docs" / "INTERVIEW_WALKTHROUGH.md"
        sys.stdout.write(path.read_text())


if __name__ == "__main__":
    main()
