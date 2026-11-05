"""Process-wide catalog, policies, mock provider, and decision log."""

from __future__ import annotations

import threading

from switchboard.catalog import Catalog, get_catalog
from switchboard.policy import Policy, PolicyError, load_policies, load_policy_text
from switchboard.provider import MockProvider
from switchboard.settings import Settings
from switchboard.store import Store


class Runtime:
    def __init__(self, settings: Settings, catalog: Catalog | None = None) -> None:
        self.settings = settings
        self.catalog = catalog or get_catalog()
        self.policies = load_policies(known_models=set(self.catalog.models))
        if settings.default_policy not in self.policies:
            known = ", ".join(sorted(self.policies))
            raise PolicyError(f"SWITCHBOARD_POLICY={settings.default_policy!r} is not one of: {known}")
        self.active = settings.default_policy
        self.store = Store(settings.db_path)
        self.provider = MockProvider(self.catalog)
        self._lock = threading.Lock()

    def policy(self, name: str | None = None) -> Policy:
        key = name or self.active
        try:
            return self.policies[key]
        except KeyError as exc:
            raise KeyError(key) from exc

    def set_active(self, name: str) -> Policy:
        policy = self.policy(name)
        with self._lock:
            self.active = policy.name
        return policy

    def parse_candidate(self, text: str) -> Policy:
        return load_policy_text(text, known_models=set(self.catalog.models))
