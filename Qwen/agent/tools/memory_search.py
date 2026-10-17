# 设计文档：[记忆工具化改造](../../../../文档/Qwen/Agent/记忆工具化改造/design/详细设计.md)
from typing import Annotated
from pydantic import Field
from dataclasses import replace
from agent.entities import ToolSpec


def lookup(keyword, history=()):
    """纯检索已提交历史，只返回最近三条真实用户消息。"""
    keyword = keyword.strip()
    hits = [content for role, content in history
            if role == "user" and not content.startswith("[观察]")
            and "<think>" not in content and keyword in content]
    return {"matches": hits[-3:], "found": bool(hits)}


def bind_history(history):
    """冻结本轮历史，避免调用方后续修改列表或消息影响检索。"""
    snapshot = tuple((message["role"], message["content"]) for message in history)
    return replace(TOOL, handler=lambda keyword: lookup(keyword, snapshot))


TOOL = ToolSpec(
    name="memory_search",
    description="检索用户此前说过的内容。参数为非空关键词，未命中不代表用户从未说过。",
    argument_type=Annotated[str, Field(min_length=1, max_length=256, pattern=r"\S")],
    handler=lookup,
)
