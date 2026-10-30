"""Harness-independent task template management."""

from .manager import TaskManager
from .models import (
    IntentMatch,
    TaskDefinition,
    TaskError,
    TaskValidationError,
    Template,
    TemplateError,
    ValidationIssue,
    ValidationResult,
    YamlError,
)

__all__ = [
    "IntentMatch",
    "TaskDefinition",
    "TaskError",
    "TaskManager",
    "TaskValidationError",
    "Template",
    "TemplateError",
    "ValidationIssue",
    "ValidationResult",
    "YamlError",
]
