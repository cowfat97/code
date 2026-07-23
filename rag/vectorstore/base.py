"""向量存储基础：SearchResult + VectorStore 抽象接口。"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Dict, List


@dataclass
class SearchResult:
    """单条检索结果。

    检索命中后，通过 chunk_id 回查父块：
        result → chunk_id → Chunk.parent_id → 父块原文 → LLM 上下文
    """
    chunk_id: str
    score: float
    content: str = ""
    metadata: dict = field(default_factory=dict)


class VectorStore(ABC):
    """向量库 — 抽象接口。

    一种向量库一个子类。当前实现 Milvus，后续可扩展 Pinecone、Qdrant 等。

    核心方法:
        insert     — 写入向量（含稠密+稀疏）
        search     — 稠密向量检索
        hybrid_search — 稠密+稀疏混合检索
        delete_by_filter — 按条件删除
    """

    @abstractmethod
    def insert(self, embeddings: List, collection_name: str = "default") -> List[str]:
        """批量写入向量。返回写入的 ID 列表。"""
        ...

    @abstractmethod
    def search(self, query_embedding, collection_name: str = "default",
               top_k: int = 20, filter_expr: str | None = None) -> List[SearchResult]:
        """稠密向量 top-K 检索。"""
        ...

    @abstractmethod
    def hybrid_search(self, query_embedding, collection_name: str = "default",
                      top_k: int = 20, dense_weight: float = 1.0,
                      sparse_weight: float = 0.7,
                      filter_expr: str | None = None) -> List[SearchResult]:
        """稠密+稀疏混合检索。"""
        ...

    @abstractmethod
    def delete_by_filter(self, filter_expr: str,
                         collection_name: str = "default") -> int:
        """按条件删除。返回删除的行数。"""
        ...

    @abstractmethod
    def collection_exists(self, collection_name: str) -> bool:
        ...

    @abstractmethod
    def drop_collection(self, collection_name: str) -> None:
        ...
