import pytest

from grasp_metaskills.compiler import CompilationError, GraphCompiler
from grasp_metaskills.contracts import NodeResult, Skill, SkillContract, SkillDependency
from grasp_metaskills.registry import SkillRegistry
from grasp_metaskills.runtime import GraphRuntime


def skill(id, requires=(), provides=(), effects=(), version="1.0.0", dependencies=()):
    return Skill(
        id=id,
        name=id,
        version=version,
        metadata={"requires": list(requires), "provides": list(provides)},
        contract=SkillContract(effects=list(effects)),
        dependencies=list(dependencies),
    )


def registry(tmp_path, skills):
    r = SkillRegistry(tmp_path / "skills.db")
    for s in skills:
        r.register(s)
    return r


@pytest.mark.asyncio
async def test_all_providers_survive_backward_filter_and_execute(tmp_path):
    r = registry(
        tmp_path,
        [
            skill("a", provides=["cap"]),
            skill("b", provides=["cap"]),
            skill("root", requires=["cap"], effects=["done(x)"]),
        ],
    )
    graph = await GraphCompiler(r).compile(goal=["done(x)"], proposal=[{"skill": "root"}])
    assert {n.skill.id for n in graph.nodes if n.skill} == {"a", "b", "root"}
    assert graph.node("root:1").preconditions == []
    assert {(e.source, e.target) for e in graph.edges if e.label.startswith("capability:")} == {
        ("a:1", "root:1"),
        ("b:1", "root:1"),
    }
    called = []

    class Executor:
        async def execute(self, node, inputs, context):
            called.append(node.skill.id)
            return NodeResult(observed_effects=node.effects)

    state = await GraphRuntime(r, Executor()).execute(graph)
    assert state.status == "succeeded"
    assert called[-1] == "root"


@pytest.mark.asyncio
@pytest.mark.parametrize("cycle", [False, True])
async def test_missing_or_cyclic_source_capability_fails(tmp_path, cycle):
    skills = [skill("root", requires=["cap"], provides=["root-cap"], effects=["done(x)"])]
    if cycle:
        skills.append(skill("provider", requires=["root-cap"], provides=["cap"]))
    r = registry(tmp_path, skills)
    with pytest.raises(CompilationError, match="capability"):
        await GraphCompiler(r).compile(goal=["done(x)"])


@pytest.mark.asyncio
async def test_explicit_version_pin_capability_provider_uses_same_snapshot(tmp_path):
    old = skill("provider", provides=["cap"], version="1.0.0")
    new = skill("provider", provides=["different"], version="2.0.0")
    root = skill(
        "root",
        requires=["cap"],
        effects=["done(x)"],
        dependencies=[SkillDependency(id="provider", version="==1.0.0")],
    )
    r = registry(tmp_path, [old, new, root])
    graph = await GraphCompiler(r).compile(goal=["done(x)"])
    providers = [n.skill for n in graph.nodes if n.skill and n.skill.id == "provider"]
    assert [s.version for s in providers] == ["1.0.0"]


@pytest.mark.asyncio
async def test_transitive_provider_closure_and_automatic_goal_planning(tmp_path):
    r = registry(
        tmp_path,
        [
            skill("leaf", provides=["leaf-cap"]),
            skill("middle", requires=["leaf-cap"], provides=["cap"]),
            skill("root", requires=["cap"], effects=["done(x)"]),
        ],
    )
    graph = await GraphCompiler(r).compile(goal=["done(x)"])
    order = graph.topological_order()
    assert order.index("leaf:1") < order.index("middle:1") < order.index("root:1")
    assert all(not n.preconditions for n in graph.nodes if n.skill)


@pytest.mark.asyncio
async def test_proposal_root_version_pin_uses_historical_capabilities(tmp_path):
    r = registry(
        tmp_path,
        [
            skill("provider", provides=["old-cap"]),
            skill("root", requires=["old-cap"], effects=["done(x)"], version="1.0.0"),
            skill("root", requires=["missing-new-cap"], effects=["done(x)"], version="2.0.0"),
        ],
    )
    graph = await GraphCompiler(r).compile(
        goal=["done(x)"], proposal=[{"skill": "root", "version": "1.0.0"}]
    )
    assert graph.node("root:1").skill.version == "1.0.0"
    assert graph.node("provider:1").skill.id == "provider"


@pytest.mark.asyncio
async def test_fact_initial_condition_does_not_satisfy_capability(tmp_path):
    r = registry(tmp_path, [skill("root", requires=["cap"], effects=["done(x)"])])
    with pytest.raises(CompilationError, match="capability"):
        await GraphCompiler(r).compile(goal=["done(x)"], initial_conditions=["cap"])


@pytest.mark.asyncio
async def test_mandatory_capability_order_conflict_is_error(tmp_path):
    from grasp_metaskills.contracts import SkillContract

    provider = skill("provider", provides=["cap"]).model_copy(
        update={"contract": SkillContract(preconditions=["done(x)"])}
    )
    r = registry(tmp_path, [provider, skill("root", requires=["cap"], effects=["done(x)"])])
    with pytest.raises(CompilationError, match="cycle"):
        await GraphCompiler(r).compile(goal=["done(x)"], proposal=[{"skill": "root"}])
