"""Agent tools (sandboxed) and their OpenAI function specs.

Nothing here touches the network or sends mail. `send_email` writes to an in-memory outbox and URL
tools write to an egress log, so the demo can show exactly what would have left the company.
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from aegis.demo.data import CUSTOMERS, WIKI_PAGES, search_wiki
from aegis.guard.urls import host_of
from aegis.llm.base import ToolCall
from aegis.types import EntityType


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    params: dict[str, str]
    recipient_fields: tuple[str, ...] = ()
    url_fields: tuple[str, ...] = ()
    # For structured outputs: field -> entity type, tokenized by schema before the model sees them.
    sensitive_output_fields: dict[str, EntityType] = field(default_factory=dict)

    def openai(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {k: {"type": "string", "description": v} for k, v in self.params.items()},
                    "required": list(self.params),
                },
            },
        }


TOOLS: dict[str, ToolSpec] = {
    t.name: t
    for t in [
        ToolSpec(
            "lookup_customer",
            "Fetch a customer record from the CRM by id (for example C-1042).",
            {"customer_id": "CRM customer id"},
            sensitive_output_fields={
                "name": EntityType.PERSON_NAME,
                "email": EntityType.EMAIL,
                "phone": EntityType.PHONE,
                "card_on_file": EntityType.CREDIT_CARD,
            },
        ),
        ToolSpec(
            "search_wiki", "Search the internal wiki. Returns page ids and titles.", {"query": "search terms"}
        ),
        ToolSpec("read_wiki", "Read an internal wiki page by id.", {"page_id": "wiki page id"}),
        ToolSpec(
            "send_email",
            "Send an email.",
            {"to": "recipient address", "subject": "subject line", "body": "plain text body"},
            recipient_fields=("to",),
        ),
        ToolSpec(
            "share_document",
            "Share a document with a recipient.",
            {"doc_id": "document id", "recipient": "recipient address"},
            recipient_fields=("recipient",),
        ),
        ToolSpec("http_get", "Fetch a web page.", {"url": "absolute URL"}, url_fields=("url",)),
        ToolSpec(
            "render_image", "Render an image in the chat by URL.", {"url": "image URL"}, url_fields=("url",)
        ),
        ToolSpec(
            "post_webhook",
            "POST a JSON payload to a webhook URL.",
            {"url": "webhook URL", "payload": "JSON payload as a string"},
            url_fields=("url",),
        ),
    ]
}

TOOL_SPECS = [t.openai() for t in TOOLS.values()]


class Sandbox:
    """In-memory stand-ins for mail, file sharing, and the network."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.outbox: list[dict[str, Any]] = []
        self.egress: list[dict[str, Any]] = []
        self.shares: list[dict[str, Any]] = []

    def reset(self) -> None:
        with self._lock:
            self.outbox.clear()
            self.egress.clear()
            self.shares.clear()

    def evidence(self) -> dict[str, Any]:
        with self._lock:
            return {"outbox": list(self.outbox), "egress": list(self.egress), "shares": list(self.shares)}

    def execute(self, call: ToolCall, *, mode: str) -> tuple[str, dict[str, Any] | None]:
        """Run a tool. Returns (text output, structured output or None)."""
        a = {k: str(v) for k, v in call.arguments.items()}
        now = datetime.now(UTC).isoformat(timespec="seconds")
        if call.name == "lookup_customer":
            record = CUSTOMERS.get(a.get("customer_id", "").strip().upper())
            if record is None:
                return json.dumps({"error": "customer not found"}), None
            return json.dumps(record), dict(record)
        if call.name == "search_wiki":
            return json.dumps(search_wiki(a.get("query", ""))), None
        if call.name == "read_wiki":
            page = WIKI_PAGES.get(a.get("page_id", ""))
            return (page["body"] if page else "page not found"), None
        with self._lock:
            if call.name == "send_email":
                self.outbox.append(
                    {
                        "at": now,
                        "mode": mode,
                        "to": a.get("to", ""),
                        "subject": a.get("subject", ""),
                        "body": a.get("body", ""),
                    }
                )
                return f"email queued to {a.get('to', '')}", None
            if call.name == "share_document":
                self.shares.append(
                    {
                        "at": now,
                        "mode": mode,
                        "doc_id": a.get("doc_id", ""),
                        "recipient": a.get("recipient", ""),
                    }
                )
                return "document shared", None
            if call.name in ("http_get", "render_image", "post_webhook"):
                url = a.get("url", "")
                self.egress.append(
                    {
                        "at": now,
                        "mode": mode,
                        "tool": call.name,
                        "url": url,
                        "host": host_of(url),
                        "payload": a.get("payload"),
                    }
                )
                if call.name == "http_get":
                    return "<html><body>Shipping status: in transit, expected in 2 days.</body></html>", None
                return "ok", None
        return f"unknown tool {call.name}", None
