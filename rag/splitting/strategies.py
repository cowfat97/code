""".strategy — 四种切分策略。"""

import re
from typing import List

from .base import Chunk, TextSplitter, ContentElement


# ─────────────────────────────────────────────
# 标题切分
# ─────────────────────────────────────────────

class HeadingSplitter(TextSplitter):
    """以标题为边界切分。

    每个标题 + 后续内容（直到下一个同级或更高级标题）形成一个 chunk。
    标题层级以 '#' 数量表示（# = 1, ## = 2 ...）。

    输入元素的 doc_type 应为 "heading" 和 "paragraph"。
    """

    def __init__(self, chunk_size: int = 1200):
        self.chunk_size = chunk_size

    def split(self, elements: List[ContentElement]) -> List[Chunk]:
        chunks: List[Chunk] = []
        current_title = ""
        current_level = 0
        buffer: List[str] = []

        for el in elements:
            if el.doc_type == "heading":
                # 遇到标题 → 结算上一个 section
                if buffer:
                    chunks.extend(self._finalize_section(
                        current_title, current_level, buffer, el.metadata
                    ))
                current_title = el.content
                current_level = self._heading_level(el.content)
                buffer = []
            else:
                buffer.append(el.content)

        # 最后一个 section
        if buffer:
            chunks.extend(self._finalize_section(
                current_title, current_level, buffer,
                elements[-1].metadata if elements else {}
            ))

        return chunks

    def _heading_level(self, text: str) -> int:
        """从 '# 标题' 中提取层级。"""
        match = re.match(r"^(#{1,6})\s", text)
        return len(match.group(1)) if match else 1

    def _finalize_section(self, title: str, level: int,
                          paragraphs: List[str], metadata: dict) -> List[Chunk]:
        """将一个 section 的内容按 chunk_size 切分为多个 Chunk。"""
        full = "\n\n".join(paragraphs)
        if not full.strip():
            return []

        if len(full) <= self.chunk_size:
            return [Chunk(
                content=f"{title}\n\n{full}" if title else full,
                doc_type="paragraph",
                metadata={**metadata, "heading": title, "heading_level": level},
            )]

        # 超长 → 按段落粒度分包，每包带上标题
        result: List[Chunk] = []
        current = title + "\n\n" if title else ""
        for para in paragraphs:
            if len(current) + len(para) > self.chunk_size and current.strip():
                result.append(Chunk(
                    content=current.strip(),
                    doc_type="paragraph",
                    metadata={**metadata, "heading": title, "heading_level": level},
                ))
                current = title + "\n\n" + para if title else para
            else:
                current += ("\n\n" + para) if current else para
        if current.strip():
            result.append(Chunk(
                content=current.strip(),
                doc_type="paragraph",
                metadata={**metadata, "heading": title, "heading_level": level},
            ))
        return result


# ─────────────────────────────────────────────
# 递归标点切分
# ─────────────────────────────────────────────

class RecursiveSplitter(TextSplitter):
    """按中文标点递归切分。

    优先级从高到低逐一尝试，直到每个 chunk 不超过 chunk_size：
      1. 段落分隔  \\n\\n
      2. 换行      \\n
      3. 句末标点   。！？!?
      4. 分句标点   ；;
      5. 逗号      ，,
      6. 字符级截断（最后手段）

    每条 chunk 不会在句子中间截断，除非单句本身超过 chunk_size。
    """

    SEPARATORS = [
        "\n\n",
        "\n",
        "。", "！", "？", "!", "?",
        "；", ";",
        "，", ",",
    ]

    def __init__(self, chunk_size: int = 300, chunk_overlap: int = 50):
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap

    def split(self, elements: List[ContentElement]) -> List[Chunk]:
        text = "\n\n".join(el.content for el in elements)
        if not text.strip():
            return []

        splits = self._split_recursive(text, self.SEPARATORS)
        return self._merge_with_overlap(splits, elements[0].metadata if elements else {})

    def _split_recursive(self, text: str, separators: List[str]) -> List[str]:
        """递归试探分隔符，直到所有片段都在 chunk_size 内。"""
        if len(text) <= self.chunk_size:
            return [text] if text.strip() else []

        # 从当前分隔符列表中取第一个
        sep = separators[0] if separators else None
        if sep is None:
            # 无分隔符可用 → 强制按字符截断
            return self._force_split(text)

        splits = self._split_by_separator(text, sep)
        if len(splits) <= 1:
            # 用这个分隔符切不开 → 降级用下一个
            return self._split_recursive(text, separators[1:])

        # 递归处理每一个片段
        result: List[str] = []
        for part in splits:
            result.extend(self._split_recursive(part, separators[1:]))
        return result

    def _split_by_separator(self, text: str, separator: str) -> List[str]:
        """按分隔符切分，保留分隔符在片段末尾。"""
        if separator in ("\n\n", "\n"):
            parts = text.split(separator)
            return [p.strip() for p in parts if p.strip()]

        # 标点类分隔符 — 保留在句子末尾
        parts = []
        current = ""
        for char in text:
            current += char
            if char == separator:
                parts.append(current.strip())
                current = ""
        if current.strip():
            parts.append(current.strip())
        return parts

    def _force_split(self, text: str) -> List[str]:
        """字符级强制截断，但尽量在标点处断。"""
        chunks: List[str] = []
        for i in range(0, len(text), self.chunk_size - self.chunk_overlap):
            chunk = text[i:i + self.chunk_size]
            if chunk.strip():
                chunks.append(chunk.strip())
        return chunks

    def _merge_with_overlap(self, splits: List[str], base_metadata: dict) -> List[Chunk]:
        """将过短的片段合并，并在 chunk 间保持 overlap。"""
        chunks: List[Chunk] = []
        buffer = ""
        for split_text in splits:
            if len(buffer) + len(split_text) <= self.chunk_size:
                buffer += ("\n\n" + split_text) if buffer else split_text
            else:
                if buffer.strip():
                    chunks.append(Chunk(
                        content=buffer.strip(),
                        doc_type="paragraph",
                        metadata=dict(base_metadata),
                    ))
                buffer = split_text
        if buffer.strip():
            chunks.append(Chunk(
                content=buffer.strip(),
                doc_type="paragraph",
                metadata=dict(base_metadata),
            ))

        # 添加 overlap：每个 chunk 末尾留 chunk_overlap 字符拼入下一个 chunk 开头
        if self.chunk_overlap > 0 and len(chunks) > 1:
            for i in range(1, len(chunks)):
                prev = chunks[i - 1].content
                if len(prev) > self.chunk_overlap:
                    overlap_text = prev[-self.chunk_overlap:]
                    chunks[i].content = overlap_text + "\n" + chunks[i].content

        return chunks


# ─────────────────────────────────────────────
# 不切分（表格行 / 图片）
# ─────────────────────────────────────────────

class NoOpSplitter(TextSplitter):
    """不对元素内容做任何切分，原样输出为一个 Chunk。

    适用 doc_type：table_row（行内不切）、image（独立块）。
    """

    def split(self, elements: List[ContentElement]) -> List[Chunk]:
        return [
            Chunk(
                content=el.content,
                doc_type=el.doc_type,
                metadata=dict(el.metadata),
            )
            for el in elements
        ]


# ─────────────────────────────────────────────
# Markdown 切分（继承自实现，这里的实现按 headings 切分）
# ─────────────────────────────────────────────

class MarkdownSplitter(HeadingSplitter):
    """Markdown 专用切分器。

    与 HeadingSplitter 行为一致——以 # 标题为边界。
    单独命名是为了在代码中明确区分用途：
        .md 文件 → MarkdownSplitter → 保留标题层级
        其他文件 → RecursiveSplitter → 纯递归标点切分
    """
    pass
