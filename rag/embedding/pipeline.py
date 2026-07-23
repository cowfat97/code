"""批量向量化编排：Chunk → Embedding，含去重缓存。"""

import hashlib
from typing import Dict, List

from splitting.base import Chunk

from .base import Embedding, Embedder


class EmbeddingPipeline:
    """将 Chunk 列表批量转为 Embedding 列表。

    缓存策略: 按 content hash 去重——相同文本不重复编码。
    这对于父子块场景特别有用（父块和子块可能共享部分内容）。

    使用方式:
        pipeline = EmbeddingPipeline(BGEM3Embedder())
        embeddings = pipeline.embed_chunks(chunks)
    """

    def __init__(self, embedder: Embedder, cache_enabled: bool = True):
        self._embedder = embedder
        self._cache: Dict[str, Embedding] = {}
        self._cache_enabled = cache_enabled

    @property
    def embedder(self) -> Embedder:
        return self._embedder

    @property
    def dim(self) -> int:
        return self._embedder.dim

    @property
    def has_sparse(self) -> bool:
        return self._embedder.has_sparse

    def embed_chunks(self, chunks: List[Chunk]) -> List[Embedding]:
        """批量编码 Chunk，返回等长 Embedding 列表。"""
        if not chunks:
            return []

        # 计算去重映射
        unique_texts, index_map = self._deduplicate(chunks)

        # 批量编码唯一文本
        unique_embeddings = self._embedder.embed(unique_texts)

        # 建立缓存
        if self._cache_enabled:
            for text, emb in zip(unique_texts, unique_embeddings):
                key = self._hash(text)
                self._cache[key] = emb

        # 还原到原始顺序，回填 chunk_id
        result: List[Embedding] = []
        for i, chunk in enumerate(chunks):
            emb = unique_embeddings[index_map[i]]
            result.append(Embedding(
                dense=emb.dense,
                sparse=emb.sparse,
                chunk_id=chunk.chunk_id,
                metadata={
                    **chunk.metadata,
                    "content_hash": self._hash(chunk.content),
                },
            ))

        return result

    def embed_query(self, query: str) -> Embedding:
        key = self._hash(query)
        if self._cache_enabled and key in self._cache:
            return self._cache[key]
        emb = self._embedder.embed_query(query)
        if self._cache_enabled:
            self._cache[key] = emb
        return emb

    def _deduplicate(self, chunks: List[Chunk]) -> tuple[List[str], List[int]]:
        """对 chunks 按 content hash 去重。

        Returns:
            (unique_texts, index_map)
            index_map[i] = unique_texts 中第 i 个 chunk 对应的索引
        """
        seen: Dict[str, int] = {}
        unique_texts: List[str] = []
        index_map: List[int] = []

        for chunk in chunks:
            text = chunk.content
            key = self._hash(text)

            if self._cache_enabled and key in self._cache:
                # 命中缓存 → 不重复编码，但仍需要在 unique 列表中占位
                if key not in seen:
                    seen[key] = len(unique_texts)
                    unique_texts.append(text)  # 会被缓存跳过，但占位
                index_map.append(seen[key])
                continue

            if key in seen:
                index_map.append(seen[key])
            else:
                seen[key] = len(unique_texts)
                unique_texts.append(text)
                index_map.append(seen[key])

        return unique_texts, index_map

    def _hash(self, text: str) -> str:
        return hashlib.md5(text.encode("utf-8")).hexdigest()

    def clear_cache(self) -> None:
        self._cache.clear()


class ParentChildEmbeddingPipeline:
    """父子块场景专用：父块入 LLM 上下文，子块入向量索引。

    只对子块做向量化（检索是子块命中），父块保留原文（LLM 用）。

    使用方式:
        pipeline = ParentChildEmbeddingPipeline(BGEM3Embedder())
        parent_texts, child_embeddings = pipeline.embed(parents, children)
        # → child_embeddings 入 Milvus
        # → parent_texts 在检索命中后通过 parent_id 回填到 LLM 上下文
    """

    def __init__(self, embedder: Embedder):
        self._pipeline = EmbeddingPipeline(embedder)

    def embed(self, parents: List[Chunk],
              children: List[Chunk]) -> tuple[List[Chunk], List[Embedding]]:
        """只对子块向量化。

        Returns:
            (parents, child_embeddings)
        """
        child_embeddings = self._pipeline.embed_chunks(children)
        return parents, child_embeddings
