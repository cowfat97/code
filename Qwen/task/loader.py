"""Bounded YAML parsing, limited to JSON-compatible values."""

import math
from collections.abc import Hashable
from typing import Any

import yaml
from yaml.nodes import MappingNode

from .models import YamlError

MAX_BYTES = 1_048_576
MAX_NODES = 20_000
MAX_DEPTH = 64


class _Loader(yaml.SafeLoader):
    def construct_mapping(
        self, node: MappingNode, deep: bool = False
    ) -> dict[Hashable, Any]:
        result: dict[Hashable, Any] = {}
        for key_node, value_node in node.value:
            key = self.construct_object(key_node, deep=deep)
            if not isinstance(key, str):
                raise YamlError("Mapping keys must be strings")
            if key in result:
                raise YamlError(f"Duplicate mapping key: {key}")
            result[key] = self.construct_object(value_node, deep=deep)
        return result


def check_json(value: Any) -> None:
    """Bound traversal including expanded aliases and reject cyclic objects."""
    count = 0
    active: set[int] = set()

    def visit(item: Any, depth: int) -> None:
        nonlocal count
        count += 1
        if count > MAX_NODES or depth > MAX_DEPTH:
            raise YamlError("Document exceeds structural limits")
        if type(item) in (dict, list):
            identity = id(item)
            if identity in active:
                raise YamlError("Cyclic values are not supported")
            active.add(identity)
            if isinstance(item, dict):
                for key, child in item.items():
                    if type(key) is not str:
                        raise YamlError("Mapping keys must be strings")
                    visit(child, depth + 1)
            else:
                for child in item:
                    visit(child, depth + 1)
            active.remove(identity)
        elif type(item) not in (str, int, float, bool, type(None)):
            raise YamlError("Values must be JSON-compatible")
        elif isinstance(item, float) and not math.isfinite(item):
            raise YamlError("Numbers must be finite")

    visit(value, 0)


def parse_yaml(text: str) -> dict[str, Any]:
    if not isinstance(text, str):
        raise YamlError("YAML input must be text")
    if len(text.encode("utf-8")) > MAX_BYTES:
        raise YamlError("Document exceeds size limit")
    try:
        value = yaml.load(text, Loader=_Loader)
        check_json(value)
    except (yaml.YAMLError, RecursionError, ValueError) as exc:
        raise YamlError("Invalid YAML document") from exc
    if not isinstance(value, dict):
        raise YamlError("Task YAML must be a mapping")
    return value
