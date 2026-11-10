const VIEWS = [
  ["desk", "Desk"],
  ["decide", "Decisions"],
  ["policies", "Policies"],
  ["registry", "Registry"],
  ["matrix", "Control matrix"],
  ["evidence", "Evidence pack"],
];

const state = {
  snap: null,
  view: "desk",
  caseId: "eu-support-us",
  policy: "shipped",
  live: null,
  file: "002-residency.cedar",
  filter: "all",
};

function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, (ch) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  }[ch]));
}

function pill(status) {
  return `<span class="pill ${esc(status)}">${esc(status)}</span>`;
}

function tags(ids, kind) {
  if (!ids.length) return '<span class="quiet">none</span>';
  return ids.map((id) => `<span class="pill ${kind}">${esc(id)}</span>`).join(" ");
}

async function boot() {
  const response = await fetch("/api/snapshot");
  state.snap = await response.json();
  document.getElementById("nav").innerHTML = VIEWS.map(
    ([id, label]) =>
      `<button type="button" data-view="${id}" ${state.view === id ? 'aria-current="true"' : ""}>${label}</button>`,
  ).join("");
  document.getElementById("nav").addEventListener("click", (event) => {
    const button = event.target.closest("button");
    if (!button) return;
    state.view = button.dataset.view;
    for (const node of document.querySelectorAll("#nav button")) {
      node.setAttribute("aria-current", node === button ? "true" : "false");
    }
    draw();
  });
  await loadDecision();
  draw();
}

async function loadDecision() {
  const response = await fetch("/api/decide", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ case_id: state.caseId, policy: state.policy }),
  });
  state.live = await response.json();
}

function draw() {
  const titles = {
    desk: "Auditor desk",
    decide: "Decisions",
    policies: "Policy files",
    registry: "Model registry",
    matrix: "Control matrix",
    evidence: "Evidence pack",
  };
  document.getElementById("title").textContent = titles[state.view];
  const counts = state.snap.counts;
  document.getElementById("mast-status").textContent =
    `${counts.met} met · ${counts.partial} partial · ${counts.gap} gaps`;
  const main = document.getElementById("main");
  const renderers = { desk: desk, decide: decide, policies: policies, registry: registry, matrix: matrix, evidence: evidence };
  main.innerHTML = renderers[state.view]();
  wire(main);
}

function wire(main) {
  main.querySelectorAll("[data-jump]").forEach((node) => {
    node.addEventListener("click", () => {
      state.view = node.dataset.jump;
      if (node.dataset.case) state.caseId = node.dataset.case;
      document.querySelectorAll("#nav button").forEach((button) => {
        button.setAttribute("aria-current", button.dataset.view === state.view ? "true" : "false");
      });
      if (node.dataset.case) {
        loadDecision().then(draw);
      } else {
        draw();
      }
    });
  });
  main.querySelectorAll("[data-case]").forEach((node) => {
    if (node.dataset.jump) return;
    node.addEventListener("click", () => {
      state.caseId = node.dataset.case;
      loadDecision().then(draw);
    });
  });
  main.querySelectorAll("[data-policy]").forEach((node) => {
    node.addEventListener("click", () => {
      state.policy = node.dataset.policy;
      loadDecision().then(draw);
    });
  });
  main.querySelectorAll("[data-file]").forEach((node) => {
    node.addEventListener("click", () => {
      state.file = node.dataset.file;
      draw();
    });
  });
  main.querySelectorAll("[data-filter]").forEach((node) => {
    node.addEventListener("click", () => {
      state.filter = node.dataset.filter;
      draw();
    });
  });
}

function desk() {
  const snap = state.snap;
  const counts = snap.counts;
  const violation = snap.audit.violations[0];
  const gaps = snap.gaps.map((row) => `<li>${pill(row.status)}<span><b>${esc(row.id)}</b> ${esc(row.title)} — ${esc(row.because)}</span></li>`).join("");
  return `
    <section class="stats">
      <article class="stat gap"><b>${counts.gap}</b><span>gaps an auditor would open</span></article>
      <article class="stat partial"><b>${counts.partial}</b><span>partial controls</span></article>
      <article class="stat met"><b>${counts.met}</b><span>controls met</span></article>
      <article class="stat"><b>${snap.audit.event_count}</b><span>Aegis-shaped audit events, chain ${snap.audit.chain_ok ? "verified" : "broken"}</span></article>
    </section>
    <section class="banner">
      <div class="mark">GAP</div>
      <div>
        <strong>Residency violation in the Aegis stub</strong>
        <p>${esc(violation.label)} data on route <span class="mono">${esc(violation.route)}</span> went to ${esc(violation.region)} (${esc(violation.model)}) as <span class="mono">${esc(violation.request_id)}</span>. DLP had already redacted the card. Redaction is not residency.</p>
      </div>
    </section>
    <div class="grid-2">
      <section class="panel">
        <h2>Open gaps</h2>
        <ul class="list">${gaps}</ul>
      </section>
      <section class="panel">
        <h2>Try the decision</h2>
        <p class="quiet">The same EU confidential ticket, two models. The US model has a permit. The residency forbid overrides it.</p>
        <p><button class="case" type="button" data-jump="decide" data-case="eu-support-local">Allow · EU model <small>atlas-eu-mini · eu-central-1</small></button></p>
        <p><button class="case" type="button" data-jump="decide" data-case="eu-support-us">Block · US model <small>frontier-us-large · us-east-1</small></button></p>
        <p class="quiet">Head <span class="mono">${esc(snap.audit.head_hash.slice(0, 16))}</span> · policy ${esc(snap.policy_digest.slice(0, 12))}</p>
      </section>
    </div>`;
}

function decide() {
  const live = state.live;
  const decision = live.decision;
  const request = state.snap.decisions.find((item) => item.id === state.caseId).request;
  const model = live.model;
  const rows = Object.entries(request).map(([key, value]) => `<tr><th>${esc(key)}</th><td class="mono">${esc(value)}</td></tr>`).join("");
  const cases = state.snap.decisions.map((item) => {
    const pressed = item.id === state.caseId ? "true" : "false";
    return `<button class="case" type="button" data-case="${esc(item.id)}" aria-pressed="${pressed}"><b>${esc(item.title)}</b><small>${esc(item.expect.effect)} · ${esc(item.id)}</small></button>`;
  }).join("");
  const banner = state.policy === "no-residency"
    ? `<div class="warn-banner">002-residency.cedar is not loaded. This is the change the regression gate rejects. Locked case match: ${live.matches_locked_case ? "yes" : "no"}.</div>`
    : "";
  const excerpt = live.excerpt
    ? `<pre class="excerpt">${esc(live.excerpt)}</pre>`
    : `<p class="quiet">No policy line. ${esc(decision.primary_rule)} is what the engine does when nothing else matches.</p>`;
  const modelBits = model
    ? `${esc(model.region)} · ${esc(model.risk_tier)} · oversight ${model.human_oversight ? "yes" : "no"} · ${esc(model.status)}`
    : "not in the registry";
  return `
    <div class="decide">
      <div class="cases">${cases}</div>
      <section class="panel stage">
        <div class="stage-top">
          <div>
            <p class="rule">${esc(decision.primary_rule)}</p>
            <p class="reason">${esc(decision.reason)}</p>
          </div>
          <div class="stamp ${esc(decision.effect)}">${esc(decision.effect)}</div>
        </div>
        <div class="toggle">
          <button type="button" data-policy="shipped" aria-pressed="${state.policy === "shipped"}">Shipped policies</button>
          <button type="button" data-policy="no-residency" aria-pressed="${state.policy === "no-residency"}">Drop residency file</button>
        </div>
        ${banner}
        <p>Permits ${tags(decision.matched_permits, "met")}</p>
        <p>Forbids ${tags(decision.matched_forbids, "gap")}</p>
        <p class="quiet">Model ${esc(decision.model_id)} · ${modelBits}</p>
        <table>${rows}</table>
        <h2>Policy</h2>
        ${excerpt}
      </section>
    </div>`;
}

function policies() {
  const files = state.snap.policy_files;
  const current = files.find((file) => file.name === state.file) || files[0];
  const buttons = files.map((file) => `<button type="button" data-file="${esc(file.name)}" aria-pressed="${file.name === current.name}">${esc(file.name)}</button>`).join("");
  const body = current.text.split("\n").map((line, index) => {
    const kind = line.trim().startsWith("forbid") ? "f" : line.trim().startsWith("permit") ? "p" : line.includes("@id") ? "k" : "";
    return `<span class="ln">${String(index + 1).padStart(2, " ")}</span><span class="${kind}">${esc(line)}</span>`;
  }).join("\n");
  return `
    <div class="policy-wrap">
      <div class="files">${buttons}</div>
      <pre class="policy">${body}</pre>
    </div>
    <p class="quiet">Cedar subset: permit or forbid, optional when, ==, !=, in, &amp;&amp;, ||, !. Forbid wins. No match is a deny. Unknown syntax is a parse error.</p>`;
}

function registry() {
  const cards = state.snap.models.map((model) => `
    <article class="model">
      <header>
        <h3>${esc(model.id)}</h3>
        <span class="region">${esc(model.region)}</span>
      </header>
      <div class="chips">
        <span class="pill ${model.status === "active" ? "met" : "neutral"}">${esc(model.status)}</span>
        <span class="pill ${model.risk_tier === "unacceptable" || model.risk_tier === "high" ? "gap" : "neutral"}">${esc(model.risk_tier)} risk</span>
        <span class="pill neutral">${esc(model.provider)}</span>
        <span class="pill ${model.human_oversight ? "met" : "gap"}">${model.human_oversight ? "oversight" : "no oversight"}</span>
      </div>
      <p>${esc(model.intended_use)}</p>
      <dl class="kv">
        <dt>Purpose</dt><dd class="mono">${esc(model.purpose)}</dd>
        <dt>Oversight</dt><dd>${model.human_oversight ? "reviewer assigned" : "no reviewer"}</dd>
        <dt>Card</dt><dd>${model.card_complete ? "complete" : "incomplete"}</dd>
        <dt>Provider review</dt><dd>${model.provider_reviewed ? "signed" : "not signed"}</dd>
        <dt>Out of scope</dt><dd>${esc(model.out_of_scope.join("; "))}</dd>
        <dt>Limits</dt><dd>${esc(model.known_limitations.join("; "))}</dd>
      </dl>
    </article>`).join("");
  return `<div class="models">${cards}</div>`;
}

function matrix() {
  const filters = [
    ["all", "All"],
    ["gap", "Gaps"],
    ["eu_ai_act", "EU AI Act"],
    ["nist_ai_rmf", "NIST AI RMF"],
  ];
  const buttons = filters.map(([id, label]) => `<button type="button" data-filter="${id}" aria-pressed="${state.filter === id}">${label}</button>`).join("");
  const rows = state.snap.matrix.controls.filter((row) => {
    if (state.filter === "all") return true;
    if (state.filter === "gap") return row.status === "gap";
    return row.framework === state.filter;
  }).map((row) => `
    <tr>
      <td class="mono">${esc(row.ref)}</td>
      <td><b>${esc(row.title)}</b><div class="quiet">${esc(row.id)}</div></td>
      <td>${pill(row.status)}</td>
      <td class="because">${esc(row.because)}</td>
    </tr>`).join("");
  return `
    <div class="filters">${buttons}</div>
    <section class="panel">
      <table>
        <thead><tr><th>Ref</th><th>Control</th><th>Status</th><th>Why</th></tr></thead>
        <tbody>${rows}</tbody>
      </table>
    </section>`;
}

function evidence() {
  const snap = state.snap;
  const violation = snap.audit.violations[0];
  const gapList = snap.gaps.map((row) => `<li>${pill("gap")}<span><b>${esc(row.ref)} ${esc(row.title)}</b> — ${esc(row.because)} <span class="quiet">Treatment: ${esc(row.treatment)}</span></span></li>`).join("");
  const partialList = snap.partials.map((row) => `<li>${pill("partial")}<span><b>${esc(row.ref)} ${esc(row.title)}</b> — ${esc(row.because)}</span></li>`).join("");
  const decisionRows = snap.decisions.map((item) => `<tr><td class="mono">${esc(item.id)}</td><td>${esc(item.decision.effect)}</td><td class="mono">${esc(item.decision.primary_rule)}</td></tr>`).join("");
  const sloRows = snap.slo.objectives.map((item) => `<tr><td>${esc(item.id)}</td><td>${esc(item.app)}</td><td>${item.target}</td><td>${item.sli}</td><td>${pill(item.status === "within_budget" ? "met" : item.status === "ticket" ? "partial" : "gap")}</td></tr>`).join("");
  return `
    <article class="doc">
      <p class="lede">Evidence pack for ${esc(snap.tenant)}. Window ${esc(snap.window.start)} to ${esc(snap.window.end)}. ${esc(snap.classification)}.</p>
      <section>
        <h3>Scope</h3>
        <p>Systems in the pack: Aegis audit vocabulary (offline stub), Lens SLO snapshot (offline stub), Charter decisions on the shipped policy bundle <span class="mono">${esc(snap.policy_digest.slice(0, 16))}</span>.</p>
      </section>
      <section>
        <h3>Planted finding</h3>
        <p>${esc(violation.request_id)} at ${esc(violation.ts)}: ${esc(violation.label)} routed <span class="mono">${esc(violation.route)}</span> to ${esc(violation.region)} on ${esc(violation.model)}. Chain verified, head <span class="mono">${esc(snap.audit.head_hash.slice(0, 16))}</span>, ${snap.audit.event_count} events.</p>
      </section>
      <section>
        <h3>Gaps</h3>
        <ul class="list">${gapList}</ul>
      </section>
      <section>
        <h3>Partials</h3>
        <ul class="list">${partialList}</ul>
      </section>
      <section>
        <h3>Lens objectives</h3>
        <table><thead><tr><th>Objective</th><th>App</th><th>Target</th><th>SLI</th><th>Status</th></tr></thead><tbody>${sloRows}</tbody></table>
        <p class="quiet">${esc(snap.slo.note)}</p>
      </section>
      <section>
        <h3>Locked decisions</h3>
        <table><thead><tr><th>Case</th><th>Effect</th><th>Primary rule</th></tr></thead><tbody>${decisionRows}</tbody></table>
      </section>
      <section>
        <h3>Cost</h3>
        <p>Charter provider cost $0. A projected external review of this pack is $${snap.cost.projected_llm_review_usd} (${esc(snap.cost.note)}).</p>
      </section>
      <p class="foot">Decision p95 ${snap.latency.p95_us} µs over ${snap.latency.rounds} rounds of the residency deny. Measured on this process, not a production SLO.</p>
    </article>`;
}

boot();
