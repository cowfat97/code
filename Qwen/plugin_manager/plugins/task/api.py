"""Independent, stateless task validation child plugin."""

from __future__ import annotations

import asyncio
import json
import math
from collections.abc import Mapping
from copy import deepcopy
from dataclasses import asdict
from pathlib import Path
from typing import TYPE_CHECKING, Any, Self

from jsonschema import Draft202012Validator

if TYPE_CHECKING:
    from .clarification import LLMProvider
from .manager import TaskManager
from .models import ValidationIssue


class Plugin:
    """Validate task definitions; hosts own conversation and graph dispatch."""

    def __init__(
        self,
        *,
        templates_dir: str | Path | None = None,
        fallback_template: str | None = None,
        llm_provider: LLMProvider | None = None,
        config_file: str | Path | None = None,
    ) -> None:
        settings, base = self._configuration(config_file)
        self.manager = TaskManager(
            templates_dir
            if templates_dir is not None
            else base / settings["templates_dir"]
        )
        self.fallback_template = (
            settings["fallback_template"]
            if fallback_template is None
            else fallback_template
        )
        if (
            not isinstance(self.fallback_template, str)
            or not self.fallback_template.strip()
        ):
            raise ValueError("fallback_template must be a nonempty string")
        self._settings = settings
        self._provider = llm_provider
        if self._provider is None and settings["llm"] is not None:
            from .provider import OpenAIProvider

            self._provider = OpenAIProvider(settings["llm"])
        self._started = False
        self._closing = False
        self._active: set[asyncio.Task[Any]] = set()
        self._close_task: asyncio.Task[None] | None = None

    @staticmethod
    def _configuration(path: str | Path | None) -> tuple[dict[str, Any], Path]:
        path = (
            Path(__file__).parent / "config/task.json" if path is None else Path(path)
        ).resolve()

        def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
            result: dict[str, Any] = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError("Duplicate task configuration key")
                result[key] = value
            return result

        value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique)
        allowed = {
            "templates_dir",
            "fallback_template",
            "llm",
            "timeout",
            "max_questions_per_round",
            "max_prompt_chars",
            "max_response_chars",
            "rules",
        }
        if not isinstance(value, dict) or set(value) - allowed:
            raise ValueError("Invalid task configuration fields")
        settings = {
            "templates_dir": "../templates",
            "fallback_template": "basic",
            "llm": None,
            "timeout": 60.0,
            "max_questions_per_round": 3,
            "max_prompt_chars": 100000,
            "max_response_chars": 100000,
            "rules": {
                "general": [
                    {
                        "id": "goal",
                        "text": "目标与成功条件明确，不能将建议当成用户决定",
                        "blocking": True,
                    },
                    {
                        "id": "scope",
                        "text": "明确任务范围与不包含的内容",
                        "blocking": True,
                    },
                    {
                        "id": "acceptance",
                        "text": "输出要求和验收标准必须可核对",
                        "blocking": True,
                    },
                    {
                        "id": "evidence",
                        "text": "不把未知事实写成已验证事实；缺少依据时提出事实核查请求",
                        "blocking": True,
                    },
                ],
                "templates": {},
            },
            **value,
        }
        for key in ("templates_dir", "fallback_template"):
            if not isinstance(settings[key], str) or not settings[key].strip():
                raise ValueError(f"{key} must be a nonempty string")
        if settings["llm"] is not None and not isinstance(settings["llm"], dict):
            raise ValueError("llm must be an object or null")
        for key in (
            "max_questions_per_round",
            "max_prompt_chars",
            "max_response_chars",
        ):
            if type(settings[key]) is not int or settings[key] < 1:
                raise ValueError(f"{key} must be a positive integer")
        timeout = settings["timeout"]
        if (
            isinstance(timeout, bool)
            or not isinstance(timeout, (int, float))
            or not math.isfinite(timeout)
            or timeout <= 0
        ):
            raise ValueError("timeout must be positive and finite")
        rules = settings["rules"]
        if (
            not isinstance(rules, dict)
            or set(rules) != {"general", "templates"}
            or not isinstance(rules["templates"], dict)
        ):
            raise ValueError("rules requires general and templates")
        groups = [rules["general"], *rules["templates"].values()]
        for group in groups:
            if not isinstance(group, list):
                raise TypeError("Rule groups must be lists")
            ids: set[str] = set()
            for rule in group:
                if not isinstance(rule, dict) or set(rule) != {
                    "id",
                    "text",
                    "blocking",
                }:
                    raise ValueError("Rules require id, text and blocking")
                if (
                    any(
                        not isinstance(rule[k], str) or not rule[k].strip()
                        for k in ("id", "text")
                    )
                    or type(rule["blocking"]) is not bool
                    or rule["id"] in ids
                ):
                    raise ValueError("Invalid or duplicate rule")
                ids.add(rule["id"])
        return settings, path.parent

    @classmethod
    def from_config(
        cls, path: str | Path | None = None, *, llm_provider: LLMProvider | None = None
    ) -> Self:
        return cls(config_file=path, llm_provider=llm_provider)

    def _rules_for(self, template_id: str) -> list[dict[str, Any]]:
        rules = self._settings["rules"]
        result: list[dict[str, Any]] = deepcopy(
            rules["general"] + rules["templates"].get(template_id, [])
        )
        if len({r["id"] for r in result}) != len(result):
            raise ValueError("Rule IDs must be unique across applicable layers")
        return result

    async def start(self) -> Self:
        if self._started or self._closing:
            raise RuntimeError("plugin is already started or closing")
        self.manager.load_template(self.fallback_template)
        self.manager.list_templates()
        self._started = True
        self._close_task = None
        return self

    async def _cleanup(self) -> None:
        try:
            tasks = list(self._active)
            for task in tasks:
                task.cancel()
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
        finally:
            self._started = False
            self._closing = False

    async def aclose(self) -> None:
        if asyncio.current_task() in self._active:
            raise RuntimeError("Cannot close Task from its active operation")
        if self._close_task is None:
            if not self._started:
                return
            self._closing = True
            self._close_task = asyncio.create_task(self._cleanup())
        await asyncio.shield(self._close_task)

    async def __aenter__(self) -> Self:
        return await self.start()

    async def __aexit__(self, exc_type: object, exc: object, traceback: object) -> None:
        await self.aclose()

    def _check(self, document: dict[str, Any], *, planning: bool) -> dict[str, Any]:
        """Validate task data before planning; interaction remains owned by the host."""
        allowed = {
            "task",
            "goal",
            "initial_conditions",
            "context",
            "inputs",
            "proposal",
            "order_hints",
            "task_data",
        }
        unknown = document.keys() - allowed
        if unknown:
            raise ValueError(f"Unknown task request fields: {sorted(unknown)}")
        request = deepcopy(document)
        if "task" in request and not isinstance(request["task"], str):
            raise TypeError("task must be a string")
        supplied = request.pop("task_data", None)
        if supplied is not None and not isinstance(supplied, Mapping):
            raise TypeError("task_data must be a mapping")
        if "task_data" in document and supplied is None:
            raise TypeError("task_data must be a mapping")
        data = dict(supplied) if supplied is not None else {}
        descriptions = [
            request.get("task"),
            data.get("objective"),
            data.get("domain"),
            data.get("category"),
        ]
        intent_text = "\n".join(
            value for value in descriptions if isinstance(value, str)
        )
        selection = self.manager.recognize(intent_text, fallback=self.fallback_template)
        template_id = selection.template_id
        template = self.manager.load_template(template_id)
        declares_objective = "objective" in template.schema.get("properties", {})
        if supplied is None and declares_objective:
            if "task" in request:
                data["objective"] = request["task"]
            elif (
                template_id == "basic"
                and isinstance(request.get("goal"), list)
                and request["goal"]
                and all(isinstance(goal, str) for goal in request["goal"])
            ):
                data["objective"] = "Achieve: " + ", ".join(request["goal"])
        validation = self.manager.validate(data, template_id=template_id)
        issues = list(validation.issues)
        envelope = {
            "type": "object",
            "properties": {
                "goal": {
                    "type": "array",
                    "minItems": 1,
                    "items": {"type": "string", "minLength": 1},
                },
                "initial_conditions": {"type": "array", "items": {"type": "string"}},
                "inputs": {
                    "type": "object",
                    "additionalProperties": {"type": "object"},
                },
                "context": {"type": "object"},
                "proposal": {"type": ["array", "null"], "items": {"type": "object"}},
                "order_hints": {"type": ["array", "null"], "items": {"type": "object"}},
            },
        }
        for error in Draft202012Validator(envelope).iter_errors(request):
            path = "/" + "/".join(
                str(part).replace("~", "~0").replace("/", "~1")
                for part in error.absolute_path
            )
            issues.append(ValidationIssue(path, error.message, str(error.validator)))
        if planning:
            for field in ("proposal", "order_hints"):
                if field in request:
                    issues.append(
                        ValidationIssue(
                            f"/{field}",
                            "Explicit compilation fields require a goal and prepare/run",
                            "incompatible",
                        )
                    )
        definition = (
            self.manager.create(data, template_id=template_id)
            if validation.valid
            else None
        )
        # Only validated, default-merged data may supply the planning objective.
        objective = (
            definition.data.get("objective")
            if definition is not None
            else data.get(
                "objective",
                self.manager.load_template(template_id).defaults.get("objective"),
            )
        )
        description = request.get("task", objective)
        if planning and (not isinstance(description, str) or not description.strip()):
            issues.append(
                ValidationIssue(
                    "/task", "Provide a task description for planning", "required"
                )
            )
        if issues:
            return {
                "status": "needs_input",
                "issues": [asdict(issue) for issue in issues],
                "intent": asdict(selection),
            }
        assert definition is not None
        if "task" not in request and isinstance(objective, str):
            request["task"] = objective
        if planning:
            context = request.get("context", {})
            if not isinstance(context, dict):
                raise TypeError("context must be a mapping")
            request["context"] = {**context, "task_data": definition.data}
        return {
            "status": "ready",
            "task_definition": definition.as_dict(),
            "intent": asdict(selection),
            "request": request,
        }

    async def invoke(
        self, operation: str, payload: Mapping[str, Any] | None = None
    ) -> dict[str, Any]:
        if not self._started or self._closing:
            raise RuntimeError("plugin is not started")
        if payload is not None and not isinstance(payload, Mapping):
            raise TypeError("plugin payload must be a mapping")
        document = deepcopy(dict(payload or {}))
        if operation in {"analyze", "revise", "confirm"}:
            owner = asyncio.current_task()
            assert owner is not None
            if owner in self._active:
                raise RuntimeError(
                    "Recursive Task semantic operations are not supported"
                )
            self._active.add(owner)
            try:
                async with asyncio.timeout(self._settings["timeout"]):
                    return await self._clarify(operation, document)
            finally:
                self._active.discard(owner)
        if operation == "check":
            target = document.pop("target_operation", "prepare")
            if not isinstance(target, str) or target not in {"plan", "prepare", "run"}:
                raise ValueError("target_operation must be plan, prepare or run")
            return self._check(
                document, planning=target == "plan" or "goal" not in document
            )
        if operation == "templates.list":
            if document:
                raise ValueError("templates.list accepts no fields")
            return {"templates": self.manager.list_templates()}
        if operation == "templates.get":
            if set(document) != {"template_id"} or not isinstance(
                document["template_id"], str
            ):
                raise ValueError("templates.get requires template_id")
            return asdict(self.manager.load_template(document["template_id"]))
        if operation == "parse_yaml":
            if set(document) != {"text"} or not isinstance(document["text"], str):
                raise ValueError("parse_yaml requires text")
            return {"data": self.manager.parse_yaml(document["text"])}
        raise ValueError(f"unsupported task operation: {operation}")

    async def check(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        return await self.invoke("check", payload)

    def _semantic_validation(self, request: dict[str, Any]) -> dict[str, Any]:
        return self._check(request, planning="goal" not in request)

    async def _clarify(
        self, operation: str, document: dict[str, Any]
    ) -> dict[str, Any]:
        from .clarification import Clarifier, blockers, encode, revision, validate_draft

        engine = Clarifier(
            self._provider,
            timeout=self._settings["timeout"],
            max_prompt_chars=self._settings["max_prompt_chars"],
            max_response_chars=self._settings["max_response_chars"],
        )
        previous = None
        answers: dict[str, Any] = {}
        if operation == "analyze":
            request = document
        elif operation == "revise":
            if (
                set(document) - {"draft", "answers", "changes"}
                or "draft" not in document
            ):
                raise ValueError("revise requires draft and optional answers/changes")
            previous = validate_draft(document["draft"])
            answers = document.get("answers", {})
            if not isinstance(answers, dict) or any(
                not isinstance(k, str) for k in answers
            ):
                raise TypeError("answers must map question IDs to JSON values")
            encode(answers)
            known = {q["id"]: q for q in previous["review"]["questions"]}
            answered = set(previous["answers"]) | answers.keys()
            if answers.keys() - (known.keys() | previous["answers"].keys()):
                raise ValueError("Unknown answer question ID")
            for key, value in answers.items():
                if value is None or (isinstance(value, str) and not value.strip()):
                    raise ValueError("Answers cannot be empty")
                if key in known and not set(known[key]["depends_on"]) <= answered:
                    raise ValueError("Answer prerequisites have not been resolved")
            changes = document.get("changes", {})
            if not isinstance(changes, dict):
                raise TypeError("changes must be an object")
            request = {**previous["base_request"], **deepcopy(changes)}
            if "task_data" in changes and isinstance(changes["task_data"], dict):
                request["task_data"] = {
                    **previous["base_request"].get("task_data", {}),
                    **changes["task_data"],
                }
        else:
            if set(document) != {"draft", "version", "revision", "approved"}:
                raise ValueError(
                    "confirm requires draft, version, revision and approved"
                )
            draft = validate_draft(document["draft"])
            if (
                document["approved"] is not True
                or type(document["version"]) is not int
                or document["version"] != draft["version"]
                or document["revision"] != draft["revision"]
            ):
                raise ValueError("Explicit approval of the exact draft is required")
            checked = self._semantic_validation(draft["request"])
            template = self.manager.load_template(checked["intent"]["template_id"])
            if (
                template.id != draft["template_id"]
                or template.hash != draft["template_hash"]
                or self._rules_for(template.id) != draft["rules"]
            ):
                raise ValueError(
                    "Template or checklist changed; revise before confirming"
                )
            if blockers(draft) or checked["status"] != "ready":
                raise ValueError("Unresolved requirements block confirmation")
            approved_revision = draft["revision"]
            draft["confirmed"] = True
            draft["revision"] = revision(draft)
            snapshot = {
                "id": draft["id"],
                "version": draft["version"],
                "revision": draft["revision"],
                "approved_revision": approved_revision,
                "spec": deepcopy(draft["review"]["spec"]),
                "decisions": deepcopy(draft["decision_log"]),
                "rules": deepcopy(draft["rules"]),
                "template_hash": draft["template_hash"],
            }
            request = deepcopy(checked["request"])
            request["context"] = {**request.get("context", {}), "task_spec": snapshot}
            return {
                "status": "confirmed",
                "draft": draft,
                "confirmed_spec": snapshot,
                "request": request,
            }
        checked = self._semantic_validation(request)
        template = self.manager.load_template(checked["intent"]["template_id"])
        for attempt in range(2):
            draft = await engine.build(
                request,
                template_id=template.id,
                template_hash=template.hash,
                template_schema=template.schema,
                rules=self._rules_for(template.id),
                previous=previous,
                answers=answers,
            )
            validation = self._semantic_validation(draft["request"])
            selected = self.manager.load_template(validation["intent"]["template_id"])
            if (
                selected.id == template.id
                and selected.hash == template.hash
                and self._rules_for(selected.id) == draft["rules"]
            ):
                break
            if attempt == 1:
                raise ValueError(
                    "Task routing did not stabilize; clarify the domain explicitly"
                )
            template = selected
        # No actionable top-level Graph request is returned before explicit approval.
        issues = list(validation.get("issues", [])) + blockers(draft)
        frontier = [
            q
            for q in draft["review"]["questions"]
            if set(q["depends_on"]) <= draft["answers"].keys()
        ]
        frontier = frontier[: self._settings["max_questions_per_round"]]
        return {
            "status": "needs_clarification" if issues else "awaiting_confirmation",
            "draft": draft,
            "questions": [q for q in frontier if q["kind"] == "decision"],
            "fact_requests": [q for q in frontier if q["kind"] == "fact"],
            "validation": {"valid": not issues, "issues": issues},
            "summary": deepcopy(draft["review"]["spec"]),
        }

    async def analyze(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        return await self.invoke("analyze", payload)

    async def revise(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        return await self.invoke("revise", payload)

    async def confirm(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        return await self.invoke("confirm", payload)
