"""Whole-system checks use real registries, contracts, scheduling and arithmetic."""

import asyncio
from collections import Counter

import pytest

from grasp_metaskills import (
    CompilationError,
    ExecutionGraph,
    GraphCompiler,
    GraphRuntime,
    GraphState,
    NodeResult,
    NodeState,
    RepairEngine,
    Skill,
    SkillContract,
    SkillNode,
    SkillRegistry,
    VerificationResult,
)

NUMBER = {"type": "object", "properties": {"value": {"type": "integer"}}, "required": ["value"]}


def add(registry, sid, pre=(), effects=(), **kwargs):
    return registry.register(
        Skill(
            id=sid,
            name=sid,
            contract=SkillContract(preconditions=list(pre), effects=list(effects), **kwargs),
        )
    )


class Arithmetic:
    def __init__(self):
        self.calls = Counter()

    async def execute(self, node, inputs, context):
        sid = node.skill.id
        self.calls[sid] += 1
        if sid == "source":
            return NodeResult(output={"value": 3}, observed_effects=["seed(x)"])
        if sid in {"transform", "alternative"}:
            value = inputs["value"] * 2
            return NodeResult(
                output={"value": value}, observed_effects=["ready(x)"] if value == 6 else []
            )
        if sid == "bad":
            raise RuntimeError("definitive execution failure")
        if sid == "side":
            return NodeResult(output={"value": 7}, observed_effects=["side(x)"])
        if sid == "finish":
            value = inputs["value"] + 1
            return NodeResult(
                output={"value": value}, observed_effects=["done(x)"] if value == 7 else []
            )
        raise ValueError(sid)


@pytest.mark.asyncio
async def test_discovery_auto_compilation_binding_execution_feedback_and_recovery(tmp_path):
    path = tmp_path / "skills.db"
    executor = Arithmetic()
    with SkillRegistry(path) as registry:
        add(registry, "source", effects=["seed(x)"], output_schema=NUMBER)
        add(
            registry,
            "transform",
            ["seed(x)"],
            ["ready(x)"],
            input_schema=NUMBER,
            output_schema=NUMBER,
        )
        graph = await GraphCompiler(registry).compile(goal=["ready(x)"], task="transform source")
        assert graph.metadata["registry_discovery"]
        assert graph.node("transform:1").bindings["value"].node_id == "source:1"
        state = await GraphRuntime(registry, executor).execute(graph)
        assert state.status == "succeeded"
        assert state.nodes["transform:1"].result.output == {"value": 6}
        assert registry.feedback("transform")[0]["success"]
        confirmed = state.nodes
    with SkillRegistry(path) as registry:
        recovered = await GraphRuntime(registry, executor).resume(graph.id)
        assert recovered.nodes == confirmed
        assert executor.calls == Counter(source=1, transform=1)


@pytest.mark.asyncio
async def test_local_substitution_reuses_independent_branch():
    with SkillRegistry() as registry:
        add(registry, "source", effects=["seed(x)"], output_schema=NUMBER)
        add(registry, "bad", ["seed(x)"], ["ready(x)"], input_schema=NUMBER, output_schema=NUMBER)
        add(
            registry,
            "alternative",
            ["seed(x)"],
            ["ready(x)"],
            input_schema=NUMBER,
            output_schema=NUMBER,
        )
        add(registry, "side", effects=["side(x)"])
        add(
            registry, "finish", ["ready(x)"], ["done(x)"], input_schema=NUMBER, output_schema=NUMBER
        )
        # Explicit data source is the nearest state producer; an unrelated ancestor
        # also emits value, so declare its purpose rather than guessing.
        graph = await GraphCompiler(registry).compile(
            goal=["ready(x)", "side(x)"],
            proposal=[
                {"skill": "source", "args": []},
                {"skill": "bad", "args": []},
                {"skill": "side", "args": []},
            ],
        )
        executor = Arithmetic()
        state = await GraphRuntime(
            registry, executor, repair_engine=RepairEngine(registry, operator_order=["Substitute"])
        ).execute(graph)
        assert state.status == "succeeded"
        assert state.graph_version == 2 and graph.version == 1
        assert executor.calls == Counter(source=1, bad=1, alternative=1, side=1)
        assert state.repair_audit[0]["operator"] == "Substitute"
        assert "side:1" not in state.repair_audit[0]["affected"]
        assert state.nodes["side:1"].attempt == 1
        persisted, _ = registry.load_run(graph.id)
        assert ExecutionGraph.model_validate(persisted).node("bad:1").skill.id == "alternative"


@pytest.mark.asyncio
async def test_repair_failure_is_bounded_and_audited():
    with SkillRegistry() as registry:
        add(registry, "bad", effects=["ready(x)"])
        add(registry, "alternative", ["unavailable(x)"], ["ready(x)"])
        graph = await GraphCompiler(registry).compile(
            goal=["ready(x)"], proposal=[{"skill": "bad", "args": []}]
        )
        state = await GraphRuntime(
            registry,
            Arithmetic(),
            repair_engine=RepairEngine(registry, operator_order=["Substitute"]),
        ).execute(graph)
        assert state.status == "failed"
        assert state.graph_version == 1
        assert state.repair_attempts["bad:1"] == 1
        assert state.repair_audit[-1]["reason"] == "local-failed"
        assert state.repair_audit[-1]["rejected"]


@pytest.mark.asyncio
async def test_multiple_candidate_paths_choose_satisfiable_path():
    with SkillRegistry() as registry:
        add(registry, "a_unreachable", ["missing(x)"], ["ready(x)"])
        add(registry, "source", effects=["seed(x)"], output_schema=NUMBER)
        add(registry, "transform", ["seed(x)"], ["ready(x)"], input_schema=NUMBER)
        graph = await GraphCompiler(registry).compile(goal=["ready(x)"])
        state = await GraphRuntime(registry, Arithmetic()).execute(graph)
        assert state.status == "succeeded"
        assert not any(n.skill and n.skill.id == "a_unreachable" for n in graph.nodes)


@pytest.mark.asyncio
async def test_parallel_nodes_rendezvous_without_serial_deadlock():
    with SkillRegistry() as registry:
        add(registry, "left", effects=["left(x)"])
        add(registry, "right", effects=["right(x)"])
        graph = await GraphCompiler(registry).compile(goal=["left(x)", "right(x)"])
        arrived = set()
        barrier = asyncio.Event()

        class Rendezvous:
            async def execute(self, node, inputs, context):
                arrived.add(node.skill.id)
                if len(arrived) == 2:
                    barrier.set()
                await asyncio.wait_for(barrier.wait(), 1)
                return NodeResult(observed_effects=[node.skill.id + "(x)"])

        state = await GraphRuntime(registry, Rendezvous(), concurrency=2).execute(graph)
        assert state.status == "succeeded" and arrived == {"left", "right"}


@pytest.mark.asyncio
async def test_missing_precondition_prevents_executor_call():
    with SkillRegistry() as registry:
        add(registry, "bad", ["missing(x)"], ["ready(x)"])
        graph = await GraphCompiler(registry, strict_preconditions=False).compile(
            goal=["ready(x)"], proposal=[{"skill": "bad", "args": []}]
        )
        executor = Arithmetic()
        state = await GraphRuntime(registry, executor).execute(graph)
        assert state.status == "failed" and not executor.calls
        assert state.nodes["bad:1"].verification.category == "precondition"


@pytest.mark.asyncio
async def test_static_type_conflict():
    with SkillRegistry() as registry:
        add(
            registry,
            "source",
            effects=["seed(x)"],
            output_schema={
                "type": "object",
                "properties": {"value": {"type": "string"}},
                "required": ["value"],
            },
        )
        add(registry, "transform", ["seed(x)"], ["ready(x)"], input_schema=NUMBER)
        with pytest.raises(CompilationError, match="type conflict"):
            await GraphCompiler(registry).compile(goal=["ready(x)"])


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "fault,category",
    [("effect", "postcondition"), ("output", "output_schema"), ("input", "input_schema")],
)
async def test_verification_failure_attribution(fault, category):
    with SkillRegistry() as registry:
        skill = add(
            registry,
            "operation",
            effects=["ready(x)"],
            input_schema=NUMBER if fault == "input" else {},
            output_schema=NUMBER,
        )
        node = SkillNode(
            id="op",
            skill=skill,
            effects=["ready(x)"],
            input_values={"value": "wrong"} if fault == "input" else {},
        )
        graph = ExecutionGraph(nodes=[node], goal=["ready(x)"])

        class Invalid:
            async def execute(self, node, inputs, context):
                return NodeResult(
                    output={"value": "wrong" if fault == "output" else 6},
                    observed_effects=[] if fault == "effect" else ["ready(x)"],
                )

        state = await GraphRuntime(registry, Invalid()).execute(graph)
        assert state.status == "failed"
        assert state.nodes["op"].verification.category == category
        assert not state.facts


@pytest.mark.asyncio
async def test_skill_update_during_execution_keeps_pinned_version():
    with SkillRegistry() as registry:
        add(registry, "versioned", effects=["ready(x)"])
        graph = await GraphCompiler(registry).compile(goal=["ready(x)"])

        class UpdatingExecutor:
            async def execute(self, node, inputs, context):
                registry.register(
                    Skill(
                        id="versioned",
                        name="versioned",
                        version="2.0.0",
                        contract=SkillContract(effects=["new(x)"]),
                    )
                )
                assert node.skill.version == "1.0.0"
                return NodeResult(observed_effects=["ready(x)"])

        state = await GraphRuntime(registry, UpdatingExecutor()).execute(graph)
        assert state.status == "succeeded"
        assert graph.node("versioned:1").skill.version == "1.0.0"
        assert registry.get("versioned").version == "2.0.0"
        assert registry.feedback("versioned", "1.0.0")[0]["success"]


@pytest.mark.asyncio
async def test_registry_search_changes_candidate_priority():
    with SkillRegistry() as registry:
        registry.register(
            Skill(id="a", name="generic", contract=SkillContract(effects=["ready(x)"]))
        )
        registry.register(
            Skill(
                id="z",
                name="requested specialized transformation",
                contract=SkillContract(effects=["ready(x)"]),
            )
        )
        graph = await GraphCompiler(registry).compile(goal=["ready(x)"], task="specialized")
        assert graph.metadata["registry_discovery"] == ["z"]
        assert [n.skill.id for n in graph.nodes if n.skill] == ["z"]


@pytest.mark.asyncio
async def test_definitive_execution_retry_and_feedback():
    with SkillRegistry() as registry:
        add(registry, "operation", effects=["ready(x)"])
        graph = await GraphCompiler(registry).compile(goal=["ready(x)"])
        keys = []

        class Retry:
            async def execute(self, node, inputs, context):
                keys.append(context.idempotency_key)
                if len(keys) == 1:
                    raise RuntimeError("definitive transient failure")
                return NodeResult(observed_effects=["ready(x)"])

        state = await GraphRuntime(registry, Retry(), retries=1).execute(graph)
        assert state.status == "succeeded" and len(set(keys)) == 2
        assert state.nodes["operation:1"].attempt == 2


@pytest.mark.asyncio
async def test_timeout_unknown_is_not_blindly_retried():
    with SkillRegistry() as registry:
        add(registry, "operation", effects=["ready(x)"])
        graph = await GraphCompiler(registry).compile(goal=["ready(x)"])
        calls = []

        class Slow:
            async def execute(self, node, inputs, context):
                calls.append(context.idempotency_key)
                await asyncio.sleep(1)
                return NodeResult(observed_effects=["ready(x)"])

        runtime = GraphRuntime(registry, Slow(), retries=3, timeout=0.01)
        state = await runtime.execute(graph)
        assert state.status == "outcome-unknown" and len(calls) == 1
        assert (await runtime.resume(graph.id)).status == "outcome-unknown"
        assert len(calls) == 1


@pytest.mark.asyncio
async def test_custom_verifier_and_required_rule():
    with SkillRegistry() as registry:
        add(registry, "side", effects=["side(x)"], validators=["positive"])
        graph = await GraphCompiler(registry).compile(goal=["side(x)"])

        class Positive:
            async def verify(self, node, inputs, result, context):
                return VerificationResult(passed=result.output["value"] > 0)

        assert (
            await GraphRuntime(registry, Arithmetic(), verifier=Positive()).execute(graph)
        ).status == "succeeded"
        graph.id += "-without-verifier"
        failed = await GraphRuntime(registry, Arithmetic()).execute(graph)
        assert failed.nodes["side:1"].verification.category == "custom_validator"


@pytest.mark.asyncio
async def test_resume_persisted_result_without_reexecuting_skill():
    with SkillRegistry() as registry:
        skill = add(registry, "side", effects=["side(x)"])
        graph = ExecutionGraph(
            nodes=[SkillNode(id="side", skill=skill, effects=["side(x)"])], goal=["side(x)"]
        )
        state = GraphState(
            graph_id=graph.id,
            nodes={
                "side": NodeState(
                    status="verifying",
                    attempt=1,
                    result=NodeResult(output={"value": 7}, observed_effects=["side(x)"]),
                )
            },
        )
        registry.save_run(graph.id, graph.model_dump(mode="json"), state.model_dump(mode="json"))
        executor = Arithmetic()
        resumed = await GraphRuntime(registry, executor).resume(graph.id)
        assert resumed.status == "succeeded" and not executor.calls


@pytest.mark.asyncio
async def test_cancel_running_task_persists_state_and_trace():
    with SkillRegistry() as registry:
        add(registry, "operation", effects=["ready(x)"])
        graph = await GraphCompiler(registry).compile(goal=["ready(x)"])
        started = asyncio.Event()

        class Waiting:
            async def execute(self, node, inputs, context):
                started.set()
                await asyncio.Event().wait()
                return NodeResult()

        runtime = GraphRuntime(registry, Waiting())
        execution = asyncio.create_task(runtime.execute(graph))
        await asyncio.wait_for(started.wait(), 1)
        runtime.cancel(graph.id)
        state = await asyncio.wait_for(execution, 1)
        assert state.status == "cancelled"
        assert registry.load_run(graph.id)[1]["status"] == "cancelled"
        assert any(t.event == "cancelled" for t in state.trace)


@pytest.mark.asyncio
async def test_insert_prerequisite_executes_only_needed_new_node():
    with SkillRegistry() as registry:
        registry.register(
            Skill(
                id="prepare",
                name="prepare",
                contract=SkillContract(params=["token"], effects=["ready(token)"]),
            )
        )
        add(registry, "consume", ["ready(x)"], ["done(x)"])
        graph = await GraphCompiler(registry, strict_preconditions=False).compile(
            goal=["done(x)"], proposal=[{"skill": "consume", "args": []}]
        )
        calls = []
        prepared = set()

        class StatefulExecutor:
            async def execute(self, node, inputs, context):
                calls.append(node.skill.id)
                if node.skill.id == "prepare":
                    prepared.add(node.args[0])
                    return NodeResult(observed_effects=[f"ready({node.args[0]})"])
                return NodeResult(observed_effects=["done(x)"] if "x" in prepared else [])

        state = await GraphRuntime(
            registry,
            StatefulExecutor(),
            repair_engine=RepairEngine(registry, operator_order=["InsertPrereq"]),
        ).execute(graph)
        assert state.status == "succeeded" and state.graph_version == 2
        assert calls == ["prepare", "consume"]
        assert state.repair_audit[0]["added_nodes"] == ["prepare:1"]


@pytest.mark.asyncio
async def test_timeout_explicitly_idempotent_can_retry():
    with SkillRegistry() as registry:
        registry.register(
            Skill(
                id="operation",
                name="operation",
                metadata={"idempotent": True},
                contract=SkillContract(effects=["ready(x)"]),
            )
        )
        graph = await GraphCompiler(registry).compile(goal=["ready(x)"])
        calls = []

        class EventuallyFast:
            async def execute(self, node, inputs, context):
                calls.append(context.idempotency_key)
                if len(calls) == 1:
                    await asyncio.sleep(1)
                return NodeResult(observed_effects=["ready(x)"])

        state = await GraphRuntime(registry, EventuallyFast(), timeout=0.01, retries=1).execute(
            graph
        )
        assert state.status == "succeeded" and len(calls) == 2


@pytest.mark.asyncio
async def test_cache_invalidation_reexecutes_changed_input():
    with SkillRegistry() as registry:
        skill = add(
            registry, "identity", effects=["ready(x)"], input_schema=NUMBER, output_schema=NUMBER
        )
        graph = ExecutionGraph(
            goal=["ready(x)"],
            nodes=[
                SkillNode(
                    id="identity", skill=skill, input_values={"value": 1}, effects=["ready(x)"]
                )
            ],
        )
        calls = []

        class Identity:
            async def execute(self, node, inputs, context):
                calls.append(inputs["value"])
                return NodeResult(output=inputs, observed_effects=["ready(x)"])

        runtime = GraphRuntime(registry, Identity())
        state = await runtime.execute(graph)
        graph.node("identity").input_values["value"] = 2
        updated = await runtime.execute(graph, state)
        assert calls == [1, 2]
        assert updated.nodes["identity"].result.output["value"] == 2
        assert state.nodes["identity"].result.output["value"] == 1
        assert any(t.event == "cache_invalidated" for t in updated.trace)


@pytest.mark.asyncio
async def test_unknown_retry_unblocks_downstream_after_reconciliation():
    with SkillRegistry() as registry:
        add(registry, "source", effects=["seed(x)"], output_schema=NUMBER)
        add(registry, "transform", ["seed(x)"], ["ready(x)"], input_schema=NUMBER)
        graph = await GraphCompiler(registry).compile(goal=["ready(x)"])

        class FirstSlow(Arithmetic):
            async def execute(self, node, inputs, context):
                if node.skill.id == "source":
                    await asyncio.sleep(1)
                return await super().execute(node, inputs, context)

        unknown = await GraphRuntime(registry, FirstSlow(), timeout=0.01).execute(graph)
        assert unknown.status == "outcome-unknown"
        assert unknown.nodes["transform:1"].status == "blocked"
        recovered = await GraphRuntime(registry, Arithmetic()).resume(graph.id, retry_unknown=True)
        assert recovered.status == "succeeded"
        assert recovered.nodes["transform:1"].result.output == {"value": 6}


@pytest.mark.asyncio
async def test_cancelled_external_action_recovers_with_original_key():
    with SkillRegistry() as registry:
        add(registry, "operation", effects=["ready(x)"])
        graph = await GraphCompiler(registry).compile(goal=["ready(x)"])
        started = asyncio.Event()
        external_results = {}
        calls = []

        class External:
            async def execute(self, node, inputs, context):
                calls.append(context.idempotency_key)
                if context.idempotency_key not in external_results:
                    external_results[context.idempotency_key] = NodeResult(
                        observed_effects=["ready(x)"]
                    )
                    started.set()
                    await asyncio.Event().wait()
                return external_results[context.idempotency_key]

        runtime = GraphRuntime(registry, External())
        run = asyncio.create_task(runtime.execute(graph))
        await asyncio.wait_for(started.wait(), 1)
        runtime.cancel(graph.id)
        cancelled = await asyncio.wait_for(run, 1)
        assert cancelled.status == "cancelled"
        assert cancelled.nodes["operation:1"].status == "outcome-unknown"
        assert (await runtime.resume(graph.id)).status == "outcome-unknown"
        recovered = await runtime.resume(graph.id, retry_unknown=True)
        assert recovered.status == "succeeded"
        assert len(external_results) == 1 and calls[0] == calls[1]


@pytest.mark.asyncio
async def test_cancellation_during_verification_resumes_raw_result():
    with SkillRegistry() as registry:
        add(registry, "side", effects=["side(x)"])
        graph = await GraphCompiler(registry).compile(goal=["side(x)"])
        started = asyncio.Event()

        class WaitingVerifier:
            async def verify(self, node, inputs, result, context):
                started.set()
                await asyncio.Event().wait()
                return VerificationResult(passed=True)

        executor = Arithmetic()
        runtime = GraphRuntime(registry, executor, verifier=WaitingVerifier())
        run = asyncio.create_task(runtime.execute(graph))
        await asyncio.wait_for(started.wait(), 1)
        runtime.cancel(graph.id)
        state = await asyncio.wait_for(run, 1)
        assert state.status == "cancelled"
        recovered = await GraphRuntime(registry, executor).resume(graph.id)
        assert recovered.status == "succeeded"
        assert executor.calls == Counter(side=1)
