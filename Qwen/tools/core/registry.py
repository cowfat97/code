"""A single metadata registry for functions and MCP tools."""

import copy
import inspect
from dataclasses import dataclass
from typing import Any

from jsonschema import validators

from .models import DuplicateToolError, ToolDefinition, ToolNotFoundError
from .schema import function_schema


@dataclass
class Entry:
    definition: ToolDefinition
    target: Any
    arguments_model: Any = None
    remote_name: str | None = None


class ToolRegistry:
    def __init__(self) -> None:
        self.entries: dict[str, Entry] = {}

    def add(self, entry: Entry) -> None:
        name = entry.definition.name
        if not isinstance(name, str) or not name.strip():
            raise ValueError("tool name must be nonempty")
        if name in self.entries:
            raise DuplicateToolError(name)
        for schema in (entry.definition.input_schema, entry.definition.output_schema):
            if schema is not None:
                validators.validator_for(schema).check_schema(schema)
        self.entries[name] = copy.deepcopy(entry) if entry.target is None else entry

    def register(
        self,
        fn: Any,
        *,
        name: str | None = None,
        description: str | None = None,
        input_schema: Any = None,
        output_schema: Any = None,
    ) -> None:
        if not callable(fn):
            raise TypeError("tool must be callable")
        model = None
        if input_schema is None:
            input_schema, model, _ = function_schema(fn)
        if output_schema is None:
            from .schema import output_schema as infer

            output_schema = infer(fn)
        self.add(
            Entry(
                ToolDefinition(
                    name if name is not None else fn.__name__,
                    description if description is not None else inspect.getdoc(fn) or "",
                    copy.deepcopy(input_schema),
                    copy.deepcopy(output_schema),
                    "local",
                ),
                fn,
                model,
            )
        )

    def get(self, name: str) -> Entry:
        try:
            return self.entries[name]
        except KeyError:
            raise ToolNotFoundError(name) from None

    def remove(self, name: str) -> Entry:
        entry = self.get(name)
        del self.entries[name]
        return entry

    def list_tools(self) -> list[ToolDefinition]:
        return [copy.deepcopy(e.definition) for e in self.entries.values()]
