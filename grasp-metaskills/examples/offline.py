"""Deterministic generic dataflow; no model, shell skill, JS or Rust process."""

import asyncio

from grasp_metaskills import (
    GraphCompiler,
    GraphRuntime,
    NodeResult,
    Skill,
    SkillContract,
    SkillRegistry,
)

NUMBER = {
    "type": "object",
    "properties": {"value": {"type": "integer"}},
    "required": ["value"],
    "additionalProperties": False,
}


class ArithmeticExecutor:
    async def execute(self, node, inputs, context):
        if node.skill.id == "emit":
            value = 3
            return NodeResult(output={"value": value}, observed_effects=["seed(x)"])
        if node.skill.id == "scale":
            value = inputs["value"] * 2
            return NodeResult(
                output={"value": value}, observed_effects=["ready(x)"] if value == 6 else []
            )
        raise ValueError(f"Unregistered executor capability: {node.skill.id}")


async def main():
    with SkillRegistry() as registry:
        registry.register(
            Skill(
                id="emit",
                name="Emit integer",
                contract=SkillContract(effects=["seed(x)"], output_schema=NUMBER),
            )
        )
        registry.register(
            Skill(
                id="scale",
                name="Scale integer",
                contract=SkillContract(
                    preconditions=["seed(x)"],
                    effects=["ready(x)"],
                    input_schema=NUMBER,
                    output_schema=NUMBER,
                ),
            )
        )
        graph = await GraphCompiler(registry).compile(goal=["ready(x)"])
        state = await GraphRuntime(registry, executor=ArithmeticExecutor()).execute(graph)
        print("status:", state.status)
        for node_id, node in state.nodes.items():
            if node.result and node.result.output:
                print(node_id, node.result.output)
        print("trace events:", len(state.trace))


if __name__ == "__main__":
    asyncio.run(main())
