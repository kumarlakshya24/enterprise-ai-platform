"""Render the SLO dashboard as one self-contained HTML file. No network, no JS required."""

from __future__ import annotations

import html
from typing import Any

STATUS_WORD = {"ok": "Within budget", "ticket": "Ticket", "page": "Page"}


def _esc(value: object) -> str:
    return html.escape(str(value), quote=True)


def _pct(value: float) -> str:
    return f"{value * 100:.2f}%"


def _remaining_label(value: float) -> str:
    if value < 0:
        return "Budget exhausted"
    return f"{value * 100:.0f}% of 30-day budget left"


def _chart(report: dict[str, Any]) -> str:
    series = report["series"]
    safety = {row["ts"]: row["aegis_safety"] for row in report["safety_series"]}
    width, height = 760, 250
    left, right, top, bottom = 44, 12, 18, 28
    inner_w = width - left - right
    inner_h = height - top - bottom
    y_min, y_max = 0.55, 1.0

    def xy(index: int, value: float) -> tuple[float, float]:
        x = left + (index / max(len(series) - 1, 1)) * inner_w
        clamped = min(y_max, max(y_min, value))
        y = top + (1 - (clamped - y_min) / (y_max - y_min)) * inner_h
        return x, y

    def polyline(values: list[float | None]) -> str:
        parts: list[str] = []
        for index, value in enumerate(values):
            if value is None:
                continue
            x, y = xy(index, value)
            parts.append(f"{x:.1f},{y:.1f}")
        return " ".join(parts)

    pop = polyline([row["lumen_population"] for row in series])
    safe = polyline([safety[row["ts"]] for row in series])
    dots = []
    for index, row in enumerate(series):
        if index % 3 or row["lumen_sample"] is None:
            continue
        x, y = xy(index, row["lumen_sample"])
        dots.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="1.6" class="dot"/>')
    slo_y = xy(0, 0.95)[1]
    grid = []
    for tick in (0.6, 0.7, 0.8, 0.9, 1.0):
        y = xy(0, tick)[1]
        grid.append(
            f'<line x1="{left}" y1="{y:.1f}" x2="{width - right}" y2="{y:.1f}" class="grid"/>'
            f'<text x="{left - 6}" y="{y + 3:.1f}" class="tick" text-anchor="end">{tick:.0%}</text>'
        )
    markers = []
    stamps = [row["ts"] for row in series]
    for marker in report["markers"]:
        if marker["ts"] not in stamps:
            continue
        index = stamps.index(marker["ts"])
        x, _ = xy(index, 1)
        markers.append(f'<line x1="{x:.1f}" y1="{top}" x2="{x:.1f}" y2="{height - bottom}" class="marker"/>')
    axis = (
        f'<text x="{left}" y="{height - 6}" class="tick">{_esc(series[0]["ts"][5:10])}</text>'
        f'<text x="{width - right}" y="{height - 6}" class="tick" text-anchor="end">{_esc(series[-1]["ts"][5:10])}</text>'
    )
    return f"""<svg viewBox="0 0 {width} {height}" role="img" aria-label="Lumen quality and Aegis safety over 14 days">
      {"".join(grid)}
      <line x1="{left}" y1="{slo_y:.1f}" x2="{width - right}" y2="{slo_y:.1f}" class="slo-line"/>
      <text x="{width - right}" y="{slo_y - 4:.1f}" class="slo-label" text-anchor="end">quality target 95%</text>
      {"".join(markers)}
      <polyline points="{safe}" class="line safety"/>
      <polyline points="{pop}" class="line population"/>
      {"".join(dots)}
      {axis}
    </svg>"""


def _budget_bar(remaining: float) -> str:
    shown = min(1.0, max(0.0, remaining))
    tone = "good" if remaining > 0.5 else "ticket" if remaining > 0 else "page"
    return f'<div class="bar"><span class="{tone}" style="width:{shown * 100:.1f}%"></span></div>'


def _cards(report: dict[str, Any]) -> str:
    blocks = []
    for row in report["slo"]["objectives"]:
        burns = []
        for label in ("1h", "6h", "24h", "72h"):
            trusted = row["burn_trusted"][label]
            text = f"{label} {row['burn'][label]:.1f}×" if trusted else f"{label} thin"
            burns.append(f'<span class="chip {"dim" if not trusted else ""}">{text}</span>')
        last = row["last_page"] or "no page in window"
        blocks.append(
            f"""<article class="card status-{row["status"]}">
              <header><span>{_esc(row["id"])}</span><em class="pill">{_esc(STATUS_WORD[row["status"]])}</em></header>
              <p class="sli">{_pct(row["sli"])}</p>
              <p class="target">target {_pct(row["target"])}</p>
              {_budget_bar(row["remaining"])}
              <p class="remain">{_esc(_remaining_label(row["remaining"]))}</p>
              <div class="chips">{"".join(burns)}</div>
              <p class="last">Last page {_esc(last[5:16].replace("T", " ") if row["last_page"] else last)}</p>
            </article>"""
        )
    return "\n".join(blocks)


def _drift(report: dict[str, Any]) -> str:
    signals = report["drift"]["signals"]
    peak = max(signal["psi"] for signal in signals)
    peak = max(peak, 0.25)
    rows = []
    for signal in signals:
        width = min(100.0, signal["psi"] / peak * 100)
        rows.append(
            f"""<div class="psi">
              <div class="psi-name"><span>{_esc(signal["name"])}</span><b>{signal["psi"]:.2f}</b></div>
              <div class="bar"><span class="{signal["level"]}" style="width:{width:.1f}%"></span>
                <i class="threshold" style="left:{(0.25 / peak) * 100:.1f}%"></i></div>
            </div>"""
        )
    cusum = report["drift"]["cusum"]
    return f"""<div class="drift-head">
        <h2>Drift</h2>
        <p>PSI, first 7 days against the last 48 hours. The tick is 0.25.</p>
      </div>
      {"".join(rows)}
      <p class="cusum">CUSUM on the Lumen sample fail rate first crosses h={cusum["h"]} at
        <b>{_esc(cusum["first_alarm"])}</b>. Baseline μ={cusum["mu"]:.3f}.</p>"""


def _incidents(report: dict[str, Any]) -> str:
    body = []
    for event in report["incidents"]:
        body.append(
            "<tr>"
            f"<td>{_esc(event['ts'][5:16].replace('T', ' '))}</td>"
            f"<td>{_esc(event['objective'])}</td>"
            f"<td>{_esc(event['from'])} → {_esc(event['to'])}</td>"
            f"<td>{event['burn_1h']:.1f}×</td>"
            f"<td>{event['burn_6h']:.1f}×</td>"
            "</tr>"
        )
    return f"""<table>
      <thead><tr><th>When</th><th>Objective</th><th>Change</th><th>1h</th><th>6h</th></tr></thead>
      <tbody>{"".join(body)}</tbody>
    </table>"""


def _traces(report: dict[str, Any]) -> str:
    blocks = []
    for trace in report["traces"]:
        rows = []
        for row in trace["rows"]:
            tone = "err" if row["status"] != "STATUS_CODE_OK" else "ok"
            rows.append(
                f"""<div class="span">
                  <div class="span-name">{_esc(row["name"])}<em>{row["ms"]:.0f} ms</em></div>
                  <div class="track"><i class="{tone}" style="margin-left:{row["start_pct"]:.2f}%;width:{row["width_pct"]:.2f}%"></i></div>
                </div>"""
            )
        blocks.append(f"<h3>{_esc(trace['title'])}</h3>{''.join(rows)}")
    return "\n".join(blocks)


def _gate(report: dict[str, Any]) -> str:
    def column(gate: dict[str, Any]) -> str:
        items = []
        for rule in gate["rules"]:
            klass = "pass" if rule["passed"] else "fail"
            items.append(
                f'<li class="{klass}"><b>{_esc(rule["rule_id"])}</b><span>{_esc(rule["detail"])}</span></li>'
            )
        word = "PASS" if gate["passed"] else "FAIL"
        regs = ""
        if gate["safety_regressions"]:
            names = ", ".join(gate["safety_regressions"])
            regs = f'<p class="regs">New unsafe ids: {_esc(names)}</p>'
        return f"""<div class="gate-col {word.lower()}">
          <header><span>{_esc(gate["name"])}</span><em>{word}</em></header>
          <ul>{"".join(items)}</ul>
          {regs}
        </div>"""

    return column(report["gate_clean"]) + column(report["gate_regressed"])


def render_html(report: dict[str, Any]) -> str:
    window = report["window"]
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Lens · SLO</title>
<style>
  :root {{
    --bg: #10130f;
    --panel: #181c16;
    --panel-2: #20261d;
    --line: #31382c;
    --text: #e8eee2;
    --muted: #8e9986;
    --good: #b7c48a;
    --ticket: #e0b15a;
    --page: #e08a72;
    --accent: #d7b48a;
    --pop: #d7b48a;
    --sample: #7f8f86;
    --safe: #8aa8c4;
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0; background:
      radial-gradient(1200px 500px at 10% -10%, #2a261c 0%, transparent 55%),
      var(--bg);
    color: var(--text);
    font-family: Inter, "DejaVu Sans", sans-serif;
    font-size: 14px; line-height: 1.45;
  }}
  main {{ width: min(1180px, calc(100% - 40px)); margin: 0 auto; padding: 28px 0 48px; }}
  header.top {{ display: flex; justify-content: space-between; align-items: flex-end; gap: 24px; margin-bottom: 22px; }}
  .brand {{ font-family: "JetBrains Mono", "DejaVu Sans Mono", monospace; letter-spacing: 0.22em; font-size: 13px; color: var(--accent); }}
  h1 {{ font-size: 28px; font-weight: 520; margin: 4px 0 0; letter-spacing: -0.03em; }}
  .meta {{ color: var(--muted); text-align: right; font-variant-numeric: tabular-nums; }}
  .banner {{
    border: 1px solid var(--line); background: var(--panel); border-radius: 12px;
    padding: 10px 14px; color: var(--muted); margin-bottom: 16px;
  }}
  .cards {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; }}
  .card {{ background: var(--panel); border: 1px solid var(--line); border-radius: 14px; padding: 14px 14px 12px; }}
  .card header, .gate-col header {{ display: flex; justify-content: space-between; align-items: center; color: var(--muted); text-transform: uppercase; letter-spacing: 0.08em; font-size: 11px; }}
  .sli {{ font-family: "JetBrains Mono", monospace; font-size: 32px; margin: 10px 0 0; letter-spacing: -0.04em; }}
  .target, .remain, .last, .cusum {{ color: var(--muted); margin: 2px 0 8px; }}
  .pill {{ font-style: normal; border-radius: 999px; padding: 2px 8px; border: 1px solid var(--line); }}
  .status-ok .pill {{ color: var(--good); }}
  .status-ticket .pill {{ color: var(--ticket); }}
  .status-page .pill {{ color: var(--page); }}
  .bar {{ position: relative; height: 7px; background: #2a3128; border-radius: 99px; overflow: hidden; margin: 8px 0; }}
  .bar > span {{ display: block; height: 100%; border-radius: 99px; }}
  .bar > span.good, .bar > span.ok {{ background: var(--good); }}
  .bar > span.ticket, .bar > span.watch {{ background: var(--ticket); }}
  .bar > span.page, .bar > span.alert {{ background: var(--page); }}
  .chips {{ display: flex; flex-wrap: wrap; gap: 4px; }}
  .chip {{ font-family: "JetBrains Mono", monospace; font-size: 11px; color: var(--text); background: var(--panel-2); border-radius: 6px; padding: 2px 6px; }}
  .chip.dim {{ opacity: 0.4; }}
  .split {{ display: grid; grid-template-columns: 1.4fr 0.8fr; gap: 12px; margin-top: 12px; }}
  .panel {{ background: var(--panel); border: 1px solid var(--line); border-radius: 14px; padding: 14px 16px 16px; margin-top: 12px; }}
  .split .panel {{ margin-top: 0; }}
  h2 {{ margin: 0 0 4px; font-size: 16px; font-weight: 560; }}
  .legend {{ display: flex; gap: 14px; color: var(--muted); font-size: 12px; margin: 4px 0 8px; }}
  .swatch {{ display: inline-block; width: 16px; height: 3px; margin-right: 6px; vertical-align: middle; }}
  .swatch.pop {{ background: var(--pop); }}
  .swatch.sample {{ background: var(--sample); }}
  .swatch.safe {{ background: var(--safe); }}
  svg {{ width: 100%; height: auto; }}
  .grid {{ stroke: #2c3328; stroke-width: 1; }}
  .tick {{ fill: var(--muted); font-size: 10px; font-family: "JetBrains Mono", monospace; }}
  .slo-line {{ stroke: var(--good); stroke-dasharray: 3 4; stroke-width: 1; }}
  .slo-label, .marker-label {{ fill: var(--muted); font-size: 10px; font-family: Inter, sans-serif; }}
  .marker {{ stroke: #6d5a3e; stroke-dasharray: 2 3; }}
  .line {{ fill: none; stroke-width: 1.6; }}
  .line.population {{ stroke: var(--pop); stroke-width: 2.1; }}
  .dot {{ fill: var(--sample); opacity: 0.85; }}
  .line.safety {{ stroke: var(--safe); stroke-width: 1.4; opacity: 0.85; }}
  .psi {{ margin: 8px 0; }}
  .psi-name {{ display: flex; justify-content: space-between; font-size: 13px; }}
  .psi-name b {{ font-family: "JetBrains Mono", monospace; font-weight: 500; }}
  .threshold {{ position: absolute; top: -2px; width: 1px; height: 11px; background: var(--text); opacity: 0.7; }}
  table {{ width: 100%; border-collapse: collapse; font-variant-numeric: tabular-nums; }}
  th {{ text-align: left; color: var(--muted); font-weight: 500; font-size: 12px; }}
  td, th {{ padding: 6px 8px 6px 0; border-bottom: 1px solid var(--line); }}
  .span {{ display: grid; grid-template-columns: 240px 1fr; gap: 10px; align-items: center; margin: 4px 0; }}
  .span-name {{ font-family: "JetBrains Mono", monospace; font-size: 12px; display: flex; justify-content: space-between; }}
  .span-name em {{ color: var(--muted); font-style: normal; }}
  .track {{ height: 10px; background: #262c22; border-radius: 99px; position: relative; }}
  .track i {{ position: absolute; top: 0; height: 10px; border-radius: 99px; display: block; }}
  .track i.ok {{ background: var(--accent); }}
  .track i.err {{ background: var(--page); }}
  h3 {{ font-size: 13px; font-weight: 560; margin: 12px 0 6px; color: var(--accent); }}
  .gates {{ display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }}
  .gate-col {{ background: var(--panel-2); border-radius: 12px; padding: 12px; }}
  .gate-col header em {{ font-style: normal; font-family: "JetBrains Mono", monospace; }}
  .gate-col.pass header em {{ color: var(--good); }}
  .gate-col.fail header em {{ color: var(--page); }}
  .gate-col ul {{ list-style: none; padding: 0; margin: 10px 0 0; }}
  .gate-col li {{ margin: 0 0 8px; }}
  .gate-col li span {{ display: block; color: var(--muted); font-size: 12px; }}
  .gate-col li.fail b {{ color: var(--page); }}
  .gate-col li.pass b {{ color: var(--good); }}
  .regs {{ color: var(--page); }}
  footer {{ color: var(--muted); margin-top: 18px; font-size: 12px; }}
  body[data-view="slo"] .only-drift, body[data-view="slo"] .only-trace, body[data-view="slo"] .only-gate {{ display: none; }}
  body[data-view="drift"] .only-slo, body[data-view="drift"] .only-trace, body[data-view="drift"] .only-gate {{ display: none; }}
  body[data-view="trace"] .split,
  body[data-view="trace"] .only-slo, body[data-view="trace"] .only-drift, body[data-view="trace"] .only-gate,
  body[data-view="trace"] .panel-drift {{ display: none; }}
  body[data-view="gate"] .split,
  body[data-view="gate"] .only-slo, body[data-view="gate"] .only-drift, body[data-view="gate"] .only-trace,
  body[data-view="gate"] .panel-drift {{ display: none; }}
</style>
</head>
<body>
<main>
  <header class="top">
    <div>
      <div class="brand">LENS</div>
      <h1>LLMOps, on the sample you can afford to judge</h1>
    </div>
    <div class="meta">
      <div>synthetic · seed {report["seed"]} · heuristic judge</div>
      <div>{_esc(window["start"][:10])} → {_esc(window["end"][:10])}</div>
    </div>
  </header>
  <p class="banner">Traces are generated, not captured from a live Aegis or Lumen process. The gate numbers are the heuristic on the hand-labeled gold set. Burn rates use a 30-day budget; a dim chip means that window had too few events to page.</p>
  <section class="cards only-slo">{_cards(report)}</section>
  <section class="split">
    <div class="panel only-slo">
      <h2>Quality and safety</h2>
      <div class="legend">
        <span><i class="swatch pop"></i>Lumen pass rate, all requests</span>
        <span><i class="swatch sample"></i>Lumen eval sample, every 3rd hour</span>
        <span><i class="swatch safe"></i>Aegis safety screen</span>
      </div>
      {_chart(report)}
      <p class="remain">Dashed lines: the lumen-v2.4 ramp on 2 Nov, then the dependency blip on 3 Nov 18:00. Dots are the eval sample.</p>
    </div>
    <div class="panel panel-drift">{_drift(report)}</div>
  </section>
  <section class="panel only-drift">
    <h2>Alert transitions</h2>
    <p class="remain">A page holds until the 6-hour burn falls under 4×, so a noisy hour cannot open and close the same incident.</p>
    {_incidents(report)}
  </section>
  <section class="panel only-trace">
    <h2>Traces</h2>
    <p class="remain">Built by the Aegis and Lumen adapters. The red bar is a blocked tool call, not a failed dashboard.</p>
    {_traces(report)}
  </section>
  <section class="panel only-gate">
    <h2>CI gate</h2>
    <p class="remain">Same judge, same gold inputs. The seeded prompt is the only thing that changed.</p>
    <div class="gates">{_gate(report)}</div>
  </section>
  <footer>Generated by lens.dashboard.render from the eval report. Do not hand-edit.</footer>
</main>
<script>
  const view = new URLSearchParams(location.search).get("view");
  if (view) document.body.dataset.view = view;
</script>
</body>
</html>
"""
