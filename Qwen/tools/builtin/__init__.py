"""Explicit builtins; importing this package does not execute tools."""

from collections.abc import Callable
from typing import Any

from .text import count_chars

BUILTIN_TOOLS: dict[str, Callable[..., Any]] = {"count_chars": count_chars}


def configured_tools(config: Any, base: Any) -> dict[str, Callable[..., Any]]:
    """Create gateway-local policy closures; never mutate global builtin definitions."""
    from .files import FileTools
    from .network import HTTPTools
    from .validation import validate_json

    files = FileTools(
        [(base / root).resolve() for root in config.read_roots],
        (base / config.artifact_dir).resolve(),
        config.max_file_bytes,
        config.max_list_entries,
    )
    network = HTTPTools(config.http_allowed_origins, config.max_response_bytes)
    return {
        "read_file": files.read_file,
        "list_files": files.list_files,
        "parse_document": files.parse_document,
        "write_artifact": files.write_artifact,
        "validate_json": validate_json,
        "http_request": network.http_request,
        **BUILTIN_TOOLS,
    }
