"""Explicit skill-to-tool binding; effect evidence comes from the tool result."""

from typing import Any

from ..contracts import ExecutionContext, NodeResult, SkillNode
from .ports import ToolsPort


class ToolSkillExecutor:
    def __init__(self, tools: ToolsPort) -> None:
        self.tools = tools

    async def execute(
        self, node: SkillNode, inputs: dict[str, Any], context: ExecutionContext
    ) -> NodeResult:
        if node.skill is None:
            raise ValueError("tool execution requires a skill snapshot")
        tool_name = node.skill.metadata.get("tool")
        if not isinstance(tool_name, str) or not tool_name:
            raise ValueError(f"skill {node.skill.id!r} has no tool binding")
        response = await self.tools.call(tool_name, inputs)
        if response.is_error:
            raise RuntimeError(f"tool {tool_name!r} returned an error: {response.content!r}")
        data = response.data
        if not isinstance(data, dict) or "output" not in data:
            raise ValueError("tool data must contain a NodeResult object with an output field")
        return NodeResult.model_validate(data)
