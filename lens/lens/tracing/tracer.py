"""Deterministic span ids and a small constructor. No collector, no network."""

from __future__ import annotations

import hashlib

from lens.models import Span


def hex_id(nbytes: int, *parts: str) -> str:
    digest = hashlib.sha256("|".join(parts).encode()).hexdigest()
    return digest[: nbytes * 2]


def new_span(
    *,
    trace_id: str,
    name: str,
    parent_span_id: str | None,
    kind: str,
    start_ns: int,
    end_ns: int,
    attributes: dict[str, str | int | float | bool],
    service_name: str,
    status_code: str = "STATUS_CODE_OK",
    status_message: str = "",
) -> Span:
    if end_ns < start_ns:
        raise ValueError(f"{name} ends before it starts")
    return Span(
        trace_id=trace_id,
        span_id=hex_id(8, trace_id, name, str(start_ns)),
        parent_span_id=parent_span_id,
        name=name,
        kind=kind,
        start_ns=start_ns,
        end_ns=end_ns,
        status_code=status_code,
        status_message=status_message,
        attributes=attributes,
        service_name=service_name,
    )
