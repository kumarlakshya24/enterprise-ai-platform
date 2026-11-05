"""Mock OIDC IdP service (demo only). Real deployments point OIDC_* settings at Okta/Entra."""

from __future__ import annotations

import os
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from aegis.idp.issuer import DIRECTORY, TokenIssuer

ISSUER = os.environ.get("IDP_ISSUER", "http://idp:9000")
AUDIENCE = os.environ.get("OIDC_AUDIENCE", "aegis-gateway")
_pem = os.environ.get("IDP_PRIVATE_KEY_PEM", "").encode() or None

issuer = TokenIssuer(ISSUER, AUDIENCE, private_key_pem=_pem)
app = FastAPI(title="mock-idp", docs_url=None, redoc_url=None)


class TokenRequest(BaseModel):
    username: str


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/.well-known/openid-configuration")
def discovery() -> dict[str, Any]:
    return {
        "issuer": ISSUER,
        "jwks_uri": f"{ISSUER}/.well-known/jwks.json",
        "token_endpoint": f"{ISSUER}/token",
        "id_token_signing_alg_values_supported": ["RS256"],
        "claims_supported": ["sub", "tid", "email", "name", "roles", "amr"],
    }


@app.get("/.well-known/jwks.json")
def jwks() -> dict[str, Any]:
    return issuer.jwks()


@app.get("/users")
def users() -> list[dict[str, Any]]:
    return [
        {
            "username": u.username,
            "name": u.name,
            "tenant_id": u.tenant_id,
            "roles": list(u.roles),
            "sso": "sso" in u.amr,
            "description": u.description,
        }
        for u in DIRECTORY.values()
    ]


@app.post("/token")
def token(req: TokenRequest) -> dict[str, Any]:
    """Demo sign-in: pick a synthetic user. A real IdP runs the SSO + MFA flow here."""
    user = DIRECTORY.get(req.username)
    if user is None:
        raise HTTPException(404, "unknown demo user")
    return {"access_token": issuer.issue(user), "token_type": "Bearer", "expires_in": 3600}
