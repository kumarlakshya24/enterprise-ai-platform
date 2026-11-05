"""Grounded answer generation with citations and refusal.

Two paths share the same contract (answer text with [n] citations, or a refusal):
  * LLM path - prompt with fenced, PII-redacted context; output is post-validated:
    citations must reference supplied documents, and an answer without a valid
    citation is discarded and treated as a refusal (never return an uncited policy).
  * Extractive path - select the most relevant sentences from the retrieved chunks
    with the cross-encoder, never selecting injection-flagged sentences.
"""

from __future__ import annotations

import logging
import re
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutTimeout
from dataclasses import dataclass, field

import numpy as np

from app.generation.prompts import NOT_FOUND, REFUSAL_TEXT, SYSTEM_PROMPT, user_prompt
from app.models import Candidate, Principal
from app.providers.embeddings import Embedder
from app.providers.llm import LLM
from app.ranking.reranker import Reranker
from app.security import injection, pii
from app.textproc import estimate_tokens, split_sentences

log = logging.getLogger(__name__)
_CITE_RE = re.compile(r"\[(\d+)\]")


@dataclass
class GenerationResult:
    text: str
    refused: bool
    citations: list[dict] = field(default_factory=list)
    reason: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    projected_input_tokens: int = 0
    projected_output_tokens: int = 0
    model: str = ""
    redactions: Counter = field(default_factory=Counter)
    degraded: list[str] = field(default_factory=list)
    top_score: float | None = None  # best evidence score (extractive path), for calibration


def _table_row_sentences(table: str) -> list[str]:
    lines = [ln for ln in table.split("\n") if ln.strip().startswith("|")]
    if len(lines) < 3:
        return []
    cells = lambda ln: [c.strip() for c in ln.strip().strip("|").split("|")]  # noqa: E731
    header = cells(lines[0])
    out = []
    for ln in lines[2:]:
        row = cells(ln)
        out.append("; ".join(f"{h}: {v}" for h, v in zip(header, row, strict=False) if v))
    return out


def candidate_segments(c: Candidate, guard: bool) -> list[tuple[str, str]]:
    """Return (section, text) answer candidates: single sentences and 2-sentence windows.

    Windows let the cross-encoder pick "Employees may carry over 5 days. Carried-over
    days expire on March 31." as one unit instead of truncating mid-thought. Table
    rows become "Header: value; ..." sentences and are never windowed together.
    """
    section = c.heading_path[-1] if c.heading_path else ""
    out: list[tuple[str, str]] = []
    block: list[str] = []
    table: list[str] = []

    def flush_block() -> None:
        sents = [x for x in block if len(x.split()) >= 3]
        if guard:
            sents = [x for x in sents if not injection.is_risky(x)]
        out.extend((section, x) for x in sents)
        out.extend((section, f"{a} {b}") for a, b in zip(sents, sents[1:], strict=False))
        block.clear()

    for line in c.content.split("\n") + [""]:
        if line.strip().startswith("|"):
            table.append(line)
            continue
        if table:
            flush_block()
            out.extend((section, r) for r in _table_row_sentences("\n".join(table)))
            table = []
        if line.startswith("#"):
            flush_block()
            section = line.lstrip("# ").strip()
            continue
        if not line.strip():
            continue
        block.extend(split_sentences(re.sub(r"^\s*(?:[-*+]|\d+[.)])\s+", "", line)))
    flush_block()
    return out


def _section(c: Candidate) -> str:
    sec = c.heading_path[-1] if c.heading_path else ""
    return "" if sec.lower() == c.title.lower() else sec


def _cite(contexts: list[Candidate], idxs: list[int]) -> list[dict]:
    out = []
    for i in sorted(set(idxs)):
        c = contexts[i - 1]
        out.append(
            {
                "index": i,
                "doc_id": c.doc_id,
                "title": c.title,
                "chunk_id": c.chunk_id,
                "chunk_index": c.chunk_index,
                "section": _section(c),
                "version": c.version_label,
                "reference": c.citation_ref(),
            }
        )
    return out


class Generator:
    def __init__(
        self,
        llm: LLM,
        reranker: Reranker | None,
        embedder: Embedder,
        max_tokens: int,
        min_sentence_score: float,
        executor: ThreadPoolExecutor,
    ):
        self.llm, self.reranker, self.embedder = llm, reranker, embedder
        self.max_tokens, self.min_sentence_score = max_tokens, min_sentence_score
        self.executor = executor

    def refusal(self, reason: str) -> GenerationResult:
        return GenerationResult(REFUSAL_TEXT, True, reason=reason, model=self.llm.name)

    # ------------------------------------------------------------------ public
    def generate(
        self,
        question: str,
        contexts: list[Candidate],
        principal: Principal | None,
        redact_pii: bool,
        guard_injection: bool,
        budget_ms: int,
    ) -> GenerationResult:
        if not contexts:
            return self.refusal("no_context")
        projected_in = estimate_tokens(SYSTEM_PROMPT + user_prompt(question, contexts, principal))
        if not self.llm.generative:
            res = self.extractive(question, contexts, guard_injection)
            res.projected_input_tokens = projected_in
            res.projected_output_tokens = estimate_tokens(res.text) + 10
            return res
        fut = self.executor.submit(self._llm_answer, question, contexts, principal, redact_pii, budget_ms / 1000)
        try:
            res = fut.result(timeout=budget_ms / 1000 + 1)
        except (FutTimeout, Exception) as e:  # noqa: BLE001 - slow path: degrade, don't fail the request
            log.warning("generation fallback to extractive: %s", type(e).__name__)
            res = self.extractive(question, contexts, guard_injection)
            res.degraded.append(f"generation_{'timeout' if isinstance(e, FutTimeout) else 'error'}")
        res.projected_input_tokens = res.input_tokens or projected_in
        res.projected_output_tokens = res.output_tokens or estimate_tokens(res.text)
        return res

    # ------------------------------------------------------------------ LLM path
    def _llm_answer(
        self, question: str, contexts: list[Candidate], principal: Principal | None, redact_pii: bool, timeout_s: float
    ) -> GenerationResult:
        red = Counter()
        ctx = contexts
        if redact_pii:
            ctx = []
            for c in contexts:
                r = pii.redact(c.content)
                red.update(r.counts)
                ctx.append(Candidate(**{**c.__dict__, "content": r.text}))
        out = self.llm.complete(SYSTEM_PROMPT, user_prompt(question, ctx, principal), self.max_tokens, timeout_s)
        text = out.text.strip()
        base = dict(input_tokens=out.input_tokens, output_tokens=out.output_tokens, model=out.model, redactions=red)
        if not text or text.startswith(NOT_FOUND):
            return GenerationResult(REFUSAL_TEXT, True, reason="model_not_found", **base)
        idxs = [int(n) for n in _CITE_RE.findall(text)]
        valid = [i for i in idxs if 1 <= i <= len(contexts)]
        text = _CITE_RE.sub(lambda m: m.group(0) if 1 <= int(m.group(1)) <= len(contexts) else "", text)
        if not valid:
            log.warning("discarding uncited LLM answer")
            return GenerationResult(REFUSAL_TEXT, True, reason="uncited_answer", **base)
        return GenerationResult(text, False, _cite(contexts, valid), **base)

    # ------------------------------------------------------------------ extractive path
    def extractive(
        self,
        question: str,
        contexts: list[Candidate],
        guard_injection: bool,
        max_segments: int = 2,
        margin: float = 1.5,
    ) -> GenerationResult:
        pool: list[tuple[int, str, str]] = []
        for i, c in enumerate(contexts, start=1):
            pool += [(i, sec, txt) for sec, txt in candidate_segments(c, guard_injection)]
        if not pool:
            return self.refusal("no_extractable_sentences")
        texts = [f"{contexts[i - 1].title} - {sec}: {txt}" for i, sec, txt in pool]
        if self.reranker is not None:
            scores = np.asarray(self.reranker.score(question, texts), dtype=np.float32)
            threshold = self.min_sentence_score
        else:
            qv = self.embedder.embed([question])[0]
            scores = self.embedder.embed(texts) @ qv
            threshold = 0.3
        order = [int(j) for j in np.argsort(-scores)]
        best = float(scores[order[0]])
        if best < threshold:
            res = GenerationResult(REFUSAL_TEXT, True, reason="low_sentence_relevance", model="extractive")
            res.top_score = best
            return res
        chosen: list[int] = []
        for j in order:
            if scores[j] < max(threshold, best - margin) or len(chosen) >= max_segments:
                break
            # skip segments that overlap text already chosen (windows share sentences)
            if any(pool[j][2] in pool[k][2] or pool[k][2] in pool[j][2] for k in chosen):
                continue
            chosen.append(j)
        chosen.sort(key=lambda j: (pool[j][0], j))
        parts = [f"{pool[j][2].rstrip()} [{pool[j][0]}]" for j in chosen]
        res = GenerationResult(
            " ".join(parts), False, _cite(contexts, [pool[j][0] for j in chosen]), model="extractive"
        )
        res.top_score = best
        return res
