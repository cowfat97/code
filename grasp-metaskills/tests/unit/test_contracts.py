import pytest
from pydantic import ValidationError

from grasp_metaskills.contracts import (
    DependencyEdge,
    ExecutionGraph,
    Skill,
    SkillContract,
    SkillNode,
)


def test_skill_frozen():
    skill = Skill(id="a", name="A")
    with pytest.raises(ValidationError):
        skill.version = "2"


def test_invalid_reference_and_cycle():
    nodes = [SkillNode(id=x, skill=Skill(id=x, name=x)) for x in ["a", "b"]]
    graph = ExecutionGraph(
        nodes=nodes, edges=[DependencyEdge(source="a", target="missing", type="order")]
    )
    assert any("unknown" in e for e in graph.validate_graph())
    graph.edges = [
        DependencyEdge(source="a", target="b", type="order"),
        DependencyEdge(source="b", target="a", type="state"),
    ]
    assert any("cycle" in e for e in graph.validate_graph())


def test_snapshot_and_serialization():
    skill = Skill(id="a", name="A", contract=SkillContract(effects=["ready(x)"]))
    graph = ExecutionGraph(nodes=[SkillNode(id="a:1", skill=skill, effects=["ready(x)"])])
    assert ExecutionGraph.model_validate_json(graph.model_dump_json()) == graph
    assert graph.descendants({"a:1"}) == {"a:1"}
