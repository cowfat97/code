"""Local stdio MCP configuration; installation is outside this module."""

import json
from pathlib import Path
from typing import Self

from pydantic import BaseModel, ConfigDict, Field


class MCPServerConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    command: str = Field(min_length=1)
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] | None = None
    cwd: str | None = None
    enabled: bool = True
    allowed_tools: list[str] | None = None
    connection_timeout: float = Field(default=30.0, gt=0, allow_inf_nan=False)


class MCPConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    mcp_servers: dict[str, MCPServerConfig] = Field(default_factory=dict)

    @classmethod
    def load(cls, path: str | Path) -> Self:
        path = Path(path).resolve()
        config = cls.model_validate(json.loads(path.read_text(encoding="utf-8")))
        for server in config.mcp_servers.values():
            # Relative server arguments use this explicit working directory.
            server.cwd = str((path.parent / (server.cwd or ".")).resolve())
        return config
