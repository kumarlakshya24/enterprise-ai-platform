from __future__ import annotations

import pytest

from forge.guard.ast_guard import check_python
from forge.guard.imports import GuardError
from forge.policy.schema import load_default_policy

POLICY = load_default_policy()
ALLOW = frozenset(POLICY.imports.allow)
DENY = frozenset(POLICY.imports.deny)


def _check(code: str, max_bytes: int = 4000) -> None:
    check_python(code, allow=ALLOW, deny=DENY, max_bytes=max_bytes)


def test_math_snippet_is_allowed() -> None:
    _check("import math\nprint(int(math.sqrt(9)))")


@pytest.mark.parametrize(
    ("code", "rule"),
    [
        ("import os", "R-IMPORT-HARD-DENY"),
        ("import socket", "R-IMPORT-HARD-DENY"),
        ("from os import listdir", "R-IMPORT-HARD-DENY"),
        ("import urllib.request", "R-IMPORT-HARD-DENY"),
        ("import pathlib", "R-IMPORT-DENY"),
        ("import csv", "R-IMPORT-NOT-ALLOWLISTED"),
        ("from . import name", "R-IMPORT-RELATIVE"),
        ("print(eval('1'))", "R-NAME-DENIED"),
        ("open('x')", "R-NAME-DENIED"),
        ("print(value.__class__)", "R-ATTR-DENIED"),
        ("print(fn.__globals__)", "R-ATTR-DENIED"),
        ("(", "R-SYNTAX"),
    ],
)
def test_denied_snippets(code: str, rule: str) -> None:
    with pytest.raises(GuardError) as caught:
        _check(code)
    assert caught.value.rule == rule


def test_hard_deny_wins_even_if_allow_lists_os() -> None:
    with pytest.raises(GuardError) as caught:
        check_python("import os", allow=frozenset({"os", "math"}), deny=frozenset(), max_bytes=1000)
    assert caught.value.rule == "R-IMPORT-HARD-DENY"


def test_code_size_limit() -> None:
    with pytest.raises(GuardError) as caught:
        _check("x = 1\n" * 800, max_bytes=100)
    assert caught.value.rule == "R-LIMIT-CODE"
