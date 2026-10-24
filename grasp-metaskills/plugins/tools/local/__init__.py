"""Plugin-owned tools: add modules here, import functions, and add them to TOOLS."""

from collections.abc import Callable
from typing import Any

from ..registry import ToolRegistry

TOOLS: dict[str, Callable[..., Any]] = {}


def register_tools(registry: ToolRegistry) -> None:
    """Register the explicit tool map once for each plugin startup."""
    for name, function in TOOLS.items():
        registry.register(function, name=name)
