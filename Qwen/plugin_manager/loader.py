"""Strict configuration and lazy loading of independent child packages."""

from __future__ import annotations

import json
import keyword
from collections.abc import Callable
from importlib import import_module
from pathlib import Path
from typing import Any, cast

from .contracts import Plugin


def _object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON field: {key}")
        result[key] = value
    return result


def _constant(value: str) -> Any:
    raise ValueError(f"non-finite JSON number: {value}")


def load_factories(path: Path) -> list[tuple[str, Callable[[], Plugin]]]:
    """Read declarations without importing or constructing any child plugin."""
    value = json.loads(
        path.read_text(encoding="utf-8"),
        object_pairs_hook=_object,
        parse_constant=_constant,
    )
    if not isinstance(value, dict) or set(value) != {"plugins"}:
        raise ValueError("configuration must contain only plugins")
    if not isinstance(value["plugins"], list):
        raise ValueError("plugins must be a list")  # noqa: TRY004 - config errors use ValueError
    result: list[tuple[str, Callable[[], Plugin]]] = []
    names: set[str] = set()
    for item in value["plugins"]:
        if not isinstance(item, dict) or set(item) - {
            "name",
            "type",
            "enabled",
            "config_file",
        }:
            raise ValueError("invalid plugin declaration fields")
        name, kind = item.get("name"), item.get("type")
        if not isinstance(name, str) or not name or any(c.isspace() for c in name):
            raise ValueError("plugin name must be nonempty without whitespace")
        if name in names:
            raise ValueError(f"duplicate plugin name: {name}")
        names.add(name)
        if (
            not isinstance(kind, str)
            or not kind.isidentifier()
            or keyword.iskeyword(kind)
        ):
            raise ValueError("plugin type must be one Python module identifier")
        enabled = item.get("enabled", True)
        if not isinstance(enabled, bool):
            raise ValueError("enabled must be boolean")  # noqa: TRY004 - config errors use ValueError
        config = item.get("config_file")
        if config is not None and (not isinstance(config, str) or not config.strip()):
            raise ValueError("config_file must be a nonempty path or null")
        if enabled:
            config_path = (path.parent / config).resolve() if config else None
            result.append((name, _factory(kind, config_path)))
    return result


def _factory(kind: str, config: Path | None) -> Callable[[], Plugin]:
    def create() -> Plugin:
        module = import_module(f"{__package__}.plugins.{kind}.api")
        if config is None:
            return cast(Plugin, module.Plugin())
        return cast(Plugin, module.Plugin.from_config(config))

    return create
