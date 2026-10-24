"""Real SQLite/compiler/runtime contract for the plugin operation boundary."""

import asyncio
import importlib

import pytest
from pydantic import ValidationError

from grasp_metaskills import NodeResult, RepairEngine, Skill, SkillContract, SkillRegistry


def plugin_type():
    module = importlib.util.find_spec("grasp_metaskills.plugin")
    assert module is not None, "Plugin operation facade is missing"
    return importlib.import_module("grasp_metaskills.plugin").SkillGraphPlugin


class Executor:
    def __init__(self):
        self.calls = []

    async def execute(self, node, inputs, context):
        self.calls.append((node.skill.id, context.idempotency_key))
        return NodeResult(output={"value": 9}, observed_effects=list(node.effects))


def register(registry, id="work"):
    return registry.register(Skill(id=id, name=id, contract=SkillContract(effects=["done(x)"])))


@pytest.mark.asyncio
async def test_prepare_execute_persist_and_reopen(tmp_path):
    executor = Executor()
    path = tmp_path / "skills.db"
    with SkillRegistry(path) as registry:
        register(registry)
        plugin = plugin_type()(registry, executor)
        assert plugin.skills is registry
        prepared = await plugin.invoke("prepare", {"goal": ["done(x)"]})
        assert prepared["status"] == "prepared" and not executor.calls
        assert not (await plugin.invoke("cancel", {"graph_id": prepared["graph_id"]}))[
            "cancel_requested"
        ]
        report = await plugin.invoke("execute", {"graph_id": prepared["graph_id"]})
        assert report["status"] == "succeeded"
        assert {"value": 9} in report["outputs"].values()
        assert report == await plugin.invoke("status", {"graph_id": prepared["graph_id"]})
    with SkillRegistry(path) as registry:
        plugin = plugin_type()(registry, executor)
        resumed = await plugin.invoke("resume", {"graph_id": prepared["graph_id"]})
        assert resumed["status"] == "succeeded" and len(executor.calls) == 1


@pytest.mark.asyncio
async def test_run_and_strict_requests():
    with SkillRegistry() as registry:
        register(registry)
        plugin = plugin_type()(registry, Executor())
        assert (await plugin.invoke("run", {"goal": ["done(x)"]}))["status"] == "succeeded"
        for operation, payload in [
            ("run", {"goal": ["done(x)"], "arbitrary": True}),
            ("run", {"goal": "done(x)"}),
            ("execute", {"graph_id": 1}),
            ("resume", {"graph_id": "x", "retry_unknown": "yes"}),
        ]:
            with pytest.raises(ValidationError):
                await plugin.invoke(operation, payload)
        with pytest.raises(ValueError):
            await plugin.invoke("__getattribute__", {})
        with pytest.raises(KeyError):
            await plugin.invoke("status", {"graph_id": "unknown"})
        with pytest.raises(KeyError):
            await plugin.invoke("cancel", {"graph_id": "unknown"})


@pytest.mark.asyncio
async def test_native_skill_operations():
    spec = {
        "metadata": {"id": "native", "name": "Native", "version": "1.2.0"},
        "grasp_contract": {"effects": ["done(x)"]},
    }
    with SkillRegistry() as registry:
        plugin = plugin_type()(registry, Executor())
        registered = await plugin.invoke("skills.register", {"spec": spec})
        skill = registered["skill"]
        assert skill["contract"]["effects"] == ["done(x)"]
        found = await plugin.invoke("skills.search", {"query": "Native"})
        assert found["results"][0]["skill"]["id"] == "native"
        got = await plugin.invoke("skills.get", {"skill_id": "native", "version": skill["version"]})
        assert got["skill"] == skill
        assert len((await plugin.invoke("skills.history", {"skill_id": "native"}))["history"]) == 1
        assert (await plugin.invoke("skills.dependencies", {"skill_id": "native"}))[
            "dependencies"
        ] == []
        assert (await plugin.invoke("skills.compose", {"skill_id": "native"}))["composition"][
            "spec"
        ]["metadata"]["id"] == "native"
        assert "native" in (await plugin.invoke("skills.export", {}))["json"]
        assert (await plugin.invoke("skills.delete", {"skill_id": "native"}))["deleted"]
        with pytest.raises(KeyError):
            await plugin.invoke("skills.get", {"skill_id": "native"})


@pytest.mark.asyncio
async def test_cancel_recovery_and_active_guard():
    entered = asyncio.Event()
    keys = []

    class Blocking:
        async def execute(self, node, inputs, context):
            keys.append(context.idempotency_key)
            if len(keys) == 1:
                entered.set()
                await asyncio.Event().wait()
            return NodeResult(observed_effects=list(node.effects))

    with SkillRegistry() as registry:
        register(registry)
        plugin = plugin_type()(registry, Blocking())
        prepared = await plugin.invoke("prepare", {"goal": ["done(x)"]})
        payload = {"graph_id": prepared["graph_id"]}
        active = asyncio.create_task(plugin.invoke("execute", payload))
        await asyncio.wait_for(entered.wait(), 2)
        with pytest.raises(RuntimeError):
            await plugin.invoke("execute", payload)
        assert (await plugin.invoke("cancel", payload))["cancel_requested"]
        cancelled = await active
        assert cancelled["status"] == "cancelled"
        assert (await plugin.invoke("resume", payload))["status"] == "outcome-unknown"
        assert (await plugin.invoke("resume", {**payload, "retry_unknown": True}))[
            "status"
        ] == "succeeded"
        assert len(keys) == 2 and keys[0] == keys[1]


@pytest.mark.asyncio
async def test_repair_report_uses_latest_graph():
    class Failing(Executor):
        async def execute(self, node, inputs, context):
            if node.skill.id == "bad":
                raise ValueError("failed")
            return await super().execute(node, inputs, context)

    with SkillRegistry() as registry:
        register(registry, "bad")
        register(registry, "good")
        plugin = plugin_type()(registry, Failing(), repair_engine=RepairEngine(registry))
        report = await plugin.invoke(
            "run", {"goal": ["done(x)"], "proposal": [{"skill": "bad", "args": []}]}
        )
        assert report["status"] == "succeeded"
        assert report["graph_version"] > 1
        assert report["repair_audit"]
        assert report == await plugin.invoke("status", {"graph_id": report["graph_id"]})
