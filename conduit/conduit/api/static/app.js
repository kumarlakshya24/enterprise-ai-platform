const $ = (id) => document.getElementById(id);

function esc(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;");
}

function markTokens(text) {
  return esc(text).replaceAll(
    /\[(PERSON:[a-z0-9-]+|EMAIL|PHONE|CARD|SSN|erased)\]/g,
    "<mark>[$1]</mark>",
  );
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function api(path, options) {
  const response = await fetch(path, {
    headers: { "content-type": "application/json" },
    ...options,
  });
  const body = await response.json();
  if (!response.ok) {
    throw new Error(body.error || response.statusText);
  }
  return body;
}

function showError(error) {
  const banner = $("banner");
  banner.hidden = false;
  banner.textContent = error.message || String(error);
}

function clearError() {
  $("banner").hidden = true;
}

function render(status) {
  $("p50").textContent = `${Number(status.lag_ms.p50).toFixed(2)} ms`;
  $("p95").textContent = `${Number(status.lag_ms.p95).toFixed(2)} ms`;
  $("behind").textContent = String(status.lag_events);
  $("head-label").textContent = `log head ${status.log_head} · offset ${status.consumer_offset}`;
  $("alias").textContent = status.alias.name;
  $("alias-model").textContent = status.alias.model_version;
  $("search-model").textContent = status.alias.model_version;
  const small = status.projection.usd_per_million_docs["text-embedding-3-small"];
  $("cost").textContent = small == null ? "—" : `$${Number(small).toFixed(2)}`;
  $("quarantine").textContent = `quarantine ${status.quarantine}`;
  $("reuse").textContent = `Embeddings computed ${status.embed_calls} · reused ${status.embed_reused}`;
  $("stage-alias").textContent = status.alias.name;

  const forgotten = new Set(status.subjects.filter((subject) => subject.tombstoned).map((subject) => subject.id));
  const log = $("log");
  log.innerHTML = status.events
    .map((event) => {
      const chips = (event.subject_ids || [])
        .filter((id) => !forgotten.has(id))
        .map((id) => `<span class="chip">${esc(id.replace("subj-", ""))}</span>`)
        .join("");
      return `<li><span class="seq">${String(event.seq).padStart(2, "0")}</span><span class="op ${esc(event.op)}">${esc(event.op)}</span><b>${esc(event.title)}</b><span class="chips">${chips}<span class="seq">v${esc(event.doc_version)}</span></span></li>`;
    })
    .join("");

  if (status.preview) {
    $("raw").textContent = status.preview.raw;
    $("redacted").innerHTML = markTokens(status.preview.redacted);
  } else if (status.proof && status.proof.verified) {
    $("raw").textContent = "Raw preview cleared. The forgotten subject's text is no longer held for display.";
    $("redacted").textContent = "The index and the log were scrubbed. Replay reads the scrubbed log.";
  }

  const cards = $("gen-cards");
  const generations = status.generations.length
    ? status.generations
    : [];
  cards.innerHTML = generations
    .map((gen) => {
      const role = gen.read ? "SERVING READS" : gen.state.toUpperCase();
      return `<article class="gen ${esc(gen.name)} ${gen.read ? "read" : ""}">
        <div class="name">${esc(gen.name)}</div>
        <div class="role">${esc(role)}</div>
        <div class="meta">${esc(gen.model_version)} · ${esc(gen.dim)}-d · ${esc(gen.chunks)} chunks · ${esc(gen.docs)} docs · hw ${esc(gen.high_water)}</div>
      </article>`;
    })
    .join("");

  const migration = status.migration;
  const source = Number(migration.source_high_water || 0);
  const target = Number(migration.target_high_water || 0);
  const pct = source > 0 ? Math.min(100, Math.round((target / source) * 100)) : migration.state === "idle" ? 0 : 0;
  $("mig-bar").style.width = `${migration.state === "ready_to_swap" ? 100 : pct}%`;
  if (migration.state === "idle") {
    $("mig-note").textContent = `Read alias is ${status.alias.name} on ${status.alias.model_version}. No migration in progress.`;
  } else if (migration.state === "ready_to_swap") {
    $("mig-note").textContent = `${migration.target} on the new model has caught the log. Swap moves reads. Roll back is still available after.`;
  } else {
    $("mig-note").textContent = `Dual-write ${migration.source} → ${migration.target}. Shadow high water ${target} of ${source}. New events land in both once the shadow is contiguous.`;
  }

  const select = $("subject");
  const previous = select.value;
  select.innerHTML = status.subjects
    .map((subject) => {
      const suffix = subject.tombstoned ? " · forgotten" : ` · ${subject.chunks} chunks`;
      return `<option value="${esc(subject.id)}">${esc(subject.name)}${esc(suffix)}</option>`;
    })
    .join("");
  if (previous) select.value = previous;

  const proof = status.proof;
  const stamp = $("stamp");
  if (!proof) {
    stamp.textContent = "no request";
    stamp.className = "stamp";
    $("proof").innerHTML = `
      <div><dt>Chunks removed</dt><dd>—</dd></div>
      <div><dt>Links remaining</dt><dd>—</dd></div>
      <div><dt>Email in the index</dt><dd>—</dd></div>
      <div><dt>Email in the log</dt><dd>—</dd></div>`;
    $("proof-note").textContent =
      "Erasure writes the tombstone first, then deletes every matching vector, then scrubs the log so a rebuild cannot put the person back.";
  } else if (proof.verified) {
    stamp.textContent = "verified";
    stamp.className = "stamp ok";
    $("proof").innerHTML = `
      <div><dt>Chunks removed</dt><dd>${esc(proof.chunks_removed)}</dd></div>
      <div><dt>Links remaining</dt><dd>${esc(proof.remaining_chunks)}</dd></div>
      <div><dt>Email in the index</dt><dd>${esc(proof.email_in_chunks)}</dd></div>
      <div><dt>Email in the log</dt><dd>${esc(proof.email_in_log)}</dd></div>`;
    $("proof-note").textContent = `${proof.display_name} is gone from every generation, the log, and the embedding cache entries that nothing else uses. A replay cannot restore the vectors.`;
  }
}

async function refresh() {
  render(await api("/api/status"));
}

async function search(query) {
  $("query").value = query;
  const result = await api(`/api/search?q=${encodeURIComponent(query)}&k=3`);
  const hits = $("hits");
  if (!result.hits.length) {
    hits.innerHTML = `<li><b>No hits in ${esc(result.generation)}</b><span class="score">${esc(result.model_version)}</span></li>`;
    return result;
  }
  hits.innerHTML = result.hits
    .map(
      (hit) =>
        `<li><b>${esc(hit.doc_id)}</b><span class="score">${esc(hit.score.toFixed(3))} · ${esc(result.model_version)}</span></li>`,
    )
    .join("");
  return result;
}

async function play() {
  const button = $("play");
  button.disabled = true;
  document.body.dataset.demoState = "running";
  clearError();
  try {
    render(await api("/api/reset", { method: "POST" }));
    $("hits").innerHTML = "";
    $("query").value = "";
    const loaded = await api("/api/ingest", { method: "POST", body: JSON.stringify({ script: "demo" }) });
    render(loaded);
    const head = loaded.log_head;
    for (let index = 0; index < head; index += 1) {
      render(await api("/api/consume", { method: "POST", body: JSON.stringify({ limit: 1 }) }));
      await sleep(240);
    }
    console.log("DEMO_MARK stream");
    await sleep(900);
    render(await api("/api/migration/start", { method: "POST", body: JSON.stringify({ model_version: "emb-v2" }) }));
    for (let guard = 0; guard < 20; guard += 1) {
      const status = await api("/api/status");
      if (status.migration.state !== "dual_writing") {
        render(status);
        break;
      }
      render(await api("/api/migration/step", { method: "POST", body: JSON.stringify({ limit: 4 }) }));
      await sleep(220);
    }
    console.log("DEMO_MARK migration");
    await sleep(700);
    render(await api("/api/swap", { method: "POST" }));
    console.log("DEMO_MARK swap");
    await sleep(500);
    await search("mileage reimbursement receipt");
    await sleep(1100);
    const forgotten = await api("/api/forget", {
      method: "POST",
      body: JSON.stringify({ subject_id: "subj-ava-chen" }),
    });
    render(forgotten);
    console.log("DEMO_MARK rtbf");
    await sleep(700);
    render(await api("/api/replay", { method: "POST" }));
    await search("ava.chen@northwind.example");
    console.log("DEMO_MARK replay");
    await sleep(1200);
    document.body.dataset.demoState = "done";
  } catch (error) {
    document.body.dataset.demoState = "error";
    showError(error);
  } finally {
    button.disabled = false;
  }
}

$("play").addEventListener("click", play);
$("reset").addEventListener("click", async () => {
  clearError();
  render(await api("/api/reset", { method: "POST" }));
  $("hits").innerHTML = "";
});
$("load").addEventListener("click", async () => {
  clearError();
  try {
    render(await api("/api/ingest", { method: "POST", body: JSON.stringify({ script: "demo" }) }));
  } catch (error) {
    showError(error);
  }
});
$("consume").addEventListener("click", async () => {
  clearError();
  render(await api("/api/consume", { method: "POST", body: "{}" }));
});
$("migrate").addEventListener("click", async () => {
  clearError();
  try {
    render(await api("/api/migration/start", { method: "POST", body: JSON.stringify({ model_version: "emb-v2" }) }));
  } catch (error) {
    showError(error);
  }
});
$("step").addEventListener("click", async () => {
  clearError();
  try {
    render(await api("/api/migration/step", { method: "POST", body: JSON.stringify({ limit: 20 }) }));
  } catch (error) {
    showError(error);
  }
});
$("swap").addEventListener("click", async () => {
  clearError();
  try {
    render(await api("/api/swap", { method: "POST" }));
  } catch (error) {
    showError(error);
  }
});
$("rollback").addEventListener("click", async () => {
  clearError();
  try {
    render(await api("/api/rollback", { method: "POST" }));
  } catch (error) {
    showError(error);
  }
});
$("forget").addEventListener("click", async () => {
  clearError();
  try {
    render(await api("/api/forget", { method: "POST", body: JSON.stringify({ subject_id: $("subject").value }) }));
  } catch (error) {
    showError(error);
  }
});
$("replay").addEventListener("click", async () => {
  clearError();
  try {
    render(await api("/api/replay", { method: "POST" }));
  } catch (error) {
    showError(error);
  }
});
$("search-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  clearError();
  try {
    await search($("query").value);
  } catch (error) {
    showError(error);
  }
});

refresh().catch(showError);
