"""Token vault: placeholder tokenization and RBAC-scoped restoration.

Keys (all with TTL):
  {p}:{tenant}:sess:{session}                          -> owner sub
  {p}:{tenant}:{session}:{purpose}:ctr:{TYPE}          -> counter
  {p}:{tenant}:{session}:{purpose}:idx:{hmac}          -> placeholder (same value, same placeholder)
  {p}:{tenant}:{session}:{purpose}:tok:{placeholder}   -> {"ct": AES-GCM ciphertext, "type", "owner"}

The AAD binds tenant, owner, session, purpose, and placeholder. A ciphertext copied under a
different context fails to decrypt even if the access check above it had a bug.
"""

from __future__ import annotations

import json
import re
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field

from aegis.dlp.engine import ScanResult
from aegis.types import SECRET_TYPES, EntityAction, EntityType, RestoreScope
from aegis.vault.backends import KVBackend
from aegis.vault.crypto import VaultCipher, VaultIntegrityError

PLACEHOLDER_TYPES = "|".join(t.value for t in EntityType)
# Tolerant: models sometimes drop brackets or swap the underscore for a space.
PLACEHOLDER_RE = re.compile(rf"\[?\b({PLACEHOLDER_TYPES})[_ ](\d{{1,4}})\b\]?")
STRICT_PLACEHOLDER_RE = re.compile(rf"\[({PLACEHOLDER_TYPES})_(\d{{1,4}})\]")
_URL_RE = re.compile(r"https?://\S+", re.IGNORECASE)


class SessionOwnershipError(PermissionError):
    pass


@dataclass(frozen=True)
class VaultContext:
    tenant_id: str
    user_id: str
    session_id: str
    purpose: str = "chat"

    def aad(self, placeholder: str) -> bytes:
        return "|".join((self.tenant_id, self.user_id, self.session_id, self.purpose, placeholder)).encode()


@dataclass
class RestoreResult:
    text: str
    restored: list[dict[str, str]] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)

    @property
    def complete(self) -> bool:
        return not self.missing


def mask_value(etype: EntityType, value: str) -> str:
    digits = re.sub(r"\D", "", value)
    if etype is EntityType.CREDIT_CARD:
        return f"•••• {digits[-4:]}"
    if etype is EntityType.SSN:
        return f"•••-••-{digits[-4:]}"
    if etype is EntityType.PHONE:
        return f"•••-•••-{digits[-4:]}"
    if etype is EntityType.EMAIL and "@" in value:
        local, _, domain = value.partition("@")
        return f"{local[:1]}•••@{domain}"
    if etype is EntityType.PERSON_NAME:
        return " ".join(f"{p[0]}." for p in value.split() if p)
    if etype is EntityType.ORG:
        return f"{value[:1]}•••"
    return "[REDACTED]"


class TokenVault:
    def __init__(
        self, backend: KVBackend, cipher: VaultCipher, ttl_seconds: int = 900, prefix: str = "aegis:v1"
    ) -> None:
        self.backend = backend
        self.cipher = cipher
        self.ttl = ttl_seconds
        self.prefix = prefix

    # ------------------------------------------------------------------ sessions

    def _sess_key(self, tenant: str, session_id: str) -> str:
        return f"{self.prefix}:{tenant}:sess:{session_id}"

    def open_session(self, tenant_id: str, user_id: str, session_id: str | None = None) -> str:
        """Create a session owned by `user_id`, or verify ownership of an existing one."""
        if session_id is None:
            session_id = uuid.uuid4().hex
        if not re.fullmatch(r"[A-Za-z0-9_-]{8,64}", session_id):
            raise SessionOwnershipError("invalid session id")
        key = self._sess_key(tenant_id, session_id)
        if self.backend.set_if_absent(key, user_id, self.ttl):
            return session_id
        owner = self.backend.get(key)
        if owner != user_id:
            raise SessionOwnershipError("session belongs to another user")
        return session_id

    def session_owner(self, tenant_id: str, session_id: str) -> str | None:
        return self.backend.get(self._sess_key(tenant_id, session_id))

    # ------------------------------------------------------------------ tokenize

    def _base(self, ctx: VaultContext) -> str:
        return f"{self.prefix}:{ctx.tenant_id}:{ctx.session_id}:{ctx.purpose}"

    def _next_placeholder(self, etype: EntityType, ctx: VaultContext) -> str:
        n = self.backend.incr(f"{self._base(ctx)}:ctr:{etype.value}", self.ttl)
        return f"[{etype.value}_{n}]"

    def tokenize(self, value: str, canonical: str, etype: EntityType, ctx: VaultContext) -> str:
        idx_key = f"{self._base(ctx)}:idx:{self.cipher.index(ctx.user_id, etype.value, canonical)}"
        existing = self.backend.get(idx_key)
        if existing:
            return existing
        placeholder = self._next_placeholder(etype, ctx)
        record = {
            "ct": self.cipher.encrypt(value, ctx.aad(placeholder)),
            "type": etype.value,
            "owner": ctx.user_id,
        }
        self.backend.set(f"{self._base(ctx)}:tok:{placeholder}", json.dumps(record), self.ttl)
        if not self.backend.set_if_absent(idx_key, placeholder, self.ttl):
            # Lost a race with a concurrent request in the same session: use the winner's placeholder.
            winner = self.backend.get(idx_key)
            if winner:
                return winner
        return placeholder

    def redaction_placeholder(self, etype: EntityType, ctx: VaultContext) -> str:
        """Irreversible: a placeholder with no stored value (used for secrets)."""
        return self._next_placeholder(etype, ctx)

    def apply(self, scan: ScanResult, ctx: VaultContext) -> str:
        """Replace every applied finding with its placeholder. Assigns numbers left to right."""
        for f in scan.applied:
            if f.action is EntityAction.TOKENIZE:
                f.placeholder = self.tokenize(f.value, f.canonical or f.value, f.entity_type, ctx)
            elif f.action is EntityAction.REDACT:
                f.placeholder = self.redaction_placeholder(f.entity_type, ctx)
            elif f.action is EntityAction.BLOCK:
                f.placeholder = f"[{f.entity_type.value}_BLOCKED]"
        out = scan.text
        for f in sorted(scan.applied, key=lambda x: x.start, reverse=True):
            out = out[: f.start] + (f.placeholder or "") + out[f.end :]
        return out

    # ------------------------------------------------------------------ resolve / restore

    def resolve(self, placeholder: str, ctx: VaultContext) -> tuple[EntityType, str] | None:
        """Return (type, real value) for the session owner, or None if unknown/expired."""
        owner = self.session_owner(ctx.tenant_id, ctx.session_id)
        if owner is not None and owner != ctx.user_id:
            raise SessionOwnershipError("session belongs to another user")
        raw = self.backend.get(f"{self._base(ctx)}:tok:{placeholder}")
        if raw is None:
            return None
        record = json.loads(raw)
        if record.get("owner") != ctx.user_id:
            raise SessionOwnershipError("token belongs to another user")
        try:
            value = self.cipher.decrypt(record["ct"], ctx.aad(placeholder))
        except VaultIntegrityError:
            raise SessionOwnershipError("token context mismatch") from None
        return EntityType(record["type"]), value

    def restore_text(
        self, text: str, ctx: VaultContext, scopes: Mapping[EntityType, RestoreScope]
    ) -> RestoreResult:
        """Replace placeholders with values per role scope. Never restores inside URLs."""
        protected = [(m.start(), m.end()) for m in _URL_RE.finditer(text)]
        result = RestoreResult(text="")
        pieces: list[str] = []
        last = 0
        cache: dict[str, tuple[EntityType, str] | None] = {}
        for m in PLACEHOLDER_RE.finditer(text):
            if any(s <= m.start() < e for s, e in protected):
                continue
            etype_s, num = m.group(1), m.group(2)
            canonical = f"[{etype_s}_{num}]"
            if canonical not in cache:
                cache[canonical] = self.resolve(canonical, ctx)
            hit = cache[canonical]
            pieces.append(text[last : m.start()])
            last = m.end()
            if hit is None:
                pieces.append(canonical)
                if canonical not in result.missing:
                    result.missing.append(canonical)
                continue
            etype, value = hit
            scope = scopes.get(etype, RestoreScope.NEVER)
            if scope is RestoreScope.FULL:
                pieces.append(value)
            elif scope is RestoreScope.MASKED:
                pieces.append(mask_value(etype, value))
            else:
                pieces.append(canonical)
            result.restored.append(
                {"placeholder": canonical, "entity_type": etype.value, "scope": scope.name.lower()}
            )
        pieces.append(text[last:])
        result.text = "".join(pieces)
        return result

    def detokenize_for_tool(self, text: str, ctx: VaultContext, allowed: set[EntityType]) -> str:
        """Restore placeholders inside a tool argument for an approved internal destination.

        Types in `allowed` are restored in full, secrets never, everything else masked.
        """
        scopes = {t: (RestoreScope.FULL if t in allowed else RestoreScope.MASKED) for t in EntityType}
        for t in SECRET_TYPES:
            scopes[t] = RestoreScope.NEVER
        return self.restore_text(text, ctx, scopes).text
