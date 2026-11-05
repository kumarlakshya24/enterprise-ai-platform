"""Environment configuration. Offline defaults. No secrets."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def load_env_file(path: str | Path = ".env") -> None:
    """Load KEY=VALUE pairs without overriding the real environment."""
    file = Path(path)
    if not file.is_file():
        return
    for raw in file.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


@dataclass(frozen=True)
class Settings:
    db_path: str
    effects_path: str
    lease_seconds: float
    guard: str
    aegis_base_url: str
    knowledge: str
    lumen_base_url: str
    lumen_user_id: str
    host: str
    port: int

    @classmethod
    def from_env(cls) -> Settings:
        load_env_file()
        return cls(
            db_path=os.environ.get("ATLAS_DB", "./var/atlas.db"),
            effects_path=os.environ.get("ATLAS_EFFECTS_DB", "./var/effects.db"),
            lease_seconds=float(os.environ.get("ATLAS_LEASE_SECONDS", "30")),
            guard=os.environ.get("ATLAS_GUARD", "offline"),
            aegis_base_url=os.environ.get("AEGIS_BASE_URL", "http://127.0.0.1:8080"),
            knowledge=os.environ.get("ATLAS_KNOWLEDGE", "offline"),
            lumen_base_url=os.environ.get("LUMEN_BASE_URL", "http://127.0.0.1:8000"),
            lumen_user_id=os.environ.get("LUMEN_USER_ID", "atlas-worker"),
            host=os.environ.get("ATLAS_HOST", "127.0.0.1"),
            port=int(os.environ.get("ATLAS_PORT", "8095")),
        )
