"""Human approval queue for risky tool calls and chat requests.

* Payload encrypted at rest (AES-GCM, AAD bound to the approval id and tenant).
* Approvers need `tool:approve`, must be in the same tenant, and cannot approve their own request.
* Every approval expires; an expired approval can never execute.
"""

from __future__ import annotations

import json
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Engine, insert, select, update

from aegis.audit.store import AuditStore
from aegis.auth.oidc import Principal
from aegis.db import approvals
from aegis.vault.crypto import VaultCipher


class ApprovalError(Exception):
    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, UTC).isoformat(timespec="seconds")


@dataclass
class ApprovalRecord:
    id: str
    tenant_id: str
    requester_id: str
    kind: str
    status: str
    created_at: float
    expires_at: float
    decided_by: str | None
    decided_at: float | None
    summary: dict[str, Any]
    run_id: str | None
    result: dict[str, Any] | None

    def public(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "status": self.status,
            "requester_id": self.requester_id,
            "created_at": _iso(self.created_at),
            "expires_at": _iso(self.expires_at),
            "decided_by": self.decided_by,
            "decided_at": _iso(self.decided_at) if self.decided_at else None,
            "summary": self.summary,
            "run_id": self.run_id,
            "result": self.result,
        }


class ApprovalService:
    def __init__(
        self, engine: Engine, cipher: VaultCipher, audit: AuditStore, clock: Callable[[], float] = time.time
    ):
        self.engine = engine
        self.cipher = cipher
        self.audit = audit
        self.clock = clock

    @staticmethod
    def _aad(approval_id: str, tenant_id: str) -> bytes:
        return f"approval|{approval_id}|{tenant_id}".encode()

    def create(
        self,
        *,
        kind: str,
        principal: Principal,
        summary: dict[str, Any],
        payload: dict[str, Any],
        ttl_seconds: int,
        run_id: str | None = None,
        session_id: str | None = None,
        policy_version: str | None = None,
    ) -> dict[str, Any]:
        aid = str(uuid.uuid4())
        now = self.clock()
        enc = self.cipher.encrypt(json.dumps(payload), self._aad(aid, principal.tenant_id))
        with self.engine.begin() as conn:
            conn.execute(
                insert(approvals).values(
                    id=aid,
                    tenant_id=principal.tenant_id,
                    requester_id=principal.sub,
                    kind=kind,
                    status="pending",
                    created_at=now,
                    expires_at=now + ttl_seconds,
                    summary=json.dumps(summary),
                    payload_enc=enc,
                    run_id=run_id,
                )
            )
        ev = self.audit.append(
            "approval_requested",
            tenant_id=principal.tenant_id,
            user_id=principal.sub,
            session_id=session_id,
            policy_version=policy_version,
            route="require_approval",
            outcome="pending",
            details={
                "approval_id": aid,
                "kind": kind,
                "summary": summary,
                "expires_at": _iso(now + ttl_seconds),
            },
        )
        return {"id": aid, "expires_at_iso": _iso(now + ttl_seconds), "audit_event_id": ev["event_id"]}

    def _row(self, approval_id: str, tenant_id: str) -> tuple[ApprovalRecord, str]:
        with self.engine.connect() as conn:
            r = conn.execute(
                select(approvals).where(approvals.c.id == approval_id, approvals.c.tenant_id == tenant_id)
            ).first()
        if r is None:
            raise ApprovalError(404, "not_found", "approval not found")
        rec = ApprovalRecord(
            r.id,
            r.tenant_id,
            r.requester_id,
            r.kind,
            r.status,
            r.created_at,
            r.expires_at,
            r.decided_by,
            r.decided_at,
            json.loads(r.summary),
            r.run_id,
            json.loads(r.result) if r.result else None,
        )
        return rec, r.payload_enc

    def _expire_if_due(self, rec: ApprovalRecord) -> ApprovalRecord:
        if rec.status == "pending" and self.clock() > rec.expires_at:
            with self.engine.begin() as conn:
                conn.execute(update(approvals).where(approvals.c.id == rec.id).values(status="expired"))
            self.audit.append(
                "approval_expired",
                tenant_id=rec.tenant_id,
                user_id=rec.requester_id,
                outcome="expired",
                details={"approval_id": rec.id},
            )
            rec.status = "expired"
        return rec

    def get(self, approval_id: str, tenant_id: str) -> ApprovalRecord:
        rec, _ = self._row(approval_id, tenant_id)
        return self._expire_if_due(rec)

    def payload(self, approval_id: str, tenant_id: str) -> dict[str, Any]:
        _, enc = self._row(approval_id, tenant_id)
        result: dict[str, Any] = json.loads(self.cipher.decrypt(enc, self._aad(approval_id, tenant_id)))
        return result

    def list(
        self, tenant_id: str, status: str | None = None, requester_id: str | None = None
    ) -> list[dict[str, Any]]:
        q = select(approvals.c.id).where(approvals.c.tenant_id == tenant_id)
        if requester_id:
            q = q.where(approvals.c.requester_id == requester_id)
        with self.engine.connect() as conn:
            ids = [r.id for r in conn.execute(q.order_by(approvals.c.created_at.desc()).limit(200))]
        recs = [self.get(i, tenant_id) for i in ids]
        return [r.public() for r in recs if status is None or r.status == status]

    def decide(
        self,
        approval_id: str,
        approver: Principal,
        approve: bool,
        executor: Callable[[ApprovalRecord, dict[str, Any]], dict[str, Any]] | None,
        note: str = "",
    ) -> dict[str, Any]:
        rec = self.get(approval_id, approver.tenant_id)
        if rec.status == "expired":
            raise ApprovalError(410, "expired", "approval expired; the action will never run")
        if rec.status != "pending":
            raise ApprovalError(409, "already_decided", f"approval is already {rec.status}")
        if approver.sub == rec.requester_id:
            self.audit.append(
                "approval_self_attempt",
                tenant_id=approver.tenant_id,
                user_id=approver.sub,
                outcome="denied",
                details={"approval_id": rec.id},
            )
            raise ApprovalError(403, "four_eyes", "you cannot approve your own request")
        if not approver.has("tool:approve"):
            self.audit.append(
                "approval_denied_permission",
                tenant_id=approver.tenant_id,
                user_id=approver.sub,
                outcome="denied",
                details={"approval_id": rec.id},
            )
            raise ApprovalError(403, "forbidden", "missing permission tool:approve")

        status = "approved" if approve else "denied"
        now = self.clock()
        with self.engine.begin() as conn:
            changed = conn.execute(
                update(approvals)
                .where(approvals.c.id == rec.id, approvals.c.status == "pending")
                .values(status=status, decided_by=approver.sub, decided_at=now)
            ).rowcount
        if changed != 1:
            raise ApprovalError(409, "already_decided", "approval was decided concurrently")
        self.audit.append(
            "approval_granted" if approve else "approval_rejected",
            tenant_id=approver.tenant_id,
            user_id=approver.sub,
            outcome=status,
            details={
                "approval_id": rec.id,
                "requester_id": rec.requester_id,
                "kind": rec.kind,
                "note": note[:200],
            },
        )
        rec.status, rec.decided_by, rec.decided_at = status, approver.sub, now
        if approve and executor is not None:
            result = executor(rec, self.payload(rec.id, rec.tenant_id))
            with self.engine.begin() as conn:
                conn.execute(
                    update(approvals)
                    .where(approvals.c.id == rec.id)
                    .values(status="executed", result=json.dumps(result))
                )
            rec.status, rec.result = "executed", result
        return rec.public()

    def mark_executed(self, approval_id: str, tenant_id: str, result: dict[str, Any]) -> None:
        with self.engine.begin() as conn:
            conn.execute(
                update(approvals)
                .where(approvals.c.id == approval_id, approvals.c.tenant_id == tenant_id)
                .values(status="executed", result=json.dumps(result))
            )
