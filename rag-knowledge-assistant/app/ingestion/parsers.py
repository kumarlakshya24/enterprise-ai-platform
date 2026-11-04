"""Format-specific parsers that turn files into structural `Block`s.

Every parser preserves:
  * the heading hierarchy (each block carries its full heading path),
  * tables as single atomic blocks rendered as Markdown (header row kept),
  * numbered policy clauses ("2.1 ...") and list items as their own units,
  * document metadata (front-matter, PDF sidecar `.meta.yaml`, or API-supplied).
"""
from __future__ import annotations

import datetime as dt
import re
from pathlib import Path
from typing import Any

import yaml

from app.models import Block, DocumentMeta, ParsedDocument

SUPPORTED_SUFFIXES = {".md", ".markdown", ".txt", ".pdf"}
_CLAUSE_RE = re.compile(r"^(\d+(?:\.\d+)+)\s+\S")
_LIST_RE = re.compile(r"^(\s*)([-*+]|\d+[.)])\s+(.*)$")
_FRONT_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.S)


class ParseError(ValueError):
    pass


# --------------------------------------------------------------------------- metadata

def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def build_meta(raw: dict[str, Any], fallback_id: str, fallback_title: str) -> DocumentMeta:
    known = {"doc_id", "title", "team", "doc_type", "version", "updated", "visibility", "allowed_roles", "audience"}
    updated = raw.get("updated")
    if isinstance(updated, str):
        updated = dt.date.fromisoformat(updated)
    visibility = str(raw.get("visibility", "public")).lower()
    if visibility not in {"public", "team", "restricted"}:
        raise ParseError(f"invalid visibility '{visibility}'")
    if visibility == "restricted" and not raw.get("allowed_roles"):
        raise ParseError("restricted documents must declare allowed_roles")
    audience = raw.get("audience") or ["all"]
    if isinstance(audience, str):
        audience = [a.strip() for a in audience.split(",")]
    roles = raw.get("allowed_roles") or []
    if isinstance(roles, str):
        roles = [r.strip() for r in roles.split(",")]
    return DocumentMeta(
        doc_id=_slug(str(raw.get("doc_id") or fallback_id)),
        title=str(raw.get("title") or fallback_title),
        team=str(raw.get("team", "company")).lower(),
        doc_type=str(raw.get("doc_type", "document")).lower(),
        version_label=str(raw.get("version", "1.0")),
        updated=updated,
        visibility=visibility,
        allowed_roles=[str(r).lower() for r in roles],
        audience=[str(a).lower() for a in audience],
        extra={k: v for k, v in raw.items() if k not in known},
    )


def split_front_matter(text: str) -> tuple[dict[str, Any], str]:
    m = _FRONT_RE.match(text)
    if not m:
        return {}, text
    data = yaml.safe_load(m.group(1)) or {}
    if not isinstance(data, dict):
        raise ParseError("front-matter must be a mapping")
    return data, text[m.end():]


# --------------------------------------------------------------------------- markdown

def _is_table_line(line: str) -> bool:
    s = line.strip()
    return s.startswith("|") and s.endswith("|") and s.count("|") >= 2


def _normalize_table(lines: list[str]) -> str:
    return "\n".join(line.strip() for line in lines)


def parse_markdown_body(body: str) -> list[Block]:
    blocks: list[Block] = []
    path: list[tuple[int, str]] = []
    para: list[str] = []
    lines = body.splitlines()

    def hp() -> tuple[str, ...]:
        return tuple(t for _, t in path)

    def flush_para() -> None:
        if para:
            text = " ".join(p.strip() for p in para).strip()
            if text:
                kind = "clause" if _CLAUSE_RE.match(text) else "paragraph"
                blocks.append(Block(kind, text, heading_path=hp()))
            para.clear()

    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if m := re.match(r"^(#{1,6})\s+(.*)$", stripped):
            flush_para()
            level, title = len(m.group(1)), m.group(2).strip()
            while path and path[-1][0] >= level:
                path.pop()
            path.append((level, title))
            blocks.append(Block("heading", title, level=level, heading_path=hp()))
        elif _is_table_line(stripped):
            flush_para()
            tbl = []
            while i < len(lines) and _is_table_line(lines[i]):
                tbl.append(lines[i])
                i += 1
            blocks.append(Block("table", _normalize_table(tbl), heading_path=hp()))
            continue
        elif m := _LIST_RE.match(line):
            flush_para()
            item = [m.group(0).strip()]
            i += 1
            # continuation lines that are indented and not a new item
            while i < len(lines) and lines[i].startswith("   ") and not _LIST_RE.match(lines[i]):
                item.append(lines[i].strip())
                i += 1
            blocks.append(Block("list_item", " ".join(item), heading_path=hp()))
            continue
        elif not stripped:
            flush_para()
        else:
            # a numbered clause always starts a new unit
            if _CLAUSE_RE.match(stripped):
                flush_para()
            para.append(stripped)
        i += 1
    flush_para()
    return blocks


# --------------------------------------------------------------------------- plain text

def _is_text_heading(line: str, nxt: str | None) -> bool:
    s = line.strip()
    if not s or len(s) > 80:
        return False
    if nxt is not None and re.fullmatch(r"[=-]{3,}", nxt.strip() or "x"):
        return True
    letters = [c for c in s if c.isalpha()]
    return bool(letters) and s.upper() == s and not s.endswith(".") and len(s.split()) <= 10


def parse_text_body(body: str) -> list[Block]:
    """Plain text: ALL-CAPS or underlined lines become headings; blank lines split paragraphs.

    Runs of 2+ consecutive short lines without terminal punctuation (e.g. a
    holiday calendar) are one logical list, so each line becomes a list item
    instead of being glued into a run-on paragraph.
    """
    lines = body.splitlines()
    md_lines: list[str] = []
    level_seen = False

    def is_short(s: str) -> bool:
        s = s.strip()
        return bool(s) and len(s) <= 70 and not s.endswith((".", ":", "?", "!"))

    for idx, line in enumerate(lines):
        nxt = lines[idx + 1] if idx + 1 < len(lines) else None
        prv = lines[idx - 1] if idx > 0 else None
        if re.fullmatch(r"\s*[=-]{3,}\s*", line):
            continue
        if _is_text_heading(line, nxt):
            md_lines.append(("# " if not level_seen else "## ") + line.strip())
            level_seen = True
        elif is_short(line) and ((nxt is not None and is_short(nxt)) or (prv is not None and is_short(prv)
                                                                         and not _is_text_heading(prv, line))):
            md_lines.append("- " + line.strip())
        else:
            md_lines.append(line)
    return parse_markdown_body("\n".join(md_lines))


# --------------------------------------------------------------------------- pdf

def parse_pdf(path: Path) -> tuple[list[Block], str, str]:
    """Extract headings (by font size / weight), paragraphs and tables from a PDF.

    Tables are located with pdfplumber's ruling-line detection and emitted as
    Markdown; words that fall inside a table's bbox are excluded from body text,
    so table content is never duplicated or split into loose lines.
    """
    import pdfplumber

    blocks: list[Block] = []
    path_stack: list[tuple[int, str]] = []
    all_text: list[str] = []
    title = ""
    with pdfplumber.open(str(path)) as pdf:
        title = (pdf.metadata or {}).get("Title", "") or ""
        sizes = [round(c["size"], 1) for p in pdf.pages for c in p.chars]
        body_size = max(set(sizes), key=sizes.count) if sizes else 10.0
        for pno, page in enumerate(pdf.pages, start=1):
            tables = page.find_tables()
            bboxes = [t.bbox for t in tables]
            items: list[tuple[float, str, Any]] = []
            for t in tables:
                rows = [[(c or "").replace("\n", " ").strip() for c in r] for r in t.extract()]
                if not rows:
                    continue
                md = ["| " + " | ".join(rows[0]) + " |", "| " + " | ".join("---" for _ in rows[0]) + " |"]
                md += ["| " + " | ".join(r) + " |" for r in rows[1:]]
                items.append((t.bbox[1], "table", "\n".join(md)))

            def outside(obj: dict) -> bool:
                cx, cy = (obj["x0"] + obj["x1"]) / 2, (obj["top"] + obj["bottom"]) / 2
                return not any(b[0] <= cx <= b[2] and b[1] <= cy <= b[3] for b in bboxes)

            words = page.extract_words(extra_attrs=["size", "fontname"], keep_blank_chars=False, use_text_flow=True)
            words = [w for w in words if outside(w)]
            # group words into lines
            lines: list[dict] = []
            for w in words:
                if lines and abs(lines[-1]["top"] - w["top"]) < 2.5:
                    lines[-1]["words"].append(w)
                    lines[-1]["bottom"] = max(lines[-1]["bottom"], w["bottom"])
                else:
                    lines.append({"top": w["top"], "bottom": w["bottom"], "words": [w]})
            # group lines into paragraphs by vertical gap and style
            para: list[dict] = []

            def emit_para() -> None:
                if not para:
                    return
                text = " ".join(" ".join(w["text"] for w in ln["words"]) for ln in para).strip()
                size = max(w["size"] for ln in para for w in ln["words"])
                bold = all("Bold" in w["fontname"] for ln in para for w in ln["words"])
                kind = "heading" if (size > body_size * 1.15 or (bold and len(text) < 90)) else "paragraph"
                items.append((para[0]["top"], kind, (text, size)))
                para.clear()

            for ln in lines:
                if para:
                    gap = ln["top"] - para[-1]["bottom"]
                    same_style = round(max(w["size"] for w in ln["words"]), 1) == round(
                        max(w["size"] for w in para[-1]["words"]), 1)
                    if gap > 4 or not same_style:
                        emit_para()
                para.append(ln)
            emit_para()

            for _, kind, payload in sorted(items, key=lambda x: x[0]):
                if kind == "table":
                    blocks.append(Block("table", payload, heading_path=tuple(t for _, t in path_stack), page=pno))
                    all_text.append(payload)
                elif kind == "heading":
                    text, size = payload
                    level = 1 if size > body_size * 1.6 else 2
                    while path_stack and path_stack[-1][0] >= level:
                        path_stack.pop()
                    path_stack.append((level, text))
                    blocks.append(Block("heading", text, level=level, heading_path=tuple(t for _, t in path_stack), page=pno))
                    all_text.append(text)
                else:
                    text, _ = payload
                    kind2 = "clause" if _CLAUSE_RE.match(text) else "paragraph"
                    blocks.append(Block(kind2, text, heading_path=tuple(t for _, t in path_stack), page=pno))
                    all_text.append(text)
    if not title:
        title = next((b.text for b in blocks if b.kind == "heading"), path.stem)
    return blocks, title, "\n".join(all_text)


# --------------------------------------------------------------------------- entry point

def parse_file(path: Path, data: bytes | None = None, meta_override: dict | None = None) -> ParsedDocument:
    """Parse a file from disk (or raw bytes with its filename) into a ParsedDocument."""
    suffix = path.suffix.lower()
    if suffix not in SUPPORTED_SUFFIXES:
        raise ParseError(f"unsupported file type '{suffix}'")
    sidecar: dict[str, Any] = {}
    side = path.with_suffix(path.suffix + ".meta.yaml")
    if data is None and side.exists():
        sidecar = yaml.safe_load(side.read_text()) or {}

    if suffix == ".pdf":
        if data is not None:
            import tempfile
            with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
                tmp.write(data)
            try:
                blocks, title, raw = parse_pdf(Path(tmp.name))
            finally:
                Path(tmp.name).unlink(missing_ok=True)
        else:
            blocks, title, raw = parse_pdf(path)
        front: dict[str, Any] = {}
    else:
        text = data.decode("utf-8") if data is not None else path.read_text(encoding="utf-8")
        front, body = split_front_matter(text)
        blocks = parse_text_body(body) if suffix == ".txt" else parse_markdown_body(body)
        raw = body
        title = next((b.text for b in blocks if b.kind == "heading"), path.stem)

    merged = {**sidecar, **front, **(meta_override or {})}
    meta = build_meta(merged, fallback_id=path.stem, fallback_title=title)
    if not any(b.kind != "heading" for b in blocks):
        raise ParseError("document contains no extractable text")
    return ParsedDocument(meta=meta, blocks=blocks, source_path=str(path), raw_text=raw)
