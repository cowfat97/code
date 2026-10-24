import pytest

from grasp_metaskills.compiler import CompilationError, GraphCompiler, schema_compatible
from grasp_metaskills.contracts import Skill, SkillContract, SkillDependency


class Registry:
    def __init__(self, skills):
        self.skills = skills

    def list(self):
        return self.skills

    def get(self, skill_id, version=None):
        return next(s for s in self.skills if s.id == skill_id)


def skill(id, pre=(), eff=(), **kwargs):
    return Skill(
        id=id,
        name=id,
        version="1.0.0",
        contract=SkillContract(preconditions=list(pre), effects=list(eff), **kwargs),
    )


@pytest.mark.asyncio
async def test_automatic_backward_chain():
    graph = await GraphCompiler(
        Registry(
            [
                skill("first", eff=["a(x)"]),
                skill("last", ["a(x)"], ["done(x)"]),
                skill("irrelevant", eff=["other(x)"]),
            ]
        )
    ).compile(goal=["done(x)"])
    assert [n.skill.id for n in graph.nodes if n.skill] == ["first", "last"]
    assert graph.validate_graph() == []


@pytest.mark.asyncio
async def test_parameter_binding_and_missing():
    compiler = GraphCompiler(
        Registry([skill("last", ["ready(item)"], ["done(item)"], params=["item"])])
    )
    with pytest.raises(CompilationError, match="unreachable|missing"):
        await compiler.compile(goal=["done(apple)"])
    graph = await compiler.compile(goal=["done(apple)"], initial_conditions=["ready(apple)"])
    assert graph.node("last:1").args == ["apple"]


@pytest.mark.asyncio
async def test_soft_cycle_and_invalid_hint():
    compiler = GraphCompiler(
        Registry([skill("first", eff=["a(x)"]), skill("last", ["a(x)"], ["done(x)"])])
    )
    graph = await compiler.compile(
        goal=["done(x)"], order_hints=[{"from": "last:1", "to": "first:1"}]
    )
    assert graph.validate_graph() == []
    assert not any(e.source == "last:1" and e.target == "first:1" for e in graph.edges)
    with pytest.raises(CompilationError, match="invalid dependency"):
        await compiler.compile(goal=["done(x)"], order_hints=[{"from": "absent", "to": "first:1"}])


@pytest.mark.asyncio
async def test_schema_conflict():
    compiler = GraphCompiler(
        Registry(
            [
                skill(
                    "first",
                    eff=["a(x)"],
                    output_schema={"type": "object", "properties": {"value": {"type": "string"}}},
                ),
                skill(
                    "last",
                    ["a(x)"],
                    ["done(x)"],
                    input_schema={
                        "type": "object",
                        "required": ["value"],
                        "properties": {"value": {"type": "integer"}},
                    },
                ),
            ]
        )
    )
    with pytest.raises(CompilationError, match="type|schema"):
        await compiler.compile(goal=["done(x)"])


@pytest.mark.asyncio
async def test_initial_goal_needs_no_skill():
    graph = await GraphCompiler(Registry([])).compile(
        goal=["done(x)"], initial_conditions=["done(x)"]
    )
    assert [n.id for n in graph.nodes] == ["src", "snk"]


@pytest.mark.asyncio
async def test_alternative_branch_backtracking():
    graph = await GraphCompiler(
        Registry([skill("bad", ["missing(x)"], ["done(x)"]), skill("good", eff=["done(x)"])])
    ).compile(goal=["done(x)"])
    assert [n.skill.id for n in graph.nodes if n.skill] == ["good"]


@pytest.mark.asyncio
async def test_explicit_hard_cycle():
    compiler = GraphCompiler(
        Registry([skill("a", ["b(x)"], ["a(x)"]), skill("b", ["a(x)"], ["b(x)"])])
    )
    with pytest.raises(CompilationError, match="cycle"):
        await compiler.compile(
            goal=["a(x)"], proposal=[{"skill": "a", "args": []}, {"skill": "b", "args": []}]
        )


@pytest.mark.asyncio
async def test_version_dependency():
    dependency = skill("a", eff=["a(x)"])
    consumer = skill("b", eff=["done(x)"]).model_copy(
        update={"dependencies": [SkillDependency(id="a", version=">=1")]}
    )
    graph = await GraphCompiler(Registry([dependency, consumer])).compile(goal=["done(x)"])
    assert any(e.source == "a:1" and e.target == "b:1" for e in graph.edges)
    consumer = consumer.model_copy(
        update={"dependencies": [SkillDependency(id="a", version=">=2")]}
    )
    with pytest.raises(CompilationError, match="missing dependency"):
        await GraphCompiler(Registry([dependency, consumer])).compile(goal=["done(x)"])


def test_schema_subset_boundaries():
    assert schema_compatible({"type": "integer"}, {"type": "number"})
    assert not schema_compatible({"type": "number"}, {"type": "integer"})
    assert not schema_compatible({"type": "string"}, {"type": "string", "pattern": "x"})
    assert schema_compatible({"type": "string", "pattern": "x"}, {"type": "string", "pattern": "x"})


def test_binding_does_not_capture_other_parameter_names():
    from grasp_metaskills.compiler import bind_skill

    node = bind_skill(skill("move", eff=["at(x,y)"], params=["x", "y"]), ["y", "z"])
    assert node.effects == ["at(y,z)"]
