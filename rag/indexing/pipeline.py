"""索引编排：Chunk → Embed → Insert 一条流水线。"""

from typing import List

from embedding.base import Embedding
from embedding.pipeline import EmbeddingPipeline, ParentChildEmbeddingPipeline
from splitting.base import Chunk
from splitting.pipeline import SplitPipeline, ParentChildPipeline
from vectorstore.base import SearchResult, VectorStore


class IndexPipeline:
    """单层索引编排：切分 → 向量化 → 写入向量库。

    使用方式:
        pipeline = IndexPipeline(splitter, embedder, store)
        pipeline.index(elements, collection_name="kb")
    """

    def __init__(self, splitter: SplitPipeline,
                 embedder: EmbeddingPipeline,
                 store: VectorStore):
        self._splitter = splitter
        self._embedder = embedder
        self._store = store

    def index(self, elements: list, collection_name: str = "default",
              rebuild: bool = False) -> int:
        """执行完整索引流程。

        Returns:
            写入的向量数量
        """
        if rebuild and self._store.collection_exists(
            f"{collection_name}_dense"
        ):
            self._store.drop_collection(collection_name)

        if not self._store.collection_exists(f"{collection_name}_dense"):
            self._store.create_collection(
                collection_name, dim=self._embedder.dim
            )

        chunks = self._splitter.split(elements)
        embeddings = self._embedder.embed_chunks(chunks)
        self._store.insert(embeddings, collection_name)

        return len(embeddings)

    def search(self, query: str, collection_name: str = "default",
               top_k: int = 20) -> List[SearchResult]:
        query_emb = self._embedder.embed_query(query)
        if self._embedder.has_sparse:
            return self._store.hybrid_search(
                query_emb, collection_name, top_k
            )
        return self._store.search(query_emb, collection_name, top_k)


class ParentChildIndexPipeline:
    """父子块索引编排：切分 → 父子关联 → 子块向量化 → 写入。

    父块不入向量库，原文通过子块的 parent_content 字段在检索命中时回填。

    使用方式:
        pipeline = ParentChildIndexPipeline(parent_child_splitter,
                                             parent_child_embedder, store)
        pipeline.index(elements, collection_name="kb")
    """

    def __init__(self, splitter: ParentChildPipeline,
                 embedder: ParentChildEmbeddingPipeline,
                 store: VectorStore):
        self._splitter = splitter
        self._embedder = embedder
        self._store = store

    def index(self, elements: list, collection_name: str = "default",
              is_markdown: bool = False, rebuild: bool = False) -> tuple[
        List[Chunk], List[Embedding]
    ]:
        """父子块索引。父块不入库，子块入 Milvus。"""
        if rebuild and self._store.collection_exists(
            f"{collection_name}_dense"
        ):
            self._store.drop_collection(collection_name)

        if not self._store.collection_exists(f"{collection_name}_dense"):
            self._store.create_collection(
                collection_name, dim=self._embedder.dim
            )

        parents, children = self._splitter.split(elements, is_markdown)
        _, child_embeddings = self._embedder.embed(parents, children)
        self._store.insert(child_embeddings, collection_name)

        return parents, child_embeddings

    def search(self, query: str, collection_name: str = "default",
               top_k: int = 20,
               filter_expr: str | None = None) -> List[SearchResult]:
        query_emb = self._embedder._pipeline.embed_query(query)
        if self._embedder.has_sparse:
            return self._store.hybrid_search(
                query_emb, collection_name, top_k,
                filter_expr=filter_expr,
            )
        return self._store.search(
            query_emb, collection_name, top_k,
            filter_expr=filter_expr,
        )
