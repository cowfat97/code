"""Embedding 模块基础：向量数据结构 + Embedder 抽象接口。"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List


@dataclass
class Embedding:
    """单个 Chunk 的向量表示。

    BGE-M3 一次 forward 产出两种向量：
    - dense:  1024 维浮点向量，语义匹配
    - sparse: 词级权重字典 {token_id: weight}，关键词精确命中
    """
    dense: List[float]           # 稠密向量
    sparse: dict[int, float] | None = None  # 稀疏向量，None = 模型/模式不支持
    chunk_id: str = ""           # 回指 splitting.Chunk.chunk_id
    metadata: dict = field(default_factory=dict)


class Embedder(ABC):
    """向量化器 — 策略接口。

    一种模型一个子类。当前支持 BGE-M3（稠密+稀疏双输出），
    后续可扩展其他模型（text2vec、Jina、Cohere 等）。
    """

    @abstractmethod
    def embed(self, texts: List[str]) -> List[Embedding]:
        """将文本列表转为向量列表。"""
        ...

    @abstractmethod
    def embed_query(self, query: str) -> Embedding:
        """将单条查询文本转为向量（某些模型对 query 和 doc 使用不同编码方式）。"""
        ...

    @property
    @abstractmethod
    def dim(self) -> int:
        """稠密向量维度。"""
        ...

    @property
    @abstractmethod
    def has_sparse(self) -> bool:
        """是否产出稀疏向量。"""
        ...
