"""Settings, read from environment variables only. No secrets have defaults."""

from __future__ import annotations

import base64
import logging
import os
import secrets
from dataclasses import dataclass, field

log = logging.getLogger("aegis.config")


class ConfigError(RuntimeError):
    pass


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def _env_bool(name: str, default: bool) -> bool:
    raw = _env(name)
    if not raw:
        return default
    return raw.lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    raw = _env(name)
    return int(raw) if raw else default


def _env_list(name: str, default: str) -> list[str]:
    return [p.strip() for p in _env(name, default).split(",") if p.strip()]


def parse_keyring(raw: str) -> dict[str, bytes]:
    """Parse `kid1:base64key,kid0:base64key` into {kid: 32-byte key}."""
    keys: dict[str, bytes] = {}
    for chunk in raw.split(","):
        part = chunk.strip()
        if not part:
            continue
        if ":" not in part:
            raise ConfigError("AEGIS_VAULT_KEYS entries must look like kid:base64key")
        kid, b64 = part.split(":", 1)
        key = base64.b64decode(b64)
        if len(key) != 32:
            raise ConfigError(f"vault key {kid!r} must be 32 bytes (AES-256)")
        keys[kid.strip()] = key
    return keys


@dataclass
class Settings:
    env: str = "demo"  # demo | dev | prod
    demo_mode: bool = True

    database_url: str = "sqlite:///./aegis.db"
    redis_url: str = ""  # empty -> in-memory backends (single process only)

    vault_keys: dict[str, bytes] = field(default_factory=dict)
    vault_active_kid: str = ""
    vault_ttl_seconds: int = 900
    audit_hmac_key: bytes = b""

    oidc_issuer: str = "http://idp:9000"
    oidc_audience: str = "aegis-gateway"
    oidc_jwks_url: str = "http://idp:9000/.well-known/jwks.json"
    allowed_tenants: list[str] = field(default_factory=lambda: ["acme"])
    idp_token_url: str = "http://idp:9000/token"  # noqa: S105 - a URL, not a secret

    llm_provider: str = "mock"  # mock | openai_compatible
    llm_base_url: str = ""
    llm_api_key: str = field(default="", repr=False)
    llm_model: str = "gpt-4o-mini"
    llm_timeout_seconds: float = 30.0
    local_llm_provider: str = "mock"
    local_llm_base_url: str = ""
    local_llm_model: str = "local-llm"

    ner_backend: str = "spacy"  # spacy | heuristic | off
    rate_limit_per_minute: int = 60
    max_body_bytes: int = 64 * 1024
    agent_max_steps: int = 6
    policy_path: str = ""  # empty -> bundled default policy
    log_level: str = "INFO"

    ephemeral_keys: bool = False

    @classmethod
    def from_env(cls) -> Settings:
        env = _env("AEGIS_ENV", "demo").lower()
        s = cls(
            env=env,
            demo_mode=_env_bool("AEGIS_DEMO_MODE", env != "prod"),
            database_url=_env("DATABASE_URL", "sqlite:///./aegis.db"),
            redis_url=_env("REDIS_URL"),
            vault_ttl_seconds=_env_int("AEGIS_VAULT_TTL_SECONDS", 900),
            oidc_issuer=_env("OIDC_ISSUER", "http://idp:9000"),
            oidc_audience=_env("OIDC_AUDIENCE", "aegis-gateway"),
            oidc_jwks_url=_env("OIDC_JWKS_URL", "http://idp:9000/.well-known/jwks.json"),
            allowed_tenants=_env_list("AEGIS_ALLOWED_TENANTS", "acme"),
            idp_token_url=_env("IDP_TOKEN_URL", "http://idp:9000/token"),
            llm_provider=_env("LLM_PROVIDER", "mock"),
            llm_base_url=_env("LLM_BASE_URL"),
            llm_api_key=_env("LLM_API_KEY"),
            llm_model=_env("LLM_MODEL", "gpt-4o-mini"),
            llm_timeout_seconds=float(_env("LLM_TIMEOUT_SECONDS", "30")),
            local_llm_provider=_env("LOCAL_LLM_PROVIDER", "mock"),
            local_llm_base_url=_env("LOCAL_LLM_BASE_URL"),
            local_llm_model=_env("LOCAL_LLM_MODEL", "local-llm"),
            ner_backend=_env("AEGIS_NER_BACKEND", "spacy"),
            rate_limit_per_minute=_env_int("AEGIS_RATE_LIMIT_PER_MINUTE", 60),
            max_body_bytes=_env_int("AEGIS_MAX_BODY_BYTES", 64 * 1024),
            agent_max_steps=_env_int("AEGIS_AGENT_MAX_STEPS", 6),
            policy_path=_env("AEGIS_POLICY_PATH"),
            log_level=_env("AEGIS_LOG_LEVEL", "INFO"),
        )
        raw_keys = _env("AEGIS_VAULT_KEYS")
        raw_audit = _env("AEGIS_AUDIT_HMAC_KEY")
        if raw_keys:
            s.vault_keys = parse_keyring(raw_keys)
            s.vault_active_kid = _env("AEGIS_VAULT_ACTIVE_KID") or next(iter(s.vault_keys))
            if s.vault_active_kid not in s.vault_keys:
                raise ConfigError("AEGIS_VAULT_ACTIVE_KID is not in AEGIS_VAULT_KEYS")
        if raw_audit:
            s.audit_hmac_key = base64.b64decode(raw_audit)
        s.ensure_keys()
        if s.llm_provider == "openai_compatible" and not s.llm_base_url:
            raise ConfigError("LLM_PROVIDER=openai_compatible requires LLM_BASE_URL")
        return s

    def ensure_keys(self) -> None:
        """Production refuses to start without keys. Demo/dev generate ephemeral ones."""
        missing = not self.vault_keys or not self.audit_hmac_key
        if not missing:
            return
        if self.env == "prod":
            raise ConfigError("AEGIS_VAULT_KEYS and AEGIS_AUDIT_HMAC_KEY are required when AEGIS_ENV=prod")
        log.warning(
            "No vault/audit keys configured: generating ephemeral keys (env=%s). "
            "Tokens and the audit chain will not survive a restart. Run `make env` to create .env.",
            self.env,
        )
        if not self.vault_keys:
            self.vault_keys = {"ephemeral": secrets.token_bytes(32)}
            self.vault_active_kid = "ephemeral"
        if not self.audit_hmac_key:
            self.audit_hmac_key = secrets.token_bytes(32)
        self.ephemeral_keys = True
