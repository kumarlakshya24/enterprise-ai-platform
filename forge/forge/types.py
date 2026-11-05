"""Shared request and result types."""

from __future__ import annotations

from dataclasses import dataclass, field


class Outcome:
    """String outcomes stored in audit records and reports."""

    ALLOW = "allow"
    DENY = "deny"
    LIMITED = "limited"
    ERROR = "error"


@dataclass(frozen=True)
class Limits:
    """Effective limits after policy defaults are clamped to hard ceilings."""

    timeout_ms: int
    max_memory_mb: int
    max_output_bytes: int
    max_code_bytes: int
    max_write_bytes: int
    allow_imports: frozenset[str]
    deny_imports: frozenset[str]


@dataclass(frozen=True)
class ToolRequest:
    tool: str
    code: str | None = None
    path: str | None = None
    content: str | None = None
    timeout_ms: int | None = None
    max_memory_mb: int | None = None
    max_output_bytes: int | None = None
    actor: str = "agent"


@dataclass(frozen=True)
class Preview:
    """Decision a raw interpreter would make. Never an execution."""

    would_allow: bool
    executed: bool
    risk: str
    note: str


@dataclass
class RunResult:
    tool: str
    outcome: str
    rule: str
    reasons: list[str]
    stdout: str
    spawned: bool
    duration_ms: float
    preview: Preview
    error: str = ""
    audit_seq: int | None = None
    code_sha256: str = ""
    extra: dict[str, str] = field(default_factory=dict)
