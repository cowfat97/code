"""Composable Python adapters; see ../../docs/python-harness-integration.md.

Only ordinary asynchronous functions and public grasp_metaskills contracts are
required. No host, plugin, global registry, shell, retry or cache is installed.
"""

from collections.abc import Awaitable, Callable, Mapping
from types import MappingProxyType
from typing import Any, TypeAlias

from grasp_metaskills import ExecutionContext, NodeResult, SkillNode, VerificationResult

Tool: TypeAlias = Callable[
    [dict[str, Any], ExecutionContext], Awaitable[NodeResult | dict[str, Any]]
]
Rule: TypeAlias = Callable[
    [SkillNode, dict[str, Any], NodeResult, ExecutionContext], Awaitable[VerificationResult]
]


class PythonHarnessExecutor:
    """Dispatch only explicitly allowed immutable skill ID/version capabilities.

    The application owns function permissions and external idempotency handling.
    The runtime owns retries, cancellation, persistence and built-in validation.
    """

    def __init__(self, tools: Mapping[tuple[str, str], Tool]) -> None:
        self._tools: Mapping[tuple[str, str], Tool] = MappingProxyType(dict(tools))

    async def execute(
        self, node: SkillNode, inputs: dict[str, Any], context: ExecutionContext
    ) -> NodeResult:
        if node.skill is None:
            raise LookupError(f"Node {node.id!r} has no skill snapshot")
        key = (node.skill.id, node.skill.version)
        try:
            tool = self._tools[key]
        except KeyError:
            raise LookupError(f"No Python capability registered for skill {key!r}") from None
        return NodeResult.model_validate(await tool(inputs, context))


class PythonHarnessVerifier:
    """Run named supplemental checks; the runtime retains its built-in checks."""

    def __init__(self, rules: Mapping[str, Rule]) -> None:
        self._rules: Mapping[str, Rule] = MappingProxyType(dict(rules))

    async def verify(
        self,
        node: SkillNode,
        inputs: dict[str, Any],
        result: NodeResult,
        context: ExecutionContext,
    ) -> VerificationResult:
        if node.skill is None:
            return VerificationResult(
                passed=False, category="custom_validator", message="Node has no skill snapshot"
            )
        for name in node.skill.contract.validators:
            rule = self._rules.get(name)
            if rule is None:
                return VerificationResult(
                    passed=False,
                    category="custom_validator",
                    message=f"No Python validation rule registered for {name!r}",
                )
            verdict = VerificationResult.model_validate(await rule(node, inputs, result, context))
            if not verdict.passed:
                return verdict
        return VerificationResult(passed=True)
