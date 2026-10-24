"""Explicit JSON/TOML configuration. Nothing connects during import."""

import json
import tomllib
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class MCPServerConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    transport: Literal["stdio", "streamable_http", "sse"] = "stdio"
    command: str | None = None
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] | None = None
    url: str | None = None
    headers: dict[str, str] = Field(default_factory=dict)
    connection_timeout: float = Field(default=30.0, gt=0, allow_inf_nan=False)
    enabled: bool = True
    allowed_tools: list[str] | None = None

    @model_validator(mode="after")
    def check_transport(self) -> Self:
        if self.enabled and not (self.command if self.transport == "stdio" else self.url):
            raise ValueError("enabled server requires command (stdio) or url (HTTP/SSE)")
        return self


class ToolsConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    mcp_servers: dict[str, MCPServerConfig] = Field(default_factory=dict)

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> Self:
        return cls.model_validate(value)

    @classmethod
    def load(cls, path: str | Path) -> Self:
        path = Path(path)
        with path.open("rb") as stream:
            value = tomllib.load(stream) if path.suffix.lower() == ".toml" else json.load(stream)
        return cls.from_mapping(value)
