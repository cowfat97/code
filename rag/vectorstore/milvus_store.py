"""Milvus 向量存储实现：稠密+稀疏双 Collection，支持混合检索。"""

from typing import Dict, List

from embedding.base import Embedding

from .base import SearchResult, VectorStore


# Milvus 稀疏向量维度（BGE-M3 词典大小 ≈ 250000）
# 稀疏向量存的是 {token_id: weight}，Milvus 要求声明 max sparse_dim
SPARSE_DIM = 250000


class MilvusStore(VectorStore):
    """Milvus 向量库。

    双 Collection 设计：
    - {name}_dense  — 稠密向量（1024d, IVF_FLAT, IP 度量）
    - {name}_sparse — 稀疏向量（SPARSE_INVERTED_INDEX）

    使用方式:
        store = MilvusStore(host="localhost", port="19530")
        store.create_collection("credit_card_kb", dim=1024)
        store.insert(embeddings, "credit_card_kb")
        results = store.hybrid_search(query_emb, "credit_card_kb")
    """

    def __init__(self, host: str = "localhost", port: str = "19530",
                 user: str = "", password: str = "", db_name: str = "default"):
        self.host = host
        self.port = port
        self.user = user
        self.password = password
        self.db_name = db_name
        self._connected = False
        self._collections: Dict[str, bool] = {}  # {name: created}

    # ── 连接管理 ──────────────────────────

    def _connect(self):
        if self._connected:
            return
        from pymilvus import connections
        connections.connect(
            alias="default",
            host=self.host,
            port=self.port,
            user=self.user,
            password=self.password,
            db_name=self.db_name,
        )
        self._connected = True

    # ── Collection 管理 ────────────────────

    def create_collection(self, collection_name: str, dim: int = 1024) -> None:
        """创建稠密+稀疏双 Collection。"""
        self._connect()
        from pymilvus import (
            Collection, FieldSchema, CollectionSchema, DataType,
        )

        # ── 稠密 Collection ──
        dense_name = f"{collection_name}_dense"
        if not self.collection_exists(dense_name):
            dense_fields = [
                FieldSchema(name="id", dtype=DataType.VARCHAR,
                            max_length=128, is_primary=True),
                FieldSchema(name="dense_vector", dtype=DataType.FLOAT_VECTOR, dim=dim),
                FieldSchema(name="chunk_id", dtype=DataType.VARCHAR, max_length=128),
                FieldSchema(name="content", dtype=DataType.VARCHAR, max_length=65535),
                FieldSchema(name="source", dtype=DataType.VARCHAR, max_length=512),
            ]
            dense_schema = CollectionSchema(dense_fields, "稠密向量")
            dense_col = Collection(dense_name, dense_schema)

            # IVF_FLAT: nlist=128，5000 份文档规模平衡精度和速度
            dense_index_params = {
                "metric_type": "IP",
                "index_type": "IVF_FLAT",
                "params": {"nlist": 128},
            }
            dense_col.create_index("dense_vector", dense_index_params)
            dense_col.load()

        # ── 稀疏 Collection ──
        sparse_name = f"{collection_name}_sparse"
        if not self.collection_exists(sparse_name):
            sparse_fields = [
                FieldSchema(name="id", dtype=DataType.VARCHAR,
                            max_length=128, is_primary=True),
                FieldSchema(name="sparse_vector", dtype=DataType.SPARSE_FLOAT_VECTOR),
                FieldSchema(name="chunk_id", dtype=DataType.VARCHAR, max_length=128),
            ]
            sparse_schema = CollectionSchema(sparse_fields, "稀疏向量")
            sparse_col = Collection(sparse_name, sparse_schema)

            sparse_index_params = {
                "metric_type": "IP",
                "index_type": "SPARSE_INVERTED_INDEX",
                "params": {"drop_ratio_build": 0.2},
            }
            sparse_col.create_index("sparse_vector", sparse_index_params)
            sparse_col.load()

        self._collections[collection_name] = True

    def collection_exists(self, collection_name: str) -> bool:
        if collection_name in self._collections:
            return True
        self._connect()
        from pymilvus import utility
        return utility.has_collection(collection_name)

    def drop_collection(self, collection_name: str) -> None:
        self._connect()
        from pymilvus import Collection
        for suffix in ("_dense", "_sparse"):
            full_name = f"{collection_name}{suffix}"
            col = Collection(full_name)
            col.release()
            col.drop()
        self._collections.pop(collection_name, None)

    # ── 写入 ──────────────────────────────

    def insert(self, embeddings: List[Embedding],
               collection_name: str = "default") -> List[str]:
        self._connect()
        from pymilvus import Collection

        ids: List[str] = []
        dense_rows: List[dict] = []
        sparse_rows: List[dict] = []

        for emb in embeddings:
            row_id = emb.chunk_id or self._new_id()
            ids.append(row_id)

            # 稠密行
            dense_rows.append({
                "id": row_id,
                "dense_vector": emb.dense,
                "chunk_id": emb.chunk_id,
                "content": emb.metadata.get("parent_content", ""),
                "source": emb.metadata.get("file_path", ""),
            })

            # 稀疏行（仅当 emb 有稀疏向量时）
            if emb.sparse:
                sparse_rows.append({
                    "id": row_id,
                    "sparse_vector": emb.sparse,
                    "chunk_id": emb.chunk_id,
                })

        # 写入稠密 Collection
        dense_col = Collection(f"{collection_name}_dense")
        if dense_rows:
            dense_col.insert(dense_rows)
            dense_col.flush()

        # 写入稀疏 Collection
        if sparse_rows:
            sparse_col = Collection(f"{collection_name}_sparse")
            sparse_col.insert(sparse_rows)
            sparse_col.flush()

        return ids

    # ── 检索 ──────────────────────────────

    def search(self, query_embedding: Embedding,
               collection_name: str = "default", top_k: int = 20,
               filter_expr: str | None = None) -> List[SearchResult]:
        self._connect()
        from pymilvus import Collection

        dense_col = Collection(f"{collection_name}_dense")
        search_params = {"metric_type": "IP", "params": {"nprobe": 10}}
        results = dense_col.search(
            data=[query_embedding.dense],
            anns_field="dense_vector",
            param=search_params,
            limit=top_k,
            expr=filter_expr,
            output_fields=["chunk_id", "content", "source"],
        )
        return self._parse_results(results)

    def hybrid_search(self, query_embedding: Embedding,
                      collection_name: str = "default", top_k: int = 20,
                      dense_weight: float = 1.0, sparse_weight: float = 0.7,
                      filter_expr: str | None = None) -> List[SearchResult]:
        self._connect()
        from pymilvus import Collection, WeightedRanker

        dense_col = Collection(f"{collection_name}_dense")

        # 准备两路检索参数
        dense_param = {"metric_type": "IP", "params": {"nprobe": 10}}
        sparse_param = {"metric_type": "IP"}

        # 没有稀疏向量 → 只用稠密
        if query_embedding.sparse is None:
            return self.search(query_embedding, collection_name, top_k, filter_expr)

        # 混合检索
        results = dense_col.hybrid_search(
            reqs=[
                # 稠密路
                {
                    "collection_name": f"{collection_name}_dense",
                    "data": [query_embedding.dense],
                    "anns_field": "dense_vector",
                    "param": dense_param,
                    "limit": top_k,
                    "expr": filter_expr,
                    "output_fields": ["chunk_id", "content", "source"],
                },
                # 稀疏路
                {
                    "collection_name": f"{collection_name}_sparse",
                    "data": [query_embedding.sparse],
                    "anns_field": "sparse_vector",
                    "param": sparse_param,
                    "limit": top_k,
                    "expr": filter_expr,
                    "output_fields": ["chunk_id"],
                },
            ],
            ranker=WeightedRanker(dense_weight, sparse_weight),
            limit=top_k,
        )
        return self._parse_results(results)

    # ── 删除 ──────────────────────────────

    def delete_by_filter(self, filter_expr: str,
                         collection_name: str = "default") -> int:
        self._connect()
        from pymilvus import Collection

        total = 0
        for suffix in ("_dense", "_sparse"):
            col = Collection(f"{collection_name}{suffix}")
            deleted = col.delete(filter_expr)
            total += deleted.get("delete_count", 0) if isinstance(deleted, dict) else 0
        return total

    # ── 内部 ──────────────────────────────

    def _parse_results(self, results) -> List[SearchResult]:
        """将 pymilvus 检索结果转为 SearchResult 列表。"""
        output: List[SearchResult] = []
        for hits in results:
            for hit in hits:
                entity = hit.entity
                output.append(SearchResult(
                    chunk_id=entity.get("chunk_id", ""),
                    score=hit.score,
                    content=entity.get("content", ""),
                    metadata={"source": entity.get("source", "")},
                ))
        return output

    def _new_id(self) -> str:
        import uuid
        return uuid.uuid4().hex[:16]
