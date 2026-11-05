// Generates data.js (window.D) from the saved eval run, so the video never hard-codes a metric.
import fs from 'node:fs';
import path from 'node:path';
const here = path.dirname(new URL(import.meta.url).pathname);
// summary.json is written by Python and may contain NaN (not valid JSON); map it to null.
const raw = fs.readFileSync(path.join(here, '../../eval_results/latest/summary.json'), 'utf8').replace(/\bNaN\b/g, 'null');
const s = JSON.parse(raw);
const prof = {};
for (const [n, p] of Object.entries(s.profiles)) prof[n] = {
  ac: p.answer_correct, rc: p.refusal_correct, leak: p.rbac_leak_rate, inj: p.injection_followed_rate,
  ct: p.cross_team_top1_error, mrr: p.mrr, pmrr: p.pre_rerank_mrr, p95: p.latency_p95_ms.total, p50: p.latency_p50_ms };
const c = s.cache;
const D = { run: s.run_id, n: s.n_questions, prof,
  cache: { hit: c.paraphrase_pass.hit_rate, hitms: c.paraphrase_pass.hit_latency_p50_ms, missms: c.paraphrase_pass.miss_latency_p50_ms,
           nmPairs: c.near_miss.pairs, nmFalse: c.near_miss.false_hits.length, sweep: c.threshold_sweep },
  inv: { replaced: c.invalidation.chunks_replaced, unchanged: c.invalidation.chunks_unchanged, embedded: c.invalidation.embeddings_computed } };
fs.writeFileSync(path.join(here, 'data.js'), 'window.D = ' + JSON.stringify(D) + ';\n');
console.log('data.js written from run', D.run);
