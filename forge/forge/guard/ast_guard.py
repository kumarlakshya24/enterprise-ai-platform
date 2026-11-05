"""AST gate for untrusted Python snippets.

The gate looks at the snippet only. Allowed stdlib modules are already compiled
and are not re-parsed here.
"""

from __future__ import annotations

import ast
from collections.abc import Set

from forge.guard.constants import DENIED_ATTRS, DENIED_NAMES
from forge.guard.imports import GuardError, classify_module


def check_python(
    code: str,
    *,
    allow: Set[str],
    deny: Set[str],
    max_bytes: int,
) -> None:
    size = len(code.encode("utf-8"))
    if size > max_bytes:
        raise GuardError("R-LIMIT-CODE", f"code is {size} bytes; limit is {max_bytes}")
    try:
        tree = ast.parse(code, filename="<sandbox>")
    except SyntaxError as exc:
        raise GuardError("R-SYNTAX", "snippet is not valid Python") from exc
    _Visitor(allow, deny).visit(tree)


class _Visitor(ast.NodeVisitor):
    def __init__(self, allow: Set[str], deny: Set[str]) -> None:
        self._allow = allow
        self._deny = deny

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            self._module(alias.name)
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.level:
            raise GuardError("R-IMPORT-RELATIVE", "relative imports are denied")
        if node.module:
            self._module(node.module)
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        attr = node.attr
        if attr in DENIED_ATTRS or (attr.startswith("__") and attr.endswith("__")):
            raise GuardError("R-ATTR-DENIED", f"attribute {attr} is denied")
        self.generic_visit(node)

    def visit_Name(self, node: ast.Name) -> None:
        name = node.id
        if name in DENIED_NAMES or (name.startswith("__") and name.endswith("__")):
            raise GuardError("R-NAME-DENIED", f"name {name} is denied")
        self.generic_visit(node)

    def _module(self, name: str) -> None:
        rule = classify_module(name, allow=self._allow, deny=self._deny)
        if rule == "R-IMPORT-HARD-DENY":
            raise GuardError(rule, f"{name.split('.', 1)[0]} cannot be granted by policy")
        if rule == "R-IMPORT-DENY":
            raise GuardError(rule, f"{name.split('.', 1)[0]} is denied by policy")
        if rule == "R-IMPORT-NOT-ALLOWLISTED":
            raise GuardError(rule, f"{name.split('.', 1)[0]} is not on the import allowlist")
