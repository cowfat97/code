"""Generated invariants, rather than fixed sample paths."""

import asyncio

from hypothesis import given, settings
from hypothesis import strategies as st

from grasp_metaskills.contracts import (
    DependencyEdge,
    ExecutionGraph,
    GraphState,
    NodeResult,
    NodeState,
    RepairOperation,
    Skill,
    SkillContract,
    SkillNode,
)


@given(
    st.integers(min_value=1, max_value=35),
    st.sets(
        st.tuples(st.integers(min_value=0, max_value=34), st.integers(min_value=0, max_value=34)),
        max_size=100,
    ),
)
def test_generated_dag_references_and_topological_order(count, pairs):
    nodes = [SkillNode(id=str(i), skill=Skill(id=str(i), name=str(i))) for i in range(count)]
    edges = [
        DependencyEdge(source=str(a), target=str(b), type="order")
        for a, b in pairs
        if a < b < count
    ]
    graph = ExecutionGraph(nodes=nodes, edges=edges)
    assert graph.validate_graph() == []
    order = graph.topological_order()
    assert all(order.index(e.source) < order.index(e.target) for e in graph.edges)


@given(st.integers(min_value=1, max_value=8))
@settings(max_examples=20, deadline=None)
def test_compiler_generated_chains_are_acyclic_and_versions_fixed(count):
    from grasp_metaskills.compiler import GraphCompiler
    from grasp_metaskills.registry import SkillRegistry

    registry = SkillRegistry()
    for i in range(count):
        registry.register(
            Skill(
                id=f"s{i}",
                name=f"s{i}",
                contract=SkillContract(
                    preconditions=[f"p{i - 1}(x)"] if i else [], effects=[f"p{i}(x)"]
                ),
            )
        )
    graph = asyncio.run(GraphCompiler(registry).compile(goal=[f"p{count - 1}(x)"]))
    assert graph.validate_graph() == []
    assert len([n for n in graph.nodes if n.kind == "skill"]) == count
    registry.register(Skill(id="s0", name="new", version="2.0.0"))
    assert all(n.skill.version == "1.0.0" for n in graph.nodes if n.skill)
    assert all(
        e.source in {n.id for n in graph.nodes} and e.target in {n.id for n in graph.nodes}
        for e in graph.edges
    )
    registry.close()


@given(st.integers(min_value=1, max_value=15))
def test_repair_retains_independent_verified_branch(count):
    from grasp_metaskills.registry import SkillRegistry
    from grasp_metaskills.repair import RepairEngine

    registry = SkillRegistry()
    original = Skill(id="original", name="original", contract=SkillContract(effects=["ready(x)"]))
    alternative = Skill(
        id="alternative", name="alternative", contract=SkillContract(effects=["ready(x)"])
    )
    registry.register(original)
    registry.register(alternative)
    nodes = [SkillNode(id="root", skill=original, effects=["ready(x)"])]
    states = {"root": NodeState(status="failed")}
    for i in range(count):
        sid = f"side{i}"
        nodes.append(SkillNode(id=sid, skill=Skill(id=sid, name=sid)))
        states[sid] = NodeState(status="succeeded", result=NodeResult(output={"i": i}))
    graph = ExecutionGraph(nodes=nodes, goal=["ready(x)"])
    state = GraphState(graph_id=graph.id, nodes=states)
    result = RepairEngine(registry).apply(
        graph, state, RepairOperation(type="Substitute", node_id="root", replacement=alternative)
    )
    assert not result.graph.validate_graph()
    for i in range(count):
        assert result.state.nodes[f"side{i}"] == states[f"side{i}"]
    registry.close()


@given(st.integers(min_value=1, max_value=20))
def test_invalid_repair_cannot_introduce_unproduced_prerequisite(index):
    import pytest

    from grasp_metaskills.registry import SkillRegistry
    from grasp_metaskills.repair import RepairEngine, RepairError

    with SkillRegistry() as registry:
        original = registry.register(
            Skill(id="original", name="original", contract=SkillContract(effects=["ready(x)"]))
        )
        invalid = registry.register(
            Skill(
                id="invalid",
                name="invalid",
                contract=SkillContract(
                    preconditions=[f"unavailable{index}(x)"], effects=["ready(x)"]
                ),
            )
        )
        graph = ExecutionGraph(
            goal=["ready(x)"], nodes=[SkillNode(id="root", skill=original, effects=["ready(x)"])]
        )
        before = graph.model_dump_json()
        with pytest.raises(RepairError, match="precondition"):
            RepairEngine(registry).apply(
                graph,
                GraphState(graph_id=graph.id),
                RepairOperation(type="Substitute", node_id="root", replacement=invalid),
            )
        assert graph.model_dump_json() == before and graph.validate_graph() == []
