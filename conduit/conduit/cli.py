"""Command line. `python -m conduit.cli` is what the Makefile calls."""

from __future__ import annotations

import argparse
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path

from conduit.embedder import FakeEmbedder
from conduit.evalrun import run_eval, write_reports
from conduit.pipeline import ROOT, Conduit
from conduit.redact import InProcessRedactor


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="conduit")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("eval")
    sub.add_parser("demo")
    sub.add_parser("interview")
    serve = sub.add_parser("serve")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8098)
    args = parser.parse_args(argv)
    if args.cmd == "eval":
        return _cmd_eval()
    if args.cmd == "demo":
        return _cmd_demo()
    if args.cmd == "interview":
        return _cmd_interview()
    if args.cmd == "serve":
        return _cmd_serve(args.host, args.port)
    return 2


def _cmd_eval() -> int:
    report = run_eval()
    write_reports(report)
    lag = report["lag_ms"]
    print(f"recall@1: {report['recall_at_1']:.0%} → after swap {report['recall_at_1_after_swap']:.0%}")
    print(
        f"update reuse: {report['embed_reused_on_updates']} reused, "
        f"{report['embed_calls_on_updates']} embedded"
    )
    print(f"migration embeds: {report['migration_embed_calls']} (reused {report['migration_reused']})")
    print(f"rtbf remaining: {report['rtbf_remaining_chunks']}")
    print(f"apply p50/p95: {lag['p50']} / {lag['p95']} ms")
    small = report["usd_per_million_docs_small"]
    print(f"projected $/M docs at measured size, text-embedding-3-small: {small}")
    print(f"gates: {'PASS' if report['gates_pass'] else 'FAIL'}")
    print(f"wrote {ROOT / 'reports' / 'eval.json'}")
    return 0 if report["gates_pass"] else 1


def _cmd_demo() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="conduit-demo-")) / "demo.db"
    conduit = Conduit(tmp, embedder=FakeEmbedder(), redactor=InProcessRedactor())
    try:
        conduit.reset()
        conduit.ingest_script("demo")
        conduit.consume()
        status = conduit.status()
        print(f"consumed log head {status['log_head']}, quarantine {status['quarantine']}")
        preview = status["preview"]
        if isinstance(preview, dict):
            print(f"redacted {preview['doc_id']}: {', '.join(preview['findings'])}")
        print(f"embedding reuse on the stream: {status['embed_reused']} chunks")
        conduit.start_migration("emb-v2")
        while conduit.store.migration().state == "dual_writing":
            conduit.migration_step(limit=20)
        conduit.swap()
        alias = conduit.status()["alias"]
        assert isinstance(alias, dict)
        print(f"read alias → {alias['name']} ({alias['model_version']})")
        found = conduit.search("mileage reimbursement receipt", k=1)
        hits = found["hits"]
        assert isinstance(hits, list)
        top = hits[0]["doc_id"] if hits else None
        print(f"search 'mileage reimbursement receipt' → {top} via {found['model_version']}")
        proof = conduit.forget("subj-ava-chen")
        print(
            f"forget subj-ava-chen: removed {proof['chunks_removed']}, "
            f"remaining {proof['remaining_chunks']}, verified {proof['verified']}"
        )
        conduit.replay()
        still = conduit.store.subject_chunk_count("subj-ava-chen")
        email = conduit.store.count_like("ava.chen@northwind.example")
        print(f"replay: ava links {still}, email in chunks {email['chunks']}, email in log {email['events']}")
        ok = (
            status["quarantine"] == 1
            and top == "handbook-expenses"
            and proof["verified"] is True
            and still == 0
            and email["chunks"] == 0
            and email["events"] == 0
            and alias["model_version"] == "emb-v2"
        )
        print("PASS" if ok else "FAIL")
        return 0 if ok else 1
    finally:
        conduit.close()


def _cmd_interview() -> int:
    path = ROOT / "docs" / "INTERVIEW_WALKTHROUGH.md"
    sys.stdout.write(path.read_text(encoding="utf-8"))
    if not path.read_text(encoding="utf-8").endswith("\n"):
        sys.stdout.write("\n")
    return 0


def _cmd_serve(host: str, port: int) -> int:
    import uvicorn

    from conduit.api.app import create_app

    uvicorn.run(create_app(), host=host, port=port, log_level="info")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
