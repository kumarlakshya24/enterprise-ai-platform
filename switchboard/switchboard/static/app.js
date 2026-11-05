const state = { scenarios: [], policies: [], active: null, selectedId: null };

const $ = (id) => document.getElementById(id);

async function api(path, options) {
  const response = await fetch(path, {
    headers: { "content-type": "application/json" },
    ...options,
  });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = body.detail || response.statusText;
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  return body;
}

function esc(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;");
}

function money(value) {
  if (value === null || value === undefined) return "—";
  const abs = Math.abs(value);
  const digits = abs >= 0.01 ? 4 : 6;
  return (value < 0 ? "-$" : "$") + abs.toFixed(digits);
}

function outcomeTag(decision) {
  const outcome = decision.outcome;
  const klass = outcome === "rejected" || outcome === "failed" ? "bad" : outcome === "fallback" ? "warn" : "";
  const degraded = decision.degraded ? " · degraded" : "";
  return `<span class="tag ${klass}">${outcome}${degraded}</span>`;
}

function candidateRows(decision) {
  return decision.candidates
    .map((candidate) => {
      const scores = candidate.scores || {};
      const why = candidate.eligible
        ? `score ${scores.total ?? "—"}`
        : candidate.reject_reasons.join("; ");
      return `<tr class="${candidate.selected ? "picked" : ""} ${candidate.eligible ? "" : "out"}">
        <td>${candidate.selected ? "● " : ""}${candidate.model}</td>
        <td>${candidate.capability.toFixed(2)}</td>
        <td>${candidate.latency_ms.toFixed(0)} ms</td>
        <td>${money(candidate.cost_usd)}</td>
        <td>${candidate.eligible ? "yes" : "no"}</td>
        <td>${esc(why)}</td>
      </tr>`;
    })
    .join("");
}

function renderDecision(decision) {
  const comparison = decision.comparison;
  const timing = decision.timing;
  const features = decision.features;
  const output = decision.output
    ? `<h2>Mock output</h2><pre class="out"></pre>`
    : "";
  const root = document.createElement("div");
  root.innerHTML = `
    <h2>Decision ${outcomeTag(decision)}</h2>
    <p class="small muted">Policy ${decision.policy.version_id} · selection ${decision.policy.selection}
      · floor ${decision.constraints.required_capability.toFixed(2)}
      · headroom ${decision.constraints.min_headroom.toFixed(2)}
      · budget ${money(decision.constraints.budget_usd)}
      · SLO ${decision.constraints.latency_slo_ms} ms</p>
    <div class="kpis">
      <div class="kpi"><span class="muted small">Chosen</span><b>${decision.chosen_model || "none"}</b></div>
      <div class="kpi"><span class="muted small">Spend</span><b>${money(comparison.spend_usd)}</b></div>
      <div class="kpi"><span class="muted small">Always premium</span><b>${money(comparison.always_premium_cost_usd)}</b></div>
      <div class="kpi"><span class="muted small">Savings</span><b>${comparison.savings_pct}%</b></div>
    </div>
    <p class="small">Task <strong>${features.task}</strong>, complexity ${features.complexity.toFixed(2)},
      sensitivity ${features.sensitivity}, about ${features.tokens_in} in / ${features.tokens_out} out.
      Catalog latency ${timing.simulated_latency_ms} ms. Router overhead ${timing.router_overhead_ms} ms (measured).</p>
    <table class="grid">
      <thead><tr><th>Model</th><th>Capability</th><th>Catalog latency</th><th>Est. cost</th><th>Eligible</th><th>Why</th></tr></thead>
      <tbody>${candidateRows(decision)}</tbody>
    </table>
    <h2>Why</h2>
    <ul class="why">${decision.why.map((line) => `<li></li>`).join("")}</ul>
    ${output}
  `;
  root.querySelectorAll(".why li").forEach((node, index) => {
    node.textContent = decision.why[index];
  });
  const pre = root.querySelector("pre.out");
  if (pre && decision.output) pre.textContent = decision.output.text;
  return root;
}

function renderCompare(payload) {
  const root = document.createElement("div");
  const cards = payload.results
    .map((decision) => {
      const klass = decision.outcome === "rejected" || decision.outcome === "failed" ? "bad" : "picked";
      const eligible = decision.candidates.filter((item) => item.eligible).map((item) => item.model);
      return `<article class="card ${klass}">
        <h3>${decision.policy.name}</h3>
        <p>${outcomeTag(decision)} <strong>${decision.chosen_model || "none"}</strong></p>
        <p class="small">Eligible: ${eligible.join(", ") || "none"}</p>
        <p class="small">Spend ${money(decision.comparison.spend_usd)} · premium ${money(decision.comparison.always_premium_cost_usd)} · save ${decision.comparison.savings_pct}%</p>
        <p class="small muted">${esc(decision.why[decision.why.length - 2] || "")}</p>
      </article>`;
    })
    .join("");
  root.innerHTML = `
    <h2>Same prompt, four policies</h2>
    <div class="compare">${cards}</div>
    <p class="small">Four recorded decisions. Combined spend ${money(payload.totals.spend_usd)}
      versus always-premium ${money(payload.totals.always_premium_cost_usd)}
      (save ${money(payload.totals.savings_usd)}).</p>
  `;
  return root;
}

function renderStats(stats) {
  const box = $("stats");
  const models = Object.entries(stats.by_model)
    .map(([name, count]) => `${name} ${count}`)
    .join(" · ") || "no traffic yet";
  box.innerHTML = `
    <h2>Recorded traffic</h2>
    <div class="kpis">
      <div class="kpi"><span class="muted small">Requests</span><b>${stats.requests}</b></div>
      <div class="kpi"><span class="muted small">Spend</span><b>${money(stats.spend_usd)}</b></div>
      <div class="kpi"><span class="muted small">Vs always premium</span><b>${stats.savings_pct}%</b></div>
      <div class="kpi"><span class="muted small">Router p95</span><b>${stats.router_overhead_ms.p95} ms</b></div>
    </div>
    <p class="small muted">${models}. ${stats.note || ""}</p>
  `;
}

function payload() {
  const budget = $("budget").value;
  const slo = $("slo").value;
  return {
    prompt: $("prompt").value,
    policy: $("policy").value,
    budget_usd: budget ? Number(budget) : null,
    latency_slo_ms: slo ? Number(slo) : null,
  };
}

function show(node) {
  const slot = $("result");
  slot.replaceChildren(node);
  document.body.dataset.ready = "true";
}

async function refreshStats() {
  renderStats(await api("/v1/stats"));
}

async function runRoute(dryRun) {
  document.body.dataset.ready = "false";
  const body = payload();
  body.dry_run = dryRun;
  const scenario = state.scenarios.find((item) => item.id === state.selectedId);
  if (
    scenario &&
    scenario.fault &&
    scenario.prompt === body.prompt &&
    scenario.policy === body.policy
  ) {
    body.fault = scenario.fault;
  }
  try {
    const decision = await api("/v1/route", { method: "POST", body: JSON.stringify(body) });
    show(renderDecision(decision));
    await refreshStats();
  } catch (error) {
    show(Object.assign(document.createElement("p"), { textContent: error.message }));
  }
}

async function runCompare() {
  document.body.dataset.ready = "false";
  const body = payload();
  delete body.policy;
  try {
    const result = await api("/v1/compare", { method: "POST", body: JSON.stringify(body) });
    show(renderCompare(result));
    await refreshStats();
  } catch (error) {
    show(Object.assign(document.createElement("p"), { textContent: error.message }));
  }
}

function selectScenario(scenario) {
  state.selectedId = scenario.id;
  $("prompt").value = scenario.prompt;
  $("policy").value = scenario.policy;
  $("blurb").textContent = scenario.blurb;
  document.querySelectorAll(".chips button").forEach((button) => {
    button.classList.toggle("active", button.dataset.id === scenario.id);
  });
}

function fillControls() {
  const select = $("policy");
  select.replaceChildren();
  for (const policy of state.policies) {
    const option = document.createElement("option");
    option.value = policy.name;
    option.textContent = `${policy.name} · ${policy.selection} · $${policy.budget_usd} · ${policy.latency_slo_ms} ms`;
    select.append(option);
  }
  if (state.active) select.value = state.active;
  const chips = $("scenarios");
  chips.replaceChildren();
  for (const scenario of state.scenarios) {
    const button = document.createElement("button");
    button.type = "button";
    button.dataset.id = scenario.id;
    button.textContent = scenario.title;
    button.addEventListener("click", () => selectScenario(scenario));
    chips.append(button);
  }
}

async function boot() {
  const [health, policyBody, scenarioBody] = await Promise.all([
    api("/healthz"),
    api("/v1/policies"),
    api("/v1/scenarios"),
  ]);
  state.policies = policyBody.policies;
  state.active = policyBody.active;
  state.scenarios = scenarioBody.scenarios;
  $("health").textContent = `active ${health.policy} · ${health.models.length} models · ${health.version}`;
  fillControls();
  const params = new URLSearchParams(location.search);
  const shot = params.get("shot");
  if (shot === "compare") {
    selectScenario(state.scenarios[0]);
    const caption = document.createElement("p");
    caption.id = "shot-caption";
    caption.textContent = "Same prompt, four policies";
    document.querySelector("main").prepend(caption);
    await runCompare();
    return;
  }
  const scenario = state.scenarios.find((item) => item.id === shot) || state.scenarios[0];
  selectScenario(scenario);
  if (shot) {
    const caption = document.createElement("p");
    caption.id = "shot-caption";
    caption.textContent = scenario.title;
    document.querySelector("main").prepend(caption);
    await runRoute(false);
  } else {
    await refreshStats();
  }
}

$("run").addEventListener("click", () => runRoute(false));
$("dry").addEventListener("click", () => runRoute(true));
$("compare").addEventListener("click", () => runCompare());
$("reset").addEventListener("click", async () => {
  await api("/v1/demo/reset", { method: "POST", body: "{}" });
  $("result").replaceChildren();
  await refreshStats();
});

boot().catch((error) => {
  $("blurb").textContent = error.message;
});
