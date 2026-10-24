import asyncio

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from grasp_metaskills.contracts import (
    DependencyEdge,
    ExecutionGraph,
    GraphState,
    NodeResult,
    NodeState,
    Skill,
    SkillNode,
)
from grasp_metaskills.registry import SkillRegistry
from grasp_metaskills.runtime import GraphRuntime


class RecordingExecutor:
    def __init__(self):
        self.calls = []
        self.active = 0
        self.peak = 0

    async def execute(self, node, inputs, context):
        self.calls.append(node.id)
        self.active += 1
        self.peak = max(self.peak, self.active)
        await asyncio.sleep(0.005)
        self.active -= 1
        return NodeResult(output={"value": node.id}, observed_effects=node.effects)


def graph_for(names, registry):
    nodes = []
    for n in names:
        skill = registry.register(Skill(id=n, name=n))
        nodes.append(SkillNode(id=n, skill=skill, effects=[n]))
    return ExecutionGraph(nodes=nodes)


@pytest.mark.asyncio
async def test_parallel_and_resume_preserves_results(tmp_path):
    with SkillRegistry(tmp_path / "registry.db") as registry:
        executor = RecordingExecutor()
        graph = graph_for(["a", "b", "c"], registry)
        runtime = GraphRuntime(registry, executor, concurrency=2)
        state = await runtime.execute(graph)
        assert state.status == "succeeded"
        assert executor.peak == 2
        before = state.model_dump(mode="json")["nodes"]
        resumed = await runtime.resume(graph.id)
        assert resumed.model_dump(mode="json")["nodes"] == before
        assert len(executor.calls) == 3


@pytest.mark.asyncio
async def test_failure_propagation(tmp_path):
    with SkillRegistry(tmp_path / "registry.db") as registry:
        graph = graph_for(["a", "b"], registry)
        graph.node("a").preconditions = ["missing"]
        graph.edges = [DependencyEdge(source="a", target="b", type="order")]
        executor = RecordingExecutor()
        state = await GraphRuntime(registry, executor).execute(graph)
        assert state.nodes["a"].verification.category == "precondition"
        assert state.nodes["b"].status == "blocked"
        assert executor.calls == []


@pytest.mark.asyncio
async def test_resume_unknown_requires_confirmation(tmp_path):
    with SkillRegistry(tmp_path / "registry.db") as registry:
        graph = graph_for(["a"], registry)
        state = GraphState(graph_id=graph.id, nodes={"a": NodeState(status="running", attempt=1)})
        registry.save_run(graph.id, graph.model_dump(mode="json"), state.model_dump(mode="json"))
        executor = RecordingExecutor()
        runtime = GraphRuntime(registry, executor)
        assert (await runtime.resume(graph.id)).status == "outcome-unknown"
        assert executor.calls == []
        assert (await runtime.resume(graph.id, retry_unknown=True)).status == "succeeded"


@settings(max_examples=12, deadline=None)
@given(
    st.lists(
        st.text(alphabet="abcdef", min_size=1, max_size=6), min_size=1, max_size=8, unique=True
    )
)
def test_property_preconditions_never_execute(names):
    with SkillRegistry() as registry:
        executor = RecordingExecutor()
        graph = graph_for(names, registry)
        for node in graph.nodes:
            node.preconditions = ["never-observed"]
        state = asyncio.run(GraphRuntime(registry, executor).execute(graph))
        assert executor.calls == []
        assert all(n.status == "failed" for n in state.nodes.values())


@settings(max_examples=12, deadline=None)
@given(
    st.lists(
        st.text(alphabet="abcdef", min_size=1, max_size=6), min_size=1, max_size=8, unique=True
    )
)
def test_property_resume_keeps_confirmed(names):
    with SkillRegistry() as registry:
        executor = RecordingExecutor()
        graph = graph_for(names, registry)
        runtime = GraphRuntime(registry, executor)
        state = asyncio.run(runtime.execute(graph))
        resumed = asyncio.run(runtime.resume(graph.id))
        assert resumed.nodes == state.nodes
        assert executor.calls == names


@pytest.mark.asyncio
async def test_unknown_recovery_reuses_original_idempotency_key():
    with SkillRegistry() as registry:
        graph = graph_for(["a"], registry)
        state = GraphState(
            graph_id=graph.id,
            nodes={
                "a": NodeState(status="running", attempt=1, idempotency_key="external-attempt-key")
            },
        )
        registry.save_run(graph.id, graph.model_dump(mode="json"), state.model_dump(mode="json"))
        keys = []

        class DeduplicatingExecutor:
            async def execute(self, node, inputs, context):
                keys.append(context.idempotency_key)
                return NodeResult(observed_effects=["a"])

        recovered = await GraphRuntime(registry, DeduplicatingExecutor()).resume(
            graph.id, retry_unknown=True
        )
        assert recovered.status == "succeeded"
        assert keys == ["external-attempt-key"]
        assert recovered.nodes["a"].attempt == 1
