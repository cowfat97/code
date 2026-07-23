"""文本向量化模块 — 策略模式。

将 splitting 模块产出的 Chunk 转为向量，支持稠密+稀疏双输出。

模块结构:
    base.py       — Embedding 数据结构 + Embedder 抽象接口
    bge_m3.py     — BGE-M3 实现（单模型双输出：稠密 1024d + 稀疏词权重）
    pipeline.py   — 批量编码编排 + 去重缓存 + 父子块专用流程

文本流:
    Chunk(splitting) → EmbeddingPipeline → Embedding → Milvus

使用方式:
    from embedding import BGEM3Embedder, EmbeddingPipeline

    embedder = BGEM3Embedder("BAAI/bge-m3")
    pipeline = EmbeddingPipeline(embedder)
    embeddings = pipeline.embed_chunks(chunks)
    query_vec = pipeline.embed_query("信用卡年费怎么免")
"""

from .base import Embedding, Embedder
from .bge_m3 import BGEM3Embedder
from .pipeline import (
    EmbeddingPipeline,
    ParentChildEmbeddingPipeline,
)

__all__ = [
    "Embedding",
    "Embedder",
    "BGEM3Embedder",
    "EmbeddingPipeline",
    "ParentChildEmbeddingPipeline",
]
