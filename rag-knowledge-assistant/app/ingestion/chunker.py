"""Structure-aware semantic chunking.

Algorithm (see ARCHITECTURE.md §Chunking):
  1. Group blocks into *sections* by heading path, so a chunk never straddles two
     unrelated headings.
  2. Inside a section build atomic *units*: a table (with its lead-in sentence),
     a numbered policy clause, a run of list items (with the sentence that
     introduces them), or a paragraph. Units are never split, except tables
     larger than the budget, which are split by row groups with the header row
     repeated, so every piece is still a self-describing table.
  3. If a section exceeds the token budget, split it recursively at the unit
     boundary with the *lowest embedding similarity* between neighbouring units
     (a semantic breakpoint), with a small penalty for unbalanced splits.
  4. Merge undersized neighbouring chunks that are siblings or parent/child,
     so short sections ("Purpose", one-line intros) don't become context-free crumbs.
  5. Each chunk carries a context header (doc title > heading path) that is
     prepended for embedding and shown in citations.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Callable, Sequence

import numpy as np

from app.models import Block, Chunk, ParsedDocument
from app.textproc import estimate_tokens

EmbedFn = Callable[[Sequence[str]], np.ndarray]


@dataclass
class _Unit:
    text: str
    kind: str
    tokens: int


@dataclass
class _Draft:
    path: tuple[str, ...]
    units: list[_Unit]

    @property
    def tokens(self) -> int:
        return sum(u.tokens for u in self.units)


def _split_table(text: str, max_tokens: int) -> list[str]:
    lines = text.split("\n")
    if estimate_tokens(text) <= max_tokens or len(lines) <= 3:
        return [text]
    header, sep, rows = lines[0], lines[1], lines[2:]
    pieces, cur = [], []
    base = estimate_tokens(header + sep)
    for row in rows:
        if cur and base + estimate_tokens("\n".join(cur + [row])) > max_tokens:
            pieces.append("\n".join([header, sep, *cur]))
            cur = []
        cur.append(row)
    if cur:
        pieces.append("\n".join([header, sep, *cur]))
    return pieces


def _build_units(blocks: list[Block], max_tokens: int) -> list[_Unit]:
    units: list[_Unit] = []
    i = 0
    while i < len(blocks):
        b = blocks[i]
        lead_in = None
        # a paragraph ending with ':' introduces the following list/table
        if b.kind == "paragraph" and b.text.rstrip().endswith(":") and i + 1 < len(blocks) \
                and blocks[i + 1].kind in ("list_item", "table"):
            lead_in = b.text
            i += 1
            b = blocks[i]
        if b.kind == "list_item":
            items = []
            while i < len(blocks) and blocks[i].kind == "list_item":
                items.append(blocks[i].text)
                i += 1
            text = "\n".join(([lead_in] if lead_in else []) + items)
            units.append(_Unit(text, "list", estimate_tokens(text)))
            continue
        if b.kind == "table":
            for piece in _split_table(b.text, max_tokens):
                text = f"{lead_in}\n{piece}" if lead_in else piece
                units.append(_Unit(text, "table", estimate_tokens(text)))
            i += 1
            continue
        if lead_in:
            units.append(_Unit(lead_in, "paragraph", estimate_tokens(lead_in)))
        units.append(_Unit(b.text, b.kind, estimate_tokens(b.text)))
        i += 1
    return units


def _sections(doc: ParsedDocument) -> list[tuple[tuple[str, ...], list[Block]]]:
    out: list[tuple[tuple[str, ...], list[Block]]] = []
    for b in doc.blocks:
        if b.kind == "heading":
            continue
        if out and out[-1][0] == b.heading_path:
            out[-1][1].append(b)
        else:
            out.append((b.heading_path, [b]))
    return out


def _semantic_split(units: list[_Unit], sims: list[float], max_tokens: int, min_tokens: int) -> list[list[_Unit]]:
    total = sum(u.tokens for u in units)
    if total <= max_tokens or len(units) == 1:
        return [units]
    prefix = np.cumsum([u.tokens for u in units])
    n = len(units)
    cands = [j for j in range(1, n) if prefix[j - 1] >= min_tokens and total - prefix[j - 1] >= min_tokens]
    if not cands:
        cands = list(range(1, n))

    def cost(j: int) -> float:
        balance = abs(prefix[j - 1] - (total - prefix[j - 1])) / total
        return sims[j - 1] + 0.15 * balance

    j = min(cands, key=cost)
    return (_semantic_split(units[:j], sims[: j - 1], max_tokens, min_tokens)
            + _semantic_split(units[j:], sims[j:], max_tokens, min_tokens))


def _related(a: tuple[str, ...], b: tuple[str, ...]) -> bool:
    if a[:-1] == b[:-1]:
        return True
    shorter, longer = (a, b) if len(a) <= len(b) else (b, a)
    return longer[: len(shorter)] == shorter


def _render(path: tuple[str, ...], units: list[_Unit], title: str, show_heading: bool) -> str:
    body = "\n".join(u.text for u in units)
    if show_heading and path and path[-1].lower() != title.lower():
        return f"## {path[-1]}\n{body}"
    return body


def chunk_document(doc: ParsedDocument, embed: EmbedFn | None = None,
                   max_tokens: int = 200, min_tokens: int = 40) -> list[Chunk]:
    title = doc.meta.title
    drafts: list[_Draft] = []
    for path, blocks in _sections(doc):
        units = _build_units(blocks, max_tokens)
        if sum(u.tokens for u in units) > max_tokens and len(units) > 1:
            sims = [0.0] * (len(units) - 1)
            if embed is not None:
                vecs = embed([u.text for u in units])
                sims = [float(np.dot(vecs[k], vecs[k + 1])) for k in range(len(units) - 1)]
            for group in _semantic_split(units, sims, max_tokens, min_tokens):
                drafts.append(_Draft(path, group))
        else:
            drafts.append(_Draft(path, units))

    # Merge undersized related neighbours. Each merged part keeps its own heading line.
    merged: list[tuple[tuple[str, ...], str, set[str], int]] = []  # path, text, kinds, tokens
    for d in drafts:
        text = _render(d.path, d.units, title, show_heading=True)
        kinds = {u.kind for u in d.units}
        tok = estimate_tokens(text)
        if merged:
            ppath, ptext, pkinds, ptok = merged[-1]
            if (ptok < min_tokens or tok < min_tokens) and ptok + tok <= max_tokens and _related(ppath, d.path):
                common = tuple(x for x, y in zip(ppath, d.path) if x == y)
                merged[-1] = (common or ppath, f"{ptext}\n{text}", pkinds | kinds, ptok + tok)
                continue
        merged.append((d.path, text, kinds, tok))

    chunks: list[Chunk] = []
    for idx, (path, text, kinds, tok) in enumerate(merged):
        crumbs = [p for p in path if p.lower() != title.lower()]
        header = " > ".join([title, *crumbs])
        ctype = "table" if kinds == {"table"} else ("mixed" if "table" in kinds else "text")
        h = hashlib.sha256(f"{header}\n{text}".encode()).hexdigest()[:16]
        chunks.append(Chunk(index=idx, content=text, heading_path=path, chunk_type=ctype,
                            token_count=tok, context_header=header, content_hash=h))
    return chunks
