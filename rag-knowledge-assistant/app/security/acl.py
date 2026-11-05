"""Identity and access control.

Two distinct mechanisms, both enforced in SQL *before* ranking:
  * visibility (security boundary): public | team (owning team only) |
    restricted (named roles only). Violating this is a data leak.
  * audience (relevance scope): which teams a policy applies to. A Sales-only
    policy may be readable by everyone, but should not answer a Finance
    analyst's question. Applied as a metadata filter, overridable per request.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml

from app.models import Principal


class UnknownUser(KeyError):
    pass


@lru_cache
def _load(path: str) -> dict:
    return yaml.safe_load(Path(path).read_text())["users"]


def get_principal(user_id: str, users_file: Path) -> Principal:
    users = _load(str(users_file))
    if user_id not in users:
        raise UnknownUser(user_id)
    u = users[user_id]
    return Principal(
        user_id=user_id, team=u["team"], roles=list(u["roles"]), display_name=u.get("display_name", user_id)
    )


def list_users(users_file: Path) -> dict:
    return _load(str(users_file))


def acl_sql(alias: str = "c") -> str:
    """SQL predicate for document visibility. Params: %(acl_team)s, %(acl_roles)s."""
    return (
        f"({alias}.visibility = 'public' OR ({alias}.visibility = 'team' AND {alias}.team = %(acl_team)s) "
        f"OR ({alias}.visibility = 'restricted' AND {alias}.allowed_roles && %(acl_roles)s::text[]))"
    )


def can_read(principal: Principal, visibility: str, team: str, allowed_roles: list[str]) -> bool:
    if visibility == "public":
        return True
    if visibility == "team":
        return principal.team == team
    return bool(set(principal.roles) & set(allowed_roles))
