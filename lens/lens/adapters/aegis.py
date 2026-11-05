"""Aegis chat/agent event → spans for DLP, policy, model, and tool calls.

The event dict matches the fields Aegis already writes to its audit log (route, label,
policy version, stage timings). Lens does not sit in the gateway process.
"""

from __future__ import annotations

from typing import Any

from lens.models import Span
from lens.tracing.tracer import hex_id, new_span

SERVICE = "aegis"


def aegis_spans(event: dict[str, Any]) -> list[Span]:
    request_id = str(event["request_id"])
    trace_id = hex_id(16, "aegis", request_id, "trace")
    start_ns = int(event.get("start_ns", 0))
    stages_ms = dict(event.get("stages_ms") or {})
    order = [
        ("aegis.dlp", int(stages_ms.get("dlp", 4)), "SPAN_KIND_INTERNAL"),
        ("aegis.classify", int(stages_ms.get("classify", 2)), "SPAN_KIND_INTERNAL"),
        ("aegis.policy", int(stages_ms.get("policy", 1)), "SPAN_KIND_INTERNAL"),
        ("aegis.llm", int(stages_ms.get("llm", 400)), "SPAN_KIND_CLIENT"),
    ]
    tool = event.get("tool")
    if tool:
        order.append(("aegis.tool", int(stages_ms.get("tool", 15)), "SPAN_KIND_INTERNAL"))
        order.append(("aegis.injection_scan", int(stages_ms.get("injection", 3)), "SPAN_KIND_INTERNAL"))
    order.append(("aegis.restore", int(stages_ms.get("restore", 1)), "SPAN_KIND_INTERNAL"))

    total_ms = sum(item[1] for item in order)
    status = str(event.get("status", "ok"))
    root = new_span(
        trace_id=trace_id,
        name="aegis.chat" if not tool else "aegis.agent",
        parent_span_id=None,
        kind="SPAN_KIND_SERVER",
        start_ns=start_ns,
        end_ns=start_ns + total_ms * 1_000_000,
        attributes={
            "lens.app": "aegis",
            "lens.route": str(event.get("route", "")),
            "lens.label": str(event.get("label", "")),
            "lens.policy.version": str(event.get("policy_version", "")),
            "lens.prompt.version": str(event.get("prompt_version", "")),
        },
        service_name=SERVICE,
        status_code="STATUS_CODE_OK" if status == "ok" else "STATUS_CODE_ERROR",
        status_message=str(event.get("status_message", "")),
    )
    spans: list[Span] = [root]
    cursor = start_ns
    for name, duration_ms, kind in order:
        end = cursor + duration_ms * 1_000_000
        attributes: dict[str, str | int | float | bool] = {"lens.stage": name.split(".", 1)[1]}
        if name == "aegis.llm":
            attributes.update(
                {
                    "gen_ai.operation.name": "chat",
                    "gen_ai.system": str(event.get("provider", "mock")),
                    "gen_ai.request.model": str(event.get("model", "mock-external")),
                    "gen_ai.usage.input_tokens": int(event.get("input_tokens", 0)),
                    "gen_ai.usage.output_tokens": int(event.get("output_tokens", 0)),
                }
            )
        if name == "aegis.policy":
            attributes["lens.route"] = str(event.get("route", ""))
            attributes["lens.policy.version"] = str(event.get("policy_version", ""))
        if name == "aegis.tool" and isinstance(tool, dict):
            decision = str(tool.get("decision", "allow"))
            attributes["lens.tool.name"] = str(tool.get("name", ""))
            attributes["lens.tool.decision"] = decision
        status_code = "STATUS_CODE_OK"
        status_message = ""
        if name == "aegis.tool" and isinstance(tool, dict) and tool.get("decision") == "block":
            status_code = "STATUS_CODE_ERROR"
            status_message = str(tool.get("rule", "blocked"))
        spans.append(
            new_span(
                trace_id=trace_id,
                name=name,
                parent_span_id=root.span_id,
                kind=kind,
                start_ns=cursor,
                end_ns=end,
                attributes=attributes,
                service_name=SERVICE,
                status_code=status_code,
                status_message=status_message,
            )
        )
        cursor = end
    return spans
