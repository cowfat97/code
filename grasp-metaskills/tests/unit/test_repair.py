"""GraSP repair semantics and stronger transactional validation."""

import pytest

from grasp_metaskills.contracts import (
    DependencyEdge,
    ExecutionGraph,
    GraphState,
    NodeResult,
    NodeState,
    RepairEvent,
    RepairOperation,
    Skill,
    SkillContract,
    SkillNode,
)
from grasp_metaskills.repair import RepairEngine, RepairError


class Library:
    def __init__(self, skills):
        self.skills = skills

    def list(self):
        return self.skills

    def search(self, query, **kwargs):
        return []


def skill(sid, pre=(), eff=(), params=()):
    return Skill(
        id=sid,
        name=sid,
        contract=SkillContract(preconditions=list(pre), effects=list(eff), params=list(params)),
    )


def fixture_graph():
    a = skill("a", eff=["a(x)"])
    b = skill("b", pre=["a(x)"], eff=["b(x)"])
    c = skill("c", eff=["c(x)"])
    graph = ExecutionGraph(
        goal=["b(x)", "c(x)"],
        nodes=[
            SkillNode(id="src", kind="src"),
            SkillNode(id="a:1", skill=a, effects=["a(x)"]),
            SkillNode(id="b:1", skill=b, preconditions=["a(x)"], effects=["b(x)"]),
            SkillNode(id="c:1", skill=c, effects=["c(x)"]),
            SkillNode(id="snk", kind="snk", preconditions=["b(x)", "c(x)"]),
        ],
        edges=[
            DependencyEdge(source="src", target="a:1", type="order"),
            DependencyEdge(source="src", target="c:1", type="order"),
            DependencyEdge(source="a:1", target="b:1", type="state", label="a(x)"),
            DependencyEdge(source="b:1", target="snk", type="order"),
            DependencyEdge(source="c:1", target="snk", type="order"),
        ],
    )
    state = GraphState(graph_id=graph.id, nodes={n.id: NodeState() for n in graph.nodes})
    state.nodes["c:1"] = NodeState(status="succeeded", result=NodeResult(observed_effects=["c(x)"]))
    return graph, state


def test_substitute_preserves_unaffected_cache_and_versions():
    graph, state = fixture_graph()
    alt = skill("alt", eff=["a(x)"])
    result = RepairEngine(Library([alt])).apply(
        graph, state, RepairOperation(type="Substitute", node_id="a:1", replacement=alt)
    )
    assert result.repaired
    assert result.graph.version == 2 and graph.version == 1
    assert result.graph.node("a:1").skill.id == "alt"
    assert result.state.nodes["c:1"] == state.nodes["c:1"]
    assert result.state.nodes["b:1"].status == "pending"
    assert result.state.repair_audit[-1]["affected"] == ["a:1", "b:1", "snk"]


def test_insert_prereq_from_upstream_operator():
    # verify.js [3]: InsertPrereq binds goto(loc) to at(agent,sink).
    graph = ExecutionGraph(
        goal=["clean(apple)"],
        nodes=[
            SkillNode(id="src", kind="src"),
            SkillNode(
                id="clean:1",
                skill=skill("clean"),
                preconditions=["at(agent,sink)"],
                effects=["clean(apple)"],
            ),
            SkillNode(id="snk", kind="snk", preconditions=["clean(apple)"]),
        ],
        edges=[
            DependencyEdge(source="src", target="clean:1", type="order"),
            DependencyEdge(source="clean:1", target="snk", type="order"),
        ],
    )
    state = GraphState(graph_id=graph.id)
    goto = skill("goto", eff=["at(agent,loc)"], params=["loc"])
    result = RepairEngine(Library([goto])).repair(
        graph, state, RepairEvent(node_id="clean:1", type="precondition", state=[])
    )
    assert result.repaired
    assert result.operation.type == "InsertPrereq"
    assert result.graph.node("goto:1").args == ["sink"]
    assert not result.graph.validate_graph()


def test_budget_and_invalid_dependency_rejected():
    graph, state = fixture_graph()
    alt = skill("bad", pre=["missing(x)"], eff=["a(x)"])
    engine = RepairEngine(Library([alt]))
    with pytest.raises(RepairError, match="precondition"):
        engine.apply(
            graph, state, RepairOperation(type="Substitute", node_id="a:1", replacement=alt)
        )
    assert graph.node("a:1").skill.id == "a"
    graph.node("a:1").repair_budget = 0
    result = engine.repair(graph, state, RepairEvent(node_id="a:1", type="execution"))
    assert not result.repaired and result.reason == "local-exhausted"


def test_rewire_cannot_fake_missing_precondition():
    graph, state = fixture_graph()
    graph.node("a:1").preconditions = ["missing(x)"]
    result = RepairEngine(Library([]), operator_order=["Rewire"]).repair(
        graph, state, RepairEvent(node_id="a:1", type="precondition")
    )
    assert not result.repaired


def test_bypass_requires_observed_downstream_facts():
    graph, state = fixture_graph()
    engine = RepairEngine(Library([]))
    with pytest.raises(RepairError):
        engine.apply(graph, state, RepairOperation(type="Bypass", node_id="a:1"))
    state.facts = ["a(x)"]
    result = engine.apply(graph, state, RepairOperation(type="Bypass", node_id="a:1"))
    assert result.state.nodes["a:1"].status == "bypassed"


def test_lmax_zero_does_not_insert():
    graph, state = fixture_graph()
    graph.node("a:1").preconditions = ["missing(x)"]
    result = RepairEngine(
        Library([skill("s", eff=["missing(x)"])]), l_max=0, operator_order=["InsertPrereq"]
    ).repair(graph, state, RepairEvent(node_id="a:1", type="precondition"))
    assert not result.repaired


def test_rebind_recomputes_concrete_predicates():
    original = skill("param", eff=["done(item)"], params=["item"])
    graph = ExecutionGraph(
        goal=["done(b)"],
        nodes=[
            SkillNode(id="param:1", skill=original, args=["a"], effects=["done(a)"]),
            SkillNode(id="snk", kind="snk", preconditions=["done(b)"]),
        ],
        edges=[DependencyEdge(source="param:1", target="snk", type="order")],
    )
    result = RepairEngine(Library([original])).apply(
        graph,
        GraphState(graph_id=graph.id),
        RepairOperation(type="Rebind", node_id="param:1", args=["b"]),
    )
    assert result.graph.node("param:1").effects == ["done(b)"]
    assert graph.node("param:1").args == ["a"]


def test_rewire_only_order_not_hard_edge():
    graph, state = fixture_graph()
    hard = next(e for e in graph.edges if e.type == "state")
    with pytest.raises(RepairError, match="order"):
        RepairEngine(Library([])).apply(
            graph, state, RepairOperation(type="Rewire", node_id="b:1", edge=hard)
        )
    result = RepairEngine(Library([])).apply(
        graph, state, RepairOperation(type="Rewire", node_id="a:1")
    )
    assert len(result.graph.edges) == len(graph.edges) - 1
    assert not result.graph.validate_graph()


def test_bypass_cannot_manufacture_bound_data():
    from grasp_metaskills.contracts import InputBinding

    graph, state = fixture_graph()
    graph.node("b:1").bindings = {"value": InputBinding(node_id="a:1", output_key="value")}
    graph.edges.append(DependencyEdge(source="a:1", target="b:1", type="data", label="value"))
    state.facts = ["a(x)"]
    with pytest.raises(RepairError, match="data"):
        RepairEngine(Library([])).apply(graph, state, RepairOperation(type="Bypass", node_id="a:1"))


def test_substitute_rejects_new_required_input_with_existing_binding():
    from grasp_metaskills.contracts import InputBinding

    graph, state = fixture_graph()
    source = Skill(
        id="source",
        name="source",
        contract=SkillContract(
            output_schema={
                "type": "object",
                "properties": {"x": {"type": "integer"}},
                "required": ["x"],
            }
        ),
    )
    graph.nodes.append(SkillNode(id="source:1", skill=source))
    graph.node("a:1").bindings = {"x": InputBinding(node_id="source:1", output_key="x")}
    graph.edges.append(DependencyEdge(source="source:1", target="a:1", type="data"))
    alt = Skill(
        id="alt",
        name="alt",
        contract=SkillContract(
            effects=["a(x)"],
            input_schema={
                "type": "object",
                "properties": {"x": {"type": "integer"}, "y": {"type": "integer"}},
                "required": ["x", "y"],
            },
        ),
    )
    with pytest.raises(RepairError, match="required|input"):
        RepairEngine(Library([alt])).apply(
            graph, state, RepairOperation(type="Substitute", node_id="a:1", replacement=alt)
        )


def test_repair_accepts_bare_exact_dependency_version():
    from grasp_metaskills.contracts import SkillDependency

    graph, state = fixture_graph()
    graph.node("b:1").skill = graph.node("b:1").skill.model_copy(
        update={"dependencies": [SkillDependency(id="a", version="1.0.0")]}
    )
    graph.edges.append(DependencyEdge(source="a:1", target="b:1", type="order"))
    result = RepairEngine(Library([])).apply(
        graph, state, RepairOperation(type="Rewire", node_id="b:1")
    )
    assert result.repaired


def test_automatic_substitute_binds_parameterized_alternative():
    graph, state = fixture_graph()
    alternative = skill("generic", eff=["a(item)"], params=["item"])
    result = RepairEngine(Library([alternative]), operator_order=["Substitute"]).repair(
        graph, state, RepairEvent(node_id="a:1", type="execution")
    )
    assert result.repaired
    assert result.graph.node("a:1").args == ["x"]
    assert result.graph.node("a:1").effects == ["a(x)"]


def test_exhausted_repair_is_audited_and_empty_order_disables_operators():
    graph, state = fixture_graph()
    graph.node("a:1").repair_budget = 0
    result = RepairEngine(Library([])).repair(
        graph, state, RepairEvent(node_id="a:1", type="execution")
    )
    assert result.state.repair_audit[-1]["reason"] == "local-exhausted"
    graph.node("a:1").repair_budget = 2
    state.facts = ["a(x)"]
    disabled = RepairEngine(Library([]), operator_order=[]).repair(
        graph, state, RepairEvent(node_id="a:1", type="execution")
    )
    assert not disabled.repaired


def test_substitute_rejects_new_unscheduled_capability_dependency():
    graph, state = fixture_graph()
    alt = skill("alt", eff=["a(x)"]).model_copy(update={"metadata": {"requires": ["network"]}})
    with pytest.raises(RepairError, match="missing capability"):
        RepairEngine(Library([alt])).apply(
            graph, state, RepairOperation(type="Substitute", node_id="a:1", replacement=alt)
        )
    assert graph.version == 1
    assert state.nodes["c:1"].status == "succeeded"
