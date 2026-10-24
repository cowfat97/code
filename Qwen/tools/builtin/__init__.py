"""Explicit builtins; importing this package does not execute tools."""

from collections.abc import Callable
from typing import Any

from .text import count_chars

BUILTIN_TOOLS: dict[str, Callable[..., Any]] = {"count_chars": count_chars}
