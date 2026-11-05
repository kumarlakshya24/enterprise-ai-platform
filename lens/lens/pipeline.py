"""Wire the gold set, the synthetic log, and the control-plane checks into one report."""

from __future__ import annotations

from collections import defaultdict
from datetime import timedelta
from typing import Any

from lens.adapters.aegis import aegis_spans
from lens.adapters.lumen import lumen_spans
from lens.config import load_yaml
from lens.drift.cusum import cusum
from lens.drift.psi import psi
from lens.evalset.cases import CASES
from lens.gate.check import evaluate_gate
from lens.judge.agreement import cohen_kappa, confusion
from lens.judge.heuristic import judge
from lens.models import GoldCase, Span, Verdict
from lens.slo.burn import budget_remaining, burn_rate, window_error_rate
from lens.synthetic.traffic import (
    BLIP,
    LAT_EDGES,
    RAMP_START,
    START,
    HourStat,
    histogram_percentile,
    simulate,
)
from lens.tracing.otlp import export_otlp

BASELINE_HOURS = 7 * 24
CURRENT_HOURS = 48


def _kappa_block(cases: tuple[GoldCase, ...], verdicts: list[Verdict]) -> dict[str, Any]:
    dimensions = {
        "pass": ([case.gold_pass for case in cases], [verdict.passed for verdict in verdicts]),
        "faithful": ([case.gold_faithful for case in cases], [verdict.faithful for verdict in verdicts]),
        "relevant": ([case.gold_relevant for case in cases], [verdict.relevant for verdict in verdicts]),
        "safe": ([case.gold_safe for case in cases], [verdict.safe for verdict in verdicts]),
        "refusal_correct": (
            [case.gold_refusal_correct for case in cases],
            [verdict.refusal_correct for verdict in verdicts],
        ),
    }
    out: dict[str, Any] = {"n": len(cases)}
    for name, (gold, pred) in dimensions.items():
        out[name] = round(cohen_kappa(gold, pred), 4)
        out[f"{name}_confusion"] = confusion(gold, pred)
    gaps = []
    for case, verdict in zip(cases, verdicts, strict=True):
        if verdict.passed != case.gold_pass or verdict.faithful != case.gold_faithful:
            gaps.append(
                {
                    "id": case.id,
                    "gap": case.known_heuristic_gap or "unexpected",
                    "gold_pass": case.gold_pass,
                    "pred_pass": verdict.passed,
                    "gold_faithful": case.gold_faithful,
                    "pred_faithful": verdict.faithful,
                    "reasons": list(verdict.reasons),
                    "note": case.note,
                }
            )
    out["disagreements"] = gaps
    return out


def _sum_dict(rows: list[HourStat], attr: str) -> dict[str, float]:
    total: dict[str, float] = defaultdict(float)
    for row in rows:
        for key, value in getattr(row, attr).items():
            total[key] += value
    return dict(total)


def _sum_hist(rows: list[HourStat]) -> list[int]:
    acc = [0] * len(LAT_EDGES)
    for row in rows:
        for index, value in enumerate(row.latency_hist):
            acc[index] += value
    return acc


def _coarse_latency(hist: list[int]) -> dict[str, float]:
    # 50 ms bins. 0-250, 250-500, 500-1000, 1000-2000, 2000+.
    cuts = [0, 5, 10, 20, 40, len(hist)]
    labels = ["0-250", "250-500", "500-1000", "1000-2000", "2000+"]
    return {label: float(sum(hist[cuts[i] : cuts[i + 1]])) for i, label in enumerate(labels)}


def _signal(
    name: str, expected: dict[str, float], actual: dict[str, float], gate: dict[str, Any]
) -> dict[str, Any]:
    value = psi(expected, actual)
    if value >= float(gate["psi_alert"]):
        level = "alert"
    elif value >= float(gate["psi_watch"]):
        level = "watch"
    else:
        level = "ok"
    return {"name": name, "psi": round(value, 4), "level": level}


def _objective_series(
    hours: list[HourStat],
    app: str,
    kind: str,
) -> tuple[list[int], list[int]]:
    chosen = [row for row in hours if app == "all" or row.app == app]
    # Hours are stored lumen-then-aegis, so "all" must be collapsed per timestamp.
    if app == "all":
        by_ts: dict[str, list[HourStat]] = defaultdict(list)
        for row in chosen:
            by_ts[row.ts].append(row)
        totals: list[int] = []
        goods: list[int] = []
        for ts in sorted(by_ts):
            rows = by_ts[ts]
            if kind == "availability":
                total = sum(row.requests for row in rows)
                errors = sum(row.errors for row in rows)
                totals.append(total)
                goods.append(total - errors)
            elif kind == "latency":
                totals.append(sum(row.requests for row in rows))
                goods.append(sum(row.latency_good for row in rows))
            else:
                raise ValueError(kind)
        return totals, goods
    totals = []
    goods = []
    for row in chosen:
        if kind == "quality":
            totals.append(row.eval_n)
            goods.append(row.eval_pass)
        elif kind == "safety":
            totals.append(row.safety_n)
            goods.append(row.safety_pass)
        elif kind == "availability":
            totals.append(row.requests)
            goods.append(row.requests - row.errors)
        elif kind == "latency":
            totals.append(row.requests)
            goods.append(row.latency_good)
        else:
            raise ValueError(kind)
    return totals, goods


def _window_trusted(end: int, totals: list[int], hours: int, min_events: int) -> bool:
    if end + 1 < hours:
        return False
    start = end - hours + 1
    return sum(totals[start : end + 1]) >= min_events


def _burns_at(
    totals: list[int],
    goods: list[int],
    end: int,
    budget: float,
    min_events: dict[int, int],
) -> dict[str, dict[str, float | bool]]:
    view: dict[str, dict[str, float | bool]] = {}
    for label, width in (("1h", 1), ("6h", 6), ("24h", 24), ("72h", 72)):
        trusted = _window_trusted(end, totals, width, min_events[width])
        rate = burn_rate(window_error_rate(totals, goods, end, width), budget)
        view[label] = {"value": round(rate, 2), "trusted": trusted}
    return view


def _status(view: dict[str, dict[str, float | bool]], alerts: dict[str, float]) -> str:
    fast = view["1h"]["trusted"] and float(view["1h"]["value"]) >= alerts["page_fast_1h"]
    slow = view["6h"]["trusted"] and float(view["6h"]["value"]) >= alerts["page_slow_6h"]
    if fast or slow:
        return "page"
    day = view["24h"]["trusted"] and float(view["24h"]["value"]) >= alerts["ticket_24h"]
    three = view["72h"]["trusted"] and float(view["72h"]["value"]) >= alerts["ticket_72h"]
    if day or three:
        return "ticket"
    return "ok"


def _incidents(
    stamps: list[str],
    series: dict[str, tuple[list[int], list[int], float]],
    alerts: dict[str, float],
    min_events: dict[int, int],
) -> list[dict[str, Any]]:
    previous = {name: "ok" for name in series}
    events: list[dict[str, Any]] = []
    clear_at = float(alerts["page_slow_clear"])
    for end, stamp in enumerate(stamps):
        for name, (totals, goods, budget) in series.items():
            view = _burns_at(totals, goods, end, budget, min_events)
            level = _status(view, alerts)
            if previous[name] == "page" and level != "page":
                hold_fast = view["1h"]["trusted"] and float(view["1h"]["value"]) >= alerts["page_fast_1h"]
                hold_slow = view["6h"]["trusted"] and float(view["6h"]["value"]) >= clear_at
                if hold_fast or hold_slow:
                    level = "page"
            if level != previous[name]:
                events.append(
                    {
                        "ts": stamp,
                        "objective": name,
                        "from": previous[name],
                        "to": level,
                        "burn_1h": view["1h"]["value"],
                        "burn_6h": view["6h"]["value"],
                    }
                )
                previous[name] = level
    return events


def _waterfall(spans: list[Span]) -> list[dict[str, Any]]:
    root = next(span for span in spans if span.parent_span_id is None)
    total = max(root.duration_ns(), 1)
    rows = []
    for span in spans:
        width = span.duration_ns() / total * 100
        rows.append(
            {
                "name": span.name,
                "start_pct": round((span.start_ns - root.start_ns) / total * 100, 2),
                "width_pct": round(max(width, 0.6), 2),
                "ms": round(span.duration_ns() / 1_000_000, 1),
                "status": span.status_code,
                "attributes": {key: span.attributes[key] for key in sorted(span.attributes)},
            }
        )
    return rows


def _exemplars() -> tuple[list[dict[str, Any]], dict[str, object]]:
    lumen_event = {
        "request_id": "ex-lumen-vpn",
        "prompt_version": "lumen-v2.3",
        "model": "mock-large",
        "provider": "mock",
        "top_score": 0.86,
        "rerank_k": 5,
        "input_tokens": 640,
        "output_tokens": 48,
        "docs": [{"id": "IT-KB-014", "score": 0.86}],
        "stages_ms": {"embed": 6, "retrieve": 11, "rerank": 47, "generate": 520, "cite": 4},
        "status": "ok",
    }
    aegis_event = {
        "request_id": "ex-aegis-tool",
        "route": "block",
        "label": "INTERNAL",
        "policy_version": "aegis-policy-v7",
        "prompt_version": "aegis-policy-v7",
        "model": "mock-external",
        "provider": "mock",
        "input_tokens": 220,
        "output_tokens": 24,
        "status": "error",
        "status_message": "tool blocked",
        "tool": {"name": "send_email", "decision": "block", "rule": "R-TOOL-PERSONAL-DOMAIN"},
        "stages_ms": {
            "dlp": 5,
            "classify": 3,
            "policy": 2,
            "llm": 360,
            "tool": 8,
            "injection": 4,
            "restore": 1,
        },
    }
    lumen = lumen_spans(lumen_event)
    aegis = aegis_spans(aegis_event)
    traces = [
        {
            "title": "Lumen · VPN timeout · lumen-v2.3",
            "service": "lumen",
            "rows": _waterfall(lumen),
        },
        {
            "title": "Aegis · send_email blocked · personal domain",
            "service": "aegis",
            "rows": _waterfall(aegis),
        },
    ]
    return traces, export_otlp([*lumen, *aegis])


def _cost(pricing: dict[str, Any]) -> dict[str, Any]:
    tokens_in = int(pricing["assumed_input_tokens"])
    tokens_out = int(pricing["assumed_output_tokens"])
    daily_requests = int(pricing["production_requests_per_day"])
    rate = float(pricing["production_sample_rate"])
    judged = daily_requests * rate

    def per_call(block: dict[str, Any]) -> float:
        return (
            tokens_in * float(block["input_usd_per_million"])
            + tokens_out * float(block["output_usd_per_million"])
        ) / 1_000_000

    stand = per_call(pricing["stand_in"])
    premium = per_call(pricing["premium"])
    return {
        "label": "projection, not a measured invoice",
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "production_requests_per_day": daily_requests,
        "sample_rate": rate,
        "judgements_per_day": int(judged),
        "stand_in_usd_per_day": round(stand * judged, 2),
        "stand_in_usd_per_day_if_unsampled": round(stand * daily_requests, 2),
        "premium_usd_per_day": round(premium * judged, 2),
        "premium_usd_per_day_if_unsampled": round(premium * daily_requests, 2),
        "heuristic_usd": 0.0,
    }


def build_report() -> dict[str, Any]:
    gate_cfg = load_yaml("gate.yaml")
    slo_cfg = load_yaml("slo.yaml")
    pricing = load_yaml("pricing.yaml")
    alerts = {key: float(value) for key, value in slo_cfg["burn_alerts"].items()}
    min_events = {int(key): int(value) for key, value in slo_cfg["burn_min_events"].items()}

    baseline_verdicts = [judge(case.observation("baseline")) for case in CASES]
    regressed_verdicts = [judge(case.observation("regressed")) for case in CASES]
    kappa = _kappa_block(CASES, baseline_verdicts)
    ids = [case.id for case in CASES]
    critical = [case.safety_critical for case in CASES]
    base_lat = [case.latency_ms_baseline for case in CASES]
    reg_lat = [case.latency_ms_regressed for case in CASES]
    clean = evaluate_gate(
        name="clean",
        ids=ids,
        baseline=baseline_verdicts,
        candidate=baseline_verdicts,
        baseline_latency=base_lat,
        candidate_latency=base_lat,
        safety_critical=critical,
        kappa=float(kappa["pass"]),
        config=gate_cfg,
    )
    regressed = evaluate_gate(
        name="regressed",
        ids=ids,
        baseline=baseline_verdicts,
        candidate=regressed_verdicts,
        baseline_latency=base_lat,
        candidate_latency=reg_lat,
        safety_critical=critical,
        kappa=float(kappa["pass"]),
        config=gate_cfg,
    )

    hours = simulate()
    lumen = [row for row in hours if row.app == "lumen"]
    aegis = [row for row in hours if row.app == "aegis"]
    base_lumen = lumen[:BASELINE_HOURS]
    cur_lumen = lumen[-CURRENT_HOURS:]
    base_aegis = aegis[:BASELINE_HOURS]
    cur_aegis = aegis[-CURRENT_HOURS:]

    signals = [
        _signal("lumen prompt", _sum_dict(base_lumen, "prompts"), _sum_dict(cur_lumen, "prompts"), gate_cfg),
        _signal("lumen model", _sum_dict(base_lumen, "models"), _sum_dict(cur_lumen, "models"), gate_cfg),
        _signal(
            "lumen latency",
            _coarse_latency(_sum_hist(base_lumen)),
            _coarse_latency(_sum_hist(cur_lumen)),
            gate_cfg,
        ),
        _signal(
            "lumen quality",
            _sum_dict(base_lumen, "quality_hist"),
            _sum_dict(cur_lumen, "quality_hist"),
            gate_cfg,
        ),
        _signal("aegis route", _sum_dict(base_aegis, "routes"), _sum_dict(cur_aegis, "routes"), gate_cfg),
        _signal("aegis policy", _sum_dict(base_aegis, "prompts"), _sum_dict(cur_aegis, "prompts"), gate_cfg),
        _signal("aegis model", _sum_dict(base_aegis, "models"), _sum_dict(cur_aegis, "models"), gate_cfg),
    ]

    # CUSUM on 6-hour blocks of the Lumen eval-sample fail rate.
    block = int(slo_cfg["cusum_block_hours"])
    fail_rates: list[float] = []
    block_end_index: list[int] = []
    for start in range(0, len(lumen), block):
        chunk = lumen[start : start + block]
        total = sum(row.eval_n for row in chunk)
        passed = sum(row.eval_pass for row in chunk)
        fail_rates.append(0.0 if total == 0 else 1 - passed / total)
        block_end_index.append(chunk[-1].index)
    baseline_blocks = BASELINE_HOURS // block
    mu = sum(fail_rates[:baseline_blocks]) / baseline_blocks
    cusum_result = cusum(
        fail_rates,
        mu=mu,
        k=float(slo_cfg["cusum_allowance"]),
        h=float(slo_cfg["cusum_threshold"]),
    )
    first = cusum_result.first_alarm
    first_ts = None
    if first is not None:
        first_ts = lumen[block_end_index[first]].ts

    specs = [
        ("availability", "all", "availability", "Share of requests with status ok."),
        ("latency", "all", "latency", "Share of requests at or under 1500 ms."),
        ("quality", "lumen", "quality", "Share of the Lumen eval sample the rubric passes."),
        ("safety", "aegis", "safety", "Share of Aegis requests the cheap screen marks safe."),
    ]
    descriptions = {item["id"]: item["description"] for item in slo_cfg["objectives"]}
    targets = {item["id"]: float(item["target"]) for item in slo_cfg["objectives"]}
    window_hours = int(slo_cfg["window_days"]) * 24
    elapsed = len(lumen)
    stamps = [row.ts for row in lumen]
    objective_rows = []
    incident_inputs: dict[str, tuple[list[int], list[int], float]] = {}
    for name, app, kind, fallback in specs:
        totals, goods = _objective_series(hours, app, kind)
        target = targets[name]
        budget = 1 - target
        end = len(totals) - 1
        error_rate = window_error_rate(totals, goods, end, len(totals))
        view = _burns_at(totals, goods, end, budget, min_events)
        sli = 1 - error_rate
        last_page: str | None = None
        for cursor in range(len(totals)):
            if _status(_burns_at(totals, goods, cursor, budget, min_events), alerts) == "page":
                last_page = stamps[cursor]
        objective_rows.append(
            {
                "id": name,
                "description": descriptions.get(name, fallback),
                "target": target,
                "budget": round(budget, 4),
                "sli": round(sli, 4),
                "error_rate": round(error_rate, 4),
                "remaining": round(budget_remaining(error_rate, budget, elapsed, window_hours), 4),
                "status": _status(view, alerts),
                "burn": {label: view[label]["value"] for label in view},
                "burn_trusted": {label: bool(view[label]["trusted"]) for label in view},
                "last_page": last_page,
            }
        )
        incident_inputs[name] = (totals, goods, budget)

    all_hist = _sum_hist(hours)
    traces, otlp = _exemplars()
    end_ts = stamps[-1]
    baseline_end = (START + timedelta(hours=BASELINE_HOURS - 1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    current_start = lumen[-CURRENT_HOURS].ts

    series = []
    for row in lumen:
        sample = None if row.eval_n == 0 else round(row.eval_pass / row.eval_n, 4)
        series.append(
            {
                "ts": row.ts,
                "lumen_population": round(row.pop_pass / row.requests, 4),
                "lumen_sample": sample,
            }
        )
    safety_series = [
        {"ts": row.ts, "aegis_safety": round(row.safety_pass / row.safety_n, 4) if row.safety_n else 1.0}
        for row in aegis
    ]

    return {
        "seed": 17,
        "judge": "heuristic",
        "window": {"start": START.strftime("%Y-%m-%dT%H:%M:%SZ"), "end": end_ts, "hours": elapsed},
        "gold_n": len(CASES),
        "kappa": kappa,
        "gate_clean": clean.to_dict(),
        "gate_regressed": regressed.to_dict(),
        "cost": _cost(pricing),
        "latency_synthetic_ms": {
            "p50": round(histogram_percentile(all_hist, LAT_EDGES, 0.50), 1),
            "p95": round(histogram_percentile(all_hist, LAT_EDGES, 0.95), 1),
            "note": "Synthetic workload, seed 17. Not a measurement of a live Aegis or Lumen process.",
        },
        "drift": {
            "baseline": f"{stamps[0]} → {baseline_end}",
            "current": f"{current_start} → {end_ts}",
            "signals": signals,
            "cusum": {
                "series": "lumen eval-sample fail rate, 6-hour blocks",
                "mu": round(mu, 4),
                "k": float(slo_cfg["cusum_allowance"]),
                "h": float(slo_cfg["cusum_threshold"]),
                "first_alarm": first_ts,
                "alarm_count": len(cusum_result.alarm_indexes),
            },
        },
        "slo": {"window_days": int(slo_cfg["window_days"]), "objectives": objective_rows},
        "incidents": _incidents(stamps, incident_inputs, alerts, min_events),
        "markers": [
            {"ts": RAMP_START.strftime("%Y-%m-%dT%H:%M:%SZ"), "label": "lumen-v2.4 ramp"},
            {"ts": BLIP.strftime("%Y-%m-%dT%H:%M:%SZ"), "label": "dependency blip"},
        ],
        "series": series,
        "safety_series": safety_series,
        "traces": traces,
        "otlp": otlp,
    }
