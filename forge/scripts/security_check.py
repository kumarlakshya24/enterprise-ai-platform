#!/usr/bin/env python3
"""Fail if the tree contains a credential or a shell executor."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCAN_ROOTS = [ROOT / "forge", ROOT / "eval", ROOT / "tests", ROOT / "scripts", ROOT / "bench"]
FORBIDDEN = [
    re.compile(r"BEGIN (?:OPENSSH|RSA|EC) PRIVATE KEY"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"sk-proj-[A-Za-z0-9]{8,}"),
    re.compile(r"sk-live-[A-Za-z0-9]{8,}"),
]
SHELL = re.compile(r"shell\s*=\s*True")


def main() -> int:
    failures: list[str] = []
    for root in SCAN_ROOTS:
        for path in root.rglob("*"):
            suffixes = {".py", ".yml", ".yaml", ".json", ".jsonl", ".md", ".html", ".js"}
            if not path.is_file() or path.suffix not in suffixes:
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            for pattern in FORBIDDEN:
                if pattern.search(text):
                    failures.append(f"{path.relative_to(ROOT)} matches {pattern.pattern}")
            if path.name == "security_check.py":
                continue
            if path.suffix == ".py" and SHELL.search(text):
                failures.append(f"{path.relative_to(ROOT)} launches a shell")
    if failures:
        print("\n".join(failures))
        return 1
    print(f"security-check passed ({sum(1 for root in SCAN_ROOTS for _ in root.rglob('*.py'))} python files scanned)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
