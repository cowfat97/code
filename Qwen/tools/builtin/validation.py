"""Offline Draft 2020-12 schema validation."""

from itertools import islice
from typing import Any

from jsonschema import Draft202012Validator
from referencing import Registry


def validate_json(value: Any, json_schema: dict[str, Any]) -> dict[str, Any]:
    """Validate JSON data offline; return up to 100 errors. Remote refs are never fetched."""

    Draft202012Validator.check_schema(json_schema)
    errors = sorted(
        islice(
            Draft202012Validator(json_schema, registry=Registry()).iter_errors(value), 100
        ),
        key=lambda error: str(list(error.absolute_path)),
    )
    return {
        "valid": not errors,
        "errors": [
            {
                "path": list(error.absolute_path),
                "message": error.message,
                "schema_path": list(error.absolute_schema_path),
            }
            for error in errors
        ],
    }
