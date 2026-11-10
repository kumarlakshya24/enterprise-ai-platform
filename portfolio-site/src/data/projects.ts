const REPO = "https://github.com/kumarlakshya24/personal-projects";

export const githubProfile = "https://github.com/kumarlakshya24";

const tree = (path: string) => `${REPO}/tree/main/${path}`;
const blob = (path: string) => `${REPO}/blob/main/${path}`;

export type Tone = "plain" | "emphasis" | "dashed";

export type FlowNode = {
  title: string;
  detail?: string;
  tone?: Tone;
};

export type FlowBlock =
  | ({ type: "node" } & FlowNode)
  | { type: "down"; label?: string }
  | {
      type: "split";
      arms: (FlowNode & { label: string; dashed?: boolean })[];
    }
  | { type: "note"; text: string };

export type Diagram = {
  title: string;
  caption: string;
  blocks: FlowBlock[];
};

export type Decision = {
  id: string;
  title: string;
  choice: string;
  tradeoff: string;
  href: string;
};

export type Fact = {
  value: string;
  label: string;
  href: string;
};

export type Link = {
  label: string;
  href: string;
};

export type Project = {
  slug: string;
  index: string;
  name: string;
  role: string;
  summary: string;
  status: "main" | "in-progress";
  branch?: string;
  problem?: string;
  diagram?: Diagram;
  decisions?: Decision[];
  facts?: Fact[];
  stack: string[];
  links?: Link[];
};

export const projects: Project[] = [
  {
    slug: "aegis",
    index: "01",
    name: "Aegis",
    role: "Security gateway",
    summary:
      "Replaces PII with placeholders before a prompt leaves the company, keeps confidential context on a local model, checks every agent tool call, and writes a tamper-evident audit log.",
    status: "main",
    problem:
      "People and agents will use the best models. A regex scanner only catches the first of four ways data leaves: pasted PII, sensitive context with no pattern to match, a tool call that sends a record to a personal inbox, and a prompt injection that hides customer data in a URL. Aegis is the only component allowed to reach an external model. It assumes the model can be fooled. Tool calls are checked by deterministic code.",
    diagram: {
      title: "Aegis request path",
      caption:
        "One stateless gateway is the enforcement point. Identity, detection, tokenization, labelling, then a policy decision. Drawn from the system diagram in secure-ai-gateway/ARCHITECTURE.md.",
      blocks: [
        {
          type: "node",
          title: "Employee or agent",
          detail: "Signed in with the company IdP",
        },
        { type: "down" },
        {
          type: "node",
          title: "Identity",
          detail: "JWT, tenant, RBAC, rate limit",
        },
        { type: "down" },
        {
          type: "node",
          title: "Detect",
          detail: "Regex, checksums, spaCy NER, normalization",
        },
        { type: "down" },
        {
          type: "node",
          title: "Tokenize",
          detail: "AES-256-GCM vault, typed placeholders",
        },
        { type: "down" },
        {
          type: "node",
          title: "Label",
          detail: "Private classifier on the residual text",
        },
        { type: "down" },
        {
          type: "node",
          tone: "emphasis",
          title: "Decide",
          detail: "Versioned policy. Fails closed.",
        },
        {
          type: "split",
          arms: [
            {
              label: "allow / redact",
              title: "External LLM",
              detail: "Sees placeholders only",
            },
            {
              label: "local_only",
              title: "Local model",
              detail: "Nothing leaves the boundary",
            },
            {
              label: "require_approval",
              title: "Second person",
              detail: "Four-eyes, then the tool runs",
            },
            {
              label: "block",
              title: "Refused",
              detail: "The reason is named",
            },
          ],
        },
        {
          type: "note",
          text: "Answers are restored for the caller’s role. A card number stays masked. Agent tool calls take the same pipeline, plus a tool guard and an injection check on tool output.",
        },
      ],
    },
    decisions: [
      {
        id: "ADR 0001",
        title: "Gateway proxy, not client-side filtering",
        choice:
          "Clients authenticate to the gateway. It is the only component with egress to external models, and the only holder of provider keys.",
        tradeoff:
          "A proxy only sees traffic that is forced through it. A personal chat tab is out of scope; egress control or a CASB has to close that gap.",
        href: blob(
          "secure-ai-gateway/docs/adr/0001-gateway-proxy-not-client-side-filtering.md",
        ),
      },
      {
        id: "ADR 0002",
        title: "Placeholder tokenization, not deletion",
        choice:
          "The same value keeps the same placeholder inside a session, so the model can tell two mentions are one person. Restoration is limited to the authorized user. The vault binds ciphertext to tenant, user, session, purpose, and placeholder.",
        tradeoff:
          "The vault is now a sensitive store. If it is down, the request is blocked rather than sent in the clear.",
        href: blob(
          "secure-ai-gateway/docs/adr/0002-placeholder-tokenization-not-deletion.md",
        ),
      },
      {
        id: "ADR 0004",
        title: "Deterministic tool guard with taint",
        choice:
          "The model is untrusted when it chooses a tool. A guard resolves placeholder recipients, enforces domain allowlists, decodes obfuscated URLs, and blocks risky tools after an injection taints the session.",
        tradeoff:
          "The demo model obeys the injection on purpose. The call is still blocked, because the check is not a prompt asking the model to behave.",
        href: blob(
          "secure-ai-gateway/docs/adr/0004-deterministic-tool-guard-with-taint.md",
        ),
      },
      {
        id: "ADR 0005",
        title: "Tamper-evident, redacted audit log",
        choice:
          "Append-only Postgres, triggers reject updates and deletes, and each row is HMAC-chained with a key that is not in the database. Content above a label threshold is withheld.",
        tradeoff:
          "Someone with the HMAC key can forge a chain. The key lives in the gateway environment, not next to the rows.",
        href: blob(
          "secure-ai-gateway/docs/adr/0005-tamper-evident-redacted-audit-log.md",
        ),
      },
    ],
    facts: [
      {
        value: "97.0% recall · 95.5% precision",
        label:
          "84-case development red-team set. 2 misses, 3 over-routes, all explained. The blind classifier holdout is separate: 86% accuracy, 94% recall on sensitive context.",
        href: blob("secure-ai-gateway/reports/redteam.md"),
      },
      {
        value: "9.2 ms p95 in-process",
        label:
          "Added latency with 3 entities, excluding model time. The Docker stack, with Postgres and Redis in the loop, is 21.2 ms p95. The budget in the architecture doc is 300 ms.",
        href: blob("secure-ai-gateway/reports/latency.md"),
      },
      {
        value: "64 cases locked",
        label:
          "Regression gate. Setting CREDIT_CARD to allow causes 7 regressions and a 409. 200 tests.",
        href: blob("secure-ai-gateway/reports/regression.md"),
      },
    ],
    stack: [
      "Python 3.11+",
      "FastAPI",
      "PostgreSQL",
      "Redis",
      "spaCy",
      "OIDC",
      "AES-256-GCM",
    ],
    links: [
      { label: "Repository", href: tree("secure-ai-gateway") },
      { label: "Architecture", href: blob("secure-ai-gateway/ARCHITECTURE.md") },
      { label: "ADRs", href: tree("secure-ai-gateway/docs/adr") },
      { label: "Demo GIF", href: blob("secure-ai-gateway/docs/media/hero.gif") },
      {
        label: "Walkthrough video",
        href: blob("secure-ai-gateway/docs/media/aegis-walkthrough.mp4"),
      },
    ],
  },
  {
    slug: "switchboard",
    index: "02",
    name: "Switchboard",
    role: "Model router",
    summary:
      "Picks the cheapest model that is good enough for each request, under a versioned policy, and records why.",
    status: "main",
    problem:
      "Sending every prompt to a flagship model pays flagship prices for an easy question. Sending every prompt to the cheap model misses the proof and the tight latency budget. That choice is usually buried in a client SDK, so nobody can say why a request landed where it did. Switchboard makes the decision explicit, on the request path, against a catalog of in-process mocks.",
    diagram: {
      title: "Switchboard routing decision",
      caption:
        "Hard constraints remove models. A named selection mode ranks what remains. Catalog latency is an estimate. Router overhead is measured. Drawn from switchboard/ARCHITECTURE.md.",
      blocks: [
        { type: "node", title: "Caller", detail: "Demo UI or HTTP client" },
        { type: "down" },
        {
          type: "node",
          title: "Classifier",
          detail: "Task, complexity, tokens, sensitivity. No weights file.",
        },
        { type: "down" },
        {
          type: "node",
          title: "Policy",
          detail: "Versioned YAML. A request can tighten a ceiling, not loosen it.",
        },
        { type: "down" },
        {
          type: "node",
          tone: "emphasis",
          title: "Constraints, then selection",
          detail: "Floor, headroom, budget, SLO, peer flag. Then weighted, cheapest, fastest, or highest capability.",
        },
        {
          type: "split",
          arms: [
            {
              label: "none eligible",
              title: "Rejected",
              detail: "Nothing is called. Spend is zero.",
            },
            {
              label: "eligible",
              title: "Mock provider",
              detail: "fast-cheap, balanced, premium, local",
            },
          ],
        },
        { type: "down", label: "timeout, error, or quality-gate miss" },
        {
          type: "node",
          title: "Fallback",
          detail: "Next eligible model, in the fallback order",
        },
        {
          type: "split",
          arms: [
            {
              label: "confidential or restricted",
              title: "Local only",
              detail: "Pin. No spill to a hosted model.",
              tone: "emphasis",
            },
            {
              label: "hosted calls failed, policy allows",
              title: "Local escape",
              detail: "Marked degraded when local is under the floor",
            },
            {
              label: "escape disabled, or pin",
              title: "Failed",
              detail: "Quality-first does not spill. A pin never cascades.",
            },
          ],
        },
        {
          type: "note",
          text: "Every outcome is appended to a SQLite log as a redacted preview and a SHA-256, not the prompt. Local is peer: false, so a zero price cannot win the cost score.",
        },
      ],
    },
    decisions: [
      {
        id: "ADR 0001",
        title: "Route in one process, not in each client",
        choice:
          "One process holds the active policy. The demo, the CLI, and the eval call the same pipeline. A per-request override can only tighten the ceiling.",
        tradeoff:
          "There is no authentication here. Identity is Aegis’s boundary. Switchboard is the route.",
        href: blob("switchboard/docs/adr/0001-route-in-one-process.md"),
      },
      {
        id: "ADR 0002",
        title: "Deterministic features, not a judge model",
        choice:
          "A leading verb, a keyword scan, a complexity function, and a sensitivity floor. Every feature is a named signal in the trace.",
        tradeoff:
          "English keywords will miss paraphrases a classifier might catch. The explanation stays a sentence, and the eval stays reproducible offline.",
        href: blob("switchboard/docs/adr/0002-rules-not-a-judge-model.md"),
      },
      {
        id: "ADR 0003",
        title: "Hard constraints, then a selection mode",
        choice:
          "Illegal models are removed first. The mode then ranks whatever remains. Headroom relaxes when applying it would empty the set, and that relaxation is recorded.",
        tradeoff:
          "A tight budget can fall through to Fast Cheap instead of rejecting. The trace shows the weighted score even when another mode won.",
        href: blob("switchboard/docs/adr/0003-constraints-then-selection.md"),
      },
      {
        id: "ADR 0004",
        title: "Local is a pin and an escape hatch, not a peer",
        choice:
          "Confidential and restricted prompts pin to local and stop fallback. A total hosted failure may escape to local only when the policy allows, and that answer is marked degraded.",
        tradeoff:
          "A pin waives the floor, the budget, the SLO, and the quality gate. Quality-first turns the escape off, so the same timeout ends as failed.",
        href: blob("switchboard/docs/adr/0004-local-is-not-a-peer.md"),
      },
    ],
    facts: [
      {
        value: "64.98% cheaper",
        label:
          "Versus always-premium, on 28 answered non-fault cases ($0.02421 vs $0.06914). The README badge rounds this to 65%. Rejected requests are not counted as savings.",
        href: blob("switchboard/reports/eval.md"),
      },
      {
        value: "0.079 ms p95 overhead",
        label:
          "Router only, n=400, in-process, SQLite append included, model time not slept. Catalog latency of the chosen model is estimated, not wall clock.",
        href: blob("switchboard/reports/latency.md"),
      },
      {
        value: "36 / 36",
        label:
          "Eval corpus against the policy spec. 29 tests. Quality-first agrees with the cheapest legal model on 2 of 4 cases, because that policy pays for capability.",
        href: blob("switchboard/reports/eval.md"),
      },
    ],
    stack: [
      "Python 3.11+",
      "FastAPI",
      "SQLite",
      "Versioned YAML policies",
      "In-process mock models",
    ],
    links: [
      { label: "Repository", href: tree("switchboard") },
      { label: "Architecture", href: blob("switchboard/ARCHITECTURE.md") },
      { label: "ADRs", href: tree("switchboard/docs/adr") },
      {
        label: "Demo GIF",
        href: blob("switchboard/docs/assets/switchboard-demo.gif"),
      },
      {
        label: "Demo video",
        href: blob("switchboard/docs/assets/switchboard-demo.mp4"),
      },
    ],
  },
  {
    slug: "lumen",
    index: "03",
    name: "Lumen",
    role: "Knowledge assistant",
    summary:
      "Answers employee questions from company documents, with citations, a refusal when the evidence is weak, and access control inside the retrieval query.",
    status: "main",
    problem:
      "Embedding a folder of PDFs and calling a model loses exact codes, slices tables in half, shows a finance analyst the sales policy, leaks a restricted document, repeats an injected instruction, and answers when nothing matches. Lumen is the knowledge path: filter before ranking, cite or refuse, and drop a cached answer when the document it cites changes.",
    diagram: {
      title: "Lumen ingestion and query",
      caption:
        "One Postgres database holds vectors, BM25 postings, ACL columns, and lineage, so a filter is part of retrieval and an update is one transaction. Drawn from rag-knowledge-assistant/ARCHITECTURE.md.",
      blocks: [
        {
          type: "node",
          title: "Documents",
          detail: "PDF, Markdown, text, with team and visibility",
        },
        { type: "down", label: "ingestion" },
        {
          type: "node",
          title: "Parse, then chunk by structure",
          detail: "Tables, clauses, and lists stay whole",
        },
        { type: "down" },
        {
          type: "node",
          title: "Postgres + pgvector",
          detail: "HNSW, BM25 postings, ACL columns, lineage",
          tone: "emphasis",
        },
        { type: "down", label: "query, with the caller’s identity" },
        {
          type: "node",
          title: "Semantic cache",
          detail: "Redis, partitioned by access scope",
        },
        {
          type: "split",
          arms: [
            {
              label: "hit",
              title: "Cached cited answer",
              detail: "Never served across a permission boundary",
            },
            {
              label: "miss",
              title: "Hybrid retrieval",
              detail: "Vector and BM25. ACL and audience in the WHERE.",
            },
          ],
        },
        { type: "down", label: "on a miss" },
        {
          type: "node",
          title: "Injection guard, then cross-encoder",
          detail: "50 candidates down to 5",
        },
        { type: "down" },
        {
          type: "node",
          tone: "emphasis",
          title: "Evidence gate",
          detail: "Weak score, or a code that appears in no evidence",
        },
        {
          type: "split",
          arms: [
            {
              label: "weak",
              title: "Not found",
              detail: "Refusal, before generation",
            },
            {
              label: "enough evidence",
              title: "Generator",
              detail: "Answers without a valid citation are discarded",
            },
          ],
        },
        {
          type: "note",
          text: "Changing a document re-indexes incrementally and evicts cached answers that cite it. Lumen has no separate ADR folder. The decisions below are the architecture document.",
        },
      ],
    },
    decisions: [
      {
        id: "Architecture §3",
        title: "One Postgres, not a separate vector database",
        choice:
          "pgvector HNSW, a real BM25 inverted index in SQL, ACL columns, and chunk lineage live in one database so filtering and re-indexing share a transaction.",
        tradeoff:
          "One store is doing several jobs. The architecture doc says what breaks as the corpus grows, including HNSW filter starvation and the iterative scan that answers it.",
        href: blob("rag-knowledge-assistant/ARCHITECTURE.md"),
      },
      {
        id: "Architecture §4.3",
        title: "Filter inside retrieval, not after top-k",
        choice:
          "Visibility and audience are predicates on both the vector query and the BM25 query. A chunk the caller may not read is never scored, never debugged, and never prompted.",
        tradeoff:
          "Post-filtering was rejected because it leaks through debug output and timing, and it shrinks recall when most of the top-k is dropped. Re-ranking without the audience filter made cross-team accuracy worse on this set.",
        href: `${blob("rag-knowledge-assistant/ARCHITECTURE.md")}#43-filtering-before-ranking-two-different-filters`,
      },
      {
        id: "Architecture §4.4",
        title: "Cross-encoder, not an LLM reranker",
        choice:
          "Score 50 fused candidates with an int8 cross-encoder and keep 5. The same score is the refusal signal. Dynamic int8 cut end-to-end p95 from 939 ms to 544 ms on the published run, with the same correctness.",
        tradeoff:
          "Re-ranking is most of the latency and scales with the candidate count. On this 52-chunk corpus, hybrid search and multi-query do not change end-to-end accuracy, because 50 candidates already cover the index. The README says that gain shows up as the corpus grows.",
        href: `${blob("rag-knowledge-assistant/ARCHITECTURE.md")}#44-re-ranking`,
      },
      {
        id: "Architecture §4.5",
        title: "Refuse before generation",
        choice:
          "If the best score is weak, or an identifier in the question appears in no evidence, the answer is “Not found in the provided documents.” Uncited answers are discarded.",
        tradeoff:
          "The published eval used the offline extractive generator, so faithfulness in that run is by construction. A hosted model is a configuration change, not a different pipeline.",
        href: `${blob("rag-knowledge-assistant/ARCHITECTURE.md")}#45-evidence-gate-generation-and-citations`,
      },
    ],
    facts: [
      {
        value: "63.0% → 89.1% answer correct",
        label:
          "46 questions, eval run 20261104-010419, extractive generator. Baseline is phase 1 of the same pipeline.",
        href: blob("rag-knowledge-assistant/eval_results/latest/summary.md"),
      },
      {
        value: "Restricted leaks 100% → 0%",
        label:
          "Wrong-team top hit 25% → 0%. Injected instructions followed 100% → 0%. Correct refusals 30% → 90%.",
        href: blob("rag-knowledge-assistant/README.md"),
      },
      {
        value: "5.2 ms p50 on a cache hit",
        label:
          "Versus 448 ms on a miss. 23.9% of reworded questions hit. 0 wrong answers served from cache. Full pipeline p95 is 544 ms.",
        href: blob("rag-knowledge-assistant/eval_results/latest/summary.md"),
      },
    ],
    stack: [
      "Python 3.12",
      "FastAPI",
      "PostgreSQL + pgvector",
      "Redis 8",
      "ONNX Runtime",
      "MiniLM embedder and cross-encoder",
    ],
    links: [
      { label: "Repository", href: tree("rag-knowledge-assistant") },
      {
        label: "Architecture",
        href: blob("rag-knowledge-assistant/ARCHITECTURE.md"),
      },
      {
        label: "Cross-team demo",
        href: blob("rag-knowledge-assistant/docs/assets/crossteam.gif"),
      },
      {
        label: "Walkthrough video",
        href: blob("rag-knowledge-assistant/docs/assets/lumen-walkthrough.mp4"),
      },
    ],
  },
  {
    slug: "forge",
    index: "04",
    name: "Forge",
    role: "Tool sandbox",
    summary:
      "Refuses a dangerous agent tool call before a process exists, and runs the rest in a short-lived interpreter.",
    status: "main",
    problem:
      "An agent that can run tools can read the wrong file, import the wrong module, or loop until the machine stalls. Forge sits at that boundary. A denial does not spawn. An allow runs in a cleaned python -I process with resource limits. The demo’s unprotected pane is a preview: it never executes a call Forge has decided to refuse.",
    diagram: {
      title: "Forge tool-call path",
      caption:
        "The guard runs before any process. Policy can shrink the allowlist. It cannot grant a hard denial. Drawn from forge/ARCHITECTURE.md.",
      blocks: [
        { type: "node", title: "Caller", detail: "Demo UI or library" },
        { type: "down", label: "tool call" },
        {
          type: "node",
          tone: "emphasis",
          title: "Tool guard",
          detail: "Path, import, tool, size. Preview is not an execution.",
        },
        {
          type: "split",
          arms: [
            {
              label: "deny",
              title: "No process",
              detail: "Shell, bad path, bad AST, hard-denied import",
              tone: "emphasis",
            },
            {
              label: "python allow",
              title: "Child interpreter",
              detail: "python -I, rlimits, audit hook, second AST gate",
            },
            {
              label: "file allow",
              title: "Workspace",
              detail: "Relative paths. “..”, absolutes, and symlinks refused.",
            },
          ],
        },
        { type: "down", label: "every decision" },
        {
          type: "node",
          title: "HMAC JSONL audit",
          detail: "Append-only. Hash and a short preview, not a second copy of the file.",
        },
        {
          type: "note",
          text: "Hard denials for os, socket, subprocess, ctypes, and the absence of a shell live in code. The child is a subprocess of the same user, not a hypervisor.",
        },
      ],
    },
    decisions: [
      {
        id: "ADR 0001",
        title: "Subprocess sandbox, not a container, as the default",
        choice:
          "A short-lived python -I process, a cleaned environment, rlimits, an audit hook, and a second AST gate inside the child. Docker is not required for the demo or CI.",
        tradeoff:
          "A same-user process is not a hypervisor. The architecture says a production deployment should add a sandbox user or a container under this guard, not instead of it.",
        href: blob("forge/docs/adr/0001-subprocess-not-container.md"),
      },
      {
        id: "ADR 0002",
        title: "Hard guards are not policy switches",
        choice:
          "YAML may shrink the import allowlist and lower limits. It cannot raise a ceiling, set network to allow, or create a shell. os, socket, and path escape are enforced in code.",
        tradeoff:
          "pathlib and the code-size cap stay in policy on purpose, so a weaker file is something the regression gate can refuse.",
        href: blob("forge/docs/adr/0002-hard-guards-not-switches.md"),
      },
      {
        id: "ADR 0003",
        title: "No shell executor",
        choice:
          "The tool name shell is recognized so the denial is explicit (R-TOOL-NO-EXECUTOR). There is no code that interprets a command string.",
        tradeoff:
          "enabled: true in YAML does not add an executor. Callers see a refusal, not a silent no-op.",
        href: blob("forge/docs/adr/0003-no-shell-executor.md"),
      },
      {
        id: "ADR 0005",
        title: "Regression gate on protected case ids",
        choice:
          "The baseline lists case ids the default policy must not allow, and utility ids it must allow. A protected id that becomes an allow fails the gate. CI does not include an update flag.",
        tradeoff:
          "The corpus locks the decisions we intend to keep. The README says it is not a claim about unknown attacks.",
        href: blob("forge/docs/adr/0005-regression-gate.md"),
      },
    ],
    facts: [
      {
        value: "55 / 55",
        label:
          "Development corpus: 41 protection, 14 utility. Not a claim about unknown attacks.",
        href: blob("forge/reports/eval.md"),
      },
      {
        value: "0.21 ms p95 to deny",
        label:
          "Deny-before-spawn. p50 is 0.13 ms. An allow that spawns one subprocess is p95 37.55 ms.",
        href: blob("forge/reports/latency.md"),
      },
      {
        value: "41 cases locked",
        label:
          "Regression gate, 0 regressions on the default policy. Granting pathlib and raising the code cap fails the gate. 54 tests.",
        href: blob("forge/reports/regression.md"),
      },
    ],
    stack: [
      "Python 3.11+",
      "FastAPI",
      "Policy YAML",
      "python -I subprocess",
      "HMAC-SHA256 JSONL",
    ],
    links: [
      { label: "Repository", href: tree("forge") },
      { label: "Architecture", href: blob("forge/ARCHITECTURE.md") },
      { label: "ADRs", href: tree("forge/docs/adr") },
      { label: "Demo GIF", href: blob("forge/docs/assets/demo.gif") },
      { label: "Demo video", href: blob("forge/docs/assets/demo.mp4") },
    ],
  },
  {
    slug: "atlas",
    index: "05",
    name: "Atlas",
    role: "Durable workflows",
    summary:
      "Runs multi-step agent workflows that survive a crash between a side effect and the record of it, without charging twice.",
    status: "main",
    problem:
      "A worker dies after a ledger debit has committed and before the run records success. Retrying the plan charges the customer twice. Atlas is the runtime for that window. A planner and specialists propose tool calls. The engine writes an event log, stores the effect under an idempotency key, and resumes from that key.",
    diagram: {
      title: "Atlas run, and the gap a kill lands in",
      caption:
        "effects.db commits the debit in its own transaction. atlas.db records completion later. Resume heals from the key. Drawn from atlas/ARCHITECTURE.md.",
      blocks: [
        { type: "node", title: "Operator", detail: "Demo UI or CLI" },
        { type: "down" },
        {
          type: "node",
          tone: "emphasis",
          title: "Atlas engine",
          detail: "Drive, lease, fencing epoch. Agents propose. The engine commits.",
        },
        {
          type: "split",
          arms: [
            {
              label: "before the side effect",
              title: "Mock LLM",
              detail: "The completion is an event, written first",
            },
            {
              label: "guard port",
              title: "Aegis contract",
              detail: "allow, require_approval, or block. HTTP fails closed.",
              dashed: true,
            },
            {
              label: "knowledge port",
              title: "Lumen contract",
              detail: "POST /ask. A refusal fails the step.",
              dashed: true,
            },
          ],
        },
        {
          type: "split",
          arms: [
            {
              label: "history",
              title: "atlas.db",
              detail: "Events, hashed checkpoints, leases",
            },
            {
              label: "commits first",
              title: "effects.db",
              detail: "Ledger, email, pager, under the idempotency key",
              tone: "emphasis",
            },
          ],
        },
        {
          type: "note",
          text: "Aegis and Lumen stay separate processes. Atlas does not import them. The offline stubs speak their contracts. SIGKILL in the gap between the two files is the test.",
        },
      ],
    },
    decisions: [
      {
        id: "ADR 0001",
        title: "Event log and checkpoints, not a status row",
        choice:
          "Append-only events are the source of truth. Resume uses the newest checkpoint whose SHA-256 matches, then folds the tail. The model decision is written before the side effect and replayed.",
        tradeoff:
          "A bad first decision stays in the log. The fold has to be deterministic: no clock reads, no fresh samples. Re-prompting was rejected because a second completion will not match the first idempotency key.",
        href: blob("atlas/docs/adr/0001-event-log-and-replay.md"),
      },
      {
        id: "ADR 0002",
        title: "Idempotency keys, not at-most-once delivery",
        choice:
          "Side effects live in a second database under {run_id}:{activity_id}. That commit returns before the engine appends activity_completed. If resume finds the key, it heals and skips the body.",
        tradeoff:
          "At-most-once drops the refund. Blind retry double-charges. The remote system has to honor the key. A provider that dedupes for ten minutes can still double-charge later, and Atlas cannot see that.",
        href: blob("atlas/docs/adr/0002-idempotency-keys-not-at-most-once.md"),
      },
      {
        id: "ADR 0003",
        title: "Saga compensations, not two-phase commit",
        choice:
          "On a permanent failure, unfinished forward work is skipped and completed steps run their compensate tool in reverse, each with its own key. Compensations ignore the step and cost caps.",
        tradeoff:
          "Atlas does not operate the ledger or the mailer, so it cannot prepare/commit them. compensation_failed is a real terminal state.",
        href: blob("atlas/docs/adr/0003-sagas-not-two-phase-commit.md"),
      },
      {
        id: "ADR 0004",
        title: "Aegis and Lumen behind ports",
        choice:
          "Guard and knowledge are ports with offline stubs and fail-closed HTTP adapters. The decision is recorded before the side effect.",
        tradeoff:
          "The stubs are subsets. Live mode targets /v1/tool-guard/evaluate, which Aegis does not expose yet, so that path blocks every call. A down Lumen becomes a refusal, not a guessed refund.",
        href: blob("atlas/docs/adr/0004-ports-for-aegis-and-lumen.md"),
      },
    ],
    facts: [
      {
        value: "16 / 16 vs 3 / 16",
        label:
          "Task success against a single-agent baseline with no log, no effect key, no approval wait, no retry, and no compensation. The mock LLM is a pure function. This is not an estimate for a sampled model.",
        href: blob("atlas/eval_results/latest/summary.md"),
      },
      {
        value: "0 of 4 crash cases duplicate",
        label:
          "The baseline duplicates 3 of 4. Mean completed steps re-run after a crash: 0 for Atlas, 3.25 for the baseline.",
        href: blob("atlas/README.md"),
      },
      {
        value: "p95 28.3 ms engine overhead",
        label:
          "40 small refunds, measured wall clock, mock agents, including file setup. p50 17.3 ms. Actual model spend in the repo is $0. The accounted dollars are a price list the budget enforcer sums.",
        href: blob("atlas/eval_results/latest/summary.md"),
      },
    ],
    stack: ["Python 3.12", "FastAPI", "SQLite event log", "SQLite effect store"],
    links: [
      { label: "Repository", href: tree("atlas") },
      { label: "Architecture", href: blob("atlas/ARCHITECTURE.md") },
      { label: "ADRs", href: tree("atlas/docs/adr") },
      {
        label: "Kill-and-resume GIF",
        href: blob("atlas/docs/assets/atlas-kill-resume.gif"),
      },
      {
        label: "Demo video",
        href: blob("atlas/docs/assets/atlas-kill-resume.mp4"),
      },
    ],
  },
  {
    slug: "lens",
    index: "06",
    name: "Lens",
    role: "Evaluation and observability",
    summary:
      "Traces retrieval, model, and tool steps, judges a sample, watches drift, and blocks a release when a candidate drops quality on a frozen set.",
    status: "main",
    problem:
      "Aegis decides what may leave. Lumen decides what the documents support. Neither one says that yesterday’s prompt is worse than last week’s. A prompt change can pass unit tests and still move a slice of answers from 97% to 55%, and the gateway error rate will not show it. Lens sits beside the request path: sample, score, burn error budgets in public, and fail CI on a hand-labeled gold set.",
    diagram: {
      title: "Lens data plane and control plane",
      caption:
        "The judge is not on the user path. Production drift pages a person. The gate blocks an artifact. Drawn from lens/ARCHITECTURE.md.",
      blocks: [
        {
          type: "split",
          arms: [
            {
              label: "route, policy, tool",
              title: "Aegis events",
              detail: "Adapter. Lens does not import Aegis.",
              dashed: true,
            },
            {
              label: "retrieval and answer",
              title: "Lumen events",
              detail: "Adapter. Lens does not import Lumen.",
              dashed: true,
            },
          ],
        },
        { type: "down", label: "async export" },
        {
          type: "node",
          title: "Trace log",
          detail: "OpenTelemetry-style spans",
        },
        { type: "down" },
        {
          type: "node",
          tone: "emphasis",
          title: "Sampler",
          detail: "Keep errors, slow traces, and safety signals. Hash the rest into a stratum.",
        },
        { type: "down" },
        {
          type: "node",
          title: "Heuristic judge",
          detail: "Kappa against hand labels is the admission test",
        },
        { type: "down" },
        {
          type: "node",
          title: "SLI counters",
          detail: "Quality uses the eval stratum only",
        },
        {
          type: "split",
          arms: [
            {
              label: "frozen gold set",
              title: "CI gate",
              detail: "Compare to the locked baseline. Exit 1 names the ids.",
              tone: "emphasis",
            },
            {
              label: "does not block the deploy",
              title: "Drift and burn",
              detail: "PSI, CUSUM, multi-window burn. Page or ticket.",
            },
          ],
        },
        {
          type: "note",
          text: "Sample rate, rubric version, SLO targets, the locked baseline, and the gate rules are commits. A bad hour in the synthetic log is not evidence that the build you are promoting is the cause.",
        },
      ],
    },
    decisions: [
      {
        id: "ADR 0001",
        title: "Sample off the request path",
        choice:
          "Export is asynchronous. Keep a trace on error, latency at or over 1500 ms, or a safety signal. Otherwise keep it when a hash of app, model, and trace id falls under the stratum rate. Otherwise drop the body and keep attributes for drift.",
        tradeoff:
          "Judging every request would add latency, and a judge outage would become a product outage. A thin sample must not be allowed to page.",
        href: blob("lens/docs/adr/0001-sample-off-the-request-path.md"),
      },
      {
        id: "ADR 0002",
        title: "A heuristic judge, with kappa as the admission test",
        choice:
          "make eval runs the heuristic. The gold set is labeled to the rubric, including three items the heuristic gets wrong on purpose: a paraphrase, a negation, and an unsupported clause.",
        tradeoff:
          "The published kappa is the heuristic against hand labels. It is not a claim about an LLM judge. No LLM was called. Kappa under the floor stops a rubric edit from moving the baseline.",
        href: blob("lens/docs/adr/0002-heuristic-judge-with-a-kappa-floor.md"),
      },
      {
        id: "ADR 0003",
        title: "Four SLOs, no blended score",
        choice:
          "Availability, latency, quality, and safety each have a target, a budget, and a burn rate. A burn of 14.4 on the 1-hour window is the fast page. A burn of 6 on the 6-hour window is the slow page.",
        tradeoff:
          "The demo has hourly counters, so it implements the long window only, and it says so. Quality is computed on the eval sample. Safety is the cheap screen on every Aegis span.",
        href: blob("lens/docs/adr/0003-split-slos-and-burn-rates.md"),
      },
      {
        id: "ADR 0004",
        title: "The gate locks a baseline. Drift does not block the deploy.",
        choice:
          "The gate replays the frozen gold set. It fails on a new safety-critical miss, a pass-rate or faithfulness drop of more than 3 points, p95 over 1.15× the baseline, or kappa under the floor.",
        tradeoff:
          "A bad hour in production is not a property of the artifact you are about to ship, so drift pages a person and does not, by itself, fail the build. The gate also locks known holes that are already in the baseline.",
        href: blob("lens/docs/adr/0004-gate-locks-a-baseline.md"),
      },
    ],
    facts: [
      {
        value: "κ 0.7591 on pass",
        label:
          "Heuristic against hand labels, gold set n=44. Faithful is 0.7295. Relevant, safe, and refusal_correct are 1.0. Three disagreements are listed in the README.",
        href: blob("lens/reports/latest/summary.md"),
      },
      {
        value: "Seeded gate fails 5 of 6 rules",
        label:
          "Clean candidate passes. The seeded prompt fails pass rate, faithfulness, the safety floor, new safety failures, and p95. Judge kappa still passes. Newly unsafe ids: lum-injection-followed, aeg-label-bypass, aeg-pii-leak.",
        href: blob("lens/reports/latest/gate_regressed.md"),
      },
      {
        value: "23 tests",
        label:
          "SLO and PSI figures describe a synthetic 14-day log, seed 17. Trace latency in that log is generated. It is not a measurement of Aegis or Lumen.",
        href: blob("lens/README.md"),
      },
    ],
    stack: [
      "Python 3.12",
      "FastAPI",
      "OpenTelemetry-style spans",
      "Heuristic judge",
      "PSI and CUSUM",
    ],
    links: [
      { label: "Repository", href: tree("lens") },
      { label: "Architecture", href: blob("lens/ARCHITECTURE.md") },
      { label: "ADRs", href: tree("lens/docs/adr") },
      { label: "Demo GIF", href: blob("lens/docs/assets/lens-demo.gif") },
      { label: "Demo video", href: blob("lens/docs/assets/lens-demo.mp4") },
    ],
  },
  {
    slug: "conduit",
    index: "07",
    name: "Conduit",
    role: "In progress",
    summary: "Embedding CDC.",
    status: "in-progress",
    branch: "feat/conduit",
    stack: [],
  },
  {
    slug: "arena",
    index: "08",
    name: "Arena",
    role: "In progress",
    summary: "Fine-tune vs RAG vs prompt bench.",
    status: "in-progress",
    branch: "feat/arena",
    stack: [],
  },
  {
    slug: "charter",
    index: "09",
    name: "Charter",
    role: "In progress",
    summary: "AI governance control plane.",
    status: "in-progress",
    branch: "feat/charter",
    stack: [],
  },
  {
    slug: "skyline",
    index: "10",
    name: "Skyline",
    role: "In progress",
    summary: "Platform CDK.",
    status: "in-progress",
    branch: "feat/skyline",
    stack: [],
  },
];

export const shipped = projects.filter((project) => project.status === "main");
export const waveTwo = projects.filter(
  (project) => project.status === "in-progress",
);

export const platform: Diagram = {
  title: "How the six systems sit together",
  caption:
    "Solid steps are the path inside a project. Dashed boxes are documented contracts. Which of those are live, and which are tested against a stand-in, is in the repository README.",
  blocks: [
    {
      type: "node",
      title: "Employees and agents",
      detail: "One question: use models safely, cheaply, reliably, and measurably",
    },
    { type: "down" },
    {
      type: "node",
      tone: "emphasis",
      title: "Aegis",
      detail: "Trust boundary. Tokenize, label, guard tools, audit.",
    },
    {
      type: "split",
      arms: [
        {
          label: "after the security decision",
          title: "Switchboard",
          detail: "Which model. Not wired yet. Both pin confidential text to local.",
          dashed: true,
        },
        {
          label: "placeholders, or nothing",
          title: "Hosted or local model",
          detail: "Aegis is the only component with egress",
        },
      ],
    },
    {
      type: "split",
      arms: [
        {
          label: "cited answers",
          title: "Lumen",
          detail: "Retrieval, RBAC, refusal",
        },
        {
          label: "multi-step work",
          title: "Atlas",
          detail: "Log, idempotency, sagas",
        },
        {
          label: "untrusted code",
          title: "Forge",
          detail: "Not wired to Atlas yet. The intended executor.",
          dashed: true,
        },
      ],
    },
    { type: "down", label: "beside the request path" },
    {
      type: "node",
      title: "Lens",
      detail: "Sample, judge, drift, SLOs. Blocks a bad release in CI.",
    },
  ],
};
