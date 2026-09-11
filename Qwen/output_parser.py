# output_parser.py —— 模型输出协议：定义 JSON 结构并转换成程序可用的行动
import json
from typing import Literal

from pydantic import BaseModel


class ActionOutput(BaseModel):
    """状态机允许模型生成的唯一 JSON 结构。"""

    thought: str
    action: Literal["answer", "memory_search"]
    argument: str


def parse_action(text):
    """校验 JSON 输出，返回 (action, argument)；校验失败返回 None。"""
    try:
        output = ActionOutput.model_validate_json(text)
    except ValueError:
        return None
    return output.action, output.argument.strip()


def fallback_reply(text):
    """约束输出意外截断时，尽量提取 argument，否则保留原文。"""
    try:
        argument = json.loads(text).get("argument")
    except (json.JSONDecodeError, AttributeError):
        return text
    return argument.strip() if isinstance(argument, str) else text
