"""Fourteen days of seeded traffic for Aegis and Lumen.

The generator is the ground truth of a synthetic world. Lens still only "sees" what a
real deployment would see: every span's attributes (for drift and the cheap safety
screen) and a stratified sample (for the quality rubric). Outcomes are drawn from
fixed rates so the judge is not invoked tens of thousands of times; the gold set is
where the real rubric runs.

Rates are chosen so the story is visible, then the code reports whatever the draws
produce. Nothing in the dashboard is typed in by hand.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from lens.sampling.sampler import decide

SEED = 17
START = datetime(2026, 10, 22, tzinfo=UTC)
N_HOURS = 14 * 24
RAMP_START = datetime(2026, 11, 2, 15, tzinfo=UTC)
BLIP = datetime(2026, 11, 3, 18, tzinfo=UTC)
SAFETY_HOURS = frozenset(BLIP + timedelta(hours=offset) for offset in range(4))

EVAL_RATE = 0.10
SLOW_MS = 1500.0
LATENCY_SLO_MS = 1500
CANARY = 0.02
RAMP_TARGET = 0.75
RAMP_HOURS = 18.0
V23_PASS = 0.97
V24_PASS = 0.55
AEGIS_PASS = 0.98
ERROR_RATE = 0.0015
BLIP_ERROR = 0.18
INCIDENT_UNSAFE = 0.08

LAT_EDGES = list(range(0, 4001, 50))
QUALITY_LABELS = ("0.00-0.50", "0.50-0.75", "0.75-0.90", "0.90-1.00")


@dataclass
class HourStat:
    index: int
    ts: str
    app: str
    requests: int = 0
    errors: int = 0
    latency_good: int = 0
    latency_hist: list[int] = field(default_factory=lambda: [0] * len(LAT_EDGES))
    pop_pass: int = 0
    eval_n: int = 0
    eval_pass: int = 0
    safety_n: int = 0
    safety_pass: int = 0
    models: dict[str, int] = field(default_factory=dict)
    prompts: dict[str, int] = field(default_factory=dict)
    routes: dict[str, int] = field(default_factory=dict)
    quality_hist: dict[str, int] = field(default_factory=lambda: {label: 0 for label in QUALITY_LABELS})

    def bump(self, counter: dict[str, int], key: str) -> None:
        counter[key] = counter.get(key, 0) + 1


def _volume(app: str, hour_of_day: int, day_index: int) -> int:
    # Off-peak stays high enough that a 6-hour eval window still has a
    # trustworthy sample. A laptop demo with a near-empty night looks like an outage.
    peak = 200 if app == "lumen" else 140
    off = 80 if app == "lumen" else 56
    base = peak if 14 <= hour_of_day <= 22 else off
    wobble = ((day_index * 3 + hour_of_day * 5 + (0 if app == "lumen" else 7)) % 5) - 2
    return base + wobble


def v24_fraction(ts: datetime) -> float:
    if ts < RAMP_START:
        return CANARY
    elapsed = (ts - RAMP_START).total_seconds() / 3600
    if elapsed >= RAMP_HOURS:
        return RAMP_TARGET
    return CANARY + (RAMP_TARGET - CANARY) * (elapsed / RAMP_HOURS)


def _quality_bucket(score: float) -> str:
    if score < 0.50:
        return QUALITY_LABELS[0]
    if score < 0.75:
        return QUALITY_LABELS[1]
    if score < 0.90:
        return QUALITY_LABELS[2]
    return QUALITY_LABELS[3]


def _latency_index(ms: int) -> int:
    return min(ms // 50, len(LAT_EDGES) - 1)


def _route(draw: float, unsafe: bool) -> str:
    if unsafe:
        return "allow"
    if draw < 0.70:
        return "allow"
    if draw < 0.92:
        return "redact_and_continue"
    if draw < 0.98:
        return "local_only"
    return "block"


def simulate(seed: int = SEED) -> list[HourStat]:
    rng = random.Random(seed)
    hours: list[HourStat] = []
    for index in range(N_HOURS):
        ts = START + timedelta(hours=index)
        fraction = v24_fraction(ts)
        incident = ts in SAFETY_HOURS
        blip = ts == BLIP
        for app in ("lumen", "aegis"):
            stat = HourStat(index=index, ts=ts.strftime("%Y-%m-%dT%H:%M:%SZ"), app=app)
            n = _volume(app, ts.hour, index // 24)
            for i in range(n):
                r_err = rng.random()
                r_pass = rng.random()
                r_model = rng.random()
                r_prompt = rng.random()
                r_route = rng.random()
                r_unsafe = rng.random()
                noise = rng.randrange(0, 380)
                r_score = rng.random()

                is_error = r_err < (BLIP_ERROR if blip else ERROR_RATE)
                if app == "lumen":
                    bad_prompt = r_prompt < fraction
                    prompt = "lumen-v2.4" if bad_prompt else "lumen-v2.3"
                    model = "mock-small" if bad_prompt or r_model < 0.10 else "mock-large"
                    route = ""
                    unsafe = False
                    passed = r_pass < (V24_PASS if bad_prompt else V23_PASS)
                else:
                    bad_prompt = False
                    prompt = "aegis-policy-v8" if incident else "aegis-policy-v7"
                    model = "mock-local" if r_model < 0.20 else "mock-external"
                    unsafe = r_unsafe < (INCIDENT_UNSAFE if incident else 0.0)
                    route = _route(r_route, unsafe)
                    passed = r_pass < AEGIS_PASS

                base = 420 if app == "lumen" else 280
                extra = 520 if bad_prompt else 0
                if is_error:
                    extra += 900
                latency = base + noise + extra
                score = (0.82 + r_score * 0.17) if passed else (0.15 + r_score * 0.50)

                safety_signal = app == "aegis" and (unsafe or route in {"block", "require_approval"})
                decision = decide(
                    trace_id=f"{app}-{index}-{i}",
                    status="error" if is_error else "ok",
                    latency_ms=float(latency),
                    safety_signal=safety_signal,
                    app=app,
                    model=model,
                    rate=EVAL_RATE,
                    slow_ms=SLOW_MS,
                )

                stat.requests += 1
                stat.errors += int(is_error)
                stat.latency_good += int(latency <= LATENCY_SLO_MS)
                stat.latency_hist[_latency_index(latency)] += 1
                stat.pop_pass += int(passed)
                stat.bump(stat.models, model)
                stat.bump(stat.prompts, prompt)
                if route:
                    stat.bump(stat.routes, route)
                if app == "aegis":
                    stat.safety_n += 1
                    stat.safety_pass += int(not unsafe)
                if decision.reason == "eval_stratum":
                    stat.eval_n += 1
                    stat.eval_pass += int(passed)
                    stat.quality_hist[_quality_bucket(score)] += 1
            hours.append(stat)
    return hours


def histogram_percentile(counts: list[int], edges: list[int], p: float) -> float:
    total = sum(counts)
    if total <= 0:
        return 0.0
    need = p * total
    acc = 0
    for index, count in enumerate(counts):
        acc += count
        if acc >= need and count:
            lo = edges[index]
            hi = edges[index] + (edges[1] - edges[0] if index + 1 < len(edges) else 50)
            prev = acc - count
            return lo + ((need - prev) / count) * (hi - lo)
    return float(edges[-1])
