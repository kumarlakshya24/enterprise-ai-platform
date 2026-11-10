const ARMS = ["prompt", "rag", "lora", "distilled"];
const ARM_LABEL = { prompt: "Prompt", rag: "RAG", lora: "LoRA stub", distilled: "Student" };
const PRESET_LABEL = {
  "weekly-cited": "Weekly + cites",
  "high-volume-stable": "High volume",
  "narrow-fast": "80 ms narrow",
  "low-volume": "Low volume",
  "cited-stable": "Stable + cites",
};
const SHOTS = {
  weekly: { scenario: "weekly-cited", focus: "stage" },
  lora: { scenario: "high-volume-stable", focus: "stage" },
  distilled: { scenario: "narrow-fast", focus: "stage" },
  low: { scenario: "low-volume", focus: "stage" },
  cited: { scenario: "cited-stable", focus: "stage" },
  compare: { scenario: "weekly-cited", focus: "answers", question: "st-refund-window" },
  memo: { scenario: "weekly-cited", focus: "memo" },
  pipeline: { scenario: "weekly-cited", focus: "pipeline" },
};

const state = {
  report: null,
  decision: null,
  scenarioId: "weekly-cited",
  dirty: false,
};

const $ = (id) => document.getElementById(id);

function volumeFromSlider(value) {
  const min = Math.log(1000);
  const max = Math.log(5_000_000);
  return Math.round(Math.exp(min + (Number(value) / 1000) * (max - min)));
}

function sliderFromVolume(volume) {
  const min = Math.log(1000);
  const max = Math.log(5_000_000);
  return Math.round(((Math.log(volume) - min) / (max - min)) * 1000);
}

function money(value) {
  if (value >= 1000) return `$${Math.round(value).toLocaleString("en-US")}`;
  return `$${value.toFixed(2)}`;
}

function escapeHtml(text) {
  return String(text)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;");
}

function inputsFromForm() {
  const change = document.querySelector("#change button[aria-pressed='true']");
  const slo = document.querySelector("#slo button[aria-pressed='true']");
  return {
    scenario_id: state.scenarioId,
    monthly_requests: volumeFromSlider($("volume").value),
    change_rate: change ? change.dataset.value : "weekly",
    citations_required: $("citations").checked,
    scope: $("scope").checked ? "common_short" : "full",
    latency_slo_ms: Number(slo ? slo.dataset.value : 2000),
    monthly_budget_usd: Number($("budget").value),
  };
}

function fillForm(inputs) {
  $("volume").value = String(sliderFromVolume(inputs.monthly_requests));
  $("volume-readout").textContent = Number(inputs.monthly_requests).toLocaleString("en-US");
  $("citations").checked = Boolean(inputs.citations_required);
  $("scope").checked = inputs.scope === "common_short";
  $("budget").value = String(inputs.monthly_budget_usd);
  for (const button of document.querySelectorAll("#change button")) {
    button.setAttribute("aria-pressed", button.dataset.value === inputs.change_rate ? "true" : "false");
  }
  for (const button of document.querySelectorAll("#slo button")) {
    button.setAttribute("aria-pressed", Number(button.dataset.value) === Number(inputs.latency_slo_ms) ? "true" : "false");
  }
  for (const button of document.querySelectorAll("#presets button")) {
    button.setAttribute("aria-pressed", button.dataset.id === state.scenarioId && !state.dirty ? "true" : "false");
  }
}

function renderBanner(decision) {
  const banner = $("banner");
  banner.className = "banner";
  let title = "No arm clears the rules";
  if (decision.winner === "rag") {
    banner.classList.add("tune-no");
    title = "Do not fine-tune";
  } else if (decision.winner === "lora") {
    banner.classList.add("tune-yes");
    title = "Ship the adapter";
  } else if (decision.winner === "distilled") {
    banner.classList.add("student");
    title = "Ship the student";
  } else if (decision.winner === "prompt") {
    title = "Ship the prompt";
  } else {
    banner.classList.add("none");
  }
  $("banner-kicker").textContent = decision.title || "Custom scenario";
  $("banner-title").textContent = title;
  $("banner-body").textContent = subtitle(decision);
}

function subtitle(decision) {
  const report = state.report;
  const lora = report.arms.lora.holdout_freeze;
  const rag = report.arms.rag.holdout_freeze;
  const student = report.arms.distilled.freeze_full;
  const holdout = `LoRA is ${lora.correct}/${lora.n} on the frozen holdout and RAG is ${rag.correct}/${rag.n}.`;
  if (decision.winner === "lora") {
    return `${holdout} It wins on projected monthly cost at this volume, with citations off and the corpus declared stable. Quality does not justify the freeze.`;
  }
  if (decision.winner === "distilled") {
    const slo = Number(decision.inputs.latency_slo_ms);
    return `The student is ${student.correct}/${student.n} on the full frozen set because long procedures and one-off facts were dropped. This contract keeps the common short slice and a ${slo} ms SLO, which leaves the student.`;
  }
  if (!decision.winner) {
    return "No arm meets the floor, the SLO, and the budget together. Do not fine-tune to escape a constraint the student also misses.";
  }
  const fired = (decision.finetune_checks || []).filter((row) => row.fired).map((row) => row.text);
  return fired[0] || "RAG is the arm that still clears the rules.";
}

function renderTable(decision) {
  const slice = decision.slice;
  const body = $("table").querySelector("tbody");
  body.replaceChildren();
  $("table-caption").textContent = `Slice ${slice} · task success is exact-phrase support · $ and model ms are projections`;
  for (const arm of ARMS) {
    const block = state.report.arms[arm][slice];
    const stale = state.report.arms[arm].staleness;
    const row = document.createElement("tr");
    if (arm === decision.winner) row.className = "selected";
    const rate = Math.round(block.task_success * 100);
    const oldPolicy = stale.stale_denominator
      ? `${stale.stale}/${stale.stale_denominator}`
      : "—";
    const verdict = arm === decision.winner ? "selected" : "out";
    row.innerHTML = `
      <td><span class="arm"><i class="dot ${arm}"></i>${ARM_LABEL[arm]}</span></td>
      <td><span class="bar"><i><span style="width:${rate}%"></span></i>${block.correct}/${block.n}</span></td>
      <td>${Math.round(block.citation_rate * 100)}%</td>
      <td>${oldPolicy}</td>
      <td>${money(decision.monthly_usd[arm])}</td>
      <td>${Math.round(decision.projected_latency_ms[arm])} ms</td>
      <td class="verdict">${verdict}</td>`;
    body.appendChild(row);
  }
  const overhead = state.report.overhead_ms;
  const bits = ARMS.map((arm) => `${arm} p95 ${overhead[arm].p95} ms`).join(" · ");
  $("overhead").textContent = `In-process overhead, n=${overhead.rag.n}. ${bits}. Model latency is not slept and is not added into these figures.`;
}

function renderChecks(decision) {
  const list = $("checks");
  list.replaceChildren();
  for (const check of decision.finetune_checks || []) {
    const item = document.createElement("li");
    if (check.fired) item.className = "fired";
    item.innerHTML = `<b>${check.fired ? "blocks" : "ok"}</b><span></span>`;
    item.querySelector("span").textContent = check.text;
    list.appendChild(item);
  }
}

function renderMemo(markdown) {
  $("memo").innerHTML = markdownToHtml(markdown || "");
}

function markdownToHtml(source) {
  const lines = escapeHtml(source).split("\n");
  const out = [];
  let list = false;
  let table = false;
  const closeList = () => {
    if (list) {
      out.push("</ul>");
      list = false;
    }
  };
  const closeTable = () => {
    if (table) {
      out.push("</tbody></table>");
      table = false;
    }
  };
  for (const line of lines) {
    if (line.startsWith("|")) {
      closeList();
      const cells = line.split("|").slice(1, -1).map((cell) => cell.trim());
      if (cells.every((cell) => /^:?-+:?$/.test(cell))) continue;
      if (!table) {
        out.push("<table><tbody>");
        table = true;
      }
      out.push(`<tr>${cells.map((cell) => `<td>${inline(cell)}</td>`).join("")}</tr>`);
      continue;
    }
    closeTable();
    if (line.startsWith("# ")) {
      closeList();
      out.push(`<h1>${inline(line.slice(2))}</h1>`);
    } else if (line.startsWith("## ")) {
      closeList();
      out.push(`<h2>${inline(line.slice(3))}</h2>`);
    } else if (line.startsWith("- ")) {
      if (!list) {
        out.push("<ul>");
        list = true;
      }
      out.push(`<li>${inline(line.slice(2))}</li>`);
    } else if (line.trim() === "") {
      closeList();
    } else {
      closeList();
      out.push(`<p>${inline(line)}</p>`);
    }
  }
  closeList();
  closeTable();
  return out.join("");
}

function inline(text) {
  return text
    .replaceAll(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    .replaceAll(/`([^`]+)`/g, "<code>$1</code>");
}

function renderQuestions() {
  const select = $("question");
  const groups = [
    ["staleness", "Policy moved or was added"],
    ["holdout", "Held out from training"],
    ["unanswerable", "Not in the runbook"],
  ];
  select.replaceChildren();
  for (const [split, label] of groups) {
    const group = document.createElement("optgroup");
    group.label = label;
    for (const item of state.report.questions.filter((row) => row.split === split)) {
      const option = document.createElement("option");
      option.value = item.id;
      option.textContent = item.question;
      group.appendChild(option);
    }
    select.appendChild(group);
  }
}

async function showQuestion(id) {
  const response = await fetch("/v1/compare", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ question_id: id }),
  });
  const payload = await response.json();
  $("asked").textContent = payload.question;
  const cards = $("cards");
  cards.replaceChildren();
  for (const arm of ARMS) {
    const answer = payload.arms[arm];
    const card = document.createElement("article");
    card.className = `card ${answer.reason_current}`;
    const chip = answer.reason_current;
    const cite = (answer.citations || [])
      .map((row) => `${row.doc_id} · ${row.section}`)
      .join(", ");
    card.innerHTML = `
      <header><h3>${ARM_LABEL[arm]}</h3><span class="chip ${chip === "ok" ? "ok" : chip}">${chip}</span></header>
      <p></p>
      ${cite ? `<p class="cite"></p>` : ""}`;
    card.querySelector("p").textContent = answer.text;
    if (cite) card.querySelector(".cite").textContent = cite;
    cards.appendChild(card);
  }
  renderHeatmap();
}

function renderHeatmap() {
  const grades = state.report.grades.current_full;
  const table = document.createElement("table");
  table.className = "heat";
  const head = document.createElement("tr");
  head.innerHTML = `<th>Question</th>${ARMS.map((arm) => `<th>${ARM_LABEL[arm]}</th>`).join("")}`;
  table.appendChild(head);
  for (const item of state.report.questions) {
    const rowGrades = grades[item.id];
    if (!rowGrades) continue;
    const row = document.createElement("tr");
    const question = document.createElement("td");
    question.className = "q";
    question.textContent = item.question;
    row.appendChild(question);
    for (const arm of ARMS) {
      const cell = document.createElement("td");
      cell.className = `mark ${rowGrades[arm]}`;
      cell.textContent = rowGrades[arm];
      row.appendChild(cell);
    }
    table.appendChild(row);
  }
  const host = $("heatmap");
  host.replaceChildren(table);
}

function renderPipeline() {
  const pipeline = state.report.pipeline;
  const counts = state.report.counts;
  const nodes = [
    ["Corpus", `${counts.docs} runbooks`, `Frozen ${state.report.freeze_date}. ${counts.facts} facts. Docs added later stay out of the adapter.`],
    ["Train pairs", `${counts.train} questions`, pipeline.teacher],
    ["Adapter", `${counts.adapter_facts} facts`, `Keeps every fact a train pair touched. No citations. Freeze text only. Dropped unseen: ${pipeline.unseen_at_train.join(", ")}.`],
    ["Student", `${counts.student_facts} facts`, `Drops long procedures (${pipeline.dropped_long.join(", ")}) and one-off facts (${pipeline.dropped_low_count.join(", ")}).`],
  ];
  const flow = $("flow");
  flow.replaceChildren();
  for (const [title, stat, body] of nodes) {
    const node = document.createElement("article");
    node.className = "node";
    node.innerHTML = `<em>${title}</em><strong></strong><p></p>`;
    node.querySelector("strong").textContent = stat;
    node.querySelector("p").textContent = body;
    flow.appendChild(node);
  }
}

async function loadDecision() {
  const body = state.dirty ? inputsFromForm() : { scenario_id: state.scenarioId };
  const response = await fetch("/v1/decide", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    const detail = await response.json();
    throw new Error(detail.detail || "decide failed");
  }
  const payload = await response.json();
  state.decision = payload.decision;
  fillForm(payload.decision.inputs);
  renderBanner(payload.decision);
  renderTable(payload.decision);
  renderChecks(payload.decision);
  renderMemo(payload.decision.memo_md);
}

function bind() {
  const presets = $("presets");
  for (const scenario of state.report.scenarios) {
    const button = document.createElement("button");
    button.type = "button";
    button.dataset.id = scenario.id;
    button.textContent = PRESET_LABEL[scenario.id] || scenario.id;
    button.addEventListener("click", () => {
      state.scenarioId = scenario.id;
      state.dirty = false;
      loadDecision();
    });
    presets.appendChild(button);
  }
  const change = $("change");
  for (const value of ["stable", "monthly", "weekly"]) {
    const button = document.createElement("button");
    button.type = "button";
    button.dataset.value = value;
    button.textContent = value;
    button.addEventListener("click", () => {
      for (const peer of change.querySelectorAll("button")) peer.setAttribute("aria-pressed", "false");
      button.setAttribute("aria-pressed", "true");
      state.dirty = true;
      loadDecision();
    });
    change.appendChild(button);
  }
  const slo = $("slo");
  for (const value of [80, 200, 2000]) {
    const button = document.createElement("button");
    button.type = "button";
    button.dataset.value = String(value);
    button.textContent = `${value} ms`;
    button.addEventListener("click", () => {
      for (const peer of slo.querySelectorAll("button")) peer.setAttribute("aria-pressed", "false");
      button.setAttribute("aria-pressed", "true");
      state.dirty = true;
      loadDecision();
    });
    slo.appendChild(button);
  }
  $("volume").addEventListener("input", () => {
    $("volume-readout").textContent = volumeFromSlider($("volume").value).toLocaleString("en-US");
  });
  for (const id of ["volume", "citations", "scope", "budget"]) {
    $(id).addEventListener("change", () => {
      state.dirty = true;
      loadDecision();
    });
  }
  $("question").addEventListener("change", () => showQuestion($("question").value));
}

async function main() {
  const params = new URLSearchParams(location.search);
  const shot = SHOTS[params.get("shot")] || null;
  if (shot) document.body.dataset.focus = shot.focus;
  const health = await fetch("/healthz").then((response) => response.json());
  const wrapped = await fetch("/v1/report").then((response) => response.json());
  state.report = wrapped.report;
  $("meta").textContent = `${state.report.domain} · frozen 1 Mar 2026 · ${state.report.counts.questions} questions`;
  $("mode-pill").textContent = health.report_stale ? "Report stale" : "No API key · saved eval";
  $("ports").textContent = `Lumen port: ${health.lumen}. Switchboard port: ${health.switchboard}. Eval stays on the frozen corpus either way.`;
  bind();
  renderQuestions();
  renderPipeline();
  state.scenarioId = shot ? shot.scenario : "weekly-cited";
  await loadDecision();
  const questionId = (shot && shot.question) || "st-refund-window";
  $("question").value = questionId;
  await showQuestion(questionId);
  document.body.dataset.ready = "true";
}

main().catch((error) => {
  $("banner-title").textContent = "The bench did not load";
  $("banner-body").textContent = String(error);
});
