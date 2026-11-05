"""SSO-only, tenant-restricted sign-in, RBAC on admin routes, and token validation edge cases."""

from __future__ import annotations

import time

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa

from aegis.idp.issuer import DIRECTORY, TokenIssuer
from tests.conftest import AUDIENCE, ISSUER, Gateway


def chat(gw: Gateway, token: str) -> int:
    r = gw.client.post("/chat", json={"message": "hello"}, headers={"Authorization": f"Bearer {token}"})
    return r.status_code


def test_missing_token(gw: Gateway) -> None:
    assert gw.client.post("/chat", json={"message": "hi"}).status_code == 401


def test_company_sso_user_is_accepted(gw: Gateway) -> None:
    assert chat(gw, gw.token("avery")) == 200


def test_personal_password_account_is_rejected(gw: Gateway) -> None:
    r = gw.client.post("/chat", json={"message": "hi"}, headers=gw.headers("personal"))
    assert r.status_code == 403
    assert r.json()["detail"]["code"] == "tenant_not_allowed"


def test_other_tenant_is_rejected_even_with_sso(gw: Gateway) -> None:
    r = gw.client.post("/chat", json={"message": "hi"}, headers=gw.headers("contractor"))
    assert r.status_code == 403 and r.json()["detail"]["code"] == "tenant_not_allowed"


def test_company_tenant_without_sso_is_rejected(gw: Gateway) -> None:
    token = gw.issuer.issue(DIRECTORY["avery"], amr=["pwd"])
    r = gw.client.post("/chat", json={"message": "hi"}, headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 403 and r.json()["detail"]["code"] == "sso_required"


def test_expired_token(gw: Gateway) -> None:
    token = gw.issuer.issue(DIRECTORY["avery"], exp=int(time.time()) - 3600)
    assert chat(gw, token) == 401


def test_wrong_audience_and_issuer(gw: Gateway) -> None:
    assert chat(gw, gw.issuer.issue(DIRECTORY["avery"], aud="some-other-app")) == 401
    other = TokenIssuer("http://evil-idp", AUDIENCE)
    assert chat(gw, other.issue(DIRECTORY["avery"])) == 401


def test_forged_signature(gw: Gateway) -> None:
    forger = TokenIssuer(ISSUER, AUDIENCE, kid=gw.issuer.kid)  # same claims, different private key
    assert chat(gw, forger.issue(DIRECTORY["avery"])) == 401


def test_alg_none_and_hs256_confusion(gw: Gateway) -> None:
    claims = {
        "iss": ISSUER,
        "aud": AUDIENCE,
        "sub": "u-1001",
        "tid": "acme",
        "amr": ["sso"],
        "roles": ["employee", "security_admin"],
        "iat": int(time.time()),
        "exp": int(time.time()) + 600,
    }
    none_token = jwt.encode(claims, key=None, algorithm="none")
    assert chat(gw, none_token) == 401
    hs = jwt.encode(claims, "guessable-shared-secret", algorithm="HS256")
    assert chat(gw, hs) == 401


def test_rbac_audit_requires_permission(gw: Gateway) -> None:
    assert gw.get("/audit", "avery").status_code == 403
    assert gw.get("/audit", "sam").status_code == 200


def test_auth_failures_are_audited_for_security(gw: Gateway) -> None:
    gw.client.post("/chat", json={"message": "hi"}, headers=gw.headers("personal"))
    events = gw.get("/audit", "sam", event_type="auth_failed").json()["events"]
    assert any(e["details"]["code"] == "tenant_not_allowed" for e in events)


def test_unrelated_rsa_key_is_not_trusted(gw: Gateway) -> None:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    claims = {
        "iss": ISSUER,
        "aud": AUDIENCE,
        "sub": "u-1001",
        "tid": "acme",
        "amr": ["sso"],
        "iat": int(time.time()),
        "exp": int(time.time()) + 600,
    }
    assert chat(gw, jwt.encode(claims, key, algorithm="RS256")) == 401
