"""向量存储模块 — 策略模式。

管理稠密+稀疏向量的写入、检索、删除。

双 Collection 设计:
    {name}_dense  — 稠密向量（1024d, IVF_FLAT, IP 度量）
    {name}_sparse — 稀疏向量（SPARSE_INVERTED_INDEX）

混合检索:
    WeightedRanker(稠密权重, 稀疏权重) 融合两路结果

使用方式:
    from vectorstore import MilvusStore

    store = MilvusStore(host="192.168.3.36", port="19530")
    store.create_collection("credit_card_kb", dim=1024)
    store.insert(embeddings, "credit_card_kb")
    results = store.hybrid_search(query_emb, "credit_card_kb")
"""

from .base import SearchResult, VectorStore
from .milvus_store import MilvusStore

__all__ = [
    "SearchResult",
    "VectorStore",
    "MilvusStore",
]
