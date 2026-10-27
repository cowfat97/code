"""Gateway settings; relative paths belong to their configuration file."""

import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field


class BuiltinConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    read_roots: list[str] = Field(default_factory=list)
    artifact_dir: str = Field(default="../artifacts", min_length=1)
    http_allowed_origins: list[str] = Field(default_factory=list)
    max_file_bytes: int = Field(default=2_000_000, gt=0)
    max_response_bytes: int = Field(default=2_000_000, gt=0)
    max_list_entries: int = Field(default=1000, gt=0)


class GatewayConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    builtin: BuiltinConfig = Field(default_factory=BuiltinConfig)
    load_builtin: bool = True
    load_mcp: bool = True
    concurrency: int = Field(default=8, gt=0)
    timeout: float = Field(default=30.0, gt=0, allow_inf_nan=False)
    mcp_file: str = Field(default="mcp.json", min_length=1)
    monitor_file: str | None = "../state/events.sqlite3"

    @classmethod
    def load(cls, path: Path):
        return cls.model_validate(json.loads(path.read_text(encoding="utf-8")))
