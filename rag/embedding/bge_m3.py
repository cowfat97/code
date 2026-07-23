"""BGE-M3 向量化器：单模型双输出（稠密+稀疏）。"""

from typing import List

from .base import Embedding, Embedder


class BGEM3Embedder(Embedder):
    """BGE-M3 向量化器。

    一个模型一次 forward 同时产出：
    - dense:  1024 维浮点向量（CLS token 输出，IP 内积度量）
    - sparse: 词级权重字典（最后一层 sparse head 输出，每个 token 一个权重）

    使用方式:
        embedder = BGEM3Embedder("BAAI/bge-m3")
        embeddings = embedder.embed(["文本1", "文本2"])
        query_vec = embedder.embed_query("查询文本")
    """

    def __init__(self, model_name: str = "BAAI/bge-m3",
                 device: str = "cpu",
                 max_length: int = 8192):
        self.model_name = model_name
        self.device = device
        self.max_length = max_length
        self._model = None

    @property
    def dim(self) -> int:
        return 1024

    @property
    def has_sparse(self) -> bool:
        return True

    def embed(self, texts: List[str]) -> List[Embedding]:
        model = self._get_model()
        output = model.encode(
            texts,
            batch_size=32,
            max_length=self.max_length,
            return_dense=True,
            return_sparse=True,
            return_colbert_vecs=False,
        )
        return [
            Embedding(
                dense=output["dense_vecs"][i].tolist(),
                sparse=self._sparse_to_dict(output["lexical_weights"][i]),
            )
            for i in range(len(texts))
        ]

    def embed_query(self, query: str) -> Embedding:
        # BGE-M3 对 query 和 doc 使用相同的编码方式，
        # 但 prompt 里加 "为这个句子生成表示以用于检索相关文章：" 可以略微提升效果
        model = self._get_model()
        output = model.encode(
            [query],
            batch_size=1,
            max_length=self.max_length,
            return_dense=True,
            return_sparse=True,
            return_colbert_vecs=False,
        )
        return Embedding(
            dense=output["dense_vecs"][0].tolist(),
            sparse=self._sparse_to_dict(output["lexical_weights"][0]),
        )

    def _sparse_to_dict(self, weights) -> dict[int, float]:
        """将 FlagEmbedding 的稀疏权重格式转为 {token_id: weight}。

        FlagEmbedding 输出的 lexical_weights 可能是：
        - dict[int, float]   → 直接返回
        - list[float]        → enumerate
        - scipy.sparse matrix → 转 dict
        """
        if isinstance(weights, dict):
            return {int(k): float(v) for k, v in weights.items()}
        if hasattr(weights, "todok"):
            # scipy.sparse dok_matrix
            return {int(k): float(v) for k, v in weights.todok().items()}
        if hasattr(weights, "toarray"):
            arr = weights.toarray().flatten()
            return {i: float(v) for i, v in enumerate(arr) if v != 0}
        # 兜底：enumerate
        return {i: float(w) for i, w in enumerate(weights) if w != 0}

    def _get_model(self):
        if self._model is None:
            from FlagEmbedding import BGEM3FlagModel
            self._model = BGEM3FlagModel(
                self.model_name,
                use_fp16=self.device != "cpu",
                device=self.device,
            )
        return self._model
