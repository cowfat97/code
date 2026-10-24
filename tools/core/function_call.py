"""Function-call wire formats, independent of a model SDK."""

import json
from typing import Any

from .models import ToolValidationError


def parse_arguments(arguments: str | dict[str, Any]) -> dict[str, Any]:
    try:
        value = json.loads(arguments) if isinstance(arguments, str) else arguments
    except (ValueError, TypeError):
        raise ToolValidationError("function arguments must be a JSON object") from None
    if not isinstance(value, dict):
        raise ToolValidationError("function arguments must be a JSON object")
    return value
