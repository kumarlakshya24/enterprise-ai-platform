"use strict";
// Aegis demo UI. Plain DOM, no framework. All model output is rendered with textContent, never innerHTML.

const state = { user: "avery", tokens: {}, scenarios: [], bundle: null };
const $ = (id) => document.getElementById(id);

function el(tag, attrs = {}, ...children) {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") n.className = v;
    else if (k === "on") for (const [ev, fn] of Object.entries(v)) n.addEventListener(ev, fn);
    else n.setAttribute(k, v);
  }
  for (const c of children.flat()) if (c !== null && c !== undefined) n.append(c instanceof Node ? c : String(c));
  return n;
}
const badge = (text, kind) => el("span", { class: `badge ${kind || text}` }, text);
const pretty = (o) => JSON.stringify(o, null, 2);

async function token(user) {
  if (state.tokens[user]) return state.tokens[user];
  const r = await fetch("/demo/login", { method: "POST", headers: { "content-type": "application/json" },
    body: JSON.stringify({ username: user }) });
  if (!r.ok) throw new Error(`sign-in failed (${r.status})`);
  state.tokens[user] = (await r.json()).access_token;
  return state.tokens[user];
}

async function api(path, { method = "GET", body, user = state.user } = {}) {
  const headers = { authorization: `Bearer ${await token(user)}` };
  if (body !== undefined) headers["content-type"] = "application/json";
  const r = await fetch(path, { method, headers, body: body === undefined ? undefined : JSON.stringify(body) });
  let data = null;
  try { data = await r.json(); } catch { data = null; }
  return { ok: r.ok, status: r.status, data };
}

function errText(res) {
  const d = res.data && res.data.detail;
  if (d && typeof d === "object") return `${res.status} ${d.code || ""}: ${d.message || ""}`;
  return `${res.status} ${typeof d === "string" ? d : "request failed"}`;
}

// ------------------------------------------------------------------ identity

async function loadUsers() {
  const users = await (await fetch("/demo/users")).json();
  const sel = $("user");
  for (const u of users) {
    const label = `${u.name} (${u.roles.filter((r) => r !== "employee").join(", ") || "employee"})` +
      (u.sso ? "" : " [password login]") + (u.tenant_id !== "acme" ? ` [tenant ${u.tenant_id}]` : "");
    sel.append(el("option", { value: u.username }, label));
  }
  sel.value = state.user;
  sel.addEventListener("change", async () => { state.user = sel.value; await whoami(); });
  await whoami();
}

async function whoami() {
  const res = await api("/demo/whoami");
  const w = $("whoami");
  w.textContent = res.ok ? `tenant ${res.data.tenant_id} · ${res.data.permissions.join(", ")}`
    : `rejected by gateway: ${errText(res)}`;
  w.className = res.ok ? "muted small" : "small err";
}

// ------------------------------------------------------------------ evidence helpers

async function evidence() {
  const res = await api("/demo/evidence");
  return res.ok ? res.data : { external_llm: [], local_llm: [], sandbox: { outbox: [], egress: [], shares: [] } };
}
const lastAt = (list) => (list.length ? list[list.length - 1].at + list.length : "");
function userContent(entry) {
  const msgs = entry.messages.filter((m) => m.role === "user");
  return msgs.length ? msgs[msgs.length - 1].content : "";
}

// ------------------------------------------------------------------ chat side by side

function fillScenarioSelect(selId, inputId, expectId, kind) {
  const sel = $(selId);
  for (const s of state.scenarios.filter((x) => x.kind === kind)) {
    sel.append(el("option", { value: s.id }, `Scenario ${s.number}: ${s.title}`));
  }
  const apply = () => {
    const s = state.scenarios.find((x) => x.id === sel.value);
    $(inputId).value = s.input;
    $(expectId).textContent = `Expected: ${s.expect}`;
  };
  sel.addEventListener("change", apply);
  apply();
}

async function runChat() {
  const message = $("chat-input").value;
  for (const id of ["u-sent", "u-answer", "p-sent", "p-answer"]) $(id).textContent = "…";
  for (const id of ["p-reasons", "p-entities", "p-audit", "p-badges"]) $(id).replaceChildren();
  $("p-classifier").textContent = "";

  let ev = await evidence();
  let before = lastAt(ev.external_llm);
  const u = await api("/demo/unprotected/chat", { method: "POST", body: { message } });
  ev = await evidence();
  if (u.ok && lastAt(ev.external_llm) !== before) {
    $("u-sent").textContent = userContent(ev.external_llm[ev.external_llm.length - 1]);
    $("u-answer").textContent = u.data.answer;
  } else {
    $("u-sent").textContent = u.ok ? message : errText(u);
    $("u-answer").textContent = u.ok ? u.data.answer : "";
  }

  before = lastAt(ev.external_llm);
  const p = await api("/chat", { method: "POST", body: { message } });
  if (!p.ok) { $("p-sent").textContent = errText(p); $("p-answer").textContent = ""; return; }
  const b = p.data;
  const d = b.decision;
  ev = await evidence();
  const external = lastAt(ev.external_llm) !== before;
  $("p-badges").append(badge(b.status), badge(d.route), badge(`context ${d.context_label}`, "neutral"),
    badge(`rule ${d.rule_id}`, "neutral"), badge(`policy ${d.policy_version}`, "neutral"));
  if (b.sent_to_llm) {
    $("p-sent").textContent = `[${b.sent_to_llm.location} model: ${b.sent_to_llm.model}]` +
      (external ? "  (third party log shows exactly this)" : "  (third party received nothing)") + "\n\n" + b.sent_to_llm.prompt;
  } else {
    $("p-sent").textContent = "Nothing was sent to any model.";
  }
  $("p-answer").textContent = b.answer;
  for (const r of d.reasons) $("p-reasons").append(el("li", {}, r));
  const base = d.regex_only_baseline;
  $("p-reasons").append(el("li", { class: "muted" },
    `regex-only DLP would have: ${base.route} (${base.entities} entities, ` +
    `${base.sends_to_external_llm ? "sent to the external LLM" : "not sent"})`));
  if (d.classifier) {
    const f = d.classifier.top_features.map((x) => `${x.feature} (${x.weight})`).join(", ");
    $("p-classifier").textContent = `Classifier ${d.classifier.label} ${d.classifier.confidence}` +
      (d.classifier.escalated_from ? ` (escalated from ${d.classifier.escalated_from})` : "") + ` · top features: ${f || "none"}`;
  }
  for (const e of b.entities) {
    $("p-entities").append(el("tr", {}, el("td", {}, e.entity_type), el("td", { class: "mono" }, e.placeholder || ""),
      el("td", {}, e.detector), el("td", {}, e.confidence), el("td", {}, e.action)));
  }
  if (!b.entities.length) $("p-entities").append(el("tr", {}, el("td", { colspan: "5", class: "muted" }, "none detected")));
  const audit = await api(`/audit?session_id=${encodeURIComponent(b.session_id)}&limit=20`, { user: "sam" });
  const ids = new Set(b.audit_event_ids);
  if (audit.ok) {
    for (const e of audit.data.events.filter((x) => ids.has(x.event_id)).reverse()) {
      $("p-audit").append(el("li", {}, `#${e.seq} ${e.event_type} ${e.route || ""} ${e.outcome || ""} hash ${e.hash.slice(0, 12)}…`));
    }
  }
  const l = b.latency_ms;
  $("p-latency").textContent = `gateway overhead ${l.gateway_overhead_ms} ms (dlp ${l.dlp_ms}, tokenize ${l.tokenize_ms}, ` +
    `classify ${l.classify_ms}, policy ${l.policy_ms}, restore ${l.restore_ms ?? "-"})`;
}

// ------------------------------------------------------------------ agent side by side

function stepItem(s) {
  const li = el("li");
  if (s.type === "final_answer") { li.append("final answer"); return li; }
  if (s.type === "approved_execution") { li.append(`approved execution: ${pretty(s.result)}`); return li; }
  li.append(el("strong", {}, s.tool), " ", el("span", { class: "mono small" }, JSON.stringify(s.arguments)));
  if (s.guard) {
    li.append(" ", badge(s.guard.verdict));
    for (const r of s.guard.reasons) li.append(el("div", { class: "rule" }, `${r.rule}: ${r.message}`));
  } else if (s.executed) {
    li.append(" ", badge("executed", "block"));
  }
  if (s.result && s.result.injection && s.result.injection.flagged) {
    li.append(el("div", { class: "err small" }, `prompt injection detected (score ${s.result.injection.score}): ` +
      s.result.injection.signals.map((x) => x.id).join(", ") + " · session tainted"));
  }
  return li;
}

const sandboxView = (ev, mode) => pretty({
  outbox: ev.sandbox.outbox.filter((x) => x.mode === mode).slice(-3),
  egress: ev.sandbox.egress.filter((x) => x.mode === mode).slice(-3),
});

async function runAgent() {
  const task = $("agent-input").value;
  for (const id of ["ua-steps", "pa-steps", "pa-badges"]) $(id).replaceChildren();
  for (const id of ["ua-evidence", "pa-task", "pa-final", "pa-evidence"]) $(id).textContent = "…";
  await api("/demo/reset", { method: "POST" });
  const u = await api("/demo/unprotected/agent", { method: "POST", body: { task } });
  if (u.ok) for (const s of u.data.steps) $("ua-steps").append(stepItem(s));
  let ev = await evidence();
  $("ua-evidence").textContent = u.ok ? sandboxView(ev, "unprotected") : errText(u);

  const p = await api("/agent/run", { method: "POST", body: { task } });
  if (!p.ok) { $("pa-final").textContent = errText(p); return; }
  const r = p.data;
  $("pa-badges").append(badge(r.status), badge(r.decision.route), badge(`run ${r.id.slice(0, 8)}`, "neutral"));
  $("pa-task").textContent = r.task_sent_to_llm;
  for (const s of r.steps) $("pa-steps").append(stepItem(s));
  $("pa-final").textContent = r.final_answer + (r.approval_id ? "\n\nSwitch to Morgan and open the Approvals tab." : "");
  ev = await evidence();
  $("pa-evidence").textContent = sandboxView(ev, "protected");
}

// ------------------------------------------------------------------ approvals

async function loadApprovals() {
  const box = $("approvals-list");
  box.replaceChildren();
  const res = await api("/approvals?status=pending");
  if (!res.ok) { box.append(el("p", { class: "err" }, errText(res))); return; }
  if (!res.data.approvals.length) box.append(el("p", { class: "muted" }, "No pending approvals visible to you."));
  for (const a of res.data.approvals) {
    const out = el("pre", { class: "box" });
    const act = (verb) => async () => {
      const r = await api(`/approvals/${a.id}/${verb}`, { method: "POST", body: { note: `${verb} from demo UI` } });
      out.textContent = r.ok ? pretty({ status: r.data.status, result: r.data.result }) : errText(r);
      const ev = await evidence();
      $("outbox").textContent = pretty(ev.sandbox.outbox.slice(-3));
    };
    box.append(el("div", { class: "card" },
      el("div", {}, badge(a.status), " ", el("strong", {}, a.summary.tool || a.kind), " to ",
        (a.summary.recipient_domains || []).join(", ") || "-", el("span", { class: "muted small" },
          ` · requested by ${a.requester_id} · expires ${a.expires_at}`)),
      el("pre", { class: "box" }, pretty(a.summary.arguments_preview || a.summary)),
      el("div", { class: "controls" },
        el("button", { class: "ok", on: { click: act("approve") } }, "Approve"),
        el("button", { class: "no", on: { click: act("deny") } }, "Deny")),
      out));
  }
  const ev = await evidence();
  $("outbox").textContent = pretty(ev.sandbox.outbox.slice(-3));
}

// ------------------------------------------------------------------ policy console

const ROUTES = ["allow", "redact_and_continue", "require_approval", "local_only", "block"];
const ACTIONS = ["tokenize", "redact", "block", "allow"];
function opts(sel, values) { sel.replaceChildren(...values.map((v) => el("option", { value: v }, v))); }

async function loadPolicy() {
  $("pol-result").textContent = "";
  const res = await api("/admin/policies");
  if (!res.ok) { $("pol-version").textContent = `${errText(res)} (switch to Sam)`; state.bundle = null; return; }
  state.bundle = res.data.bundle;
  const b = state.bundle.base;
  opts($("pol-conf"), ROUTES); opts($("pol-restr"), ROUTES); opts($("pol-int"), ROUTES);
  opts($("pol-card"), ACTIONS); opts($("pol-org"), ACTIONS);
  $("pol-conf").value = b.routing.CONFIDENTIAL; $("pol-restr").value = b.routing.RESTRICTED;
  $("pol-int").value = b.routing.INTERNAL;
  $("pol-card").value = b.entities.CREDIT_CARD.action; $("pol-org").value = b.entities.ORG.action;
  $("pol-clf").checked = b.classifier.enabled; $("pol-inj").value = b.injection.threshold;
  $("pol-allow").value = b.tools.allowed_email_domains.join(", ");
  $("pol-block").value = b.tools.blocked_email_domains.join(", ");
  $("pol-version").textContent = `active ${res.data.policy_version} · ${res.data.history.length} revisions`;
}

async function applyPolicy() {
  if (!state.bundle) { $("pol-result").textContent = "Load the policy as Sam first."; return; }
  const bundle = JSON.parse(JSON.stringify(state.bundle));
  const b = bundle.base;
  b.routing.CONFIDENTIAL = $("pol-conf").value; b.routing.RESTRICTED = $("pol-restr").value;
  b.routing.INTERNAL = $("pol-int").value;
  b.entities.CREDIT_CARD.action = $("pol-card").value; b.entities.ORG.action = $("pol-org").value;
  b.classifier.enabled = $("pol-clf").checked; b.injection.threshold = Number($("pol-inj").value);
  const split = (s) => s.split(",").map((x) => x.trim()).filter(Boolean);
  b.tools.allowed_email_domains = split($("pol-allow").value);
  b.tools.blocked_email_domains = split($("pol-block").value);
  $("pol-result").textContent = "Running the regression gate…";
  const res = await api("/admin/policies", { method: "PUT", body: { bundle, note: $("pol-note").value || "demo console" } });
  if (res.ok) {
    $("pol-result").textContent = `ACTIVATED ${res.data.policy_version}\nscopes checked: ${res.data.gate.scopes_checked.join(", ")}\n` +
      `protection regressions: 0 · utility warnings: ${res.data.gate.utility_regressions.length}`;
    await loadPolicy();
  } else if (res.status === 409) {
    const rep = res.data.detail.report;
    $("pol-result").textContent = `REFUSED: ${res.data.detail.message}\n\n` + rep.protection_regressions.slice(0, 15)
      .map((x) => `${x.scope} · ${x.case} (${x.category}) · ` + (x.reason || ((x.leaked_entities || []).length
        ? `would leak ${x.leaked_entities.join(", ")}` : x.verdict ? `verdict ${x.verdict}, expected ${x.expected}` : "")))
      .join("\n");
  } else {
    $("pol-result").textContent = errText(res);
  }
}

// ------------------------------------------------------------------ audit

async function loadAudit() {
  const rows = $("audit-rows");
  rows.replaceChildren();
  const res = await api("/audit?limit=150");
  if (!res.ok) { rows.append(el("tr", {}, el("td", { colspan: "6", class: "err" }, `${errText(res)} (switch to Sam)`))); return; }
  for (const e of res.data.events) {
    const det = JSON.stringify(e.details);
    rows.append(el("tr", {}, el("td", {}, e.seq), el("td", { class: "small" }, e.ts.slice(11, 19)),
      el("td", {}, e.user_id), el("td", {}, e.event_type), el("td", {}, [e.route, e.outcome].filter(Boolean).join(" / ")),
      el("td", { class: "mono small" }, det.length > 220 ? det.slice(0, 217) + "…" : det)));
  }
}

async function verifyAudit() {
  const res = await api("/audit/verify");
  const out = $("audit-verify-result");
  out.textContent = res.ok ? (res.data.ok ? `chain intact: ${res.data.checked} events, head ${res.data.head_hash.slice(0, 12)}…`
    : `TAMPERING DETECTED at seq ${res.data.first_bad_seq}`) : errText(res);
  out.className = res.ok && res.data.ok ? "small" : "small err";
}

// ------------------------------------------------------------------ wiring

function tabs() {
  for (const t of document.querySelectorAll(".tab")) {
    t.addEventListener("click", () => {
      document.querySelectorAll(".tab").forEach((x) => x.classList.toggle("active", x === t));
      document.querySelectorAll(".panel").forEach((p) => p.classList.toggle("active", p.id === `tab-${t.dataset.tab}`));
      if (t.dataset.tab === "approvals") loadApprovals();
      if (t.dataset.tab === "policy") loadPolicy();
      if (t.dataset.tab === "audit") loadAudit();
    });
  }
}

async function main() {
  tabs();
  state.scenarios = await (await fetch("/demo/scenarios")).json();
  fillScenarioSelect("chat-scenario", "chat-input", "chat-expect", "chat");
  fillScenarioSelect("agent-scenario", "agent-input", "agent-expect", "agent");
  $("chat-run").addEventListener("click", runChat);
  $("agent-run").addEventListener("click", runAgent);
  $("reset").addEventListener("click", async () => { await api("/demo/reset", { method: "POST" }); });
  $("approvals-refresh").addEventListener("click", loadApprovals);
  $("pol-apply").addEventListener("click", applyPolicy);
  $("pol-reload").addEventListener("click", loadPolicy);
  $("audit-refresh").addEventListener("click", loadAudit);
  $("audit-verify").addEventListener("click", verifyAudit);
  await loadUsers();
}

main();
