"""Create .env from .env.example with fresh random secrets. Never overwrites an existing .env."""

from __future__ import annotations

import base64
import secrets
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    env, example = ROOT / ".env", ROOT / ".env.example"
    if env.exists():
        print(".env already exists; leaving it alone")
        return 0
    generated = {
        "POSTGRES_PASSWORD": secrets.token_urlsafe(24),
        "REDIS_PASSWORD": secrets.token_urlsafe(24),
        "AEGIS_VAULT_KEYS": "k1:" + base64.b64encode(secrets.token_bytes(32)).decode(),
        "AEGIS_VAULT_ACTIVE_KID": "k1",
        "AEGIS_AUDIT_HMAC_KEY": base64.b64encode(secrets.token_bytes(32)).decode(),
    }
    out = []
    for raw in example.read_text().splitlines():
        key, sep, value = raw.partition("=")
        filled = sep and not raw.lstrip().startswith("#") and key in generated and not value
        out.append(f"{key}={generated[key]}" if filled else raw)
    env.write_text("\n".join(out) + "\n")
    env.chmod(0o600)
    print("wrote .env with fresh random keys (mode 600)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
