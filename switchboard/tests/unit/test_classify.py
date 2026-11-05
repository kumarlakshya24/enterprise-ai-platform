from switchboard.classify import classify, luhn_ok, redact_preview


def test_luhn_accepts_the_common_test_card() -> None:
    assert luhn_ok("4111 1111 1111 1111")
    assert not luhn_ok("4111 1111 1111 1112")


def test_task_priority_uses_the_leading_verb() -> None:
    assert classify("Summarize this Python traceback.").task == "summarize"
    assert classify("Fix the compile error in the traceback.").task == "code"
    assert classify("Prove the theorem.").task == "math"
    assert classify("Extract the key-value pairs.").task == "extract"
    assert classify("What is a load balancer?").task == "chat"


def test_code_fence_is_code_without_a_leading_verb() -> None:
    text = "Look at this.\n```python\nx = 1\n```"
    assert classify(text).task == "code"


def test_longer_text_is_more_complex_than_a_short_question() -> None:
    short = classify("What is a load balancer, in two sentences?")
    long = classify(
        "Explain cache invalidation for a production API. " * 12 + "Cover the edge cases in detail."
    )
    assert long.complexity > short.complexity
    assert short.complexity <= 0.2


def test_sensitivity_floors() -> None:
    email = classify("Ping ada@example.com about the outage.")
    assert email.sensitivity == "internal"
    assert email.pii_types == ["email"]
    secret = classify("Confidential: card 4111-1111-1111-1111 on file.")
    assert secret.sensitivity == "confidential"
    assert "card" in secret.pii_types
    restricted = classify("SSN 987-65-4320 is restricted.")
    assert restricted.sensitivity == "restricted"


def test_realtime_and_batch_hints() -> None:
    assert classify("Reply asap.").latency_sensitivity == "high"
    assert classify("Run this overnight.").latency_sensitivity == "low"
    assert classify("Hello.").latency_sensitivity == "normal"


def test_preview_redacts_email_and_keeps_a_short_prefix() -> None:
    preview = redact_preview("Email ada@example.com " + ("x" * 200))
    assert "ada@example.com" not in preview
    assert "[email]" in preview
    assert len(preview) <= 96
