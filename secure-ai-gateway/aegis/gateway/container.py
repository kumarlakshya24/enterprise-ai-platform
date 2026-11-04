"""Dependency wiring. Production builds everything from Settings; tests pass in-memory overrides."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from sqlalchemy import Engine

from aegis.agent.runner import AgentRunner, RunStore
from aegis.agent.tools import Sandbox
from aegis.audit.store import AuditStore
from aegis.auth.oidc import KeyResolver, TokenVerifier, jwks_resolver, static_resolver
from aegis.auth.ratelimit import RateLimiter
from aegis.classifier.model import load_default_classifier
from aegis.classifier.types import SensitivityClassifier
from aegis.config import ConfigError, Settings
from aegis.db import init_db, make_engine
from aegis.dlp.engine import DLPEngine
from aegis.guard.approvals import ApprovalService
from aegis.guard.injection import InjectionDetector
from aegis.guard.interceptor import ToolGuard
from aegis.guard.output import OutputSanitizer
from aegis.llm.base import LLMProvider
from aegis.llm.providers import MockProvider, OpenAICompatibleProvider
from aegis.policy.store import PolicyStore, load_bundle_file
from aegis.vault.backends import KVBackend, build_backend
from aegis.vault.crypto import VaultCipher
from aegis.vault.vault import TokenVault

log = logging.getLogger("aegis.container")


@dataclass
class Container:
    settings: Settings
    engine: Engine
    kv: KVBackend
    vault: TokenVault
    cipher: VaultCipher
    dlp: DLPEngine
    classifier: SensitivityClassifier | None
    policies: PolicyStore
    audit: AuditStore
    verifier: TokenVerifier
    rate_limiter: RateLimiter
    external_llm: LLMProvider
    local_llm: LLMProvider
    sanitizer: OutputSanitizer
    sandbox: Sandbox
    injection: InjectionDetector
    guard: ToolGuard
    approvals: ApprovalService
    runs: RunStore
    extras: dict[str, Any]

    @property
    def agent(self) -> AgentRunner:
        return AgentRunner(self)

    def health(self) -> dict[str, Any]:
        return {
            "status": "ok",
            "env": self.settings.env,
            "ner_backend": self.dlp.ner_backend,
            "classifier": getattr(self.classifier, "version", None),
            "vault_backend": type(self.kv).__name__,
            "vault_backend_ok": self.kv.ping(),
            "database": self.engine.dialect.name,
            "external_llm": {"name": self.external_llm.name, "model": self.external_llm.model},
            "local_llm": {"name": self.local_llm.name, "model": self.local_llm.model},
            "ephemeral_keys": self.settings.ephemeral_keys,
            "mode": "embedded-demo" if self.settings.embedded_demo else "services",
            "policy_version": self.policies.active().version,
        }


def _build_provider(
    kind: str, name: str, location: str, base_url: str, model: str, api_key: str, timeout: float
) -> LLMProvider:
    if kind == "openai_compatible":
        return OpenAICompatibleProvider(name, location, base_url, model, api_key=api_key, timeout=timeout)  # type: ignore[arg-type]
    return MockProvider(name, location, model=model)  # type: ignore[arg-type]


def load_classifier() -> SensitivityClassifier:
    return load_default_classifier()


def build_container(
    settings: Settings,
    *,
    key_resolver: KeyResolver | None = None,
    kv: KVBackend | None = None,
    external_llm: LLMProvider | None = None,
    local_llm: LLMProvider | None = None,
    dlp: DLPEngine | None = None,
    classifier: SensitivityClassifier | str | None = "default",
) -> Container:
    engine = make_engine(settings.database_url)
    init_db(engine)
    kv = kv or build_backend(settings.redis_url)
    cipher = VaultCipher(settings.vault_keys, settings.vault_active_kid)
    vault = TokenVault(kv, cipher, ttl_seconds=settings.vault_ttl_seconds)
    policies = PolicyStore(engine, load_bundle_file(settings.policy_path or None))
    policies.bootstrap()
    verifier = TokenVerifier(
        issuer=settings.oidc_issuer,
        audience=settings.oidc_audience,
        allowed_tenants=settings.allowed_tenants,
        key_resolver=key_resolver or jwks_resolver(settings.oidc_jwks_url),
    )
    external_llm = external_llm or _build_provider(
        settings.llm_provider,
        "external",
        "external",
        settings.llm_base_url,
        settings.llm_model,
        settings.llm_api_key,
        settings.llm_timeout_seconds,
    )
    local_llm = local_llm or _build_provider(
        settings.local_llm_provider,
        "local",
        "local",
        settings.local_llm_base_url,
        settings.local_llm_model,
        "",
        settings.llm_timeout_seconds,
    )
    dlp = dlp or DLPEngine.default(settings.ner_backend)
    audit = AuditStore(engine, settings.audit_hmac_key)
    return Container(
        settings=settings,
        engine=engine,
        kv=kv,
        vault=vault,
        cipher=cipher,
        dlp=dlp,
        classifier=load_classifier() if classifier == "default" else classifier,  # type: ignore[arg-type]
        policies=policies,
        audit=audit,
        verifier=verifier,
        rate_limiter=RateLimiter(kv, settings.rate_limit_per_minute),
        external_llm=external_llm,
        local_llm=local_llm,
        sanitizer=OutputSanitizer(),
        sandbox=Sandbox(),
        injection=InjectionDetector(),
        guard=ToolGuard(vault, dlp),
        approvals=ApprovalService(engine, cipher, audit),
        runs=RunStore(engine),
        extras={},
    )


def build_embedded_demo_container(settings: Settings) -> Container:
    """One process for a hosted demo: the mock IdP and mock models run inside the gateway.

    Trust boundaries that the compose deployment keeps separate (IdP, provider, local model) are
    collapsed here on purpose, so a free single-container host can serve the demo. Refused in prod.
    """
    if settings.env == "prod":
        raise ConfigError("embedded demo mode is not allowed in prod")
    from aegis.idp.issuer import TokenIssuer

    issuer = TokenIssuer(settings.oidc_issuer, settings.oidc_audience)
    container = build_container(settings, key_resolver=static_resolver(issuer.public_key()))
    container.extras["token_issuer"] = issuer
    return container
