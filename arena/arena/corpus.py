"""Load the frozen Harborline runbooks and the labeled questions.

A fact lives in the prose of a section. The HTML comment is the label: the phrase
that must show up in a correct answer, the pre-cutoff phrase when the policy moved,
and the alias words the adapter is allowed to memorize. Comments are stripped before
anything is retrieved, so the bench cannot answer from the label line.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

import yaml

from arena.textutil import token_set

_FRONT = re.compile(r"\A---\n(.*?)\n---\n", re.DOTALL)
_H2 = re.compile(r"^## .+$", re.MULTILINE)
_FACT = re.compile(r"<!--\s*fact\s+(.*?)\s*-->", re.DOTALL)
_FREEZE = re.compile(r"<!--\s*freeze\s+(.*?)\s*-->", re.DOTALL)
_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)


@dataclass(frozen=True, slots=True)
class Fact:
    id: str
    doc_id: str
    title: str
    section: str
    visibility: str
    in_freeze: bool
    current_text: str
    freeze_text: str
    include: str
    freeze_include: str
    aliases: str
    length: str
    alias_tokens: frozenset[str]

    @property
    def amended(self) -> bool:
        return self.include != self.freeze_include

    def text_as_of(self, as_of: str) -> str:
        if as_of == "freeze":
            return self.freeze_text
        return self.current_text

    def phrase(self, as_of: str) -> str:
        if as_of == "freeze":
            return self.freeze_include
        return self.include

    def wrong_phrase(self, as_of: str) -> str | None:
        if not self.amended:
            return None
        if as_of == "freeze":
            return self.include
        return self.freeze_include


@dataclass(frozen=True, slots=True)
class Item:
    id: str
    split: str
    question: str
    fact_ids: tuple[str, ...]
    refuse: bool


def _attrs(body: str) -> dict[str, str]:
    found: dict[str, str] = {}
    for part in body.split("|"):
        piece = part.strip()
        if not piece:
            continue
        key, value = piece.split("=", 1)
        found[key.strip()] = value.strip()
    return found


def parse_document(text: str) -> list[Fact]:
    match = _FRONT.match(text)
    if not match:
        raise ValueError("runbook is missing front matter")
    meta = yaml.safe_load(match.group(1)) or {}
    body = text[match.end() :]
    doc_id = str(meta["doc_id"])
    title = str(meta["title"])
    visibility = str(meta.get("visibility", "internal"))
    in_freeze = bool(meta.get("in_freeze", True))
    facts: list[Fact] = []
    headings = list(_H2.finditer(body))
    for index, heading in enumerate(headings):
        end = headings[index + 1].start() if index + 1 < len(headings) else len(body)
        section_name = heading.group(0)[3:].strip()
        block = body[heading.end() : end]
        fact_match = _FACT.search(block)
        if fact_match is None:
            continue
        attrs = _attrs(fact_match.group(1))
        freeze_match = _FREEZE.search(block)
        prose = _COMMENT.sub("", block).strip()
        freeze_text = freeze_match.group(1).strip() if freeze_match else prose
        include = attrs["include"]
        freeze_include = attrs.get("freeze_include", include)
        aliases = attrs.get("aliases", "")
        facts.append(
            Fact(
                id=attrs["id"],
                doc_id=doc_id,
                title=title,
                section=section_name,
                visibility=visibility,
                in_freeze=in_freeze,
                current_text=prose,
                freeze_text=freeze_text,
                include=include,
                freeze_include=freeze_include,
                aliases=aliases,
                length=attrs.get("length", "short"),
                alias_tokens=frozenset(token_set(aliases)),
            )
        )
    return facts


def load_facts(corpus_dir: Path) -> list[Fact]:
    facts: list[Fact] = []
    paths = sorted(corpus_dir.glob("*.md"))
    if not paths:
        raise FileNotFoundError(f"no runbooks in {corpus_dir}")
    for path in paths:
        facts.extend(parse_document(path.read_text(encoding="utf-8")))
    ids = [fact.id for fact in facts]
    if len(ids) != len(set(ids)):
        raise ValueError(f"duplicate fact id in {ids}")
    return facts


def load_questions(path: Path) -> tuple[dict[str, str], list[Item]]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    meta = {
        "version": str(raw["version"]),
        "freeze_date": str(raw["freeze_date"]),
        "domain": str(raw["domain"]),
    }
    items: list[Item] = []
    for row in raw["questions"]:
        items.append(
            Item(
                id=str(row["id"]),
                split=str(row["split"]),
                question=str(row["question"]),
                fact_ids=tuple(row.get("fact_ids") or ()),
                refuse=bool(row.get("refuse", False)),
            )
        )
    ids = [item.id for item in items]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate question id")
    allowed = {"train", "holdout", "staleness", "unanswerable"}
    bad = sorted({item.split for item in items} - allowed)
    if bad:
        raise ValueError(f"unknown split {bad}")
    return meta, items


def corpus_sha256(data_dir: Path) -> str:
    digest = hashlib.sha256()
    paths = sorted((data_dir / "corpus").glob("*.md"))
    paths.append(data_dir / "questions.yaml")
    paths.append(data_dir / "price_card.yaml")
    paths.append(data_dir / "policy.yaml")
    paths.append(data_dir / "scenarios.yaml")
    for path in paths:
        digest.update(path.name.encode())
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()
