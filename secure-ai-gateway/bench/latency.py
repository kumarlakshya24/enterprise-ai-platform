"""Latency benchmark: added latency from DLP, NER, tokenization, classification, policy, restore.

    python bench/latency.py                      # in-process, writes reports/latency.md
    python bench/latency.py --url http://localhost:8080 --label compose   # live stack (Postgres + Redis)

The LLM call itself is excluded: the mock provider answers in microseconds, so what is measured is
the overhead the gateway adds. Budget: p95 under 300 ms for the fast path and the full path.
"""

from __future__ import annotations

import argparse
import json
import secrets
import statistics
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from aegis.demo.scenarios import SCENARIOS_BY_ID as S  # noqa: E402

BUDGET_MS = 300.0
REPORT_MD = ROOT / "reports" / "latency.md"
REPORT_JSON = ROOT / "reports" / "latency.json"

LONG = " ".join(
    [
        S["s1_direct_paste"]["input"],
        "The customer also mentioned that the previous order arrived late and the packaging was damaged.",
        "They asked whether the loyalty discount still applies and whether they can switch to annual billing.",
        "Our notes show two earlier tickets about login problems that were resolved by resetting MFA.",
    ]
    * 5
)
PROMPTS = {
    "fast path (PUBLIC question, 81 chars)": S["s5_legit"]["input"],
    "full path (complaint with 3 entities, 270 chars)": S["s1_direct_paste"]["input"],
    "context route (confidential note, 230 chars)": S["s2_context_leak"]["input"],
    f"long prompt ({len(LONG)} chars, 15 entities)": LONG,
}


def pct(samples: list[float], p: float) -> float:
    s = sorted(samples)
    k = max(0, min(len(s) - 1, round(p / 100 * (len(s) - 1))))
    return s[k]


def stats(samples: list[float]) -> dict[str, float]:
    return {
        "p50": round(pct(samples, 50), 3),
        "p95": round(pct(samples, 95), 3),
        "p99": round(pct(samples, 99), 3),
        "mean": round(statistics.fmean(samples), 3),
        "n": len(samples),
    }


def timeit(fn: Callable[[], Any], n: int, warmup: int = 15) -> list[float]:
    for _ in range(warmup):
        fn()
    out = []
    for _ in range(n):
        t0 = time.perf_counter()
        fn()
        out.append((time.perf_counter() - t0) * 1000)
    return out


def in_process(n: int) -> dict[str, Any]:
    import spacy
    from fastapi.testclient import TestClient

    from aegis.auth.oidc import static_resolver
    from aegis.auth.rbac import restore_scopes_for
    from aegis.classifier.model import load_default_classifier
    from aegis.config import Settings
    from aegis.dlp.engine import DLPEngine
    from aegis.gateway.app import create_app
    from aegis.gateway.container import build_container
    from aegis.gateway.pipeline import classifier_view
    from aegis.idp.issuer import DIRECTORY, TokenIssuer
    from aegis.llm.providers import MockProvider
    from aegis.policy.engine import decide
    from aegis.policy.store import load_bundle_file
    from aegis.vault.backends import MemoryBackend
    from aegis.vault.crypto import VaultCipher
    from aegis.vault.vault import TokenVault, VaultContext

    policy = load_bundle_file().base
    dlp = DLPEngine.default("spacy")
    clf = load_default_classifier()
    ner = next(d for d in dlp.detectors if d.name.startswith("ner."))
    scopes = restore_scopes_for(["employee", "support_agent"])
    stages: dict[str, dict[str, Any]] = {}
    for label, text in PROMPTS.items():
        vault = TokenVault(MemoryBackend(), VaultCipher({"b": secrets.token_bytes(32)}, "b"))
        ctx = VaultContext("acme", "u-b", "sess-bench-01", "chat")
        scan = dlp.scan(text, policy)
        tokenized = vault.apply(scan, ctx)
        c = clf.classify(classifier_view(tokenized))

        counter = [0]

        def tok(scan: Any = scan, vault: TokenVault = vault, counter: list[int] = counter) -> None:
            # Cold path: a new session each time, so every value is encrypted and stored (no index hits).
            counter[0] += 1
            vault.apply(scan, VaultContext("acme", "u-b", f"sess-bench-{counter[0]:08d}", "chat"))

        stages[label] = {
            "regex detectors": stats(timeit(lambda t=text: dlp.scan(t, policy, use_ner=False), n)),
            "spaCy NER": stats(timeit(lambda t=text: ner.detect(t), n)),
            "full DLP scan": stats(timeit(lambda t=text: dlp.scan(t, policy), n)),
            "tokenize (vault, AES-GCM)": stats(timeit(tok, n)),
            "classify": stats(timeit(lambda v=classifier_view(tokenized): clf.classify(v, 0.55), n)),
            "policy decision": stats(
                timeit(
                    lambda t=text, s=scan, cc=c: decide(
                        text=t, scan=s, classification=cc, policy=policy, policy_version="b"
                    ),
                    n,
                )
            ),
            "restore": stats(timeit(lambda tk=tokenized, v=vault, cx=ctx: v.restore_text(tk, cx, scopes), n)),
        }

    # Optimization lever: the full spaCy pipeline vs NER only.
    full_nlp = spacy.load("en_core_web_sm")
    lever = {
        "spaCy full pipeline": stats(timeit(lambda: full_nlp(S["s1_direct_paste"]["input"]), n)),
        "spaCy NER only (what we run)": stats(timeit(lambda: ner.detect(S["s1_direct_paste"]["input"]), n)),
    }

    # End-to-end through FastAPI: auth, rate limit, DLP, vault, classifier, policy, 4 audit writes, restore.
    issuer = TokenIssuer("http://bench-idp", "aegis-gateway")
    settings = Settings(
        env="test",
        database_url="sqlite://",
        oidc_issuer="http://bench-idp",
        vault_keys={"k": secrets.token_bytes(32)},
        vault_active_kid="k",
        audit_hmac_key=secrets.token_bytes(32),
        rate_limit_per_minute=0,
    )
    container = build_container(
        settings,
        key_resolver=static_resolver(issuer.public_key()),
        kv=MemoryBackend(),
        external_llm=MockProvider("external", "external"),
        local_llm=MockProvider("local", "local"),
        dlp=dlp,
    )
    client = TestClient(create_app(container))
    headers = {"Authorization": f"Bearer {issuer.issue(DIRECTORY['avery'])}"}
    e2e: dict[str, Any] = {}
    for label, text in PROMPTS.items():
        server: list[float] = []

        def call(t: str = text, sink: list[float] = server) -> None:
            r = client.post("/chat", json={"message": t}, headers=headers)
            sink.append(r.json()["latency_ms"]["gateway_overhead_ms"])

        client_ms = timeit(call, n)
        e2e[label] = {
            "gateway_overhead (server)": stats(server[15:]),
            "request round trip (client)": stats(client_ms),
        }
    return {
        "mode": "in-process",
        "ner_backend": dlp.ner_backend,
        "stages": stages,
        "lever": lever,
        "e2e": e2e,
    }


def live(url: str, n: int) -> dict[str, Any]:
    import httpx

    http = httpx.Client(base_url=url, timeout=30)
    tok = http.post("/demo/login", json={"username": "avery"}).json()["access_token"]
    headers = {"Authorization": f"Bearer {tok}"}
    health = http.get("/healthz").json()
    e2e: dict[str, Any] = {}
    for label, text in PROMPTS.items():
        server: list[float] = []

        def call(t: str = text, sink: list[float] = server) -> None:
            r = http.post("/chat", json={"message": t}, headers=headers)
            if r.status_code == 429:
                raise SystemExit(
                    "rate limited: set AEGIS_RATE_LIMIT_PER_MINUTE=100000 in .env and "
                    "`docker compose up -d gateway` before benchmarking, then restore it"
                )
            r.raise_for_status()
            sink.append(r.json()["latency_ms"]["gateway_overhead_ms"])

        client_ms = timeit(call, n, warmup=5)
        e2e[label] = {
            "gateway_overhead (server)": stats(server[5:]),
            "request round trip (client)": stats(client_ms),
        }
    return {"mode": f"live {url}", "health": health, "e2e": e2e}


def table(rows: dict[str, dict[str, float]]) -> list[str]:
    out = ["| Stage | p50 ms | p95 ms | p99 ms |", "|---|---|---|---|"]
    out += [f"| {k} | {v['p50']} | {v['p95']} | {v['p99']} |" for k, v in rows.items()]
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=200)
    ap.add_argument("--url", default=None)
    ap.add_argument("--label", default="")
    args = ap.parse_args()
    import platform

    result = live(args.url, args.n) if args.url else in_process(args.n)
    result["machine"] = f"{platform.processor() or platform.machine()} · Python {platform.python_version()}"
    existing = json.loads(REPORT_JSON.read_text()) if REPORT_JSON.exists() else {}
    key = args.label or ("live" if args.url else "in_process")
    existing[key] = result
    REPORT_JSON.parent.mkdir(exist_ok=True)
    REPORT_JSON.write_text(json.dumps(existing, indent=2) + "\n")

    failed = False
    lines = [
        "# Latency report",
        "",
        "Generated by `make benchmark` (`python bench/latency.py`). Do not edit by hand. Times are milliseconds",
        "of overhead added by the gateway; the LLM call is excluded (mock provider). Budget: **p95 < 300 ms**.",
        "",
    ]
    for name, res in existing.items():
        lines += [f"## {name}: {res['mode']}", "", f"Machine: {res.get('machine', 'n/a')}", ""]
        if "stages" in res:
            for label, rows in res["stages"].items():
                lines += [f"### Stages: {label}", "", *table(rows), ""]
            lines += ["### Optimization lever: run only the NER component", "", *table(res["lever"]), ""]
        lines += [
            "### End to end through the HTTP API",
            "",
            "| Prompt | overhead p50 | overhead p95 | round trip p95 | Budget |",
            "|---|---|---|---|---|",
        ]
        for label, r in res["e2e"].items():
            over = r["gateway_overhead (server)"]
            ok = over["p95"] < BUDGET_MS
            failed |= not ok
            lines.append(
                f"| {label} | {over['p50']} | {over['p95']} | {r['request round trip (client)']['p95']} | "
                f"{'PASS' if ok else 'FAIL'} |"
            )
        lines.append("")
    lines += [
        "## How the budget is kept",
        "",
        "* Only the spaCy NER component runs (tagger, parser, lemmatizer disabled): see the lever table above.",
        "* Regex detectors are precompiled and run in well under a millisecond.",
        "* The classifier is a sparse dot product over at most a few hundred n-grams: no model server, no GPU.",
        "* Audit writes are the largest fixed cost (four appends per request, serialized by the hash chain).",
        "  Next steps if the budget tightens: batch the four events into one append, and move the chain to",
        "  per-tenant heads so replicas do not contend on one row lock.",
        "* Long prompts scale roughly linearly with length in NER; above a few thousand characters, NER could run",
        "  on sentence chunks in parallel, or be skipped for chunks with no capitalized tokens.",
    ]
    REPORT_MD.write_text("\n".join(lines) + "\n")
    for label, r in result["e2e"].items():
        o = r["gateway_overhead (server)"]
        print(f"{label}: overhead p50 {o['p50']} ms, p95 {o['p95']} ms")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
