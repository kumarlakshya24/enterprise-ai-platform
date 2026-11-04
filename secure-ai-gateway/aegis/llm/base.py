"""Provider-neutral chat types in OpenAI wire format."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

Location = Literal["external", "local"]


class ProviderError(RuntimeError):
    pass


@dataclass
class ToolCall:
    name: str
    arguments: dict[str, Any]
    id: str = field(default_factory=lambda: f"call_{uuid.uuid4().hex[:12]}")

    def to_openai(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "type": "function",
            "function": {"name": self.name, "arguments": json.dumps(self.arguments)},
        }

    @classmethod
    def from_openai(cls, d: dict[str, Any]) -> ToolCall:
        fn = d.get("function", {})
        raw = fn.get("arguments") or "{}"
        try:
            args = json.loads(raw) if isinstance(raw, str) else dict(raw)
        except json.JSONDecodeError:
            args = {"_unparsed": raw}
        return cls(name=fn.get("name", ""), arguments=args, id=d.get("id") or f"call_{uuid.uuid4().hex[:12]}")


@dataclass
class ChatMessage:
    role: Literal["system", "user", "assistant", "tool"]
    content: str | None = None
    tool_calls: list[ToolCall] | None = None
    tool_call_id: str | None = None
    name: str | None = None

    def to_openai(self) -> dict[str, Any]:
        d: dict[str, Any] = {"role": self.role, "content": self.content}
        if self.tool_calls:
            d["tool_calls"] = [tc.to_openai() for tc in self.tool_calls]
        if self.tool_call_id:
            d["tool_call_id"] = self.tool_call_id
        if self.name and self.role == "tool":
            d["name"] = self.name
        return d

    @classmethod
    def from_openai(cls, d: dict[str, Any]) -> ChatMessage:
        calls = [ToolCall.from_openai(tc) for tc in d.get("tool_calls") or []]
        return cls(
            role=d.get("role", "assistant"),
            content=d.get("content"),
            tool_calls=calls or None,
            tool_call_id=d.get("tool_call_id"),
            name=d.get("name"),
        )


@dataclass
class LLMResponse:
    message: ChatMessage
    model: str
    provider: str
    location: Location
    latency_ms: float


class LLMProvider(Protocol):
    name: str
    location: Location
    model: str

    def complete(
        self, messages: list[ChatMessage], tools: list[dict[str, Any]] | None = None
    ) -> LLMResponse: ...
