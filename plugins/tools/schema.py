"""JSON Schema checks and Python function annotation adapters."""

import inspect
from collections.abc import Callable
from typing import Any, get_type_hints

from jsonschema import validators
from pydantic import ConfigDict, TypeAdapter, create_model
from referencing import Registry

from .models import ToolResult, ToolValidationError


def validate(
    schema: dict[str, Any],
    value: Any,
    error_type: type[Exception] = ToolValidationError,
) -> None:
    validator = validators.validator_for(schema)
    validator.check_schema(schema)
    try:
        errors = sorted(
            validator(schema, registry=Registry()).iter_errors(value),
            key=lambda e: str(e.path),
        )
    except Exception as exc:
        raise error_type("schema reference could not be resolved locally") from exc
    if errors:
        raise error_type(errors[0].message)


def function_schema(
    fn: Callable[..., Any],
) -> tuple[dict[str, Any], Any, dict[str, Any] | None]:
    signature = inspect.signature(fn)
    hints = get_type_hints(fn)
    fields: dict[str, Any] = {}
    for name, parameter in signature.parameters.items():
        if parameter.kind in (
            parameter.POSITIONAL_ONLY,
            parameter.VAR_POSITIONAL,
            parameter.VAR_KEYWORD,
        ):
            raise ValueError(
                "automatic schemas require named parameters; provide input_schema for **kwargs"
            )
        annotation = hints.get(name, Any)
        default = ... if parameter.default is inspect.Parameter.empty else parameter.default
        fields[name] = (annotation, default)
    model = create_model(f"{fn.__name__}Arguments", __config__=ConfigDict(extra="forbid"), **fields)
    return model.model_json_schema(), model, output_schema(fn)


def output_schema(fn: Callable[..., Any]) -> dict[str, Any] | None:
    hints = get_type_hints(fn)
    return (
        TypeAdapter(hints["return"]).json_schema()
        if "return" in hints and hints["return"] is not ToolResult
        else None
    )
