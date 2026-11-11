/**
 * Scripted replays for the "Follow a request" section on the home page.
 *
 * Every value here is copied from a project's own offline demo or committed
 * report, and every person and record is synthetic. The projects run on their
 * own today, so a step marked `contract` is a documented interface between two
 * projects that is not wired live. Change a value here only when the source
 * named in `source` changes.
 */

const REPO = "https://github.com/kumarlakshya24/enterprise-ai-platform";
const blob = (path: string) => `${REPO}/blob/main/${path}`;

export type TraceStep = {
  /** Project slug, or "model" for the hosted or local model. */
  slug: string;
  stage: string;
  decision: string;
  detail?: string;
  /** Documented contract between projects, not wired live yet. */
  contract?: boolean;
  /** Visual outcome of the step. */
  tone?: "pass" | "stop" | "hold";
};

export type TraceScenario = {
  id: string;
  label: string;
  asker: string;
  input: string;
  steps: TraceStep[];
  outcome: string;
  source: { label: string; href: string };
};

export const traceScenarios: TraceScenario[] = [
  {
    id: "paste",
    label: "A card number pasted into chat",
    asker: "Avery Quill, support agent",
    input:
      "Draft a reply to a customer, with their name, email address, and full card number pasted in.",
    steps: [
      {
        slug: "aegis",
        stage: "Detect",
        decision: "3 entities found",
        detail: "A name, an email address, and a Luhn-valid Visa number at 0.99 confidence.",
      },
      {
        slug: "aegis",
        stage: "Tokenize",
        decision: "[PERSON_NAME_1] · [EMAIL_1] · [CREDIT_CARD_1]",
        detail: "The real values go into an AES-256-GCM vault. Only typed placeholders move on.",
      },
      {
        slug: "aegis",
        stage: "Decide",
        decision: "redact_and_continue",
        detail: "Context INTERNAL, rule R-ROUTE-INTERNAL.",
        tone: "pass",
      },
      {
        slug: "model",
        stage: "Hosted model",
        decision: "Sees placeholders only",
        detail: "The mock provider's own log shows the placeholders and nothing else.",
      },
      {
        slug: "aegis",
        stage: "Restore",
        decision: "“Dear Dana Holloway…”",
        detail: "The reply comes back readable. A support agent sees the card as •••• 1111.",
      },
      {
        slug: "lens",
        stage: "Screen",
        decision: "PII, URL, and route checks on the span",
        detail: "Lens runs a cheap screen on every Aegis span, through an adapter on synthetic traces.",
        contract: true,
      },
    ],
    outcome: "The provider never learns who the customer is, and four audit events are written.",
    source: { label: "Aegis demo guide, scenario 1", href: blob("secure-ai-gateway/docs/demo-guide.md") },
  },
  {
    id: "confidential",
    label: "A confidential note with no pattern",
    asker: "Avery Quill, support agent",
    input: "A confidential planning note about unannounced sales, with no names, numbers, or emails in it.",
    steps: [
      {
        slug: "aegis",
        stage: "Detect",
        decision: "0 entities found",
        detail: "A regex-only DLP tool would have allowed this.",
      },
      {
        slug: "aegis",
        stage: "Label",
        decision: "CONFIDENTIAL at 0.89",
        detail: "A private classifier inside the gateway. Top words: unannounced, sales, planning.",
      },
      {
        slug: "aegis",
        stage: "Decide",
        decision: "local_only",
        detail: "Labelling the text never sent it anywhere.",
        tone: "hold",
      },
      {
        slug: "model",
        stage: "Hosted model",
        decision: "Received nothing",
        detail: "The answer comes from the local model inside the boundary.",
        tone: "stop",
      },
      {
        slug: "switchboard",
        stage: "Route",
        decision: "R-SENSITIVE-LOCAL",
        detail: "Switchboard reaches the same answer on its own: confidential text is pinned to local, with no fallback.",
        contract: true,
      },
    ],
    outcome: "The most damaging leaks often have no pattern at all, so the label decides the route.",
    source: { label: "Aegis demo guide, scenario 2", href: blob("secure-ai-gateway/docs/demo-guide.md") },
  },
  {
    id: "tool",
    label: "An agent emails a record to Gmail",
    asker: "An agent working for Avery Quill",
    input: "Look up a customer and email the full record, card included, to a personal Gmail address.",
    steps: [
      {
        slug: "aegis",
        stage: "Tool guard",
        decision: "lookup_customer → allow",
        tone: "pass",
      },
      {
        slug: "aegis",
        stage: "Tool guard",
        decision: "send_email → block",
        detail:
          "Rule R-TOOL-PERSONAL-DOMAIN. The model only saw [EMAIL_1], so the guard resolves it through the vault to check the real domain.",
        tone: "stop",
      },
      {
        slug: "aegis",
        stage: "Same task, company address",
        decision: "pending_approval",
        detail: "Rule R-TOOL-HIGH-RISK. Approving your own request returns 403 four_eyes.",
        tone: "hold",
      },
      {
        slug: "aegis",
        stage: "Second person approves",
        decision: "Sent, card shown as •••• 1111",
        detail: "The approval expires after 10 minutes and is re-checked against the current policy.",
        tone: "pass",
      },
      {
        slug: "lens",
        stage: "Trace",
        decision: "Blocked tool span in the waterfall",
        detail: "Shown in the Lens demo from synthetic Aegis traces.",
        contract: true,
      },
    ],
    outcome: "Obvious exfiltration is blocked, and risky but legitimate work keeps moving with a second person.",
    source: { label: "Aegis demo guide, scenario 3", href: blob("secure-ai-gateway/docs/demo-guide.md") },
  },
  {
    id: "salary",
    label: "Sales asks for salary bands",
    asker: "Bob, Sales ops analyst",
    input: "What are the salary bands for level L5?",
    steps: [
      {
        slug: "lumen",
        stage: "Retrieve",
        decision: "Access control inside the query",
        detail: "The restricted compensation document is never a candidate for this user.",
      },
      {
        slug: "lumen",
        stage: "Gate",
        decision: "Refused: low_rerank_score",
        detail: "Nothing Bob may see answers the question well enough.",
        tone: "stop",
      },
      {
        slug: "lumen",
        stage: "Answer",
        decision: "“Not found in the provided documents.”",
        detail: "The baseline pipeline, without these steps, printed the L5 band.",
      },
      {
        slug: "lumen",
        stage: "Same question, HR admin",
        decision: "The L5 band, cited",
        tone: "pass",
      },
    ],
    outcome: "Across the eval set, restricted-document leaks went from 100% to 0%.",
    source: { label: "Lumen demo output", href: blob("rag-knowledge-assistant/eval_results/demo_output.md") },
  },
];
