"""Port stage-b-executor.js CHAIN, success/failure/resume/persist assertions."""

import pytest

from grasp_metaskills import (
    DependencyEdge,
    ExecutionGraph,
    GraphRuntime,
    NodeResult,
    Skill,
    SkillContract,
    SkillNode,
    SkillRegistry,
)


@pytest.mark.parametrize("fail", [False, True])
async def test_stage_b_chain_order_idempotency_failure_and_persistence(fail):
    with SkillRegistry() as registry:
        rows = [
            ("a", "alpha", [], ["pa(x)"]),
            ("b", "beta", ["pa(x)"], ["pb(x)"]),
            ("c", "gamma", ["pb(x)"], ["pc(x)"]),
        ]
        nodes = []
        for nid, sid, pre, effects in rows:
            skill = registry.register(
                Skill(id=sid, name=sid, contract=SkillContract(preconditions=pre, effects=effects))
            )
            nodes.append(
                SkillNode(id=nid, skill=skill, args=["x"], preconditions=pre, effects=effects)
            )
        graph = ExecutionGraph(
            id="plan-b1",
            task="chain task",
            goal=["pc(x)"],
            nodes=nodes,
            edges=[
                DependencyEdge(source="a", target="b", type="state"),
                DependencyEdge(source="b", target="c", type="state"),
            ],
        )
        log = []

        class Chain:
            async def execute(self, node, inputs, context):
                log.append((node.id, context.idempotency_key))
                if fail and node.id == "b":
                    raise RuntimeError("boom")
                # Upstream fixture returns a node id and assumes expected effects;
                # here the fixture explicitly supplies the corresponding observed fact.
                return NodeResult(
                    output={"id": node.id},
                    observed_effects=[dict(a="pa(x)", b="pb(x)", c="pc(x)")[node.id]],
                )

        runtime = GraphRuntime(registry, Chain(), concurrency=1)
        state = await runtime.execute(graph)
        assert [row[0] for row in log] == (["a", "b"] if fail else ["a", "b", "c"])
        assert all(key == f"grasp:idem:plan-b1:{nid}:1" for nid, key in log)
        assert state.nodes["a"].status == "succeeded"
        if fail:
            assert state.status == "failed" and state.nodes["b"].status == "failed"
            assert state.nodes["c"].status == "blocked"
        else:
            assert state.status == "succeeded"
            assert (await runtime.resume(graph.id)).nodes == state.nodes
            assert len(log) == 3
        assert len(registry.run_history(graph.id)) >= 4
