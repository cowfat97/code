"""Run: python examples/python_harness/demo.py --value 21.

Assembly guide: ../../docs/python-harness-integration.md
The tool functions below have no Harness or plugin dependency.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from typing import Any

from adapter import PythonHarnessExecutor, PythonHarnessVerifier

from grasp_metaskills import (
    ExecutionContext,
    GraphCompiler,
    GraphRuntime,
    NodeResult,
    Skill,
    SkillContract,
    SkillNode,
    SkillRegistry,
    VerificationResult,
)

VALUE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"value": {"type": "integer"}},
    "required": ["value"],
    "additionalProperties": False,
}
RAW_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"raw": {"type": "string"}},
    "required": ["raw"],
    "additionalProperties": False,
}


async def parse_integer(inputs: dict[str, Any], context: ExecutionContext) -> NodeResult:
    value = int(inputs["raw"])
    return NodeResult(output={"value": value}, observed_effects=["parsed(x)"])


async def double_integer(inputs: dict[str, Any], context: ExecutionContext) -> NodeResult:
    value = inputs["value"] * 2
    return NodeResult(output={"value": value}, observed_effects=["ready(x)"])


async def require_even(
    node: SkillNode,
    inputs: dict[str, Any],
    result: NodeResult,
    context: ExecutionContext,
) -> VerificationResult:
    passed = result.output["value"] % 2 == 0
    return VerificationResult(
        passed=passed,
        category="custom_validator",
        message="" if passed else "expected an even integer",
    )


async def run(value: str, database: str = ":memory:") -> dict[str, Any]:
    with SkillRegistry(database) as registry:
        parser = registry.register(
            Skill(
                id="parse",
                name="Parse integer",
                metadata={"idempotent": True},
                contract=SkillContract(
                    effects=["parsed(x)"], input_schema=RAW_SCHEMA, output_schema=VALUE_SCHEMA
                ),
            )
        )
        doubler = registry.register(
            Skill(
                id="double",
                name="Double integer",
                metadata={"idempotent": True},
                contract=SkillContract(
                    preconditions=["parsed(x)"],
                    effects=["ready(x)"],
                    input_schema=VALUE_SCHEMA,
                    output_schema=VALUE_SCHEMA,
                    validators=["even-result"],
                ),
            )
        )
        # Only this assembly point knows both skill identities and Python functions.
        executor = PythonHarnessExecutor(
            {
                (parser.id, parser.version): parse_integer,
                (doubler.id, doubler.version): double_integer,
            }
        )
        verifier = PythonHarnessVerifier({"even-result": require_even})
        graph = await GraphCompiler(registry).compile(
            task="parse integer then double",
            goal=["ready(x)"],
            inputs={"parse:1": {"raw": value}},
        )
        runtime = GraphRuntime(registry, executor, verifier=verifier, timeout=5)
        state = await runtime.execute(graph)
        final = state.nodes["double:1"].result
        return {
            "graph_id": graph.id,
            "graph_version": state.graph_version,
            "status": state.status,
            "output": final.output if final else None,
            "errors": {key: node.error for key, node in state.nodes.items() if node.error},
        }


def main() -> None:
    parser = argparse.ArgumentParser(description="Harness-independent Python function assembly")
    parser.add_argument("--value", default="21", help="An integer represented as text")
    parser.add_argument("--db", default=":memory:", help="Existing-parent SQLite path or :memory:")
    args = parser.parse_args()
    result = asyncio.run(run(args.value, args.db))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if result["status"] != "succeeded":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
