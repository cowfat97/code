"""Outer adapter tests; it calls the plugin and never dispatches tools itself."""

import importlib.util
import sys
from pathlib import Path

import pytest

from grasp_metaskills import NodeResult, Skill, SkillContract, SkillRegistry


def adapter_type():
    path = Path(__file__).parents[2] / "integration/plugin_adapter.py"
    assert path.exists(), "Outer plugin-call adapter is missing"
    spec = importlib.util.spec_from_file_location("outer_plugin_adapter", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module.PluginAdapter


def spec_definition():
    return {
        "metadata": {"id": "double", "name": "Double integer", "version": "1.0.0"},
        "sections": [],
        "grasp_contract": {
            "effects": ["ready(x)"],
            "input_schema": {
                "type": "object",
                "properties": {"seed": {"type": "integer"}},
                "required": ["seed"],
            },
            "output_schema": {
                "type": "object",
                "properties": {"answer": {"type": "integer"}},
                "required": ["answer"],
            },
        },
    }


async def test_outer_adapter_calls_real_plugin_management_and_run(tmp_path):
    adapter = adapter_type()
    from grasp_metaskills.plugin import SkillGraphPlugin

    calls = []

    class HarnessExecutor:
        async def execute(self, node, inputs, context):
            calls.append((node.skill.id, inputs["seed"], context.graph_id))
            return NodeResult(output={"answer": inputs["seed"] * 2}, observed_effects=["ready(x)"])

    with SkillRegistry(tmp_path / "run.db") as registry:
        bridge = adapter(SkillGraphPlugin(registry, HarnessExecutor()))
        skill = await bridge.call("skills.register", {"spec": spec_definition()})
        assert skill["skill"]["id"] == "double"
        found = await bridge.call("skills.search", {"query": "double"})
        assert found["results"][0]["skill"]["id"] == "double"
        report = await bridge.run({"goal": ["ready(x)"], "inputs": {"double:1": {"seed": 5}}})
        assert report["status"] == "succeeded"
        assert report["outputs"]["double:1"] == {"answer": 10}
        assert calls == [("double", 5, report["graph_id"])]
        assert (await bridge.status(report["graph_id"]))["status"] == "succeeded"
        assert (await bridge.resume(report["graph_id"]))["status"] == "succeeded"
        assert len(calls) == 1


async def test_mapping_and_inputs_are_not_mutated_by_plugin():
    adapter = adapter_type()
    calls = []

    class Plugin:
        async def invoke(self, operation, payload):
            calls.append((operation, payload.copy()))
            payload["goal"].append("changed")
            return {"status": "failed", "outputs": {}}

    request = {"message": "work", "targets": ["done(x)"]}
    bridge = adapter(
        Plugin(),
        request_mapper=lambda raw: {"task": raw["message"], "goal": raw["targets"]},
        report_mapper=lambda report: {"ok": report["status"] == "succeeded"},
    )
    assert await bridge.run(request) == {"ok": False}
    assert request == {"message": "work", "targets": ["done(x)"]}
    assert calls[0][0] == "run"


async def test_unknown_operation_and_plugin_exception_are_not_hidden():
    adapter = adapter_type()
    calls = []

    class Plugin:
        async def invoke(self, operation, payload):
            calls.append(operation)
            raise LookupError("real plugin error")

    bridge = adapter(Plugin())
    with pytest.raises(ValueError):
        await bridge.call("tools.execute", {})
    assert calls == []
    with pytest.raises(LookupError, match="real plugin error"):
        await bridge.run({"goal": ["ready(x)"]})
    assert calls == ["run"]


async def test_prepare_execute_and_invalid_return():
    adapter = adapter_type()
    from grasp_metaskills.plugin import SkillGraphPlugin

    class Executor:
        async def execute(self, node, inputs, context):
            return NodeResult(observed_effects=["ready(x)"])

    with SkillRegistry() as registry:
        registry.register(
            Skill(id="work", name="Work", contract=SkillContract(effects=["ready(x)"]))
        )
        bridge = adapter(SkillGraphPlugin(registry, Executor()))
        handle = await bridge.prepare({"goal": ["ready(x)"]})
        assert handle["status"] == "prepared"
        assert (await bridge.execute(handle["graph_id"]))["status"] == "succeeded"
        assert (await bridge.cancel(handle["graph_id"]))["cancel_requested"] is False

    class BadPlugin:
        async def invoke(self, operation, payload):
            return None

    with pytest.raises(TypeError, match="mapping"):
        await adapter(BadPlugin()).run({"goal": []})
