"""Serialize spans as OTLP/JSON (resourceSpans / scopeSpans), the shape a collector accepts."""

from __future__ import annotations

from collections import defaultdict

from lens.models import Span

SCOPE = {"name": "lens", "version": "0.1.0"}


def _attr_value(value: str | int | float | bool) -> dict[str, object]:
    if isinstance(value, bool):
        return {"boolValue": value}
    if isinstance(value, int):
        return {"intValue": str(value)}
    if isinstance(value, float):
        return {"doubleValue": value}
    return {"stringValue": value}


def _span(span: Span) -> dict[str, object]:
    body: dict[str, object] = {
        "traceId": span.trace_id,
        "spanId": span.span_id,
        "name": span.name,
        "kind": span.kind,
        "startTimeUnixNano": str(span.start_ns),
        "endTimeUnixNano": str(span.end_ns),
        "attributes": [
            {"key": key, "value": _attr_value(span.attributes[key])} for key in sorted(span.attributes)
        ],
        "status": {"code": span.status_code, "message": span.status_message},
    }
    if span.parent_span_id:
        body["parentSpanId"] = span.parent_span_id
    return body


def export_otlp(spans: list[Span]) -> dict[str, object]:
    grouped: dict[str, list[Span]] = defaultdict(list)
    for span in spans:
        grouped[span.service_name].append(span)
    resource_spans = []
    for service in sorted(grouped):
        resource_spans.append(
            {
                "resource": {
                    "attributes": [
                        {"key": "service.name", "value": {"stringValue": service}},
                    ]
                },
                "scopeSpans": [{"scope": dict(SCOPE), "spans": [_span(s) for s in grouped[service]]}],
            }
        )
    return {"resourceSpans": resource_spans}
