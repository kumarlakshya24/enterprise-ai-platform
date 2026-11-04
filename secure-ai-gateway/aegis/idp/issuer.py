"""Mock OIDC identity provider: synthetic directory and RS256 token issuance.

Stands in for Okta or Entra ID. Includes accounts the gateway must reject: a consumer account
signed in with a password (no SSO) and a user from a different tenant.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from typing import Any

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm


@dataclass(frozen=True)
class DirectoryUser:
    username: str
    sub: str
    name: str
    email: str
    tenant_id: str
    roles: tuple[str, ...]
    amr: tuple[str, ...] = ("sso", "mfa")
    description: str = ""


# Synthetic people. Corporate domain uses the reserved .example TLD.
DIRECTORY: dict[str, DirectoryUser] = {
    u.username: u
    for u in [
        DirectoryUser(
            "avery",
            "u-1001",
            "Avery Quill",
            "avery.quill@acme.example",
            "acme",
            ("employee", "support_agent"),
            description="Support agent (requester in demos)",
        ),
        DirectoryUser(
            "morgan",
            "u-1002",
            "Morgan Vale",
            "morgan.vale@acme.example",
            "acme",
            ("employee", "approver"),
            description="Support team lead (approves risky tool calls)",
        ),
        DirectoryUser(
            "sam",
            "u-1003",
            "Sam Ryder",
            "sam.ryder@acme.example",
            "acme",
            ("employee", "security_admin"),
            description="Security admin (policies, audit)",
        ),
        DirectoryUser(
            "riley",
            "u-1004",
            "Riley Chen",
            "riley.chen@acme.example",
            "acme",
            ("employee",),
            description="Employee in another team (RBAC denial demo)",
        ),
        DirectoryUser(
            "taylor",
            "u-1005",
            "Taylor Brook",
            "taylor.brook@acme.example",
            "acme",
            ("employee", "billing_specialist"),
            description="Billing specialist (sees full card numbers)",
        ),
        DirectoryUser(
            "legal-bot",
            "u-legal-bot",
            "Legal Assistant Bot",
            "legal-bot@acme.example",
            "acme",
            ("employee",),
            description="Service account with a per-user override (local-only)",
        ),
        DirectoryUser(
            "personal",
            "u-9001",
            "Personal Account",
            "someone@consumer.example",
            "consumers",
            ("employee",),
            amr=("pwd",),
            description="Consumer account, password login: must be rejected",
        ),
        DirectoryUser(
            "contractor",
            "u-7001",
            "Globex Contractor",
            "contractor@globex.example",
            "globex",
            ("employee",),
            description="SSO user from another tenant: must be rejected",
        ),
    ]
}


class TokenIssuer:
    def __init__(
        self, issuer: str, audience: str, private_key_pem: bytes | None = None, kid: str | None = None
    ) -> None:
        self.issuer = issuer
        self.audience = audience
        if private_key_pem:
            key = serialization.load_pem_private_key(private_key_pem, password=None)
            if not isinstance(key, rsa.RSAPrivateKey):
                raise ValueError("IdP key must be RSA")
            self._key = key
        else:
            self._key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self.kid = kid or uuid.uuid4().hex[:16]

    def public_key(self) -> rsa.RSAPublicKey:
        return self._key.public_key()

    def jwks(self) -> dict[str, Any]:
        jwk = RSAAlgorithm.to_jwk(self.public_key(), as_dict=True)
        jwk.update({"kid": self.kid, "use": "sig", "alg": "RS256"})
        return {"keys": [jwk]}

    def issue(self, user: DirectoryUser, ttl_seconds: int = 3600, **extra: Any) -> str:
        now = int(time.time())
        claims: dict[str, Any] = {
            "iss": self.issuer,
            "aud": self.audience,
            "sub": user.sub,
            "iat": now,
            "nbf": now,
            "exp": now + ttl_seconds,
            "tid": user.tenant_id,
            "email": user.email,
            "name": user.name,
            "roles": list(user.roles),
            "amr": list(user.amr),
            "jti": uuid.uuid4().hex,
        }
        claims.update(extra)
        return jwt.encode(claims, self._key, algorithm="RS256", headers={"kid": self.kid})
