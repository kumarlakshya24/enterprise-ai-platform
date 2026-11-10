"""Evaluate a policy bundle. Forbid overrides permit. No match is a deny."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from charter.policy.syntax import (
    Bin,
    Bundle,
    Compare,
    Expr,
    FieldPath,
    ListLit,
    Lit,
    Not,
    PathVal,
    Statement,
    Value,
    parse_policies,
)

SEVERITY: dict[str, int] = {
    "R-PROHIBITED": 100,
    "R-RESTRICTED-BLOCK": 90,
    "R-RESIDENCY-EU": 80,
    "R-OVERSIGHT": 70,
    "R-CARD-INCOMPLETE": 60,
    "R-POLICY-ERROR": 50,
    "R-MODEL-UNKNOWN": 40,
    "R-DEFAULT-DENY": 10,
}


class PolicyError(Exception):
    def __init__(self, message: str, rule_id: str) -> None:
        self.rule_id = rule_id
        super().__init__(message)


@dataclass(frozen=True)
class Request:
    principal: str
    model_id: str
    purpose: str
    data_class: str
    data_residency: str
    action: str = "invoke"
    tenant: str = "acme"

    def as_dict(self) -> dict[str, str]:
        return {
            "principal": self.principal,
            "model_id": self.model_id,
            "purpose": self.purpose,
            "data_class": self.data_class,
            "data_residency": self.data_residency,
            "action": self.action,
            "tenant": self.tenant,
        }


@dataclass(frozen=True)
class Decision:
    effect: str
    rule_ids: tuple[str, ...]
    primary_rule: str
    reason: str
    model_id: str
    matched_permits: tuple[str, ...]
    matched_forbids: tuple[str, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "effect": self.effect,
            "rule_ids": list(self.rule_ids),
            "primary_rule": self.primary_rule,
            "reason": self.reason,
            "model_id": self.model_id,
            "matched_permits": list(self.matched_permits),
            "matched_forbids": list(self.matched_forbids),
        }


def load_policies(directory: Path, *, exclude: frozenset[str] = frozenset()) -> Bundle:
    files: dict[str, str] = {}
    for path in sorted(directory.glob("*.cedar")):
        if path.name in exclude:
            continue
        files[path.name] = path.read_text(encoding="utf-8")
    if not files:
        raise FileNotFoundError(f"no policy files in {directory}")
    digest = hashlib.sha256()
    for name in sorted(files):
        digest.update(name.encode())
        digest.update(b"\0")
        digest.update(files[name].encode())
    return Bundle(
        statements=parse_policies(files),
        files=tuple(sorted(files.items())),
        digest=digest.hexdigest(),
    )


def _primary(rule_ids: tuple[str, ...]) -> str:
    return max(rule_ids, key=lambda rule: (SEVERITY.get(rule, 30), rule))


def _resolve(path: FieldPath, env: Mapping[str, Mapping[str, str | bool]], rule_id: str) -> str | bool:
    if path.parts[0] not in env:
        raise PolicyError(f"unknown path {path.dotted()}", rule_id)
    current: object = env[path.parts[0]]
    for part in path.parts[1:]:
        if not isinstance(current, Mapping) or part not in current:
            raise PolicyError(f"unknown path {path.dotted()}", rule_id)
        current = current[part]
    if isinstance(current, bool | str):
        return current
    raise PolicyError(f"path {path.dotted()} is not a string or bool", rule_id)


def _right(value: Value, env: Mapping[str, Mapping[str, str | bool]], rule_id: str) -> object:
    if isinstance(value, Lit):
        return value.value
    if isinstance(value, ListLit):
        return value.values
    if not isinstance(value, PathVal):
        raise PolicyError("value is not comparable", rule_id)
    return _resolve(value.path, env, rule_id)


def _eval(expr: Expr, env: Mapping[str, Mapping[str, str | bool]], rule_id: str) -> bool:
    if isinstance(expr, Not):
        return not _eval(expr.expr, env, rule_id)
    if isinstance(expr, Bin):
        left = _eval(expr.left, env, rule_id)
        if expr.op == "&&":
            return left and _eval(expr.right, env, rule_id)
        return left or _eval(expr.right, env, rule_id)
    return _compare(expr, env, rule_id)


def _compare(expr: Compare, env: Mapping[str, Mapping[str, str | bool]], rule_id: str) -> bool:
    left = _resolve(expr.path, env, rule_id)
    right = _right(expr.right, env, rule_id)
    if expr.op == "in":
        if not isinstance(right, tuple):
            raise PolicyError(f"{expr.path.dotted()} in a non-list", rule_id)
        return left in right
    if expr.op == "==":
        return left == right
    return left != right


def _head(statement: Statement, env: Mapping[str, Mapping[str, str | bool]]) -> bool:
    for slot in (statement.principal, statement.action, statement.resource):
        if slot.entity is None:
            continue
        node = env[slot.name]
        if node["type"] != slot.entity.type_name or node["id"] != slot.entity.id:
            return False
    return True


def _deny(model_id: str, rule: str, reason: str) -> Decision:
    return Decision(
        effect="deny",
        rule_ids=(rule,),
        primary_rule=rule,
        reason=reason,
        model_id=model_id,
        matched_permits=(),
        matched_forbids=(rule,)
        if rule not in ("R-DEFAULT-DENY", "R-MODEL-UNKNOWN", "R-POLICY-ERROR")
        else (),
    )


def evaluate(
    bundle: Bundle,
    request: Request,
    resource: Mapping[str, str | bool] | None,
) -> Decision:
    """Decide one invocation.

    `resource` is the model card's scalar fields plus id and type. None means the
    model is not in the registry: the request is denied before any permit can match.
    """
    if not request.principal or not request.action or not request.data_class or not request.data_residency:
        return _deny(request.model_id, "R-POLICY-ERROR", "request context is incomplete")
    if resource is None:
        return _deny(request.model_id, "R-MODEL-UNKNOWN", f"{request.model_id} is not in the registry")

    env: dict[str, Mapping[str, str | bool]] = {
        "principal": {"type": "User", "id": request.principal},
        "action": {"type": "Action", "id": request.action},
        "resource": resource,
        "context": {
            "purpose": request.purpose,
            "data_class": request.data_class,
            "data_residency": request.data_residency,
            "tenant": request.tenant,
        },
    }
    permits: list[str] = []
    forbids: list[str] = []
    for statement in bundle.statements:
        try:
            if not _head(statement, env):
                continue
            if statement.when is not None and not _eval(statement.when, env, statement.rule_id):
                continue
        except PolicyError as exc:
            return _deny(request.model_id, "R-POLICY-ERROR", f"{exc.rule_id}: {exc}")
        if statement.effect == "forbid":
            forbids.append(statement.rule_id)
        else:
            permits.append(statement.rule_id)

    if forbids:
        ids = tuple(forbids)
        primary = _primary(ids)
        return Decision(
            effect="deny",
            rule_ids=ids,
            primary_rule=primary,
            reason=f"forbid {primary} overrides {len(permits)} matching permit(s)",
            model_id=request.model_id,
            matched_permits=tuple(permits),
            matched_forbids=ids,
        )
    if permits:
        return Decision(
            effect="allow",
            rule_ids=tuple(permits),
            primary_rule=permits[0],
            reason=f"permit {permits[0]} matched and no forbid matched",
            model_id=request.model_id,
            matched_permits=tuple(permits),
            matched_forbids=(),
        )
    return _deny(request.model_id, "R-DEFAULT-DENY", "no permit matched")
