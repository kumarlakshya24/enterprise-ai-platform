"""Environment. Every variable has a default. No API key is read."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = Path(__file__).resolve().parent


def _env(name: str, default: str) -> str:
    value = os.environ.get(name)
    if value is None or value.strip() == "":
        return default
    return value.strip()


@dataclass(frozen=True, slots=True)
class Settings:
    host: str = "127.0.0.1"
    port: int = 8097
    lumen_url: str = ""
    switchboard_url: str = ""
    report_path: Path = ROOT / "reports" / "latest.json"
    data_dir: Path = PACKAGE / "data"
    static_dir: Path = PACKAGE / "static"

    @classmethod
    def from_env(cls) -> Settings:
        report = _env("ARENA_REPORT", str(ROOT / "reports" / "latest.json"))
        return cls(
            host=_env("ARENA_HOST", "127.0.0.1"),
            port=int(_env("ARENA_PORT", "8097")),
            lumen_url=_env("ARENA_LUMEN_URL", ""),
            switchboard_url=_env("ARENA_SWITCHBOARD_URL", ""),
            report_path=Path(report),
        )
