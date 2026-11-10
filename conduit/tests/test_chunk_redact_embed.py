from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

from conduit.chunker import chunk_document
from conduit.embedder import FAKE_MODELS, FakeEmbedder, OpenAIEmbedder, cosine
from conduit.redact import HttpRedactor, InProcessRedactor
from conduit.subjects import SUBJECTS


def test_paragraphs_with_different_subjects_do_not_share_a_chunk() -> None:
    text = (
        "Ava Chen stays in her own paragraph with enough words to stand alone as a vector.\n\n"
        "Leo Martinez stays in his own paragraph and keeps his own vector."
    )
    redacted = InProcessRedactor().redact(text, SUBJECTS).text
    chunks = chunk_document("Ticket", redacted)
    assert len(chunks) == 2
    assert chunks[0].subjects == ("subj-ava-chen",)
    assert chunks[1].subjects == ("subj-leo-martinez",)
    assert chunks[0].content_hash != chunks[1].content_hash


def test_same_text_same_hash_and_model_salt_changes_the_vector() -> None:
    first = chunk_document("Leave", "Carry 5 days into March and then stop.")
    second = chunk_document("Leave", "Carry 5 days into March and then stop.")
    assert first[0].content_hash == second[0].content_hash
    embedder = FakeEmbedder()
    left = embedder.embed(first[0].embed_text, "emb-v1")
    again = embedder.embed(first[0].embed_text, "emb-v1")
    right = embedder.embed(first[0].embed_text, "emb-v2")
    assert left == again
    assert left != right
    assert abs(cosine(left, right)) < 0.5
    assert len(left) == FAKE_MODELS["emb-v1"].dim


def test_redactor_replaces_identifiers_and_keeps_the_subject_link() -> None:
    raw = (
        "Ava Chen (ava.chen@northwind.example) called. Phone 415-555-0148. "
        "Card 4111 1111 1111 1111. Reference 219-09-9999."
    )
    result = InProcessRedactor().redact(raw, SUBJECTS)
    assert "ava.chen@northwind.example" not in result.text
    assert "Ava Chen" not in result.text
    assert "4111" not in result.text
    assert "219-09-9999" not in result.text
    assert "415-555-0148" not in result.text
    assert "[PERSON:subj-ava-chen]" in result.text
    assert "[CARD]" in result.text
    assert "[SSN]" in result.text
    assert "[PHONE]" in result.text
    kinds = {finding.kind for finding in result.findings}
    assert kinds == {"person", "card", "ssn", "phone"}


def test_redactor_unavailable_raises() -> None:
    try:
        InProcessRedactor().redact("page [[REDACTOR_UNAVAILABLE]]", SUBJECTS)
    except Exception as exc:
        assert "unavailable" in str(exc)
    else:
        raise AssertionError("expected the redactor to fail closed")


def test_http_redactor_uses_the_response_and_fails_closed() -> None:
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            length = int(self.headers.get("content-length", "0"))
            payload = json.loads(self.rfile.read(length))
            assert payload["text"] == "hello ava"
            body = json.dumps(
                {
                    "text": "hello [PERSON:subj-ava-chen]",
                    "findings": [{"kind": "person", "replacement": "[PERSON:subj-ava-chen]"}],
                }
            ).encode()
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, fmt: str, *args: object) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_address[1]
        result = HttpRedactor(f"http://127.0.0.1:{port}").redact("hello ava", SUBJECTS)
        assert result.text == "hello [PERSON:subj-ava-chen]"
    finally:
        server.shutdown()
    try:
        HttpRedactor("http://127.0.0.1:9", timeout=0.2).redact("hello", SUBJECTS)
    except Exception as exc:
        assert "aegis redact failed" in str(exc)
    else:
        raise AssertionError("expected a down redactor to fail closed")


def test_openai_adapter_refuses_without_a_key_and_does_not_post(monkeypatch: object) -> None:
    from pytest import MonkeyPatch

    assert isinstance(monkeypatch, MonkeyPatch)
    monkeypatch.delenv("CONDUIT_OPENAI_API_KEY", raising=False)

    def explode(*_args: object, **_kwargs: object) -> dict[str, object]:
        raise AssertionError("network post should not run")

    embedder = OpenAIEmbedder(api_key="", post=explode)
    try:
        embedder.embed("hello", "text-embedding-3-small")
    except Exception as exc:
        assert "CONDUIT_OPENAI_API_KEY" in str(exc)
    else:
        raise AssertionError("expected a missing key to fail before any call")

    def fake_post(
        url: str, payload: dict[str, object], headers: dict[str, str], timeout: float
    ) -> dict[str, object]:
        assert payload["model"] == "text-embedding-3-small"
        assert headers["authorization"] == "Bearer test-key"
        assert url.endswith("/embeddings")
        assert timeout == 10.0
        return {"data": [{"embedding": [0.0, 1.0]}]}

    wired = OpenAIEmbedder(api_key="test-key", post=fake_post)
    assert wired.embed("hello", "text-embedding-3-small") == (0.0, 1.0)


def test_cost_projection_is_tokens_times_list_price() -> None:
    from conduit.metrics import tokens_from_chars, usd_per_million_docs

    tokens = tokens_from_chars(800, 4)
    assert tokens == 200
    assert usd_per_million_docs(tokens, 0.02) == 4
    assert usd_per_million_docs(2000, 0.02) == 40
    assert usd_per_million_docs(8000, 0.13) == 1040
