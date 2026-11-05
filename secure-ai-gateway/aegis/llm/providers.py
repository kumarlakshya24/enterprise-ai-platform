"""LLM providers: in-process mock (default, offline) and any OpenAI-compatible HTTP endpoint."""

from __future__ import annotations

import contextlib
import time
from collections import deque
from datetime import UTC, datetime
from typing import Any

import httpx

from aegis.llm.base import ChatMessage, LLMResponse, Location, ProviderError
from aegis.llm.mock_brain import MockBrain


class MockProvider:
    """Runs MockBrain in-process and records what it received (the third party's view)."""

    def __init__(self, name: str, location: Location, model: str = "mock-1", history: int = 200) -> None:
        self.name = name
        self.location: Location = location
        self.model = model
        self.brain = MockBrain(persona=location)
        self.received: deque[dict[str, Any]] = deque(maxlen=history)

    def complete(self, messages: list[ChatMessage], tools: list[dict[str, Any]] | None = None) -> LLMResponse:
        t0 = time.perf_counter()
        self.received.append(
            {
                "at": datetime.now(UTC).isoformat(),
                "model": self.model,
                "messages": [m.to_openai() for m in messages],
                "tools": [t["function"]["name"] for t in tools or []],
            }
        )
        msg = self.brain.respond(messages, tools)
        return LLMResponse(msg, self.model, self.name, self.location, (time.perf_counter() - t0) * 1000)

    def evidence(self, limit: int = 20) -> list[dict[str, Any]]:
        return list(self.received)[-limit:]

    def reset(self) -> None:
        self.received.clear()


class OpenAICompatibleProvider:
    """OpenAI chat-completions over HTTP. Works with OpenAI, Azure-compatible proxies, vLLM, Ollama,
    and the bundled mock-llm service. The API key is sent only as a bearer header, never logged."""

    def __init__(
        self,
        name: str,
        location: Location,
        base_url: str,
        model: str,
        api_key: str = "",
        timeout: float = 30.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.name = name
        self.location: Location = location
        self.model = model
        self.base_url = base_url.rstrip("/")
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self._client = httpx.Client(timeout=timeout, headers=headers, transport=transport)

    def complete(self, messages: list[ChatMessage], tools: list[dict[str, Any]] | None = None) -> LLMResponse:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [m.to_openai() for m in messages],
            "temperature": 0,
        }
        if tools:
            payload["tools"] = tools
        t0 = time.perf_counter()
        try:
            resp = self._client.post(f"{self.base_url}/chat/completions", json=payload)
        except httpx.HTTPError as exc:
            raise ProviderError(f"{self.name} unreachable: {type(exc).__name__}") from exc
        if resp.status_code >= 400:
            raise ProviderError(f"{self.name} returned HTTP {resp.status_code}")
        try:
            data = resp.json()
            msg = ChatMessage.from_openai(data["choices"][0]["message"])
        except (ValueError, KeyError, IndexError) as exc:
            raise ProviderError(f"{self.name} returned an unexpected payload") from exc
        return LLMResponse(
            msg, data.get("model", self.model), self.name, self.location, (time.perf_counter() - t0) * 1000
        )

    def evidence(self, limit: int = 20) -> list[dict[str, Any]]:
        """Only the bundled mock-llm service exposes what it received."""
        try:
            r = self._client.get(
                f"{self.base_url.removesuffix('/v1')}/_evidence/received", params={"limit": limit}
            )
            if r.status_code == 200:
                result: list[dict[str, Any]] = r.json()
                return result
        except httpx.HTTPError:
            pass
        return []

    def reset(self) -> None:
        with contextlib.suppress(httpx.HTTPError):
            self._client.post(f"{self.base_url.removesuffix('/v1')}/_evidence/reset")
