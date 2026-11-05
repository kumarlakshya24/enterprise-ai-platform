"""Build the pre-ranking WHERE clause shared by vector and BM25 retrieval.

Filtering happens inside the SQL that produces candidates, never after ranking,
so (a) a user can never see a chunk they are not entitled to, even in debug
output, and (b) the top-k slots are not wasted on chunks that would be removed.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from app.models import Principal
from app.security.acl import acl_sql


@dataclass
class QueryFilters:
    teams: list[str] | None = None        # explicit owning-team filter from the request
    doc_types: list[str] | None = None
    audience_scope: bool = True           # restrict to docs whose audience includes the user's team or 'all'
    audience_teams: list[str] | None = None  # override: answer "as if" for these teams
    extra: dict = field(default_factory=dict)


def build_where(principal: Principal | None, filters: QueryFilters | None, enforce_acl: bool,
                alias: str = "c") -> tuple[str, dict]:
    clauses: list[str] = []
    params: dict = {}
    if enforce_acl:
        if principal is None:
            raise PermissionError("ACL enforcement requires an authenticated principal")
        clauses.append(acl_sql(alias))
        params.update(acl_team=principal.team, acl_roles=principal.roles)
    f = filters or QueryFilters(audience_scope=False)
    if f.teams:
        clauses.append(f"{alias}.team = ANY(%(f_teams)s::text[])")
        params["f_teams"] = f.teams
    if f.doc_types:
        clauses.append(f"{alias}.doc_type = ANY(%(f_types)s::text[])")
        params["f_types"] = f.doc_types
    if f.audience_scope and (principal is not None or f.audience_teams):
        aud = list(f.audience_teams or [principal.team])  # type: ignore[union-attr]
        clauses.append(f"{alias}.audience && %(f_aud)s::text[]")
        params["f_aud"] = aud + ["all"]
    return (" AND ".join(clauses) if clauses else "TRUE"), params
