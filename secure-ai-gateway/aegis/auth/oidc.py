"""JWT verification for SSO-only, tenant-restricted access."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import jwt

from aegis.auth.rbac import permissions_for, restore_scopes_for
from aegis.types import EntityType, RestoreScope


class AuthError(Exception):
    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


@dataclass(frozen=True)
class Principal:
    sub: str
    email: str
    name: str
    tenant_id: str
    roles: frozenset[str]
    permissions: frozenset[str]
    amr: tuple[str, ...] = ()
    restore_scopes: dict[EntityType, RestoreScope] = field(default_factory=dict, compare=False, hash=False)

    def has(self, permission: str) -> bool:
        return permission in self.permissions

    def public(self) -> dict[str, Any]:
        return {"sub": self.sub, "name": self.name, "tenant_id": self.tenant_id, "roles": sorted(self.roles)}


KeyResolver = Callable[[str], Any]


def jwks_resolver(jwks_url: str) -> KeyResolver:
    client = jwt.PyJWKClient(jwks_url, cache_keys=True, lifespan=300, timeout=5)

    def resolve(token: str) -> Any:
        try:
            return client.get_signing_key_from_jwt(token).key
        except jwt.PyJWKClientError as exc:
            raise AuthError(503, "jwks_unavailable", "identity provider keys unavailable") from exc

    return resolve


def static_resolver(public_key: Any) -> KeyResolver:
    return lambda _token: public_key


class TokenVerifier:
    def __init__(
        self,
        *,
        issuer: str,
        audience: str,
        allowed_tenants: list[str],
        key_resolver: KeyResolver,
        required_amr: str = "sso",
        leeway_seconds: int = 30,
    ) -> None:
        self.issuer = issuer
        self.audience = audience
        self.allowed_tenants = frozenset(allowed_tenants)
        self.key_resolver = key_resolver
        self.required_amr = required_amr
        self.leeway = leeway_seconds

    def verify(self, token: str) -> Principal:
        try:
            header = jwt.get_unverified_header(token)
        except jwt.PyJWTError as exc:
            raise AuthError(401, "invalid_token", "malformed token") from exc
        if header.get("alg") != "RS256":
            # Blocks alg=none and HS256/RS256 key-confusion attacks before any key is touched.
            raise AuthError(401, "invalid_token", "unsupported token algorithm")
        key = self.key_resolver(token)
        try:
            claims = jwt.decode(
                token,
                key,
                algorithms=["RS256"],
                audience=self.audience,
                issuer=self.issuer,
                leeway=self.leeway,
                options={"require": ["exp", "iat", "iss", "aud", "sub"]},
            )
        except jwt.ExpiredSignatureError as exc:
            raise AuthError(401, "token_expired", "token expired") from exc
        except jwt.PyJWTError as exc:
            raise AuthError(401, "invalid_token", "token verification failed") from exc

        tenant = str(claims.get("tid", ""))
        if tenant not in self.allowed_tenants:
            raise AuthError(403, "tenant_not_allowed", "this gateway only accepts the company tenant")
        amr = tuple(str(a) for a in claims.get("amr", []))
        if self.required_amr not in amr:
            raise AuthError(
                403, "sso_required", "sign in through company SSO; password logins are not accepted"
            )
        roles = frozenset(str(r) for r in claims.get("roles", []))
        return Principal(
            sub=str(claims["sub"]),
            email=str(claims.get("email", "")),
            name=str(claims.get("name", "")),
            tenant_id=tenant,
            roles=roles,
            permissions=permissions_for(roles),
            amr=amr,
            restore_scopes=restore_scopes_for(roles),
        )
