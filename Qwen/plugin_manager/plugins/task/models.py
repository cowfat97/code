"""Independent task values and typed errors."""

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Template:
    id: str
    defaults: dict[str, Any]
    schema: dict[str, Any]
    hash: str


@dataclass(frozen=True)
class ValidationIssue:
    path: str
    message: str
    code: str


@dataclass(frozen=True)
class ValidationResult:
    valid: bool
    issues: tuple[ValidationIssue, ...]


@dataclass(frozen=True)
class IntentMatch:
    template_id: str
    matched: bool
    reason: str
    keywords: tuple[str, ...] = ()


@dataclass(frozen=True)
class TaskDefinition:
    id: str
    template_id: str
    template_hash: str
    data: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        from copy import deepcopy

        return deepcopy(
            {
                "id": self.id,
                "template_id": self.template_id,
                "template_hash": self.template_hash,
                "data": self.data,
            }
        )


class TaskError(Exception):
    """Base task error."""


class TemplateError(TaskError):
    """Invalid or unavailable template."""


class YamlError(TaskError):
    """Unsafe or invalid YAML input."""


class TaskValidationError(TaskError):
    def __init__(self, result: ValidationResult):
        self.result = result
        super().__init__("; ".join(f"{i.path}: {i.message}" for i in result.issues))
