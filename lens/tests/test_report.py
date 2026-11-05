"""The full offline report: drift, burn, and a dashboard that quotes the gate."""

from __future__ import annotations

from lens.dashboard.render import render_html
from lens.pipeline import build_report
from lens.synthetic.traffic import RAMP_START


def test_report_story() -> None:
    report = build_report()
    assert report["gate_clean"]["passed"] is True
    assert report["gate_regressed"]["passed"] is False
    assert report["kappa"]["pass"] >= 0.6
    alerts = {row["name"]: row for row in report["drift"]["signals"]}
    assert alerts["lumen prompt"]["level"] == "alert"
    assert alerts["lumen model"]["level"] == "alert"
    assert alerts["lumen latency"]["level"] == "alert"
    assert alerts["lumen quality"]["level"] == "alert"
    # Route mix barely moves: allow was already the common path. The policy version moves.
    assert alerts["aegis route"]["level"] == "ok"
    assert alerts["aegis policy"]["level"] == "alert"
    alarm = report["drift"]["cusum"]["first_alarm"]
    assert alarm is not None
    assert alarm >= RAMP_START.strftime("%Y-%m-%dT%H:%M:%SZ")
    by_id = {row["id"]: row for row in report["slo"]["objectives"]}
    assert by_id["quality"]["status"] == "page"
    assert by_id["latency"]["status"] == "ok"
    assert by_id["safety"]["remaining"] < 0.5
    kinds = {(event["objective"], event["to"]) for event in report["incidents"]}
    assert ("quality", "page") in kinds
    assert ("availability", "page") in kinds
    assert ("safety", "page") in kinds
    html = render_html(report)
    assert "aeg-pii-leak" in html
    assert "lumen.retrieve" in html
    assert "aegis.tool" in html
    assert "Page" in html
    assert "Within budget" in html
