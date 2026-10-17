"""聊天工作流使用的结构化模型行动协议。"""

from typing import Any

from pydantic import BaseModel, ConfigDict


class VllmActionOutput(BaseModel):
    """单次模型行动；用于生成 JSON Schema 并校验模型返回的 JSON。

    工具名是否存在、当前是否允许调用以及调用次数由工作流继续检查。
    """

    # 拒绝协议外字段，避免模型输出未约定的数据。
    model_config = ConfigDict(extra="forbid")
    thought: str  # 行动说明，可为空字符串。
    action: str  # 注册工具名；answer 表示返回本轮最终回答。
    # 不同工具接受不同参数结构；调用时由 ToolSpec 进行严格校验。
    argument: Any
