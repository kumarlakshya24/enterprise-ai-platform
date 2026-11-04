"""Versioned policy store. One active bundle per deployment; every revision is kept."""

from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from importlib import resources
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy import Engine, insert, select, update

from aegis.db import policy_versions
from aegis.policy.schema import Policy, PolicyBundle


def load_bundle_file(path: str | Path | None = None) -> PolicyBundle:
    if path:
        raw = Path(path).read_text()
    else:
        raw = resources.files("aegis.policy").joinpath("default_policy.yaml").read_text()
    return PolicyBundle.model_validate(yaml.safe_load(raw))


@dataclass(frozen=True)
class ActivePolicy:
    revision: int
    digest: str
    bundle: PolicyBundle

    @property
    def version(self) -> str:
        return f"r{self.revision}-{self.digest}"


class PolicyStore:
    def __init__(self, engine: Engine, default_bundle: PolicyBundle, refresh_seconds: float = 5.0) -> None:
        self.engine = engine
        self.default_bundle = default_bundle
        self.refresh_seconds = refresh_seconds
        self._lock = threading.Lock()
        self._active: ActivePolicy | None = None
        self._loaded_at = 0.0
        self._effective: dict[tuple[int, str, str | None], Policy] = {}

    def bootstrap(self) -> None:
        with self.engine.begin() as conn:
            exists = conn.execute(
                select(policy_versions.c.revision).where(policy_versions.c.active.is_(True))
            ).first()
            if exists is None:
                conn.execute(
                    insert(policy_versions).values(
                        digest=self.default_bundle.digest(),
                        created_at=datetime.now(UTC).isoformat(),
                        created_by="system:bootstrap",
                        note="default policy",
                        bundle=json.dumps(self.default_bundle.model_dump(mode="json")),
                        active=True,
                    )
                )
        self._load()

    def _load(self) -> ActivePolicy:
        with self.engine.connect() as conn:
            row = conn.execute(
                select(policy_versions)
                .where(policy_versions.c.active.is_(True))
                .order_by(policy_versions.c.revision.desc())
            ).first()
        if row is None:
            raise RuntimeError("no active policy; call bootstrap()")
        bundle = PolicyBundle.model_validate(json.loads(row.bundle))
        active = ActivePolicy(int(row.revision), str(row.digest), bundle)
        with self._lock:
            if self._active is None or self._active.revision != active.revision:
                self._effective.clear()
            self._active = active
            self._loaded_at = time.monotonic()
        return active

    def active(self) -> ActivePolicy:
        if self._active is None or time.monotonic() - self._loaded_at > self.refresh_seconds:
            return self._load()
        return self._active

    def effective(self, tenant_id: str, user_sub: str | None) -> tuple[Policy, str]:
        active = self.active()
        key = (active.revision, tenant_id, user_sub)
        policy = self._effective.get(key)
        if policy is None:
            policy = active.bundle.effective(tenant_id, user_sub)
            with self._lock:
                self._effective[key] = policy
        return policy, active.version

    def activate(self, bundle: PolicyBundle, actor: str, note: str = "") -> ActivePolicy:
        """Persist and activate a bundle. Callers must run the regression gate first."""
        with self.engine.begin() as conn:
            conn.execute(
                update(policy_versions).where(policy_versions.c.active.is_(True)).values(active=False)
            )
            conn.execute(
                insert(policy_versions).values(
                    digest=bundle.digest(),
                    created_at=datetime.now(UTC).isoformat(),
                    created_by=actor,
                    note=note,
                    bundle=json.dumps(bundle.model_dump(mode="json")),
                    active=True,
                )
            )
        return self._load()

    def history(self, limit: int = 20) -> list[dict[str, Any]]:
        with self.engine.connect() as conn:
            rows = conn.execute(
                select(
                    policy_versions.c.revision,
                    policy_versions.c.digest,
                    policy_versions.c.created_at,
                    policy_versions.c.created_by,
                    policy_versions.c.note,
                    policy_versions.c.active,
                )
                .order_by(policy_versions.c.revision.desc())
                .limit(limit)
            )
            return [dict(r._mapping) for r in rows]
