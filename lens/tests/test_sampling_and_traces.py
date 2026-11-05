"""Sampler decisions and the Aegis / Lumen adapters."""

from __future__ import annotations

from lens.adapters.aegis import aegis_spans
from lens.adapters.lumen import lumen_spans
from lens.sampling.sampler import decide
from lens.tracing.otlp import export_otlp


def _decide(trace_id: str, **overrides: object) -> object:
    args = dict(
        trace_id=trace_id,
        status="ok",
        latency_ms=200.0,
        safety_signal=False,
        app="lumen",
        model="mock-large",
        rate=0.10,
        slow_ms=1500.0,
    )
    args.update(overrides)
    return decide(**args)  # type: ignore[arg-type]


def test_errors_slow_and_safety_signals_are_always_kept() -> None:
    assert _decide("a", status="error").reason == "error"  # type: ignore[attr-defined]
    assert _decide("b", latency_ms=1500).reason == "slow"  # type: ignore[attr-defined]
    assert _decide("c", safety_signal=True).reason == "safety_signal"  # type: ignore[attr-defined]


def test_hash_sample_is_deterministic_and_near_the_rate() -> None:
    first = [_decide(f"t{i}").keep for i in range(2000)]  # type: ignore[attr-defined]
    second = [_decide(f"t{i}").keep for i in range(2000)]  # type: ignore[attr-defined]
    assert first == second
    kept = sum(first)
    assert 140 < kept < 260


def test_stratum_key_changes_the_decision() -> None:
    mismatches = 0
    for i in range(300):
        large = _decide(f"s{i}", model="mock-large").keep  # type: ignore[attr-defined]
        small = _decide(f"s{i}", model="mock-small").keep  # type: ignore[attr-defined]
        mismatches += int(large != small)
    assert mismatches > 20


def test_lumen_adapter_emits_retrieval_and_model_spans() -> None:
    spans = lumen_spans(
        {
            "request_id": "q-1",
            "prompt_version": "lumen-v2.3",
            "model": "mock-large",
            "provider": "mock",
            "top_score": 0.8,
            "input_tokens": 100,
            "output_tokens": 20,
            "docs": [{"id": "IT-KB-014"}],
            "stages_ms": {"embed": 5, "retrieve": 8, "rerank": 20, "generate": 100, "cite": 2},
        }
    )
    names = [span.name for span in spans]
    assert names[0] == "lumen.query"
    assert "lumen.retrieve" in names
    assert "lumen.generate" in names
    root = spans[0]
    for child in spans[1:]:
        assert child.parent_span_id == root.span_id
        assert child.trace_id == root.trace_id
        assert root.start_ns <= child.start_ns <= child.end_ns <= root.end_ns
    model = next(span for span in spans if span.name == "lumen.generate")
    assert model.attributes["gen_ai.request.model"] == "mock-large"
    retrieve = next(span for span in spans if span.name == "lumen.retrieve")
    assert retrieve.attributes["lens.retrieval.doc_ids"] == "IT-KB-014"
    payload = export_otlp(spans)
    exported = payload["resourceSpans"][0]["scopeSpans"][0]["spans"][0]
    assert len(exported["traceId"]) == 32
    assert len(exported["spanId"]) == 16


def test_aegis_adapter_emits_a_tool_span_with_a_block_status() -> None:
    spans = aegis_spans(
        {
            "request_id": "a-1",
            "route": "block",
            "label": "INTERNAL",
            "policy_version": "aegis-policy-v7",
            "model": "mock-external",
            "provider": "mock",
            "input_tokens": 10,
            "output_tokens": 4,
            "status": "error",
            "tool": {"name": "send_email", "decision": "block", "rule": "R-TOOL-PERSONAL-DOMAIN"},
        }
    )
    tool = next(span for span in spans if span.name == "aegis.tool")
    assert tool.attributes["lens.tool.name"] == "send_email"
    assert tool.status_code == "STATUS_CODE_ERROR"
    assert spans[0].name == "aegis.agent"
