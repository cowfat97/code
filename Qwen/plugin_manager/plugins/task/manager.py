"""Template discovery, validation, creation and atomic task persistence."""

import copy
import hashlib
import json
import os
import re
import tempfile
import uuid
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError

from .loader import MAX_BYTES, check_json, parse_yaml
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

_ID = re.compile(r"[A-Za-z0-9_-]{1,64}\Z")
_DRAFT = "https://json-schema.org/draft/2020-12/schema"


def _read(path: Path) -> str:
    with path.open("rb") as stream:
        content = stream.read(MAX_BYTES + 1)
    if len(content) > MAX_BYTES:
        raise TemplateError("Template file exceeds size limit")
    return content.decode("utf-8")


def _merge(defaults: dict[str, Any], data: dict[str, Any]) -> dict[str, Any]:
    merged = copy.deepcopy(defaults)
    for key, value in data.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _merge(merged[key], value)
        else:
            merged[key] = copy.deepcopy(value)
    return merged


def _pointer(parts: list[Any]) -> str:
    return (
        "/" + "/".join(str(p).replace("~", "~0").replace("/", "~1") for p in parts)
        if parts
        else ""
    )


def _validate(data: dict[str, Any], template: Template) -> ValidationResult:
    issues: list[ValidationIssue] = []
    for error in Draft202012Validator(template.schema).iter_errors(data):
        parts = list(error.absolute_path)
        if error.validator == "required" and isinstance(error.instance, dict):
            for key in error.validator_value:
                if key not in error.instance:
                    issue = ValidationIssue(
                        _pointer(parts + [key]), "Required field is missing", "required"
                    )
                    if issue not in issues:
                        issues.append(issue)
        else:
            issues.append(
                ValidationIssue(_pointer(parts), error.message, str(error.validator))
            )
    return ValidationResult(
        not issues, tuple(sorted(issues, key=lambda i: (i.path, i.code, i.message)))
    )


def _check_schema(schema: dict[str, Any]) -> None:
    if schema.get("$schema", _DRAFT).rstrip("#") != _DRAFT:
        raise TemplateError("Only JSON Schema Draft 2020-12 is supported")
    if schema.get("type") != "object":
        raise TemplateError("Template schema must declare type object")

    map_keywords = {
        "$defs",
        "definitions",
        "properties",
        "patternProperties",
        "dependentSchemas",
        "dependencies",
    }
    single_keywords = {
        "additionalProperties",
        "unevaluatedProperties",
        "propertyNames",
        "contains",
        "items",
        "not",
        "if",
        "then",
        "else",
        "unevaluatedItems",
        "contentSchema",
        "additionalItems",
    }
    array_keywords = {"allOf", "anyOf", "oneOf", "prefixItems"}
    nodes: list[dict[str, Any]] = []

    def walk(value: Any) -> None:
        # Instance-valued keywords (const/default/enum/examples) are data, not schemas.
        if not isinstance(value, dict):
            return
        nodes.append(value)
        for key in ("$ref", "$dynamicRef", "$id"):
            if key in value and (
                not isinstance(value[key], str) or not value[key].startswith("#")
            ):
                raise TemplateError(
                    "Only local fragment schema references and IDs are allowed"
                )
        for key, child in value.items():
            if key in map_keywords and isinstance(child, dict):
                for subschema in child.values():
                    walk(subschema)
            elif key in single_keywords:
                walk(child)
            elif key in array_keywords and isinstance(child, list):
                for subschema in child:
                    walk(subschema)

    walk(schema)
    Draft202012Validator.check_schema(schema)
    # Resolve actual schema references, including optional branches, without retrieval.
    from referencing import Registry, Resource
    from referencing.jsonschema import DRAFT202012

    resource = Resource.from_contents(schema, default_specification=DRAFT202012)
    resolver = Registry().resolver_with_root(resource)
    for node in nodes:
        for key in ("$ref", "$dynamicRef"):
            if key in node:
                resolver.lookup(node[key])


class TaskManager:
    def __init__(self, template_dir: str | Path | None = None):
        self.template_dir = (
            Path(template_dir)
            if template_dir is not None
            else Path(__file__).parent / "templates"
        ).resolve()

    def list_templates(self) -> list[str]:
        if not self.template_dir.is_dir():
            raise TemplateError("Template directory does not exist")
        result = []
        for child in self.template_dir.iterdir():
            if (
                _ID.fullmatch(child.name)
                and child.is_dir()
                and (child / "template.yaml").exists()
                and (child / "schema.json").exists()
            ):
                self.load_template(child.name)
                result.append(child.name)
        return sorted(result)

    def load_template(self, template_id: str) -> Template:
        if not isinstance(template_id, str) or not _ID.fullmatch(template_id):
            raise TemplateError("Invalid template ID")
        directory = self.template_dir / template_id
        paths = [directory / "template.yaml", directory / "schema.json"]
        for path in paths:
            if not path.resolve().is_relative_to(self.template_dir):
                raise TemplateError("Template path escapes template directory")
        try:
            defaults = parse_yaml(_read(paths[0]))
            schema = parse_yaml(_read(paths[1]))
            _check_schema(schema)
        except (OSError, UnicodeError, YamlError, SchemaError) as exc:
            raise TemplateError(f"Cannot load template {template_id}: {exc}") from exc
        except TemplateError:
            raise
        except Exception as exc:
            raise TemplateError(f"Invalid schema references in {template_id}") from exc
        snapshot = json.dumps(
            {"defaults": defaults, "schema": schema},
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
        )
        digest = hashlib.sha256(snapshot.encode()).hexdigest()
        return Template(template_id, defaults, schema, digest)

    def recognize(self, text: str, *, fallback: str = "basic") -> IntentMatch:
        """Match explicit keyword routes; ambiguous matches use the generic fallback."""
        if not isinstance(text, str):
            raise TypeError("Intent text must be a string")
        self.load_template(fallback)
        normalized = text.casefold()
        candidates: list[tuple[tuple[int, int, int], str, tuple[str, ...]]] = []
        for template_id in self.list_templates():
            path = self.template_dir / template_id / "intent.json"
            if not path.resolve().is_relative_to(self.template_dir):
                raise TemplateError("Intent path escapes template directory")
            if not path.exists():
                continue
            try:
                route = json.loads(_read(path))
            except (OSError, UnicodeError, ValueError) as exc:
                raise TemplateError(f"Cannot load intent for {template_id}: {exc}") from exc
            if (
                not isinstance(route, dict)
                or route.keys() - {"keywords", "priority"}
                or not isinstance(route.get("keywords"), list)
                or not route["keywords"]
                or any(not isinstance(word, str) or not word.strip() for word in route["keywords"])
                or type(route.get("priority", 0)) is not int
            ):
                raise TemplateError(f"Invalid intent configuration for {template_id}")
            words = sorted({word.casefold() for word in route["keywords"]})
            matched = tuple(word for word in words if word in normalized)
            if matched:
                score = (route.get("priority", 0), len(matched), sum(map(len, matched)))
                candidates.append((score, template_id, matched))
        if not candidates:
            return IntentMatch(fallback, False, "unmatched")
        best = max(score for score, _, _ in candidates)
        winners = [candidate for candidate in candidates if candidate[0] == best]
        if len(winners) != 1:
            return IntentMatch(fallback, False, "ambiguous")
        _, template_id, matched = winners[0]
        return IntentMatch(template_id, True, "matched", matched)

    def parse_yaml(self, text: str) -> dict[str, Any]:
        return parse_yaml(text)

    def _effective(self, data: dict[str, Any], template: Template) -> dict[str, Any]:
        check_json(data)
        if not isinstance(data, dict):
            raise YamlError("Task data must be a mapping")
        effective = _merge(template.defaults, data)
        check_json(effective)
        return effective

    def validate(self, data: dict[str, Any], *, template_id: str) -> ValidationResult:
        template = self.load_template(template_id)
        return _validate(self._effective(data, template), template)

    def create(self, data: dict[str, Any], *, template_id: str) -> TaskDefinition:
        template = self.load_template(template_id)
        effective = self._effective(data, template)
        result = _validate(effective, template)
        if not result.valid:
            raise TaskValidationError(result)
        return TaskDefinition(str(uuid.uuid4()), template_id, template.hash, effective)

    def save(
        self, task: TaskDefinition, path: str | Path, *, overwrite: bool = False
    ) -> Path:
        if not isinstance(task, TaskDefinition):
            raise TaskError("Expected TaskDefinition")
        target = Path(path).absolute()
        if target.resolve().is_relative_to(self.template_dir):
            raise TaskError("Cannot save tasks inside template directory")
        value = task.as_dict()
        check_json(value)
        content = yaml.safe_dump(value, allow_unicode=True, sort_keys=False)
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary: str | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=target.parent,
                prefix=".task-",
                delete=False,
            ) as stream:
                temporary = stream.name
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            if overwrite:
                os.replace(temporary, target)
            else:
                os.link(temporary, target)
            return target
        finally:
            if temporary is not None:
                Path(temporary).unlink(missing_ok=True)
