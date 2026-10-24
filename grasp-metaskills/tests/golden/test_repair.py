"""verify.js [2]-[4]: strict failure, InsertPrereq goto binding, patch bounds."""

import pytest

from grasp_metaskills import (
    GraphCompiler,
    GraphState,
    RepairEngine,
    RepairEvent,
    Skill,
    SkillContract,
    SkillRegistry,
)


@pytest.mark.parametrize("lmax,repaired", [(3, True), (0, False)])
async def test_upstream_insert_prereq_exact_patch(lmax, repaired):
    with SkillRegistry() as registry:
        registry.register(
            Skill(
                id="clean",
                name="Clean object",
                contract=SkillContract(
                    params=["object"],
                    preconditions=["holding(object)", "at(agent,sink)"],
                    effects=["clean(object)"],
                ),
            )
        )
        registry.register(
            Skill(
                id="goto",
                name="Go to location",
                contract=SkillContract(params=["loc"], effects=["at(agent,loc)"]),
            )
        )
        graph = await GraphCompiler(registry, strict_preconditions=False).compile(
            goal=["clean(apple)"],
            initial_conditions=["holding(apple)"],
            proposal=[{"skill": "clean", "args": ["apple"]}],
        )
        state = GraphState(graph_id=graph.id, facts=["holding(apple)"])
        result = RepairEngine(registry, l_max=lmax, operator_order=["InsertPrereq"]).repair(
            graph,
            state,
            RepairEvent(node_id="clean:1", type="precondition", state=["holding(apple)"]),
        )
        assert result.repaired is repaired
        if repaired:
            assert result.operation.type == "InsertPrereq"
            assert result.graph.node("goto:1").args == ["sink"]
            assert result.state.repair_audit[-1]["added_nodes"] == ["goto:1"]
            assert result.state.repair_audit[-1]["added_edges"] == 2
        else:
            assert result.reason == "local-failed"
