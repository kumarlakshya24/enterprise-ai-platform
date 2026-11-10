"""Lumen and Switchboard ports fail closed and do not rewrite the bench."""

from __future__ import annotations

import json

import httpx

from arena.ports import SWITCHBOARD_PROBE_PROMPT, HttpLumen, LocalLumen, probe_lumen, probe_switchboard
from arena.world import World


def test_local_lumen_matches_the_ask_shape(world: World) -> None:
    port = LocalLumen(world.rag_current)
    result = port.ask("After approval, what is the refund window?", user_id="frank")
    assert result["source"] == "lumen-stub"
    assert result["refused"] is False
    assert result["refusal_reason"] is None
    assert "30 days" in result["answer"]
    assert result["citations"][0]["doc_id"] == "billing-refunds"
    assert "section" in result["citations"][0]
    missing = port.ask("What is the founder's favorite tea?")
    assert missing["refused"] is True
    assert missing["refusal_reason"] == "no_support"
    assert missing["citations"] == []


def test_http_lumen_reads_the_live_shape() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/ask"
        assert request.headers["X-User-Id"] == "frank"
        return httpx.Response(
            200,
            json={
                "answer": "Cited answer [1]",
                "refused": False,
                "refusal_reason": None,
                "citations": [
                    {"index": 1, "doc_id": "fin-remote", "title": "Remote", "section": "Allowance"}
                ],
            },
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    result = HttpLumen("http://lumen.test", client=client).ask("Remote work?")
    assert result["source"] == "lumen-http"
    assert result["citations"][0]["doc_id"] == "fin-remote"
    assert result["answer"] == "Cited answer [1]"


def test_lumen_probe_fails_closed() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    probed = probe_lumen("http://lumen.test", client=client)
    assert probed["ok"] is False
    assert probed["source"] == "lumen-http"
    empty = probe_lumen("")
    assert empty["source"] == "lumen-stub"
    assert empty["ok"] is True


def test_switchboard_probe_records_disagreement_without_overwriting(world: World) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["prompt"] == SWITCHBOARD_PROBE_PROMPT
        chosen = {
            "latency-first": "fast-cheap",
            "default": "balanced",
            "quality-first": "local",
        }[body["policy"]]
        return httpx.Response(200, json={"chosen_model": chosen, "outcome": "dry_run"})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    probed = probe_switchboard("http://switchboard.test", world.serving, client=client)
    assert probed["source"] == "switchboard-http"
    assert probed["arms"]["prompt"]["ok"] is True
    assert probed["arms"]["distilled"]["ok"] is True
    # quality-first on the demo prompt is premium in the Switchboard README.
    # A local answer is a disagreement, not a new Arena winner.
    assert probed["arms"]["lora"]["expected"] == "premium"
    assert probed["arms"]["lora"]["chosen"] == "local"
    assert probed["arms"]["lora"]["ok"] is False
    assert probed["ok"] is False
    assert world.serving["lora"]["switchboard_model"] == "premium"
