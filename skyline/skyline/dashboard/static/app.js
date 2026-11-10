const ORDER = ["network", "security", "switchboard", "lumen", "log-archive", "finops"];
const VOLUMES = [1000, 10000, 100000, 1000000];
const BREAKS = [
  ["clean", "Clean"],
  ["open-sg", "Open the security group"],
  ["shared-cmk", "Share one CMK"],
  ["drop-guardrail", "Drop the guardrail"],
  ["public-route", "Add an internet route"],
  ["lumen-bedrock", "Let Lumen call Bedrock"],
  ["wildcard-kms", "Star principal on a key"],
  ["share-bedrock-dns", "Share Bedrock DNS"],
];

const state = { mutation: "clean", rpd: 100000 };

function el(tag, attrs, kids) {
  const node = document.createElement(tag);
  Object.entries(attrs || {}).forEach(([key, value]) => {
    if (key === "class") node.className = value;
    else if (key === "html") node.innerHTML = value;
    else node.setAttribute(key, value);
  });
  (kids || []).forEach((kid) => node.append(kid instanceof Node ? kid : document.createTextNode(String(kid))));
  return node;
}

function money(value) {
  const number = Number(value);
  if (number === 0) return "$0.00";
  const abs = Math.abs(number);
  const digits = abs >= 1 ? 2 : abs >= 0.01 ? 4 : 6;
  const body = abs.toLocaleString("en-US", { minimumFractionDigits: digits, maximumFractionDigits: digits });
  return `${number < 0 ? "-" : ""}$${body}`;
}

function volumeLabel(rpd) {
  if (rpd >= 1000000) return "1,000,000 / day";
  if (rpd >= 1000) return `${(rpd / 1000).toLocaleString("en-US")}k / day`;
  return `${rpd} / day`;
}

async function load() {
  const response = await fetch(`/api/state?mutation=${state.mutation}&rpd=${state.rpd}`);
  if (!response.ok) throw new Error(await response.text());
  render(await response.json());
}

function render(data) {
  renderPills(data);
  renderMetrics(data);
  renderSkyline(data);
  renderVolume();
  renderFinops(data);
  renderGuardrail(data);
  renderMutations();
  renderGate(data);
  renderPillars(data);
}

function renderPills(data) {
  const pills = document.querySelector("#pills");
  pills.replaceChildren(
    el("span", { class: "pill" }, [data.region]),
    el("span", { class: "pill" }, [`${data.accounts.length} accounts`]),
    el("span", { class: "pill" }, [data.shortHash]),
    el("span", { class: "pill" }, [data.mutation === "clean" ? "clean synth" : data.mutation]),
  );
}

function renderMetrics(data) {
  const fin = data.finops;
  const passed = data.invariants.filter((row) => row.ok).length;
  const delta = Number(fin.naive_total) - Number(fin.skyline_total);
  const items = [
    ["Per 1,000", money(fin.skyline_total), `at ${data.finops.requests_per_day.toLocaleString("en-US")} requests/day`],
    ["Versus always-premium", money(fin.naive_total), delta >= 0 ? `${money(delta)} cheaper on Skyline` : `${money(-delta)} more at this volume`],
    ["Tenant keys", String(data.kms.length), "one CMK each, with an encryption context"],
    ["Gate", `${passed}/${data.invariants.length}`, data.violationCount ? "a planted break is failing" : "clean synth"],
  ];
  const root = document.querySelector("#metrics");
  root.replaceChildren(
    ...items.map(([label, value, note]) =>
      el("article", { class: "metric" }, [el("span", {}, [label]), el("strong", {}, [value]), el("em", {}, [note])]),
    ),
  );
}

function renderSkyline(data) {
  const byName = Object.fromEntries(data.accounts.map((account) => [account.name, account]));
  const max = Math.max(...data.accounts.map((account) => account.resources));
  const width = 640;
  const height = 250;
  const gap = 18;
  const slot = (width - gap * (ORDER.length - 1)) / ORDER.length;
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
  svg.setAttribute("class", "skyline-svg");
  svg.setAttribute("role", "img");
  svg.setAttribute("aria-label", "Six accounts as a skyline. Security is the tallest.");

  const ground = document.createElementNS("http://www.w3.org/2000/svg", "line");
  ground.setAttribute("x1", "0");
  ground.setAttribute("x2", String(width));
  ground.setAttribute("y1", "214");
  ground.setAttribute("y2", "214");
  ground.setAttribute("stroke", "rgba(226,176,106,0.45)");
  svg.append(ground);

  ORDER.forEach((name, index) => {
    const account = byName[name];
    const failed = data.invariants.some(
      (row) => !row.ok && row.findings.some((finding) => finding.startsWith(`${name}/`)),
    );
    const h = 70 + (account.resources / max) * 130;
    const x = index * (slot + gap);
    const y = 214 - h;
    const rect = document.createElementNS("http://www.w3.org/2000/svg", "rect");
    rect.setAttribute("x", String(x));
    rect.setAttribute("y", String(y));
    rect.setAttribute("width", String(slot));
    rect.setAttribute("height", String(h));
    rect.setAttribute("rx", "4");
    rect.setAttribute("fill", failed ? "rgba(255,140,140,0.16)" : "rgba(226,176,106,0.08)");
    rect.setAttribute("stroke", failed ? "#ffb4b4" : "rgba(226,176,106,0.7)");
    svg.append(rect);
    const windows = Math.min(12, Math.max(3, account.interfaceEndpoints + account.cmks + account.services));
    for (let i = 0; i < windows; i += 1) {
      const win = document.createElementNS("http://www.w3.org/2000/svg", "rect");
      const col = i % 3;
      const row = Math.floor(i / 3);
      win.setAttribute("class", failed ? "window bad" : row % 2 ? "window dim" : "window");
      win.setAttribute("x", String(x + 10 + col * 16));
      win.setAttribute("y", String(y + 12 + row * 16));
      win.setAttribute("width", "8");
      win.setAttribute("height", "8");
      win.setAttribute("rx", "1");
      svg.append(win);
    }
    const label = document.createElementNS("http://www.w3.org/2000/svg", "text");
    label.setAttribute("class", "building-label");
    label.setAttribute("x", String(x));
    label.setAttribute("y", "234");
    label.textContent = name;
    svg.append(label);
  });

  document.querySelector("#skyline-svg").replaceChildren(svg);
  const path = document.querySelector("#path");
  path.replaceChildren(...data.path.map((hop) => el("li", {}, [hop])));
}

function renderVolume() {
  const root = document.querySelector("#volume");
  root.replaceChildren(
    ...VOLUMES.map((rpd) => {
      const button = el("button", { type: "button", "aria-pressed": String(rpd === state.rpd) }, [volumeLabel(rpd)]);
      button.addEventListener("click", () => {
        state.rpd = rpd;
        load().catch(showError);
      });
      return button;
    }),
  );
}

function renderFinops(data) {
  const fin = data.finops;
  const delta = Number(fin.naive_total) - Number(fin.skyline_total);
  const cheaper = delta >= 0;
  const max = Math.max(
    ...fin.bars.flatMap((bar) => [Number(bar.skyline_usd), Number(bar.naive_usd)]),
    0.000001,
  );
  const body = document.querySelector("#finops-body");
  const figure = el("div", { class: "big" }, [
    el("div", {}, [
      el("div", { class: "figure" }, [money(fin.skyline_total)]),
      el("p", { class: "note" }, ["Skyline, fully loaded, this volume"]),
    ]),
    el("div", { class: cheaper ? "delta good" : "delta bad" }, [
      cheaper ? `${money(delta)} under the naive path` : `${money(-delta)} over the naive path`,
    ]),
  ]);
  const bars = el("div", { class: "bars" });
  fin.bars.forEach((bar) => {
    const sky = el("i", { class: "sky" });
    const naive = el("i", { class: "naive" });
    sky.style.width = `${(Number(bar.skyline_usd) / max) * 100}%`;
    naive.style.width = `${(Number(bar.naive_usd) / max) * 100}%`;
    bars.append(
      el("div", { class: "bar-row" }, [
        el("span", {}, [bar.id]),
        el("div", { class: "track" }, [sky, naive]),
      ]),
    );
  });
  const table = el("table", {}, [
    el("thead", {}, [
      el("tr", {}, [el("th", {}, ["Line"]), el("th", { class: "num" }, ["Skyline"]), el("th", { class: "num" }, ["Naive"])]),
    ]),
    el(
      "tbody",
      {},
      fin.lines.map((line) =>
        el("tr", {}, [
          el("td", {}, [line.label]),
          el("td", { class: "num" }, [money(line.skyline_usd)]),
          el("td", { class: "num" }, [money(line.naive_usd)]),
        ]),
      ),
    ),
  ]);
  const cross = fin.crossover_rpd
    ? `Skyline's unit cost is the lower one above about ${Number(fin.crossover_rpd).toLocaleString("en-US")} requests/day.`
    : "On this price list the naive path stays cheaper.";
  const endpoint = fin.endpoint_vs_nat_rpd
    ? `Endpoints are ${money(fin.endpoint_daily)}/day against ${money(fin.nat_daily)}/day for one NAT. Bytes would not pay that back below about ${Number(fin.endpoint_vs_nat_rpd).toLocaleString("en-US")} requests/day.`
    : `Endpoints are ${money(fin.endpoint_daily)}/day against ${money(fin.nat_daily)}/day for one NAT. The per-GB gap does not pay the hourly premium back.`;
  const avoided = `Scanning retrieved context as well would price the guardrail at ${money(fin.guardrail_full_prompt_per_1k)} per 1,000 instead of ${money(fin.guardrail_per_1k)}.`;
  const legend = el("p", { class: "note" }, ["Copper is Skyline. Slate is always-Sonnet plus one NAT."]);
  body.replaceChildren(figure, bars, legend, table, el("p", { class: "note" }, [cross]), el("p", { class: "note" }, [endpoint]), el("p", { class: "note" }, [avoided]));
}

function renderGuardrail(data) {
  const guard = data.guardrail;
  const root = document.querySelector("#guardrail-body");
  const head = el("p", { class: "note" }, [
    `${guard.enforced_ok}/${guard.enforced} enforced cases match. ${guard.gaps} case is a known gap: ${guard.blind_filters.join(", ")} are on the resource and not scored. Stub mean ${data.bench.mean_us.toFixed(1)} µs.`,
  ]);
  const rows = guard.rows.map((row) => {
    const tag = row.gap ? "gap" : row.action === "ALLOW" ? "allow" : "block";
    const label = row.gap ? "GAP" : row.action;
    return el("div", { class: "case" }, [
      el("span", { class: `tag ${tag}` }, [label]),
      el("p", { class: "text" }, [row.text]),
      el("span", { class: "mono" }, [row.filter || row.gap || ""]),
    ]);
  });
  root.replaceChildren(head, ...rows);
}

function renderMutations() {
  const root = document.querySelector("#mutations");
  root.replaceChildren(
    ...BREAKS.map(([id, label]) => {
      const button = el("button", { type: "button", "aria-pressed": String(id === state.mutation) }, [label]);
      button.addEventListener("click", () => {
        state.mutation = id;
        load().catch(showError);
      });
      return button;
    }),
  );
}

function renderGate(data) {
  const root = document.querySelector("#gate-body");
  const rows = [...data.invariants].sort((a, b) => Number(a.ok) - Number(b.ok));
  const list = rows.map((row) =>
    el("div", { class: "rule" }, [
      el("span", { class: row.ok ? "tag allow" : "tag block" }, [row.ok ? "PASS" : "FAIL"]),
      el("p", {}, [row.title]),
      el("span", { class: "mono" }, [row.rule]),
    ]),
  );
  const failed = data.invariants.filter((row) => !row.ok);
  const findings = failed.flatMap((row) => row.findings).slice(0, 6);
  const children = [...list];
  if (findings.length) children.push(el("pre", { class: "finding" }, [findings.join("\n")]));
  if (data.diff.count) {
    const lines = data.diff.changes.map((change) => `${change.op}  ${change.path}\n  ${change.before}  →  ${change.after}`);
    children.push(el("pre", { class: "diff" }, [`${data.diff.count} change(s) against the clean synth\n\n${lines.join("\n")}`]));
  }
  root.replaceChildren(...children);
}

function renderPillars(data) {
  const root = document.querySelector("#pillar-grid");
  root.replaceChildren(
    ...data.pillars.map((pillar) =>
      el("article", { class: "pillar" }, [
        el("h3", {}, [pillar.title]),
        el("p", {}, [pillar.summary]),
        el("p", { class: "gap" }, [`Gap: ${pillar.gap}`]),
      ]),
    ),
  );
}

function showError(error) {
  document.querySelector("#metrics").replaceChildren(el("p", { class: "note" }, [String(error)]));
}

load().catch(showError);
