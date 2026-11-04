"""Policy document schema. Validated on every write; invalid policies never activate."""

from __future__ import annotations

import copy
import hashlib
import json
import re
from functools import cached_property
from typing import Annotated, Any, Literal

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, PlainSerializer, field_validator

from aegis.types import EntityAction, EntityType, Label, Route

LabelField = Annotated[
    Label, BeforeValidator(Label.parse), PlainSerializer(lambda v: v.name, return_type=str)
]
RiskLevel = Literal["low", "medium", "high"]


class EntityRule(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: EntityAction = EntityAction.TOKENIZE
    min_confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    label: LabelField = Label.CONFIDENTIAL


class ContextMarker(BaseModel):
    """Deterministic label floor. Auditable and covered by the regression suite."""

    model_config = ConfigDict(extra="forbid")
    id: str
    pattern: str
    label: LabelField
    description: str = ""

    @field_validator("pattern")
    @classmethod
    def _compiles(cls, v: str) -> str:
        try:
            re.compile(v, re.IGNORECASE)
        except re.error as exc:
            raise ValueError(f"invalid regex: {exc}") from exc
        return v


class ClassifierConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool = True
    min_confidence: float = Field(default=0.55, ge=0.0, le=1.0)


class RoutingTable(BaseModel):
    model_config = ConfigDict(extra="forbid")
    PUBLIC: Route = Route.ALLOW
    INTERNAL: Route = Route.REDACT
    CONFIDENTIAL: Route = Route.LOCAL_ONLY
    RESTRICTED: Route = Route.BLOCK

    def for_label(self, label: Label) -> Route:
        route: Route = getattr(self, label.name)
        return route


class BulkRule(BaseModel):
    model_config = ConfigDict(extra="forbid")
    max_restricted_entities: int = Field(default=5, ge=1)
    action: Route = Route.REQUIRE_APPROVAL


class ToolPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")
    allowed_email_domains: list[str] = Field(default_factory=list)
    blocked_email_domains: list[str] = Field(default_factory=list)
    allowed_url_domains: list[str] = Field(default_factory=list)
    risk: dict[str, RiskLevel] = Field(default_factory=dict)
    default_risk: RiskLevel = "high"
    approval_ttl_seconds: int = Field(default=600, ge=30, le=86400)
    detokenize_for_internal: list[EntityType] = Field(default_factory=list)
    block_risky_tools_when_tainted: bool = True

    @field_validator("allowed_email_domains", "blocked_email_domains", "allowed_url_domains")
    @classmethod
    def _lower(cls, v: list[str]) -> list[str]:
        return sorted({d.strip().lower().lstrip("@.") for d in v if d.strip()})

    def risk_of(self, tool: str) -> RiskLevel:
        return self.risk.get(tool, self.default_risk)


class InjectionConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    threshold: float = Field(default=0.6, ge=0.05, le=1.0)
    on_detect: Literal["flag_and_taint", "sanitize"] = "flag_and_taint"


class AuditConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    store_content_up_to: LabelField = Label.INTERNAL


class Policy(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = "default"
    description: str = ""
    entities: dict[EntityType, EntityRule]
    allowlist_terms: list[str] = Field(default_factory=list)
    context_markers: list[ContextMarker] = Field(default_factory=list)
    classifier: ClassifierConfig = Field(default_factory=ClassifierConfig)
    routing: RoutingTable = Field(default_factory=RoutingTable)
    bulk: BulkRule = Field(default_factory=BulkRule)
    tools: ToolPolicy = Field(default_factory=ToolPolicy)
    injection: InjectionConfig = Field(default_factory=InjectionConfig)
    audit: AuditConfig = Field(default_factory=AuditConfig)

    @field_validator("entities")
    @classmethod
    def _all_entities(cls, v: dict[EntityType, EntityRule]) -> dict[EntityType, EntityRule]:
        missing = set(EntityType) - set(v)
        if missing:
            raise ValueError(f"policy must configure every entity type; missing {sorted(missing)}")
        return v

    # ---- derived helpers (not serialized)

    @cached_property
    def _allowlist_phrases(self) -> frozenset[str]:
        return frozenset(_norm_term(t) for t in self.allowlist_terms if t.strip())

    @cached_property
    def _allowlist_tokens(self) -> frozenset[str]:
        return frozenset(tok for t in self._allowlist_phrases for tok in t.split())

    @cached_property
    def compiled_markers(self) -> list[tuple[ContextMarker, re.Pattern[str]]]:
        return [(m, re.compile(m.pattern, re.IGNORECASE)) for m in self.context_markers]

    def is_allowlisted(self, text: str) -> bool:
        """A NER span is allowlisted if it is a listed phrase or every token is a listed term."""
        norm = _norm_term(text)
        if not norm:
            return False
        if norm in self._allowlist_phrases:
            return True
        return all(tok in self._allowlist_tokens for tok in norm.split())

    def rule(self, etype: EntityType) -> EntityRule:
        return self.entities[etype]


def _norm_term(s: str) -> str:
    return " ".join(re.sub(r"[^\w\s.+#-]", " ", s.lower()).split())


class PolicyBundle(BaseModel):
    """Base policy plus partial overrides. The effective policy is computed per tenant/user."""

    model_config = ConfigDict(extra="forbid")
    base: Policy
    tenant_overrides: dict[str, dict[str, Any]] = Field(default_factory=dict)
    user_overrides: dict[str, dict[str, Any]] = Field(default_factory=dict)  # key: "<tenant>/<sub>"

    def effective(self, tenant_id: str, user_sub: str | None = None) -> Policy:
        doc = self.base.model_dump(mode="json")
        layers = [self.tenant_overrides.get(tenant_id)]
        if user_sub:
            layers.append(self.user_overrides.get(f"{tenant_id}/{user_sub}"))
        for layer in layers:
            if layer:
                doc = deep_merge(doc, layer)
        return Policy.model_validate(doc)

    def validate_all(self) -> None:
        """Every override must produce a valid policy."""
        for tenant in self.tenant_overrides:
            self.effective(tenant)
        for key in self.user_overrides:
            tenant, _, sub = key.partition("/")
            if not sub:
                raise ValueError(f"user override key {key!r} must look like '<tenant>/<sub>'")
            self.effective(tenant, sub)

    def scopes(self) -> list[tuple[str, str | None]]:
        """Every (tenant, user) combination whose effective policy differs from the base."""
        out: list[tuple[str, str | None]] = [("*", None)]
        out += [(t, None) for t in self.tenant_overrides]
        for key in self.user_overrides:
            tenant, _, sub = key.partition("/")
            out.append((tenant, sub))
        return out

    def digest(self) -> str:
        canon = json.dumps(self.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canon.encode()).hexdigest()[:12]


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Dicts merge recursively; lists and scalars in the override replace the base."""
    out = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = deep_merge(out[key], value)
        else:
            out[key] = copy.deepcopy(value)
    return out
