"""Policy schema. Network cannot be set to allow; the field exists so a bad edit fails closed."""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

from forge.config import DEFAULT_POLICY_PATH


class ToolLimit(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    timeout_ms: int = Field(default=1500, ge=100, le=60_000)
    max_memory_mb: int = Field(default=256, ge=32, le=2048)
    max_output_bytes: int = Field(default=8192, ge=64, le=1_000_000)
    max_code_bytes: int = Field(default=4000, ge=64, le=100_000)
    max_write_bytes: int = Field(default=8192, ge=64, le=1_000_000)


class ImportRules(BaseModel):
    model_config = ConfigDict(extra="forbid")

    allow: list[str]
    deny: list[str] = Field(default_factory=list)


class Ceilings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    timeout_ms: int = Field(default=5000, ge=100, le=5000)
    max_memory_mb: int = Field(default=512, ge=32, le=512)
    max_output_bytes: int = Field(default=65536, ge=64, le=65536)
    max_code_bytes: int = Field(default=8000, ge=64, le=8000)
    max_write_bytes: int = Field(default=65536, ge=64, le=65536)


class Policy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: str
    network: str = "deny"
    ceilings: Ceilings = Field(default_factory=Ceilings)
    tools: dict[str, ToolLimit]
    imports: ImportRules

    @field_validator("network")
    @classmethod
    def _network_is_deny(cls, value: str) -> str:
        if value != "deny":
            raise ValueError("network must be deny")
        return value


def load_policy(path: Path | None = None) -> Policy:
    target = path or DEFAULT_POLICY_PATH
    data = yaml.safe_load(target.read_text(encoding="utf-8"))
    return Policy.model_validate(data)


def load_default_policy() -> Policy:
    return load_policy(DEFAULT_POLICY_PATH)
