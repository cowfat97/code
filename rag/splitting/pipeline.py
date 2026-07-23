"""切分编排：按区域分发策略 + 父子块两遍切分。"""

from typing import Dict, List

from .base import Chunk, TextSplitter, ContentElement, DocType
from .strategies import (
    HeadingSplitter,
    MarkdownSplitter,
    NoOpSplitter,
    RecursiveSplitter,
)

# heading 和 paragraph 属于同一"文本区域"——需要交插处理，
# 标题分割器需要同时看到 heading 和 paragraph 才能正确建 section
TEXT_TYPES: set[DocType] = {"heading", "paragraph"}


class SplitPipeline:
    """切分编排器。

    按"区域"分组，而非按 doc_type：
    - heading + paragraph → 同属文本区域，交插发给标题分割器
    - table_row            → NoOpSplitter，不切
    - image                → NoOpSplitter，独立块

    使用方式:
        pipeline = SplitPipeline(text_splitter=HeadingSplitter(1200))
        chunks = pipeline.split(elements)
    """

    def __init__(self, text_splitter: TextSplitter | None = None):
        self._text_splitter = text_splitter or RecursiveSplitter()
        self._splitters: Dict[DocType, TextSplitter] = {
            "table_row": NoOpSplitter(),
            "image": NoOpSplitter(),
        }

    def register(self, doc_type: DocType, splitter: TextSplitter) -> None:
        if doc_type in TEXT_TYPES:
            self._text_splitter = splitter
        else:
            self._splitters[doc_type] = splitter

    def split(self, elements: List[ContentElement]) -> List[Chunk]:
        """按文档顺序切分。heading+paragraph 合并为一个文本区域。"""
        chunks: List[Chunk] = []
        buffer: List[ContentElement] = []
        in_text_region: bool | None = None

        for el in elements:
            is_text = el.doc_type in TEXT_TYPES
            if in_text_region is None or is_text == in_text_region:
                buffer.append(el)
            else:
                chunks.extend(self._dispatch(buffer, in_text_region))
                buffer = [el]
            in_text_region = is_text

        if buffer:
            chunks.extend(self._dispatch(buffer, in_text_region))

        return chunks

    def _dispatch(self, buffer: List[ContentElement],
                  is_text_region: bool) -> List[Chunk]:
        if is_text_region:
            return self._text_splitter.split(buffer)
        # 非文本区域 → 按各自 doc_type 分发
        splitter = self._splitters.get(buffer[0].doc_type, NoOpSplitter())
        return splitter.split(buffer)


# ─────────────────────────────────────────────
# 父子块
# ─────────────────────────────────────────────

class ParentChildPipeline:
    """父子块两遍切分。

    子块入向量库索引（精准匹配），父块入 LLM 上下文（完整语义）。

    流程:
        ① elements → 父块切分（大 chunk_size）
        ② 每个父块 → 内部做子块切分（小 chunk_size）
        ③ 子块挂 parent_id + parent_content
    """

    def __init__(self, parent_size: int = 1200, child_size: int = 300,
                 overlap: int = 50):
        self.parent_size = parent_size
        self.child_size = child_size
        self.overlap = overlap

    def split(self, elements: List[ContentElement],
              is_markdown: bool = False) -> tuple[List[Chunk], List[Chunk]]:
        """一次调用产出父子两套 Chunk。

        Returns:
            (parent_chunks, child_chunks)
        """
        # ── 第一步：父块切分 ──
        parent_splitter = (
            MarkdownSplitter(self.parent_size) if is_markdown
            else RecursiveSplitter(self.parent_size, self.overlap)
        )
        parent_pipeline = SplitPipeline(text_splitter=parent_splitter)
        parent_chunks = parent_pipeline.split(elements)

        # ── 第二步：每个父块内部做子块切分 ──
        child_splitter = RecursiveSplitter(self.child_size, self.overlap)
        all_children: List[Chunk] = []
        for parent in parent_chunks:
            dummy = ContentElement(
                content=parent.content,
                doc_type="paragraph",
                metadata=dict(parent.metadata),
            )
            for child in child_splitter.split([dummy]):
                child.parent_id = parent.chunk_id
                child.metadata["parent_content"] = parent.content
                child.doc_type = parent.doc_type
                all_children.append(child)

        return parent_chunks, all_children


# ─────────────────────────────────────────────
# 工厂函数
# ─────────────────────────────────────────────

def create_default_pipeline() -> SplitPipeline:
    """标准文档切分——递归标点切分（非 Markdown）。"""
    return SplitPipeline(text_splitter=RecursiveSplitter(chunk_size=300, chunk_overlap=50))


def create_markdown_pipeline() -> SplitPipeline:
    """Markdown 文档切分——按标题边界切分，保留层级。"""
    return SplitPipeline(text_splitter=MarkdownSplitter(chunk_size=1200))


def create_parent_child(is_markdown: bool = False) -> ParentChildPipeline:
    return ParentChildPipeline(parent_size=1200, child_size=300, overlap=50)
