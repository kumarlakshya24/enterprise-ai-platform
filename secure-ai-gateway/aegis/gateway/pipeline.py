"""The protected request path: DLP -> tokenize -> classify -> decide -> route -> sanitize -> restore.

Every step is timed and every decision is audited. The same `prepare` step is reused by the
agent runner, so chat and agents share one policy implementation.
"""

from __future__ import annotations

import re
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from aegis.auth.oidc import Principal
from aegis.classifier.types import Classification
from aegis.dlp.engine import ScanResult
from aegis.gateway.container import Container
from aegis.guard.approvals import ApprovalError
from aegis.llm.base import ChatMessage, LLMProvider, ProviderError
from aegis.policy.engine import Decision, decide
from aegis.policy.schema import Policy
from aegis.types import Label, Route
from aegis.vault.vault import STRICT_PLACEHOLDER_RE, VaultContext

CHAT_SYSTEM_PROMPT = (
    "You are Acme's internal assistant. The user's text may contain placeholders such as [EMAIL_1] or "
    "[PERSON_NAME_1] that stand for real values held by the company gateway. Use placeholders verbatim "
    "where you need them and never try to guess the real values."
)

BLOCK_MESSAGE = (
    "This request was blocked by policy {rule}. {reason} Nothing was sent to any language model. "
    "If you believe this is a mistake, contact the security team and quote request id {request_id}."
)


def classifier_view(tokenized: str) -> str:
    """Placeholders become generic type tokens: `[EMAIL_3]` -> `[EMAIL]`."""
    return STRICT_PLACEHOLDER_RE.sub(lambda m: f"[{m.group(1)}]", tokenized)


@dataclass
class Prepared:
    request_id: str
    ctx: VaultContext
    policy: Policy
    policy_version: str
    scan: ScanResult
    tokenized: str
    classification: Classification | None
    decision: Decision
    timings: dict[str, float] = field(default_factory=dict)
    audit_ids: list[str] = field(default_factory=list)

    def entities(self) -> list[dict[str, Any]]:
        return [f.public_dict() for f in self.scan.applied]

    def audit_content(self, audit_fingerprint: str) -> dict[str, Any]:
        """Tokenized text up to the policy's label threshold; above it, only a fingerprint."""
        # Entities are already tokenized, so the residual risk is the context label.
        if self.decision.context_label <= self.policy.audit.store_content_up_to:
            return {"prompt_tokenized": self.tokenized, "length": len(self.scan.text)}
        return {
            "withheld": True,
            "reason": f"context label {self.decision.context_label.name} is above the audit content threshold",
            "fingerprint": audit_fingerprint,
            "length": len(self.scan.text),
        }


class Pipeline:
    def __init__(self, c: Container) -> None:
        self.c = c

    # ------------------------------------------------------------------ shared steps

    def prepare(
        self,
        text: str,
        principal: Principal,
        *,
        session_id: str | None,
        purpose: str,
        request_id: str | None = None,
    ) -> Prepared:
        c = self.c
        request_id = request_id or uuid.uuid4().hex[:16]
        timings: dict[str, float] = {}
        t0 = time.perf_counter()
        sid = c.vault.open_session(principal.tenant_id, principal.sub, session_id)
        ctx = VaultContext(principal.tenant_id, principal.sub, sid, purpose)
        policy, version = c.policies.effective(principal.tenant_id, principal.sub)
        timings["setup_ms"] = (time.perf_counter() - t0) * 1000

        t = time.perf_counter()
        scan = c.dlp.scan(text, policy)
        timings["dlp_ms"] = (time.perf_counter() - t) * 1000

        t = time.perf_counter()
        tokenized = c.vault.apply(scan, ctx)
        timings["tokenize_ms"] = (time.perf_counter() - t) * 1000

        t = time.perf_counter()
        classification = None
        if c.classifier is not None and policy.classifier.enabled:
            classification = c.classifier.classify(
                classifier_view(tokenized), policy.classifier.min_confidence
            )
        timings["classify_ms"] = (time.perf_counter() - t) * 1000

        t = time.perf_counter()
        decision = decide(
            text=text, scan=scan, classification=classification, policy=policy, policy_version=version
        )
        timings["policy_ms"] = (time.perf_counter() - t) * 1000
        return Prepared(request_id, ctx, policy, version, scan, tokenized, classification, decision, timings)

    def audit_prepared(self, p: Prepared, principal: Principal, kind: str) -> None:
        a = self.c.audit
        base = {
            "tenant_id": principal.tenant_id,
            "user_id": principal.sub,
            "session_id": p.ctx.session_id,
            "request_id": p.request_id,
            "policy_version": p.policy_version,
        }
        e1 = a.append(
            "prompt_received",
            **base,
            details={"kind": kind, "purpose": p.ctx.purpose, **p.audit_content(a.fingerprint(p.scan.text))},
        )
        e2 = a.append(
            "dlp_redaction",
            **base,
            outcome="redacted" if p.scan.applied else "clean",
            details={
                "entities": p.entities(),
                "entity_counts": p.scan.entity_counts(),
                "detectors_fired": p.scan.detectors_fired(),
                "discarded": [
                    {
                        k: v
                        for k, v in f.public_dict().items()
                        if k in ("entity_type", "detector", "confidence", "status")
                    }
                    for f in p.scan.discarded
                ],
                "ner_backend": self.c.dlp.ner_backend,
            },
        )
        e3 = a.append(
            "routing_decision",
            **base,
            route=p.decision.route.value,
            outcome=p.decision.route.value,
            details=p.decision.public(),
        )
        p.audit_ids += [e1["event_id"], e2["event_id"], e3["event_id"]]

    def provider_for(self, route: Route) -> LLMProvider | None:
        if route.sends_external:
            return self.c.external_llm
        if route is Route.LOCAL_ONLY:
            return self.c.local_llm
        return None

    def finalize_answer(self, answer: str, p: Prepared, principal: Principal) -> dict[str, Any]:
        t = time.perf_counter()
        sanitized = self.c.sanitizer.clean(answer, p.policy.tools.allowed_url_domains)
        restored = self.c.vault.restore_text(sanitized.text, p.ctx, principal.restore_scopes)
        p.timings["restore_ms"] = (time.perf_counter() - t) * 1000
        return {
            "answer": restored.text,
            "output_sanitizer": sanitized.removed,
            "restore": {
                "restored": restored.restored,
                "missing": restored.missing,
                "complete": restored.complete,
            },
        }

    # ------------------------------------------------------------------ chat

    def chat(
        self, text: str, principal: Principal, *, session_id: str | None, purpose: str = "chat"
    ) -> dict[str, Any]:
        t_start = time.perf_counter()
        p = self.prepare(text, principal, session_id=session_id, purpose=purpose)
        self.audit_prepared(p, principal, "chat")
        d = p.decision
        base_audit = {
            "tenant_id": principal.tenant_id,
            "user_id": principal.sub,
            "session_id": p.ctx.session_id,
            "request_id": p.request_id,
            "policy_version": p.policy_version,
        }
        response: dict[str, Any] = {
            "request_id": p.request_id,
            "session_id": p.ctx.session_id,
            "decision": d.public(),
            "entities": p.entities(),
            "discarded_findings": [f.public_dict() for f in p.scan.discarded],
            "sent_to_llm": None,
        }

        if d.route is Route.BLOCK:
            reason = d.reasons[-1] if d.reasons else ""
            ev = self.c.audit.append(
                "request_blocked",
                **base_audit,
                route=d.route.value,
                outcome="blocked",
                details={"rule_id": d.rule_id},
            )
            p.audit_ids.append(ev["event_id"])
            response.update(
                status="blocked",
                answer=BLOCK_MESSAGE.format(
                    rule=d.rule_id, reason=_sentence(reason), request_id=p.request_id
                ),
            )
            return self._finish(response, p, t_start)

        if d.route is Route.REQUIRE_APPROVAL:
            approval = self.c.approvals.create(
                kind="chat",
                principal=principal,
                summary={
                    "rule_id": d.rule_id,
                    "reasons": d.reasons,
                    "entity_counts": p.scan.entity_counts(),
                    "context_label": d.context_label.name,
                    "prompt_chars": len(text),
                },
                payload={
                    "tokenized": p.tokenized,
                    "ctx": {
                        "tenant_id": p.ctx.tenant_id,
                        "user_id": p.ctx.user_id,
                        "session_id": p.ctx.session_id,
                        "purpose": p.ctx.purpose,
                    },
                },
                ttl_seconds=p.policy.tools.approval_ttl_seconds,
                session_id=p.ctx.session_id,
                policy_version=p.policy_version,
            )
            p.audit_ids.append(approval["audit_event_id"])
            response.update(
                status="pending_approval",
                approval_id=approval["id"],
                answer=f"This request needs approval ({d.rule_id}). Approval id {approval['id']} expires at "
                f"{approval['expires_at_iso']}. Nothing has been sent yet.",
            )
            return self._finish(response, p, t_start)

        provider = self.provider_for(d.route)
        if provider is None:  # pragma: no cover - every non-block route has a provider
            raise RuntimeError(f"no provider for route {d.route}")
        return self._call_and_respond(provider, p, principal, response, t_start, base_audit)

    def resume_chat(self, approval_id: str, principal: Principal) -> dict[str, Any]:
        """After a second person approves a held chat request, the requester resumes it."""
        rec = self.c.approvals.get(approval_id, principal.tenant_id)
        if rec.kind != "chat" or rec.requester_id != principal.sub:
            raise ApprovalError(404, "not_found", "approval not found")
        if rec.status != "approved":
            raise ApprovalError(409, "not_approved", f"approval is {rec.status}")
        payload = self.c.approvals.payload(approval_id, principal.tenant_id)
        ctx = VaultContext(**payload["ctx"])
        policy, version = self.c.policies.effective(principal.tenant_id, principal.sub)
        scan = self.c.dlp.scan("", policy)
        decision = Decision(
            Route.REDACT, Label.INTERNAL, None, "R-APPROVED", [f"approved by {rec.decided_by}"], version
        )
        p = Prepared(uuid.uuid4().hex[:16], ctx, policy, version, scan, payload["tokenized"], None, decision)
        base_audit = {
            "tenant_id": principal.tenant_id,
            "user_id": principal.sub,
            "session_id": ctx.session_id,
            "request_id": p.request_id,
            "policy_version": version,
        }
        response: dict[str, Any] = {
            "request_id": p.request_id,
            "session_id": ctx.session_id,
            "decision": decision.public(),
            "approval_id": approval_id,
        }
        out = self._call_and_respond(
            self.c.external_llm, p, principal, response, time.perf_counter(), base_audit
        )
        self.c.approvals.mark_executed(approval_id, principal.tenant_id, {"executed": True, "kind": "chat"})
        return out

    def _call_and_respond(
        self,
        provider: LLMProvider,
        p: Prepared,
        principal: Principal,
        response: dict[str, Any],
        t_start: float,
        base_audit: dict[str, Any],
    ) -> dict[str, Any]:
        messages = [ChatMessage("system", CHAT_SYSTEM_PROMPT), ChatMessage("user", p.tokenized)]
        t = time.perf_counter()
        try:
            llm = provider.complete(messages)
        except ProviderError as exc:
            ev = self.c.audit.append(
                "llm_error",
                **base_audit,
                route=p.decision.route.value,
                outcome="error",
                details={"provider": provider.name, "error": str(exc)},
            )
            p.audit_ids.append(ev["event_id"])
            response.update(
                status="error", answer="The language model is unavailable. Nothing was retried elsewhere."
            )
            return self._finish(response, p, t_start)
        p.timings["llm_ms"] = (time.perf_counter() - t) * 1000
        final = self.finalize_answer(llm.message.content or "", p, principal)
        ev = self.c.audit.append(
            "llm_call",
            **base_audit,
            route=p.decision.route.value,
            outcome="ok",
            details={
                "provider": provider.name,
                "location": provider.location,
                "model": llm.model,
                "prompt_chars": len(p.tokenized),
                "response_chars": len(llm.message.content or ""),
                "placeholders_sent": sorted({f.placeholder for f in p.scan.applied if f.placeholder}),
                "output_sanitizer_removed": len(final["output_sanitizer"]),
                "restored": len(final["restore"]["restored"]),
                "restore_missing": final["restore"]["missing"],
            },
        )
        p.audit_ids.append(ev["event_id"])
        response.update(
            status="ok",
            sent_to_llm={
                "provider": provider.name,
                "location": provider.location,
                "model": llm.model,
                "prompt": p.tokenized,
            },
            **final,
        )
        return self._finish(response, p, t_start)

    def _finish(self, response: dict[str, Any], p: Prepared, t_start: float) -> dict[str, Any]:
        total = (time.perf_counter() - t_start) * 1000
        timings = {k: round(v, 3) for k, v in p.timings.items()}
        timings["total_ms"] = round(total, 3)
        timings["gateway_overhead_ms"] = round(total - p.timings.get("llm_ms", 0.0), 3)
        response["latency_ms"] = timings
        response["audit_event_ids"] = p.audit_ids
        return response


def _sentence(s: str) -> str:
    s = s.strip()
    if not s:
        return ""
    s = s[0].upper() + s[1:]
    return s if re.search(r"[.!?]$", s) else s + "."
