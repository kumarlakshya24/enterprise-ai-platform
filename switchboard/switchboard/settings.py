"""Process settings. Everything has a default so the demo runs with no env file."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _flag(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    host: str = "127.0.0.1"
    port: int = 8092
    db_path: str = "switchboard.db"
    default_policy: str = "default"
    demo_controls: bool = True
    fault_injection: bool = True
    log_level: str = "INFO"

    @property
    def project_root(self) -> Path:
        return Path(__file__).resolve().parents[1]


def load_settings() -> Settings:
    port = int(os.environ.get("SWITCHBOARD_PORT", os.environ.get("PORT", "8092")))
    return Settings(
        host=os.environ.get("SWITCHBOARD_HOST", "127.0.0.1"),
        port=port,
        db_path=os.environ.get("SWITCHBOARD_DB", "switchboard.db"),
        default_policy=os.environ.get("SWITCHBOARD_POLICY", "default"),
        demo_controls=_flag("SWITCHBOARD_DEMO_CONTROLS", True),
        fault_injection=_flag("SWITCHBOARD_FAULT_INJECTION", True),
        log_level=os.environ.get("SWITCHBOARD_LOG_LEVEL", "INFO"),
    )
