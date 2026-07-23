"""文档切分模块 — 策略模式。

SplitPipeline 负责分发：接收 Loader 产出的 ContentElement 列表，
按 doc_type 选择对应的切分策略，输出 Chunk 列表。

切分策略：
    heading   → HeadingSplitter（标题做切分边界，保留层级）
    paragraph → RecursiveSplitter（按中英文标点递归切分）
    table_row → NoOpSplitter（行内不切）
    image     → NoOpSplitter（独立块）

父子块：
    ParentChildPipeline 两遍切分 — 父块做大语义单元（LLM 上下文），
    子块做精准匹配（向量库索引），通过 parent_id 关联。

扩展新策略：
    ① 实现 TextSplitter 子类 ② 注册到 Pipeline。
"""

from .base import Chunk, TextSplitter
from .strategies import (
    HeadingSplitter,
    MarkdownSplitter,
    NoOpSplitter,
    RecursiveSplitter,
)
from .pipeline import (
    SplitPipeline,
    ParentChildPipeline,
    create_default_pipeline,
    create_markdown_pipeline,
    create_parent_child,
)

__all__ = [
    # 数据结构
    "Chunk",
    # 抽象
    "TextSplitter",
    # 策略
    "HeadingSplitter",
    "MarkdownSplitter",
    "NoOpSplitter",
    "RecursiveSplitter",
    # 编排
    "SplitPipeline",
    "ParentChildPipeline",
    # 工厂
    "create_default_pipeline",
    "create_markdown_pipeline",
    "create_parent_child",
]
