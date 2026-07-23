""".txt — chardet 编码检测 → 全文 paragraph
.md  — 按标题层级标注 heading，其余 paragraph
"""

import os
import re
from typing import List

from .base import ContentElement, DocumentLoader


class TxtLoader(DocumentLoader):
    """纯文本加载器，chardet 自动检测编码。"""

    @property
    def supported_extensions(self) -> List[str]:
        return [".txt"]

    def load(self, file_path: str) -> List[ContentElement]:
        try:
            import chardet
            with open(file_path, "rb") as f:
                raw = f.read()
            encoding = chardet.detect(raw)["encoding"] or "utf-8"
            text = raw.decode(encoding, errors="replace")
        except ImportError:
            with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                text = f.read()

        if not text.strip():
            return []

        return [ContentElement(
            content=text,
            doc_type="paragraph",
            metadata={"file_path": file_path, "file_name": os.path.basename(file_path)},
        )]


class MdLoader(DocumentLoader):
    """Markdown 加载器，利用 # 标记做结构化标注。"""

    @property
    def supported_extensions(self) -> List[str]:
        return [".md"]

    def load(self, file_path: str) -> List[ContentElement]:
        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            text = f.read()

        if not text.strip():
            return []

        elements: List[ContentElement] = []
        blocks = re.split(r"\n\n+", text)
        heading_pattern = re.compile(r"^(#{1,6})\s+(.+)$", re.MULTILINE)
        file_name = os.path.basename(file_path)

        for block in blocks:
            block = block.strip()
            if not block:
                continue

            m = heading_pattern.match(block)
            if m:
                elements.append(ContentElement(
                    content=block,
                    doc_type="heading",
                    metadata={
                        "file_path": file_path,
                        "file_name": file_name,
                        "heading_level": len(m.group(1)),
                    },
                ))
            else:
                elements.append(ContentElement(
                    content=block,
                    doc_type="paragraph",
                    metadata={"file_path": file_path, "file_name": file_name},
                ))

        return elements
