from typing import Any

from pydantic import BaseModel, ConfigDict


class VllmActionOutput(BaseModel):
    """vLLM 结构化输出使用的工具行动协议。"""

    model_config = ConfigDict(extra="forbid")
    thought: str
    action: str
    argument: Any  # 由注册工具的参数类型做进一步严格校验。
