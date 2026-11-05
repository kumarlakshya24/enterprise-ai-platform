"""Token vault: encryption at rest, binding, consistency, expiry, RBAC-scoped restore."""

from __future__ import annotations

import secrets

import pytest

from aegis.auth.rbac import restore_scopes_for
from aegis.dlp.engine import DLPEngine
from aegis.policy.schema import Policy
from aegis.types import EntityType, RestoreScope
from aegis.vault.backends import MemoryBackend
from aegis.vault.crypto import VaultCipher, VaultIntegrityError
from aegis.vault.vault import SessionOwnershipError, TokenVault, VaultContext, mask_value

COMPLAINT = "Hi, my name is Dana Holloway. Card 4111 1111 1111 1111, email dana.holloway@example.com."


class Clock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def vault(clock: Clock) -> TokenVault:
    cipher = VaultCipher({"k1": secrets.token_bytes(32)}, "k1")
    return TokenVault(MemoryBackend(clock=clock), cipher, ttl_seconds=60)


def ctx(user: str = "u-1", session: str = "sess-00000001", purpose: str = "chat") -> VaultContext:
    return VaultContext("acme", user, session, purpose)


def test_tokenize_and_restore_roundtrip(
    vault: TokenVault, dlp_engine: DLPEngine, default_policy: Policy
) -> None:
    c = ctx()
    vault.open_session("acme", "u-1", c.session_id)
    scan = dlp_engine.scan(COMPLAINT, default_policy)
    tokenized = vault.apply(scan, c)
    assert "Dana" not in tokenized and "4111" not in tokenized and "example.com" not in tokenized
    assert "[PERSON_NAME_1]" in tokenized and "[CREDIT_CARD_1]" in tokenized and "[EMAIL_1]" in tokenized
    full = dict.fromkeys(EntityType, RestoreScope.FULL)
    assert vault.restore_text(tokenized, c, full).text == COMPLAINT


def test_no_plaintext_at_rest(vault: TokenVault, dlp_engine: DLPEngine, default_policy: Policy) -> None:
    c = ctx()
    vault.open_session("acme", "u-1", c.session_id)
    vault.apply(dlp_engine.scan(COMPLAINT, default_policy), c)
    dump = "\n".join(f"{k}={v}" for k, v in vault.backend.dump().items())  # type: ignore[attr-defined]
    for raw in ("Dana", "Holloway", "4111", "dana.holloway", "example.com"):
        assert raw not in dump


def test_same_value_same_placeholder_within_session(vault: TokenVault) -> None:
    c = ctx()
    a = vault.tokenize("dana@example.com", "dana@example.com", EntityType.EMAIL, c)
    b = vault.tokenize("DANA@example.com", "dana@example.com", EntityType.EMAIL, c)
    other = vault.tokenize("victor@example.net", "victor@example.net", EntityType.EMAIL, c)
    assert a == b == "[EMAIL_1]" and other == "[EMAIL_2]"


def test_sessions_are_isolated(vault: TokenVault) -> None:
    a = vault.tokenize("dana@example.com", "dana@example.com", EntityType.EMAIL, ctx(session="sess-aaaaaaaa"))
    assert vault.resolve(a, ctx(session="sess-bbbbbbbb")) is None


def test_other_user_cannot_resolve_or_take_over_session(vault: TokenVault) -> None:
    vault.open_session("acme", "u-1", "sess-00000001")
    ph = vault.tokenize("dana@example.com", "dana@example.com", EntityType.EMAIL, ctx())
    with pytest.raises(SessionOwnershipError):
        vault.resolve(ph, ctx(user="u-2"))
    with pytest.raises(SessionOwnershipError):
        vault.open_session("acme", "u-2", "sess-00000001")


def test_purpose_binding(vault: TokenVault) -> None:
    ph = vault.tokenize("dana@example.com", "dana@example.com", EntityType.EMAIL, ctx(purpose="chat"))
    assert vault.resolve(ph, ctx(purpose="agent")) is None


def test_aad_binding_blocks_copied_ciphertext(vault: TokenVault) -> None:
    """Even if an access check were bypassed, ciphertext moved to another context will not decrypt."""
    c1 = ctx()
    ph = vault.tokenize("dana@example.com", "dana@example.com", EntityType.EMAIL, c1)
    record = vault.backend.get(f"aegis:v1:acme:{c1.session_id}:chat:tok:{ph}")
    assert record is not None
    import json

    ct = json.loads(record)["ct"]
    with pytest.raises(VaultIntegrityError):
        vault.cipher.decrypt(ct, ctx(user="u-2").aad(ph))


def test_expiry(vault: TokenVault, clock: Clock) -> None:
    c = ctx()
    ph = vault.tokenize("dana@example.com", "dana@example.com", EntityType.EMAIL, c)
    clock.t += 61
    assert vault.resolve(ph, c) is None
    r = vault.restore_text(f"hi {ph}", c, dict.fromkeys(EntityType, RestoreScope.FULL))
    assert r.text == f"hi {ph}" and r.missing == [ph] and not r.complete


def test_rbac_scopes_mask_cards_for_support_agents(vault: TokenVault) -> None:
    c = ctx()
    card = vault.tokenize("4111 1111 1111 1111", "4111111111111111", EntityType.CREDIT_CARD, c)
    name = vault.tokenize("Dana Holloway", "dana holloway", EntityType.PERSON_NAME, c)
    support = restore_scopes_for(["employee", "support_agent"])
    billing = restore_scopes_for(["employee", "billing_specialist"])
    admin_only = restore_scopes_for(["security_admin"])
    assert vault.restore_text(f"{name} {card}", c, support).text == "Dana Holloway •••• 1111"
    assert vault.restore_text(f"{name} {card}", c, billing).text == "Dana Holloway 4111 1111 1111 1111"
    assert vault.restore_text(f"{name} {card}", c, admin_only).text == f"{name} {card}"


def test_tolerant_restore_of_mangled_placeholders(vault: TokenVault) -> None:
    c = ctx()
    vault.tokenize("dana@example.com", "dana@example.com", EntityType.EMAIL, c)
    full = dict.fromkeys(EntityType, RestoreScope.FULL)
    assert (
        vault.restore_text("mail EMAIL_1 or [EMAIL 1]", c, full).text
        == "mail dana@example.com or dana@example.com"
    )


def test_never_restores_inside_urls(vault: TokenVault) -> None:
    c = ctx()
    ph = vault.tokenize("dana@example.com", "dana@example.com", EntityType.EMAIL, c)
    full = dict.fromkeys(EntityType, RestoreScope.FULL)
    out = vault.restore_text(f"see https://x.example/?e={ph}|{ph} and {ph}", c, full).text
    assert out == f"see https://x.example/?e={ph}|{ph} and dana@example.com"


def test_secrets_are_never_stored(vault: TokenVault) -> None:
    c = ctx()
    ph = vault.redaction_placeholder(EntityType.API_KEY, c)
    assert ph == "[API_KEY_1]" and vault.resolve(ph, c) is None


def test_mask_values() -> None:
    assert mask_value(EntityType.EMAIL, "dana.holloway@example.com") == "d•••@example.com"
    assert mask_value(EntityType.PHONE, "+1 312-555-0142") == "•••-•••-0142"
    assert mask_value(EntityType.PERSON_NAME, "Dana Holloway") == "D. H."


def test_key_rotation_reads_old_ciphertext() -> None:
    k_old, k_new = secrets.token_bytes(32), secrets.token_bytes(32)
    old = VaultCipher({"k0": k_old}, "k0")
    token = old.encrypt("secret", b"aad")
    rotated = VaultCipher({"k0": k_old, "k1": k_new}, "k1")
    assert rotated.decrypt(token, b"aad") == "secret"
    assert rotated.encrypt("x", b"aad").startswith("k1.")
