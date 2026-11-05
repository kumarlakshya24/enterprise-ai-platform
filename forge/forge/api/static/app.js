const previewEl = document.querySelector("#preview");
const sandboxEl = document.querySelector("#sandbox");
const titleEl = document.querySelector("#title");
const sayEl = document.querySelector("#say");
const listEl = document.querySelector("#scenarios");

function card(step, side) {
  const node = document.createElement("article");
  node.className = "card";
  if (side === "preview") {
    const preview = step.preview;
    node.innerHTML = `
      <div class="outcome ${preview.would_allow ? "allow" : "deny"}">${preview.would_allow ? "Would allow" : "Would reject"}</div>
      <p class="rule">${preview.risk}</p>
      <p>${preview.note}</p>
      <p class="rule">executed: ${preview.executed}</p>`;
    return node;
  }
  const stdout = step.stdout ? `<pre>${escapeHtml(step.stdout)}</pre>` : "";
  node.innerHTML = `
    <div class="outcome ${step.outcome}">${step.outcome} · ${step.rule}</div>
    <p class="rule">spawned ${step.spawned} · ${step.duration_ms} ms · audit #${step.audit_seq ?? "–"}</p>
    ${stdout}
    <p>${(step.reasons || []).join(" · ")}</p>`;
  return node;
}

function escapeHtml(value) {
  return value.replace(/[&<>]/g, (ch) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[ch]));
}

function render(data) {
  titleEl.textContent = data.title || "Custom call";
  sayEl.textContent = data.say || "Custom call through the same guard and audit path.";
  previewEl.innerHTML = "";
  sandboxEl.innerHTML = "";
  if (data.kind === "regression") {
    const pass = data.demo_pass;
    sandboxEl.appendChild(Object.assign(document.createElement("article"), {
      className: "card",
      innerHTML: `<div class="outcome ${pass ? "allow" : "fail"}">${pass ? "Gate refused the weaker policy" : "Gate did not fire"}</div>
        <pre>${escapeHtml((data.checks || []).map((item) => `${item.ok ? "PASS" : "FAIL"} ${item.id}\n${item.detail}`).join("\n\n"))}</pre>`,
    }));
    previewEl.appendChild(Object.assign(document.createElement("article"), {
      className: "card",
      innerHTML: `<div class="outcome deny">Would allow</div><p>A raw interpreter has no regression gate. The candidate policy would grant pathlib and a larger code cap. Forge does not activate it.</p>`,
    }));
    return;
  }
  for (const step of data.steps || []) {
    previewEl.appendChild(card(step, "preview"));
    sandboxEl.appendChild(card(step, "sandbox"));
  }
}

async function runScenario(id) {
  document.querySelectorAll(".scenario").forEach((button) => {
    button.classList.toggle("active", button.dataset.id === id);
  });
  sandboxEl.innerHTML = "<p class='fine'>Running…</p>";
  const response = await fetch("/run", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ scenario_id: id }),
  });
  render(await response.json());
  refreshHealth();
}

async function refreshHealth() {
  const health = await fetch("/healthz").then((response) => response.json());
  document.querySelector("#policy").textContent = health.policy;
  document.querySelector("#audit-pill").textContent = health.audit_ok ? `audit ${health.audit_events}` : "audit broken";
}

async function init() {
  const payload = await fetch("/scenarios").then((response) => response.json());
  for (const scenario of payload.scenarios) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "scenario";
    button.dataset.id = scenario.id;
    button.innerHTML = `<strong>${scenario.title}</strong><span>${scenario.id}</span>`;
    button.addEventListener("click", () => runScenario(scenario.id));
    listEl.appendChild(button);
  }
  await refreshHealth();
  const auto = new URLSearchParams(location.search).get("auto");
  if (auto) runScenario(auto);
}

document.querySelector("#verify").addEventListener("click", async () => {
  const report = await fetch("/audit/verify").then((response) => response.json());
  alert(report.ok ? `Audit chain OK (${report.events} events)` : `Audit broken at ${report.broken_seq} (${report.reason})`);
});

document.querySelector("#reset").addEventListener("click", async () => {
  await fetch("/session/reset", { method: "POST" });
  refreshHealth();
});

document.querySelector("#custom").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = new FormData(event.target);
  const tool = form.get("tool");
  const text = String(form.get("text") || "");
  const body = { tool };
  if (tool === "python" || tool === "shell") body.code = text;
  else body.path = text || ".";
  if (tool === "write_file") {
    body.path = "notes/ui.txt";
    body.content = text;
  }
  const response = await fetch("/run", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
  render(await response.json());
  refreshHealth();
});

init();
