"""Optional local composition. All external module imports live here."""

from __future__ import annotations

import json
from copy import deepcopy
from importlib import import_module
from pathlib import Path
from typing import Any, cast


class LocalBackend:
    def __init__(
        self,
        model: Any,
        task: Any,
        graph: Any,
        registry: Any,
        *,
        request_defaults: dict[str, Any] | None = None,
    ) -> None:
        self.request_defaults = self._defaults(request_defaults or {})
        self.model, self.task_plugin = model, task
        self.graph_plugin, self.registry = graph, registry

    @staticmethod
    def _defaults(value: Any) -> dict[str, Any]:
        if not isinstance(value, dict) or set(value) - {
            "initial_conditions",
            "inputs",
            "context",
        }:
            raise ValueError(
                "request defaults allow initial_conditions, inputs and context only"
            )
        if "initial_conditions" in value and (
            not isinstance(value["initial_conditions"], list)
            or any(
                not isinstance(item, str) or not item.strip()
                for item in value["initial_conditions"]
            )
        ):
            raise ValueError("initial_conditions must contain nonempty facts")
        if any(
            key in value and not isinstance(value[key], dict)
            for key in ("inputs", "context")
        ):
            raise ValueError("inputs and context must be objects")
        json.dumps(value, allow_nan=False)
        return deepcopy(value)

    @classmethod
    async def create(cls) -> LocalBackend:
        prefix = __package__.removesuffix("demo_harness").rstrip(".")

        def module(name: str) -> Any:
            return import_module(f"{prefix}.{name}" if prefix else name)

        model = module("model").ModelClient()
        root = Path(__file__).resolve().parent
        defaults_path = root / "config/request.json"
        defaults = cls._defaults(json.loads(defaults_path.read_text(encoding="utf-8")))
        graph_api = module("plugin_manager.plugins.graph.api")
        graph_root = Path(graph_api.__file__).parent
        state = root / "state"
        state.mkdir(exist_ok=True)
        gateway_file = state / "gateway.json"
        gateway_file.write_text(
            json.dumps(
                {
                    "load_builtin": False,
                    "load_mcp": False,
                    "monitor_file": "events.sqlite3",
                }
            ),
            encoding="utf-8",
        )
        task = module("plugin_manager.plugins.task.api").Plugin(llm_provider=model)
        graph = graph_api.Plugin(
            config={
                "skills_dir": str(graph_root / "skills/library"),
                "skills_file": str(graph_root / "config/skills.json"),
                "state_dir": str(state / "graphs"),
                "tools_config_file": str(gateway_file),
                "meta_file": str(graph_root / "config/meta.json"),
            },
            llm_provider=model,
        )
        registry = None
        try:
            await task.start()
            await graph.start()
            registry = module("plugin_manager.plugins.graph.skills").SkillRegistry(
                graph_root / "skills/library",
                state_path=state / "graphs",
            )
            return cls(model, task, graph, registry, request_defaults=defaults)
        except BaseException:
            try:
                await graph.aclose()
            finally:
                try:
                    await task.aclose()
                finally:
                    if registry is not None:
                        registry.close()
            raise

    async def task(self, operation: str, payload: dict[str, Any]) -> dict[str, Any]:
        if operation == "analyze":
            payload = {**deepcopy(self.request_defaults), **deepcopy(payload)}
        return cast(dict[str, Any], await self.task_plugin.invoke(operation, payload))

    async def complete(self, prompt: str) -> str:
        return str(await self.model.complete(prompt))

    async def prepare(self, request: dict[str, Any]) -> dict[str, Any]:
        result = await self.graph_plugin.prepare(request)
        saved = self.registry.load_run(result["graph_id"])
        if saved is None:
            raise RuntimeError("prepared graph snapshot was not persisted")
        graph, state = saved
        return {**result, "graph": graph, "state": state}

    async def aclose(self) -> None:
        try:
            await self.graph_plugin.aclose()
        finally:
            try:
                await self.task_plugin.aclose()
            finally:
                self.registry.close()
