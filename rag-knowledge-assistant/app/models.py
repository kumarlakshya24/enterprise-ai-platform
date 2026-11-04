"""Domain objects shared across modules."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any


@dataclass
class Block:
    """A structural unit produced by a parser."""
    kind: str  # heading | paragraph | list_item | clause | table
    text: str
    level: int = 0
    heading_path: tuple[str, ...] = ()
    page: int | None = None


@dataclass
class DocumentMeta:
    doc_id: str
    title: str
    team: str = "company"
    doc_type: str = "document"
    version_label: str = "1.0"
    updated: date | None = None
    visibility: str = "public"  # public | team | restricted
    allowed_roles: list[str] = field(default_factory=list)
    audience: list[str] = field(default_factory=lambda: ["all"])
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class ParsedDocument:
    meta: DocumentMeta
    blocks: list[Block]
    source_path: str | None = None
    raw_text: str = ""


@dataclass
class Chunk:
    index: int
    content: str
    heading_path: tuple[str, ...]
    chunk_type: str  # text | table | mixed
    token_count: int
    context_header: str
    content_hash: str = ""
    pii_types: list[str] = field(default_factory=list)
    injection_risk: float = 0.0

    @property
    def embed_text(self) -> str:
        return f"{self.context_header}\n{self.content}"


@dataclass
class Principal:
    user_id: str
    team: str
    roles: list[str]
    display_name: str = ""

    def scope_key(self) -> str:
        return f"{self.team}|{','.join(sorted(self.roles))}"


@dataclass
class Candidate:
    chunk_id: str
    score: float
    doc_id: str = ""
    title: str = ""
    team: str = ""
    content: str = ""
    heading_path: list[str] = field(default_factory=list)
    chunk_index: int = 0
    doc_version: int = 0
    version_label: str = ""
    injection_risk: float = 0.0
    pii_types: list[str] = field(default_factory=list)
    context_header: str = ""
    ranks: dict[str, int] = field(default_factory=dict)  # stage -> 1-based rank
    scores: dict[str, float] = field(default_factory=dict)

    def citation_ref(self) -> str:
        return f"{self.title} › chunk {self.chunk_index}"
