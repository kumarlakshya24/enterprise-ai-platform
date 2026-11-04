"""Tool guard: every agent tool call is checked here before it runs. The model is not trusted."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any

from aegis.agent.tools import TOOLS
from aegis.dlp.engine import DLPEngine
from aegis.guard.urls import decoded_views, domain_allowed, host_of
from aegis.llm.base import ToolCall
from aegis.policy.schema import Policy
from aegis.types import Label
from aegis.vault.vault import STRICT_PLACEHOLDER_RE, SessionOwnershipError, TokenVault, VaultContext


class Verdict(IntEnum):
    ALLOW = 0
    REQUIRE_APPROVAL = 1
    BLOCK = 2


@dataclass
class RunState:
    tainted: bool = False
    taint_sources: list[str] = field(default_factory=list)


@dataclass
class GuardResult:
    verdict: Verdict
    risk: str
    reasons: list[dict[str, str]] = field(default_factory=list)
    facts: dict[str, Any] = field(default_factory=dict)  # redacted facts, e.g. recipient domain

    def add(self, verdict: Verdict, rule: str, message: str) -> None:
        self.reasons.append({"rule": rule, "verdict": verdict.name.lower(), "message": message})
        self.verdict = max(self.verdict, verdict)

    def public(self) -> dict[str, Any]:
        return {
            "verdict": self.verdict.name.lower(),
            "risk": self.risk,
            "reasons": self.reasons,
            "facts": self.facts,
        }


_ADDRESS_SPLIT = re.compile(r"[,;\s]+")


class ToolGuard:
    def __init__(self, vault: TokenVault, dlp: DLPEngine) -> None:
        self.vault = vault
        self.dlp = dlp

    def _resolve(self, value: str, ctx: VaultContext) -> tuple[str | None, bool]:
        """Replace placeholders with real values for checking. Returns (value, had_unresolvable)."""
        missing = False

        def sub(m: re.Match[str]) -> str:
            nonlocal missing
            try:
                hit = self.vault.resolve(m.group(0), ctx)
            except SessionOwnershipError:
                hit = None
            if hit is None:
                missing = True
                return m.group(0)
            return hit[1]

        return STRICT_PLACEHOLDER_RE.sub(sub, value), missing

    def _restricted_raw(self, text: str, policy: Policy) -> list[str]:
        scan = self.dlp.scan(text, policy, use_ner=False)
        return sorted(
            {
                f.entity_type.value
                for f in scan.applied
                if policy.rule(f.entity_type).label is Label.RESTRICTED
            }
        )

    def check(self, call: ToolCall, ctx: VaultContext, state: RunState, policy: Policy) -> GuardResult:
        spec = TOOLS.get(call.name)
        risk = policy.tools.risk_of(call.name)
        g = GuardResult(Verdict.ALLOW, risk)
        if spec is None:
            g.add(Verdict.BLOCK, "R-TOOL-UNKNOWN", f"tool {call.name!r} is not registered")
            return g
        args = call.arguments
        for name in spec.params:
            if not isinstance(args.get(name), str) or not str(args.get(name)).strip():
                g.add(Verdict.BLOCK, "R-TOOL-ARGS", f"argument {name!r} missing or not a string")
        extra = set(args) - set(spec.params)
        if extra:
            g.add(Verdict.BLOCK, "R-TOOL-ARGS", f"unexpected arguments {sorted(extra)}")
        if g.verdict is Verdict.BLOCK:
            return g

        tools = policy.tools
        # 1. Recipients: resolve placeholders, then personal blocklist and corporate allowlist.
        for fname in spec.recipient_fields:
            resolved, missing = self._resolve(str(args[fname]), ctx)
            if missing or resolved is None:
                g.add(
                    Verdict.BLOCK,
                    "R-TOOL-RECIPIENT-UNRESOLVED",
                    "recipient placeholder could not be resolved",
                )
                continue
            domains = []
            for addr in filter(None, _ADDRESS_SPLIT.split(resolved)):
                if "@" not in addr:
                    g.add(Verdict.BLOCK, "R-TOOL-RECIPIENT-INVALID", "recipient is not an email address")
                    continue
                domain = addr.rsplit("@", 1)[1].lower().strip(".>")
                domains.append(domain)
                if domain in tools.blocked_email_domains:
                    g.add(
                        Verdict.BLOCK,
                        "R-TOOL-PERSONAL-DOMAIN",
                        f"recipient domain {domain} is a personal email provider",
                    )
                elif not domain_allowed(domain, tools.allowed_email_domains):
                    g.add(
                        Verdict.BLOCK,
                        "R-TOOL-DOMAIN-NOT-ALLOWLISTED",
                        f"recipient domain {domain} is not on the corporate allowlist",
                    )
            g.facts["recipient_domains"] = sorted(set(domains))

        # 2. URLs: domain allowlist, then any data (placeholders or raw values) in the decoded URL.
        for fname in spec.url_fields:
            url = str(args[fname])
            host = host_of(url)
            g.facts.setdefault("url_hosts", []).append(host)
            if not domain_allowed(host, tools.allowed_url_domains):
                g.add(
                    Verdict.BLOCK,
                    "R-TOOL-URL-NOT-ALLOWLISTED",
                    f"{host or 'invalid URL'} is not an allowlisted domain",
                )
            views = decoded_views(url)
            if any(STRICT_PLACEHOLDER_RE.search(v) for v in views):
                g.add(Verdict.BLOCK, "R-TOOL-DATA-IN-URL", "URL contains tokenized customer data")
            raw_types = sorted({t for v in views for t in self._sensitive_types(v, policy)})
            if raw_types:
                g.add(Verdict.BLOCK, "R-TOOL-DATA-IN-URL", f"URL contains raw {', '.join(raw_types)}")

        # 3. Payload DLP on the remaining arguments.
        for fname, value in args.items():
            if fname in spec.recipient_fields or fname in spec.url_fields:
                continue
            raw = self._restricted_raw(str(value), policy)
            if raw:
                g.add(
                    Verdict.BLOCK, "R-TOOL-RAW-SENSITIVE", f"argument {fname!r} contains raw {', '.join(raw)}"
                )
            if spec.url_fields and STRICT_PLACEHOLDER_RE.search(str(value)):
                g.add(
                    Verdict.BLOCK,
                    "R-TOOL-DATA-IN-PAYLOAD",
                    f"argument {fname!r} sends tokenized data to a URL",
                )

        # 4. Taint: after reading injected content, risky tools are off for the rest of the run.
        if state.tainted and risk in ("medium", "high") and tools.block_risky_tools_when_tainted:
            g.add(
                Verdict.BLOCK,
                "R-TOOL-TAINTED-SESSION",
                "session read content flagged as prompt injection (" + ", ".join(state.taint_sources) + ")",
            )

        # 5. High-risk actions that passed every check still need a human.
        if g.verdict is Verdict.ALLOW and risk == "high":
            g.add(
                Verdict.REQUIRE_APPROVAL,
                "R-TOOL-HIGH-RISK",
                f"{call.name} is a high-risk action and needs approval",
            )
        return g

    def _sensitive_types(self, text: str, policy: Policy) -> set[str]:
        scan = self.dlp.scan(text, policy, use_ner=False)
        return {f.entity_type.value for f in scan.applied}
