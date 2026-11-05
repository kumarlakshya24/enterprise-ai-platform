"""HTTP adapters fail closed, and succeed when the stub server speaks the contract."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from atlas.guard import HttpAegisGuard
from atlas.knowledge import REFUSAL, HttpLumen


def _serve(handler: type[BaseHTTPRequestHandler]) -> tuple[ThreadingHTTPServer, str]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address[:2]
    return server, f"http://{host}:{port}"


def test_aegis_http_adapter_maps_the_verdict() -> None:
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802
            length = int(self.headers.get("content-length", "0"))
            body = json.loads(self.rfile.read(length))
            assert body["tool"] == "http.post"
            payload = json.dumps(
                {"verdict": "block", "rule": "R-TOOL-URL-NOT-ALLOWLISTED", "message": "no"}
            ).encode()
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, fmt: str, *args: object) -> None:
            del fmt, args

    server, url = _serve(Handler)
    try:
        decision = HttpAegisGuard(url).evaluate(
            tool="http.post",
            args={"url": "https://hook.personal.test/x"},
            risk="high",
            idempotent=True,
            approved=False,
            rationale="",
        )
    finally:
        server.shutdown()
    assert decision.verdict == "block"
    assert decision.rule == "R-TOOL-URL-NOT-ALLOWLISTED"


def test_aegis_adapter_fails_closed_when_the_gateway_is_down() -> None:
    decision = HttpAegisGuard("http://127.0.0.1:1").evaluate(
        tool="ledger.post",
        args={},
        risk="high",
        idempotent=True,
        approved=True,
        rationale="",
    )
    assert decision.verdict == "block"
    assert decision.rule == "R-AEGIS-UNAVAILABLE"


def test_lumen_http_adapter_reads_the_ask_contract() -> None:
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802
            assert self.headers.get("x-user-id") == "atlas-worker"
            payload = json.dumps(
                {
                    "answer": "Refunds up to $200 are allowed. Amounts above $25 require approval.",
                    "citations": [{"doc_id": "POL-REF-014", "title": "Customer refund policy"}],
                    "refused": False,
                }
            ).encode()
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, fmt: str, *args: object) -> None:
            del fmt, args

    server, url = _serve(Handler)
    try:
        answer = HttpLumen(url, "atlas-worker").ask("What is the customer refund policy?", principal="atlas-worker")
    finally:
        server.shutdown()
    assert answer["refused"] is False
    assert answer["citations"][0]["doc_id"] == "POL-REF-014"


def test_lumen_adapter_refuses_when_the_service_is_down() -> None:
    answer = HttpLumen("http://127.0.0.1:1", "atlas-worker").ask("refund?", principal="atlas-worker")
    assert answer["refused"] is True
    assert answer["answer"] == REFUSAL
