"""Role-based access control: IdP roles -> permissions and per-entity restore scopes."""

from __future__ import annotations

from collections.abc import Iterable

from aegis.types import EntityType, RestoreScope

ROLE_PERMISSIONS: dict[str, frozenset[str]] = {
    "employee": frozenset({"chat", "agent:run", "vault:detokenize:own", "policy:read"}),
    "support_agent": frozenset(),
    "billing_specialist": frozenset(),
    "approver": frozenset({"tool:approve", "approvals:read"}),
    "security_admin": frozenset({"audit:read", "policy:write", "policy:read", "approvals:read"}),
}

_E = EntityType
_EMPLOYEE_RESTORE = {
    _E.PERSON_NAME: RestoreScope.FULL,
    _E.ORG: RestoreScope.FULL,
    _E.EMAIL: RestoreScope.FULL,
    _E.PHONE: RestoreScope.FULL,
    _E.CREDIT_CARD: RestoreScope.MASKED,
    _E.SSN: RestoreScope.MASKED,
}

# Missing entries mean NEVER. Secrets are never restorable for anyone: they are never stored.
ROLE_RESTORE: dict[str, dict[EntityType, RestoreScope]] = {
    "employee": _EMPLOYEE_RESTORE,
    "support_agent": _EMPLOYEE_RESTORE,
    "billing_specialist": {_E.CREDIT_CARD: RestoreScope.FULL},
    "approver": {},
    "security_admin": {},  # separation of duties: admins do not get extra access to data
}


def permissions_for(roles: Iterable[str]) -> frozenset[str]:
    perms: set[str] = set()
    for role in roles:
        perms |= ROLE_PERMISSIONS.get(role, frozenset())
    return frozenset(perms)


def restore_scopes_for(roles: Iterable[str]) -> dict[EntityType, RestoreScope]:
    scopes = dict.fromkeys(EntityType, RestoreScope.NEVER)
    for role in roles:
        for etype, scope in ROLE_RESTORE.get(role, {}).items():
            scopes[etype] = max(scopes[etype], scope)
    return scopes
