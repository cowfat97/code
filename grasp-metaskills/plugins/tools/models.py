"""Public tool metadata, results, and exceptions."""

from dataclasses import dataclass, field
from typing import Any


class ToolError(Exception):
    """Base error for registry operations."""


class ToolValidationError(ToolError):
    """Arguments do not satisfy the tool's JSON Schema."""


class ToolExecutionError(ToolError):
    """A tool failed or its returned value violated its schema."""


class ToolNotFoundError(ToolError):
    """The requested tool is not registered."""


class DuplicateToolError(ToolError):
    """A tool name is already registered."""


class MCPConnectionError(ToolError):
    """Configured MCP connections could not be established."""


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    description: str
    input_schema: dict[str, Any]
    output_schema: dict[str, Any] | None = None
    source: str = "local"


@dataclass
class ToolResult:
    data: Any = None
    content: list[dict[str, Any]] = field(default_factory=list)
    is_error: bool = False
