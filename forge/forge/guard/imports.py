"""Import decisions shared by the parent guard and the sandbox child."""

from __future__ import annotations

from forge.guard.constants import HARD_DENY_MODULES


class GuardError(Exception):
    def __init__(self, rule: str, detail: str) -> None:
        super().__init__(detail)
        self.rule = rule
        self.detail = detail


def module_root(name: str) -> str:
    return name.split(".", 1)[0]


def classify_module(name: str, *, allow: frozenset[str] | set[str], deny: frozenset[str] | set[str]) -> str | None:
    """Return a deny rule, or None when the import is allowed."""
    root = module_root(name)
    if root in HARD_DENY_MODULES or name in HARD_DENY_MODULES:
        return "R-IMPORT-HARD-DENY"
    if root in deny or name in deny:
        return "R-IMPORT-DENY"
    if root not in allow:
        return "R-IMPORT-NOT-ALLOWLISTED"
    return None
