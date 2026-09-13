from typing import Annotated
from pydantic import Field
from memory.session_memory import search
from .base import ToolSpec


def lookup(keyword):
    hits = search(keyword.strip())
    return {"matches": hits[-3:], "found": bool(hits)}


TOOL = ToolSpec(
    name="memory_search",
    description="检索用户此前说过的内容。参数为非空关键词，未命中不代表用户从未说过。",
    argument_type=Annotated[str, Field(min_length=1, max_length=256, pattern=r"\S")],
    handler=lookup,
)
