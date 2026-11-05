"""Run the whole stack without Docker: IdP, mock external LLM, mock local LLM, gateway.

SQLite and in-memory vault, one process per service, same trust boundaries as compose.
    python scripts/run_local.py      # then open http://localhost:8080
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PY = sys.executable


def main() -> int:
    base = {**os.environ, "PYTHONPATH": str(ROOT)}
    services = [
        ("idp", ["aegis.idp.app:app", "--port", "9000"], {"IDP_ISSUER": "http://127.0.0.1:9000"}),
        ("mock-llm", ["aegis.mock_llm.app:app", "--port", "8090"], {"MOCK_LLM_PERSONA": "external"}),
        ("local-llm", ["aegis.mock_llm.app:app", "--port", "8091"], {"MOCK_LLM_PERSONA": "local"}),
        (
            "gateway",
            ["--factory", "aegis.gateway.app:app_factory", "--port", "8080"],
            {
                "AEGIS_ENV": "dev",
                "DATABASE_URL": f"sqlite:///{ROOT / 'aegis-local.db'}",
                "OIDC_ISSUER": "http://127.0.0.1:9000",
                "OIDC_JWKS_URL": "http://127.0.0.1:9000/.well-known/jwks.json",
                "IDP_TOKEN_URL": "http://127.0.0.1:9000/token",
                "LLM_PROVIDER": "openai_compatible",
                "LLM_BASE_URL": "http://127.0.0.1:8090/v1",
                "LLM_MODEL": "mock-gpt",
                "LOCAL_LLM_PROVIDER": "openai_compatible",
                "LOCAL_LLM_BASE_URL": "http://127.0.0.1:8091/v1",
            },
        ),
    ]
    procs = []
    for name, args, env in services:
        cmd = [PY, "-m", "uvicorn", *args, "--host", "127.0.0.1", "--log-level", "warning"]
        procs.append((name, subprocess.Popen(cmd, cwd=ROOT, env={**base, **env})))
        print(f"started {name}")
        time.sleep(1.5 if name == "idp" else 0.3)
    print("open http://localhost:8080  (Ctrl-C to stop)")
    try:
        while all(p.poll() is None for _, p in procs):
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        for _, p in procs:
            p.send_signal(signal.SIGINT)
        for _, p in procs:
            p.wait(timeout=10)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
