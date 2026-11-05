from __future__ import annotations

import pytest
from pydantic import ValidationError

from forge.policy.engine import effective_limits, tighten
from forge.policy.schema import Policy, load_default_policy


def test_default_policy_clamps_timeout() -> None:
    policy = load_default_policy()
    limits = effective_limits(policy, "python")
    assert limits is not None
    assert limits.timeout_ms <= policy.ceilings.timeout_ms
    assert "math" in limits.allow_imports
    assert "pathlib" in limits.deny_imports


def test_shell_has_no_limits_even_if_enabled() -> None:
    policy = load_default_policy()
    tools = dict(policy.tools)
    tools["shell"] = policy.tools["shell"].model_copy(update={"enabled": True})
    enabled = policy.model_copy(update={"tools": tools})
    assert effective_limits(enabled, "shell") is None


def test_network_allow_is_rejected() -> None:
    policy = load_default_policy()
    data = policy.model_dump()
    data["network"] = "allow"
    with pytest.raises(ValidationError):
        Policy.model_validate(data)


def test_tighten_cannot_raise_timeout() -> None:
    limits = effective_limits(load_default_policy(), "python")
    assert limits is not None
    raised = tighten(limits, timeout_ms=999_999, max_memory_mb=None, max_output_bytes=None)
    lowered = tighten(limits, timeout_ms=200, max_memory_mb=64, max_output_bytes=128)
    assert raised.timeout_ms == limits.timeout_ms
    assert lowered.timeout_ms == 200
    assert lowered.max_memory_mb == 64
    assert lowered.max_output_bytes == 128


def test_unknown_tool_has_no_limits() -> None:
    assert effective_limits(load_default_policy(), "send_email") is None
