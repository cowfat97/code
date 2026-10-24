"""Gateway settings; relative paths belong to their configuration file."""

import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field


class GatewayConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    load_builtin: bool = True
    load_mcp: bool = True
    concurrency: int = Field(default=8, gt=0)
    timeout: float = Field(default=30.0, gt=0, allow_inf_nan=False)
    mcp_file: str = Field(default="mcp.json", min_length=1)
    monitor_file: str | None = "../state/events.sqlite3"

    @classmethod
    def load(cls, path: Path):
        return cls.model_validate(json.loads(path.read_text(encoding="utf-8")))
