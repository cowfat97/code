"""切分模块基础：Chunk 数据结构 + Splitter 抽象接口。"""

import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, Literal

# ── 类型定义（与 document.base 保持一致，避免触发 document 包的重型导入）──

DocType = Literal["heading", "table_row", "image", "paragraph"]


@dataclass
class ContentElement:
    """文档解析后的最小内容单元（轻量版，仅用于切分模块内部）。

    与 document.base.ContentElement 字段一致，避免跨包导入触发 numpy 等重依赖。
    """
    content: str
    doc_type: DocType
    metadata: dict = field(default_factory=dict)


@dataclass
class Chunk:
    """切分后的文本块。

    parent_id 用于父子块关联：
    - 父块 parent_id=None，入 LLM 上下文（完整语义单元）
    - 子块 parent_id 指向父块 chunk_id，入向量库索引（精准匹配）
    """
    content: str
    doc_type: DocType
    metadata: dict = field(default_factory=dict)
    chunk_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    parent_id: str | None = None


class TextSplitter(ABC):
    """切分器 — 策略接口。

    每种切分策略实现一个子类。
    ContentElement.doc_type 决定选哪个策略：
    - heading   → HeadingSplitter（标题做切分边界）
    - table_row → NoOpSplitter（不切，保持行完整）
    - image     → NoOpSplitter（不切，独立块）
    - paragraph → RecursiveSplitter（按标点递归切）
    """

    @abstractmethod
    def split(self, elements: List[ContentElement]) -> List[Chunk]:
        """将元素列表切分为 Chunk 列表。"""
        ...
