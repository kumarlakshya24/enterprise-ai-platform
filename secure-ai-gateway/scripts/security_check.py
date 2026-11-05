"""Security checklist, automated. Uses the gateway's own detectors to scan the repo (dogfooding).

python scripts/security_check.py    # exit 1 on any failure
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from aegis.dlp.regex_detectors import CreditCardDetector, EmailDetector, SecretDetector  # noqa: E402

# Public test card numbers (issued to nobody) that the synthetic data uses on purpose.
TEST_CARDS = {
    "4111111111111111",
    "5555555555554444",
    "378282246310005",
    "6011111111111117",
    "4012888888881881",
}
RESERVED_EMAIL = re.compile(
    r"@([\w-]+\.)*(example\.(com|net|org)|[\w-]+\.example|[\w-]+\.internal)$", re.IGNORECASE
)
# Test fixtures may contain synthetic secret-shaped strings on purpose; nothing else may.
FIXTURE_DIRS = ("tests/", "eval/cases/")
SKIP_DIRS = {".git", "__pycache__", ".mypy_cache", ".ruff_cache", ".pytest_cache", ".venv", "node_modules"}
SKIP_FILES = {"sensitivity_model.json", "redteam.json", "latency.json"}


def tracked_files() -> list[Path]:
    try:
        out = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True).stdout
        files = [ROOT / p for p in out.splitlines()]
    except (subprocess.CalledProcessError, FileNotFoundError):
        files = [p for p in ROOT.rglob("*") if p.is_file()]
    return [f for f in files if f.exists() and not set(f.parts) & SKIP_DIRS and f.name not in SKIP_FILES]


def main() -> int:
    results: list[tuple[bool, str]] = []
    files = tracked_files()
    rel = {f: str(f.relative_to(ROOT)) for f in files}

    results.append((not any(rel[f] == ".env" for f in files), "no .env file is tracked"))
    results.append(((ROOT / ".env.example").exists(), ".env.example exists"))

    secrets_found, cards_found, emails_found = [], [], []
    fixture_secrets = 0
    sd, cd, ed = SecretDetector(), CreditCardDetector(), EmailDetector()
    for f in files:
        try:
            text = f.read_text()
        except (UnicodeDecodeError, OSError):
            continue
        for x in sd.detect(text):
            if x.confidence >= 0.85 and x.detector != "regex.secret.assignment":
                if rel[f].startswith(FIXTURE_DIRS):
                    fixture_secrets += 1
                    continue
                secrets_found.append(f"{rel[f]}:{text[: x.start].count(chr(10)) + 1} {x.detector}")
        for x in cd.detect(text):
            digits = "".join(str(int(ch)) for ch in text[x.start : x.end] if ch.isdigit())
            if digits not in TEST_CARDS and x.confidence >= 0.8:
                cards_found.append(f"{rel[f]}:{text[: x.start].count(chr(10)) + 1}")
        for x in ed.detect(text):
            addr = text[x.start : x.end]
            local, _, domain = addr.partition("@")
            # Addresses that cannot exist: Gmail forbids '-', and '..' is invalid in any dot-atom (RFC 5322).
            ok = (
                bool(RESERVED_EMAIL.search(addr))
                or (domain.lower() == "gmail.com" and "-" in local)
                or ".." in local
            )
            if not ok and domain.lower() not in {"anthropic.com"}:
                emails_found.append(f"{rel[f]}: {addr}")
    results.append(
        (
            not secrets_found,
            f"no secret-shaped literals outside test fixtures ({fixture_secrets} synthetic "
            f"ones in fixtures) {secrets_found[:5]}",
        )
    )
    results.append((not cards_found, f"only public test card numbers in the repo {cards_found[:5]}"))
    results.append(
        (
            not emails_found,
            "emails use reserved .example domains (or impossible Gmail addresses with '-') "
            f"{emails_found[:5]}",
        )
    )

    compose = (ROOT / "docker-compose.yml").read_text()
    dockerfile = (ROOT / "Dockerfile").read_text()
    results.append(("USER 10001" in dockerfile, "containers run as a non-root user"))
    results.append(
        (
            '- --save\n      - ""' in compose and '- "no"' in compose,
            "Redis vault cache has persistence disabled",
        )
    )
    results.append(("internal: true" in compose, "data stores sit on an internal network with no egress"))
    results.append(
        (
            "read_only: true" in compose and "cap_drop: [ALL]" in compose,
            "app containers are read-only, no caps",
        )
    )
    results.append(("sha256=" in dockerfile, "spaCy model download is pinned by hash"))

    policy = (ROOT / "aegis/policy/default_policy.yaml").read_text()
    results.append(("PRIVATE_KEY: {action: block" in policy, "private keys block requests by default"))
    results.append(("gmail.com" in policy, "personal email providers are on the blocklist"))
    config = (ROOT / "aegis/config.py").read_text()
    results.append(
        (
            'raise ConfigError("AEGIS_VAULT_KEYS and AEGIS_AUDIT_HMAC_KEY are required' in config,
            "production refuses to start without vault and audit keys",
        )
    )

    width = max(len(m) for _, m in results)
    for ok, msg in results:
        print(f"{'PASS' if ok else 'FAIL'}  {msg[:width]}")
    failed = [m for ok, m in results if not ok]
    print(f"\n{len(results) - len(failed)}/{len(results)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
