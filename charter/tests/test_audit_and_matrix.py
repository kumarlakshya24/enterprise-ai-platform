"""The planted audit finding, the Lens contract, and the control counts."""

from __future__ import annotations

import json

from charter.config import AUDIT_PATH, LENS_SLO_TARGETS, SLO_PATH
from charter.evidence.pack import build_report
from charter.ingest.aegis import VIOLATION_REQUEST, build_events, load_audit, serialize, verify_chain
from charter.ingest.lens import load_slo


def test_fixture_matches_the_generator_and_the_chain() -> None:
    events = build_events()
    assert AUDIT_PATH.read_text(encoding="utf-8") == serialize(events)
    assert verify_chain(events) == ""
    summary = load_audit(AUDIT_PATH)
    assert summary.chain_ok
    assert len(summary.violations) == 1
    violation = summary.violations[0]
    assert violation.request_id == VIOLATION_REQUEST
    assert violation.label == "RESTRICTED"
    assert violation.route == "allow"
    assert violation.region == "us-east-1"
    assert summary.by_type["dlp_redaction"] >= 1
    assert summary.by_type["routing_decision"] >= 1
    assert summary.by_type["tool_call_blocked"] == 1
    assert summary.by_type["request_blocked"] == 1


def test_a_flipped_outcome_breaks_the_chain() -> None:
    events = json.loads("[" + ",".join(AUDIT_PATH.read_text(encoding="utf-8").splitlines()) + "]")
    events[3]["outcome"] = "tampered"
    assert verify_chain(events) != ""


def test_every_event_uses_the_aegis_field_set() -> None:
    required = {
        "seq",
        "event_id",
        "ts",
        "tenant_id",
        "user_id",
        "session_id",
        "request_id",
        "event_type",
        "policy_version",
        "route",
        "outcome",
        "details",
        "prev_hash",
        "hash",
    }
    for line in AUDIT_PATH.read_text(encoding="utf-8").splitlines():
        record = json.loads(line)
        assert required <= set(record)
        assert record["tenant_id"] == "acme"
        assert record["policy_version"] in ("acme-default@7", None)


def test_lens_targets_match_the_contract() -> None:
    snapshot = load_slo(SLO_PATH)
    for objective_id, target in LENS_SLO_TARGETS.items():
        found = snapshot.get(objective_id)
        assert found is not None
        assert found.target == target
    assert snapshot.status("quality") == "page"
    assert snapshot.status("safety") == "ticket"
    assert snapshot.status("availability") == "within_budget"
    assert snapshot.status("latency") == "within_budget"


def test_matrix_tells_the_honest_story() -> None:
    report = build_report(measure=False)
    counts = report.matrix.counts()
    assert counts == {"met": 10, "partial": 4, "gap": 3, "unmapped": 0}
    assert report.matrix.by_id("EU-10").status == "gap"
    assert "req-leak-01" in report.matrix.by_id("EU-10").because
    assert report.matrix.by_id("EU-14").status == "gap"
    assert "claims-triage-eu" in report.matrix.by_id("EU-14").because
    assert report.matrix.by_id("EU-15").status == "gap"
    assert report.matrix.by_id("EU-12").status == "met"
    assert report.matrix.by_id("NIST-GV-6.1").status == "partial"
    assert report.matrix.by_id("NIST-MS-2.6").status == "partial"
    assert report.gate.ok
    assert not report.weakened.ok
    failed = " ".join(report.weakened.failures)
    assert "eu-support-us" in failed
    assert report.decision_for("eu-support-us").decision.effect == "deny"
    assert report.decision_for("eu-support-local").decision.effect == "allow"
    assert report.decision_for("internal-eu-on-us").decision.effect == "allow"
    assert report.cost["charter_usd"] == 0
    assert float(report.cost["projected_llm_review_usd"]) > 0


def test_decision_latency_stays_under_the_ceiling() -> None:
    report = build_report(measure=True)
    assert report.latency["p95_us"] < 2000


def test_evidence_names_the_violation_and_refuses_to_be_a_certificate() -> None:
    from charter.evidence.pack import evidence_markdown

    report = build_report(measure=False)
    text = evidence_markdown(report)
    assert "not a legal opinion" in text
    assert "req-leak-01" in text
    assert "3 gap" in text or "**3 gap**" in text
