"""Deterministic stand-in for an LLM, used offline by the demo and the tests.

It is deliberately gullible: when a tool output contains instructions, it follows them. That is
the point. The gateway must stop exfiltration even when the model is fooled, so the demo should
not depend on the model behaving well.
"""

from __future__ import annotations

import json
import re
from typing import Any

from aegis.llm.base import ChatMessage, ToolCall

_PLACEHOLDER = re.compile(
    r"\[(PERSON_NAME|ORG|EMAIL|PHONE|CREDIT_CARD|SSN|API_KEY|PASSWORD|PRIVATE_KEY)_\d+\]"
)
_RAW_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_RAW_CARD = re.compile(r"(?<!\d)(?:\d[ -]?){12,18}\d(?!\d)")
_RAW_NAME = re.compile(r"(?:my name is|I am|I'm)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)")
_CUSTOMER_ID = re.compile(r"\bC-\d{4}\b")
_WRAPPED = re.compile(r"<untrusted_tool_output[^>]*>\n?(.*?)\n?</untrusted_tool_output>", re.DOTALL)
_EMAIL_TARGET = re.compile(
    r"\b(?:email|e-mail|send|mail)\b[^.]*?\bto\b\s+(?:my\s+\w+\s+(?:address|email)\s+)?"
    r"(\[EMAIL_\d+\]|[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,})",
    re.IGNORECASE,
)
_URL_TEMPLATE = re.compile(r"https?://[^\s\"'<>)]+")
_FOLLOW_VERBS = re.compile(r"\b(append|add|include|attach|embed|insert|render|load)\b", re.IGNORECASE)


def _first(pattern: re.Pattern[str], text: str, group: int = 0) -> str | None:
    m = pattern.search(text)
    return m.group(group) if m else None


def _placeholders(text: str, kind: str) -> list[str]:
    return [m.group(0) for m in _PLACEHOLDER.finditer(text) if m.group(1) == kind]


def _unwrap(content: str) -> str:
    m = _WRAPPED.search(content)
    return m.group(1) if m else content


class MockBrain:
    def __init__(self, persona: str = "external") -> None:
        self.persona = persona

    def respond(self, messages: list[ChatMessage], tools: list[dict[str, Any]] | None = None) -> ChatMessage:
        if tools:
            return self._agent_step(messages, {t["function"]["name"] for t in tools if "function" in t})
        user = next((m.content or "" for m in reversed(messages) if m.role == "user"), "")
        return ChatMessage(role="assistant", content=self._chat(user))

    # ------------------------------------------------------------------ chat

    def _chat(self, text: str) -> str:
        low = text.lower()
        if any(w in low for w in ("refund", "charged twice", "duplicate charge", "complaint")):
            return self._complaint_reply(text)
        if any(w in low for w in ("talking points", "summarize", "summary", "draft", "memo")):
            sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if len(s.strip()) > 20][:3]
            bullets = "\n".join(f"- {s}" for s in sentences) or "- (no content)"
            return f"Here are the key points I extracted:\n{bullets}\n\nLet me know if you want a longer version."
        if "backoff" in low or "retry" in low or "retries" in low:
            return (
                "Use a retry policy with exponential backoff and jitter: wait base * 2^attempt plus a random "
                "offset, cap the delay, retry only idempotent requests and 429/5xx responses, and stop after a "
                "fixed number of attempts. In Python, `urllib3.util.Retry` mounted on a requests `HTTPAdapter` "
                "does this with `backoff_factor` and `status_forcelist`."
            )
        topic = re.sub(r"\s+", " ", text).strip().rstrip("?.!")[:120]
        return (
            f"Here is a short answer on: {topic}.\n"
            "1. Start with the core concept and the problem it solves.\n"
            "2. Compare the main options against your constraints (cost, latency, operability).\n"
            "3. Prototype the simplest option and measure before optimizing."
        )

    def _complaint_reply(self, text: str) -> str:
        name = (
            next(iter(_placeholders(text, "PERSON_NAME")), None) or _first(_RAW_NAME, text, 1) or "customer"
        )
        card = next(iter(_placeholders(text, "CREDIT_CARD")), None) or _first(_RAW_CARD, text) or "on file"
        email = (
            next(iter(_placeholders(text, "EMAIL")), None) or _first(_RAW_EMAIL, text) or "your email address"
        )
        return (
            f"Dear {name},\n\n"
            "Thank you for reaching out, and I am sorry you were charged twice. I have flagged the duplicate "
            f"charge on your card {card} for a refund; it should appear within 5 business days. "
            f"We will send a confirmation to {email} once it is processed.\n\n"
            "Best regards,\nAcme Support"
        )

    # ------------------------------------------------------------------ agent

    def _agent_step(self, messages: list[ChatMessage], tools: set[str]) -> ChatMessage:
        task = next((m.content or "" for m in messages if m.role == "user"), "")
        results: dict[str, list[str]] = {}
        for m in messages:
            if m.role == "tool" and m.name:
                results.setdefault(m.name, []).append(_unwrap(m.content or ""))
        called = {tc.name for m in messages if m.role == "assistant" and m.tool_calls for tc in m.tool_calls}

        def call(name: str, **args: Any) -> ChatMessage:
            return ChatMessage(
                role="assistant", content=None, tool_calls=[ToolCall(name=name, arguments=args)]
            )

        customer_id = _first(_CUSTOMER_ID, task)
        if customer_id and "lookup_customer" in tools and "lookup_customer" not in called:
            return call("lookup_customer", customer_id=customer_id)

        wants_wiki = re.search(
            r"\b(wiki|knowledge base|kb|faq|policy page|refund policy)\b", task, re.IGNORECASE
        )
        if wants_wiki and "search_wiki" in tools and "search_wiki" not in called:
            query = "refund policy" if "refund" in task.lower() else " ".join(task.split()[:6])
            return call("search_wiki", query=query)
        if wants_wiki and "read_wiki" in tools and "read_wiki" not in called and results.get("search_wiki"):
            try:
                hits = json.loads(results["search_wiki"][-1])
                page_id = hits[0]["id"] if hits else None
            except (json.JSONDecodeError, KeyError, IndexError, TypeError):
                page_id = None
            if page_id:
                return call("read_wiki", page_id=page_id)

        customer = self._customer(results)
        injected = self._injected_url(results.get("read_wiki", []) + results.get("http_get", []), customer)
        if injected and injected[1] == "tool" and "render_image" in tools and "render_image" not in called:
            return call("render_image", url=injected[0])

        target = _first(_EMAIL_TARGET, task, 1)
        if target and "send_email" in tools and "send_email" not in called:
            return call(
                "send_email",
                to=target,
                subject=f"Customer summary {customer_id or ''}".strip(),
                body=self._summary(customer),
            )

        answer = self._summary(customer) if customer else "Done."
        if results.get("read_wiki"):
            answer += " Per the Refund Policy FAQ, duplicate charges are refunded within 5 business days."
        if injected and injected[1] == "answer":
            answer += f"\n\n![refund status]({injected[0]})"
        return ChatMessage(role="assistant", content=answer)

    @staticmethod
    def _customer(results: dict[str, list[str]]) -> dict[str, Any]:
        for raw in results.get("lookup_customer", []):
            try:
                data = json.loads(raw)
                if isinstance(data, dict):
                    return data
            except json.JSONDecodeError:
                continue
        return {}

    @staticmethod
    def _summary(c: dict[str, Any]) -> str:
        if not c:
            return "No customer record was found."
        return (
            f"Customer {c.get('name', '?')} ({c.get('email', '?')}) reported: {c.get('open_issue', 'n/a')}. "
            f"Card on file: {c.get('card_on_file', 'n/a')}. Status: {c.get('status', 'n/a')}."
        )

    @staticmethod
    def _injected_url(docs: list[str], customer: dict[str, Any]) -> tuple[str, str] | None:
        """Find an instruction to put data in a URL, and obey it (this is the gullible part)."""
        for doc in docs:
            if not _FOLLOW_VERBS.search(doc):
                continue
            for m in _URL_TEMPLATE.finditer(doc):
                url = m.group(0).rstrip(".,;")
                if "{" not in url and "<" not in url:
                    continue
                email = str(customer.get("email", ""))
                card = str(customer.get("card_on_file", "")).replace(" ", "")
                name = str(customer.get("name", ""))
                filled = (
                    url.replace("{customer_email}", email)
                    .replace("{email}", email)
                    .replace("{card_number}", card)
                    .replace("{card}", card)
                    .replace("{name}", name)
                    .replace("{data}", f"{email}|{card}")
                )
                where = (
                    "answer" if re.search(r"in your (reply|answer|response)", doc, re.IGNORECASE) else "tool"
                )
                return filled, where
        return None
