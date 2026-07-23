"""策略模式基础：抽象 Loader 接口 + 统一数据结构。"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, Literal

DocType = Literal["heading", "table_row", "image", "paragraph"]


@dataclass
class ContentElement:
    """文档解析后的最小内容单元。

    doc_type 决定下游 Splitter 的切分策略：
    - heading   → 切分边界，保留层级
    - table_row → 行内不切，保持数据完整
    - image     → 独立块，不参与切分
    - paragraph → 标准递归标点切分
    """
    content: str
    doc_type: DocType
    metadata: dict = field(default_factory=dict)


class DocumentLoader(ABC):
    """文档加载器 — 策略接口。

    每种格式实现一个子类，通过 load() 返回带 doc_type 标签的 ContentElement 列表。
    Loader 只负责提取 + 打标签，不负责切块。
    """

    @abstractmethod
    def load(self, file_path: str) -> List[ContentElement]:
        """加载文档，返回结构化元素列表。"""
        ...

    @property
    @abstractmethod
    def supported_extensions(self) -> List[str]:
        """该 Loader 支持的扩展名列表，如 ['.pdf']。"""
        ...
