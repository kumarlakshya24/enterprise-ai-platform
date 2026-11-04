"""Shared fixtures: an in-process gateway with in-memory stores, a test IdP, and mock LLMs."""

from __future__ import annotations

import secrets
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Any

import pytest
from fastapi.testclient import TestClient

from aegis.auth.oidc import static_resolver
from aegis.config import Settings
from aegis.dlp.engine import DLPEngine
from aegis.gateway.app import create_app
from aegis.gateway.container import Container, build_container
from aegis.idp.issuer import DIRECTORY, TokenIssuer
from aegis.llm.providers import MockProvider
from aegis.policy.schema import Policy
from aegis.policy.store import load_bundle_file
from aegis.vault.backends import MemoryBackend

ISSUER = "http://test-idp"
AUDIENCE = "aegis-gateway"


@pytest.fixture(scope="session")
def issuer() -> TokenIssuer:
    return TokenIssuer(ISSUER, AUDIENCE)


@pytest.fixture(scope="session")
def dlp_engine() -> DLPEngine:
    return DLPEngine.default("spacy")


@pytest.fixture(scope="session")
def default_policy() -> Policy:
    return load_bundle_file().effective("acme", None)


def make_settings(**overrides: Any) -> Settings:
    s = Settings(
        env="test",
        demo_mode=True,
        database_url="sqlite://",
        oidc_issuer=ISSUER,
        oidc_audience=AUDIENCE,
        allowed_tenants=["acme"],
        vault_keys={"k1": secrets.token_bytes(32)},
        vault_active_kid="k1",
        audit_hmac_key=secrets.token_bytes(32),
        rate_limit_per_minute=1000,
    )
    for k, v in overrides.items():
        setattr(s, k, v)
    return s


@dataclass
class Gateway:
    client: TestClient
    container: Container
    issuer: TokenIssuer
    external: MockProvider
    local: MockProvider
    kv: MemoryBackend

    def token(self, username: str, **extra: Any) -> str:
        return self.issuer.issue(DIRECTORY[username], **extra)

    def headers(self, username: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token(username)}"}

    def post(self, path: str, username: str, json: dict[str, Any]) -> Any:
        return self.client.post(path, json=json, headers=self.headers(username))

    def get(self, path: str, username: str, **params: Any) -> Any:
        return self.client.get(path, params=params, headers=self.headers(username))

    def external_saw(self) -> str:
        """Everything the external (third-party) model received, concatenated."""
        return "\n".join(str(m.get("content") or "") for r in self.external.received for m in r["messages"])


@pytest.fixture
def gateway_factory(issuer: TokenIssuer, dlp_engine: DLPEngine) -> Iterator[Callable[..., Gateway]]:
    created: list[TestClient] = []

    def factory(**settings_overrides: Any) -> Gateway:
        settings = make_settings(**settings_overrides)
        external = MockProvider("external", "external", model="mock-gpt")
        local = MockProvider("local", "local", model="local-llm")
        kv = MemoryBackend()
        container = build_container(
            settings,
            key_resolver=static_resolver(issuer.public_key()),
            kv=kv,
            external_llm=external,
            local_llm=local,
            dlp=dlp_engine,
        )
        client = TestClient(create_app(container))
        created.append(client)
        return Gateway(client, container, issuer, external, local, kv)

    yield factory
    for c in created:
        c.close()


@pytest.fixture
def gw(gateway_factory: Callable[..., Gateway]) -> Gateway:
    return gateway_factory()
