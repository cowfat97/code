"""工具元数据、参数校验和执行协议；具体 handler 由工具实现提供。"""

from dataclasses import dataclass
from typing import Callable

from pydantic import TypeAdapter


@dataclass(frozen=True)
class ToolSpec:
    """不可变的工具定义，供注册器、插件加载器和聊天工作流共享。

    调用次数、成功要求和回答附注由工作流执行；本类负责参数校验和调用。
    """

    name: str  # 唯一工具名，作为模型行动协议中的 action。
    description: str  # 提供给模型的工具用途说明。
    argument_type: object  # Pydantic TypeAdapter 支持的参数类型或模型。
    handler: Callable  # 接收校验后的单个参数对象，返回可供工作流序列化的结果。
    max_calls: int = 1  # 单轮调用次数上限，失败尝试也计入。
    require_success: bool = False  # 调用失败后是否必须重试成功才能继续本轮。
    result_footer: Callable | None = None  # 可选：接收成功结果，生成最终回答附注。

    def parameters(self):
        """生成参数 JSON Schema，供模型识别参数结构和约束。"""
        return TypeAdapter(self.argument_type).json_schema()

    def execute(self, argument):
        """严格校验参数后执行 handler；校验和执行异常交给调用方处理。"""
        value = TypeAdapter(self.argument_type).validate_python(argument, strict=True)
        return self.handler(value)

    def definition(self):
        """生成提供给模型的工具声明；不包含 handler 等本地执行对象。"""
        return {"name": self.name, "description": self.description,
                "parameters": self.parameters(), "max_calls_per_turn": self.max_calls}
