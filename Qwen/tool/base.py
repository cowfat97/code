"""工具元数据和执行约定；handler 不发送给模型。"""
from dataclasses import dataclass
from typing import Callable
from pydantic import TypeAdapter


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    argument_type: object
    handler: Callable
    max_calls: int = 1
    require_success: bool = False
    result_footer: Callable | None = None

    def parameters(self):
        return TypeAdapter(self.argument_type).json_schema()

    def execute(self, argument):
        value = TypeAdapter(self.argument_type).validate_python(argument, strict=True)
        return self.handler(value)

    def definition(self):
        return {"name": self.name, "description": self.description,
                "parameters": self.parameters(), "max_calls_per_turn": self.max_calls}
