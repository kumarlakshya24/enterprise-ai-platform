"""Mock third-party LLM service (OpenAI-compatible). Stand-in for api.openai.com in the demo.

It records every request it receives so the demo can show exactly what the third party saw.
Run two copies: one as the "external" provider, one as the "local" model inside the boundary.
"""

from __future__ import annotations

import os
import time
import uuid
from collections import deque
from datetime import UTC, datetime
from typing import Any

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from aegis.llm.base import ChatMessage
from aegis.llm.mock_brain import MockBrain

PERSONA = os.environ.get("MOCK_LLM_PERSONA", "external")
MODEL = os.environ.get("MOCK_LLM_MODEL", "mock-gpt" if PERSONA == "external" else "local-llm")

app = FastAPI(title=f"mock-llm ({PERSONA})", docs_url=None, redoc_url=None)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["GET", "POST"], allow_headers=["*"])
_brain = MockBrain(persona=PERSONA)
_received: deque[dict[str, Any]] = deque(maxlen=200)


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok", "persona": PERSONA}


@app.post("/v1/chat/completions")
async def chat_completions(request: Request) -> dict[str, Any]:
    body = await request.json()
    messages = [ChatMessage.from_openai(m) for m in body.get("messages", [])]
    tools = body.get("tools") or None
    _received.append(
        {
            "at": datetime.now(UTC).isoformat(),
            "model": body.get("model", MODEL),
            "messages": [m.to_openai() for m in messages],
            "tools": [t["function"]["name"] for t in tools or []],
            "authorization_header_present": "authorization" in request.headers,
        }
    )
    reply = _brain.respond(messages, tools)
    msg = reply.to_openai()
    return {
        "id": f"chatcmpl-{uuid.uuid4().hex[:16]}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": MODEL,
        "choices": [
            {"index": 0, "message": msg, "finish_reason": "tool_calls" if reply.tool_calls else "stop"}
        ],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    }


@app.get("/_evidence/received")
def evidence(limit: int = 20) -> list[dict[str, Any]]:
    return list(_received)[-limit:]


@app.post("/_evidence/reset")
def reset() -> dict[str, str]:
    _received.clear()
    return {"status": "reset"}
