"""Clamp policy numbers to hard ceilings and expose per-tool limits."""

from __future__ import annotations

from forge.guard.constants import KNOWN_TOOLS, SHELL_TOOL
from forge.policy.schema import Policy
from forge.types import Limits


def effective_limits(policy: Policy, tool: str) -> Limits | None:
    """Return clamped limits, or None when the tool is disabled or unknown.

    Shell never returns limits. There is no executor to configure.
    """
    if tool == SHELL_TOOL or tool not in KNOWN_TOOLS:
        return None
    spec = policy.tools.get(tool)
    if spec is None or not spec.enabled:
        return None
    cap = policy.ceilings
    return Limits(
        timeout_ms=min(spec.timeout_ms, cap.timeout_ms),
        max_memory_mb=min(spec.max_memory_mb, cap.max_memory_mb),
        max_output_bytes=min(spec.max_output_bytes, cap.max_output_bytes),
        max_code_bytes=min(spec.max_code_bytes, cap.max_code_bytes),
        max_write_bytes=min(spec.max_write_bytes, cap.max_write_bytes),
        allow_imports=frozenset(policy.imports.allow),
        deny_imports=frozenset(policy.imports.deny),
    )


def tighten(
    limits: Limits,
    *,
    timeout_ms: int | None,
    max_memory_mb: int | None,
    max_output_bytes: int | None,
) -> Limits:
    """Callers may only lower a limit."""
    output = limits.max_output_bytes if max_output_bytes is None else min(limits.max_output_bytes, max_output_bytes)
    return Limits(
        timeout_ms=min(limits.timeout_ms, timeout_ms) if timeout_ms else limits.timeout_ms,
        max_memory_mb=min(limits.max_memory_mb, max_memory_mb) if max_memory_mb else limits.max_memory_mb,
        max_output_bytes=output,
        max_code_bytes=limits.max_code_bytes,
        max_write_bytes=limits.max_write_bytes,
        allow_imports=limits.allow_imports,
        deny_imports=limits.deny_imports,
    )
