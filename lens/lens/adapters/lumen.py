"""Lumen request → server span with retrieval, rerank, model, and citation children.

The event dict is the shape Lumen already logs (stage timings, doc ids, model, prompt
version). Lens does not sit in the Lumen process.
"""

from __future__ import annotations

from typing import Any

from lens.models import Span
from lens.tracing.tracer import hex_id, new_span

SERVICE = "lumen"


def _chain(
    trace_id: str, root_id: str, start_ns: int, stages: list[tuple[str, int, str, dict[str, Any]]]
) -> list[Span]:
    spans: list[Span] = []
    cursor = start_ns
    for name, duration_ms, kind, attributes in stages:
        end = cursor + duration_ms * 1_000_000
        spans.append(
            new_span(
                trace_id=trace_id,
                name=name,
                parent_span_id=root_id,
                kind=kind,
                start_ns=cursor,
                end_ns=end,
                attributes=attributes,
                service_name=SERVICE,
            )
        )
        cursor = end
    return spans


def lumen_spans(event: dict[str, Any]) -> list[Span]:
    request_id = str(event["request_id"])
    trace_id = hex_id(16, "lumen", request_id, "trace")
    start_ns = int(event.get("start_ns", 0))
    docs = list(event.get("docs") or [])
    doc_ids = ",".join(str(doc["id"]) for doc in docs)
    stages_ms = dict(event.get("stages_ms") or {})
    embed = int(stages_ms.get("embed", 5))
    retrieve = int(stages_ms.get("retrieve", 8))
    rerank = int(stages_ms.get("rerank", 40))
    generate = int(stages_ms.get("generate", 400))
    cite = int(stages_ms.get("cite", 3))
    total_ms = embed + retrieve + rerank + generate + cite
    root_end = start_ns + total_ms * 1_000_000
    root = new_span(
        trace_id=trace_id,
        name="lumen.query",
        parent_span_id=None,
        kind="SPAN_KIND_SERVER",
        start_ns=start_ns,
        end_ns=root_end,
        attributes={
            "lens.app": "lumen",
            "lens.prompt.version": str(event.get("prompt_version", "")),
            "lens.retrieval.doc_ids": doc_ids,
            "lens.refused": bool(event.get("refused", False)),
        },
        service_name=SERVICE,
        status_code="STATUS_CODE_OK" if event.get("status", "ok") == "ok" else "STATUS_CODE_ERROR",
        status_message=str(event.get("status_message", "")),
    )
    model = str(event.get("model", "mock-large"))
    children = _chain(
        trace_id,
        root.span_id,
        start_ns,
        [
            (
                "lumen.embed",
                embed,
                "SPAN_KIND_INTERNAL",
                {"lens.stage": "embed"},
            ),
            (
                "lumen.retrieve",
                retrieve,
                "SPAN_KIND_CLIENT",
                {
                    "lens.stage": "retrieve",
                    "lens.retrieval.doc_ids": doc_ids,
                    "lens.retrieval.top_score": float(event.get("top_score") or 0.0),
                },
            ),
            (
                "lumen.rerank",
                rerank,
                "SPAN_KIND_INTERNAL",
                {"lens.stage": "rerank", "lens.retrieval.k": int(event.get("rerank_k", 5))},
            ),
            (
                "lumen.generate",
                generate,
                "SPAN_KIND_CLIENT",
                {
                    "gen_ai.operation.name": "chat",
                    "gen_ai.system": str(event.get("provider", "mock")),
                    "gen_ai.request.model": model,
                    "gen_ai.usage.input_tokens": int(event.get("input_tokens", 0)),
                    "gen_ai.usage.output_tokens": int(event.get("output_tokens", 0)),
                    "lens.prompt.version": str(event.get("prompt_version", "")),
                },
            ),
            (
                "lumen.cite",
                cite,
                "SPAN_KIND_INTERNAL",
                {"lens.stage": "cite"},
            ),
        ],
    )
    return [root, *children]
