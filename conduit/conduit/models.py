"""Value types shared by the log, the chunker, and the index."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Subject:
    id: str
    name: str
    email: str


@dataclass(frozen=True)
class Incoming:
    event_id: str
    op: str
    doc_id: str
    doc_version: int
    title: str
    text: str
    subject_ids: tuple[str, ...]
    source_ts: str


@dataclass(frozen=True)
class Event:
    seq: int
    event_id: str
    op: str
    doc_id: str
    doc_version: int
    title: str
    text: str
    subject_ids: tuple[str, ...]
    source_ts: str


@dataclass(frozen=True)
class Finding:
    kind: str
    replacement: str


@dataclass(frozen=True)
class RedactionResult:
    text: str
    findings: tuple[Finding, ...]


@dataclass(frozen=True)
class Chunk:
    index: int
    text: str
    embed_text: str
    content_hash: str
    subjects: tuple[str, ...]


@dataclass(frozen=True)
class ModelSpec:
    model_id: str
    version: str
    dim: int
    salt: str


@dataclass(frozen=True)
class Generation:
    id: int
    name: str
    model_id: str
    model_version: str
    dim: int
    state: str
    high_water: int


@dataclass
class Migration:
    state: str
    source_id: int | None = None
    target_id: int | None = None
    started_at: str | None = None


@dataclass
class Preview:
    doc_id: str
    title: str
    raw: str
    redacted: str
    findings: list[str] = field(default_factory=list)
