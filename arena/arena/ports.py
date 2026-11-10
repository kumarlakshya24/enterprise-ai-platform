"""Lumen and Switchboard, with offline stand-ins.

The eval never calls the network. A configured URL is probed on demand and a
disagreement is reported. The bench does not overwrite its own table to match
a live service.
"""

from __future__ import annotations

from typing import Any, Protocol

import httpx

from arena.arms import Answer, RetrieverArm
from arena.corpus import Fact
from arena.retrieve import Index

# The Switchboard README's demo prompt. Default → balanced, latency-first →
# fast-cheap, quality-first → premium, on catalog 2026.11.05.
SWITCHBOARD_PROBE_PROMPT = "What is a load balancer, in two sentences?"


class LumenPort(Protocol):
    def ask(self, question: str, user_id: str = "frank") -> dict[str, Any]: ...


class LocalLumen:
    """Same fields Lumen's POST /ask returns, filled by the local index."""

    source = "lumen-stub"

    def __init__(self, arm: RetrieverArm) -> None:
        self.arm = arm

    def ask(self, question: str, user_id: str = "frank") -> dict[str, Any]:
        del user_id
        answer = self.arm.answer(question)
        return _from_answer(answer, self.source)


class HttpLumen:
    source = "lumen-http"

    def __init__(self, base_url: str, user_id: str = "frank", client: httpx.Client | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        self.user_id = user_id
        self._client = client

    def ask(self, question: str, user_id: str = "frank") -> dict[str, Any]:
        client = self._client or httpx.Client(timeout=10.0)
        close = self._client is None
        try:
            response = client.post(
                f"{self.base_url}/ask",
                headers={"X-User-Id": user_id or self.user_id},
                json={"question": question},
            )
            response.raise_for_status()
            payload = response.json()
        finally:
            if close:
                client.close()
        citations = []
        for row in payload.get("citations") or []:
            citations.append(
                {
                    "index": row.get("index"),
                    "doc_id": row.get("doc_id"),
                    "title": row.get("title"),
                    "section": row.get("section"),
                }
            )
        return {
            "answer": payload.get("answer") or "",
            "refused": bool(payload.get("refused")),
            "refusal_reason": payload.get("refusal_reason"),
            "citations": citations,
            "source": self.source,
        }


def _from_answer(answer: Answer, source: str) -> dict[str, Any]:
    return {
        "answer": answer.text,
        "refused": answer.refused,
        "refusal_reason": "no_support" if answer.refused else None,
        "citations": answer.citations,
        "source": source,
    }


def probe_lumen(url: str, client: httpx.Client | None = None) -> dict[str, Any]:
    if not url:
        return {
            "source": "lumen-stub",
            "ok": True,
            "detail": "ARENA_LUMEN_URL is empty; the RAG arm stays local.",
        }
    try:
        result = HttpLumen(url, client=client).ask("Where is public status published?")
    except httpx.HTTPError:
        return {
            "source": "lumen-http",
            "ok": False,
            "detail": "Lumen did not answer. The bench stays on the stub.",
        }
    return {
        "source": "lumen-http",
        "ok": True,
        "refused": result["refused"],
        "citations": len(result["citations"]),
        "detail": "Live Lumen answered a public status question. Eval numbers stay on the frozen corpus.",
    }


def probe_switchboard(
    url: str,
    expected: dict[str, dict[str, str]],
    client: httpx.Client | None = None,
) -> dict[str, Any]:
    if not url:
        return {
            "source": "switchboard-stub",
            "ok": True,
            "arms": expected,
            "detail": "ARENA_SWITCHBOARD_URL is empty. Serving models come from the price card.",
        }
    owned = client is None
    http = client or httpx.Client(timeout=10.0)
    rows: dict[str, Any] = {}
    try:
        for arm, spec in expected.items():
            try:
                response = http.post(
                    f"{url.rstrip('/')}/v1/route",
                    json={
                        "prompt": SWITCHBOARD_PROBE_PROMPT,
                        "policy": spec["policy"],
                        "dry_run": True,
                    },
                )
                response.raise_for_status()
                chosen = response.json().get("chosen_model")
            except httpx.HTTPError:
                rows[arm] = {"ok": False, "expected": spec["switchboard_model"], "chosen": None}
                continue
            rows[arm] = {
                "ok": chosen == spec["switchboard_model"],
                "expected": spec["switchboard_model"],
                "chosen": chosen,
                "policy": spec["policy"],
            }
    finally:
        if owned:
            http.close()
    return {
        "source": "switchboard-http",
        "ok": all(row.get("ok") for row in rows.values()) if rows else False,
        "arms": rows,
        "detail": "Agreement is reported. A disagreement does not change the Arena table.",
    }


def build_local_rag(index: Index, facts: dict[str, Fact], min_overlap: int) -> RetrieverArm:
    return RetrieverArm("rag", index, facts, min_overlap, cite=True)
