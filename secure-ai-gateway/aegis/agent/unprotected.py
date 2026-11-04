"""The same agent with no controls. Demo only: shows what leaks without the gateway."""

from __future__ import annotations

from typing import Any

from aegis.agent.runner import AGENT_SYSTEM_PROMPT
from aegis.agent.tools import TOOL_SPECS, Sandbox
from aegis.llm.base import ChatMessage, LLMProvider


def run_unprotected(task: str, provider: LLMProvider, sandbox: Sandbox, max_steps: int = 6) -> dict[str, Any]:
    messages = [ChatMessage("system", AGENT_SYSTEM_PROMPT), ChatMessage("user", task)]
    steps: list[dict[str, Any]] = []
    final = None
    for _ in range(max_steps):
        msg = provider.complete(messages, TOOL_SPECS).message
        if not msg.tool_calls:
            final = msg.content or ""
            break
        messages.append(ChatMessage("assistant", msg.content, tool_calls=msg.tool_calls))
        for call in msg.tool_calls:
            output, _ = sandbox.execute(call, mode="unprotected")
            steps.append(
                {
                    "type": "tool_call",
                    "tool": call.name,
                    "arguments": call.arguments,
                    "executed": True,
                    "output_preview": output[:600],
                }
            )
            messages.append(ChatMessage("tool", output, tool_call_id=call.id, name=call.name))
    return {
        "status": "completed" if final is not None else "stopped",
        "task_sent_to_llm": task,
        "steps": steps,
        "final_answer": final,
        "controls": "none",
    }
