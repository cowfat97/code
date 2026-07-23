""".docx — python-docx 解析 XML，段落/表格/内嵌图分类标注
.doc  — antiword → LibreOffice 两级 fallback
"""

import os
import subprocess
import tempfile
from typing import List

import numpy as np
from PIL import Image
from io import BytesIO

from .base import ContentElement, DocumentLoader
from .ocr import ocr_image

HEADING_KEYWORDS = {
    "heading", "heading 1", "heading 2", "heading 3",
    "标题", "标题 1", "标题 2", "标题 3",
    "toc", "toc 1", "toc 2", "toc 3",
}


class DocxLoader(DocumentLoader):
    """.docx 加载器：按文档 XML 顺序遍历段落+表格+内嵌图。"""

    @property
    def supported_extensions(self) -> List[str]:
        return [".docx"]

    def load(self, file_path: str) -> List[ContentElement]:
        try:
            from docx import Document as DocxDocument
            from docx.document import Document as _DocumentType
            from docx.table import _Cell, Table
            from docx.oxml.table import CT_Tbl
            from docx.oxml.text.paragraph import CT_P
            from docx.text.paragraph import Paragraph
            from docx import ImagePart
        except ImportError:
            raise ImportError("请安装 python-docx: pip install python-docx")

        doc = DocxDocument(file_path)
        elements: List[ContentElement] = []
        file_name = os.path.basename(file_path)

        for block in self._iter_blocks(doc):
            if isinstance(block, Paragraph):
                text = block.text.strip()
                if not text:
                    continue

                style_name = (block.style.name if block.style else "").lower()
                is_heading = style_name in HEADING_KEYWORDS or any(
                    h in style_name for h in HEADING_KEYWORDS
                )
                doc_type = "heading" if is_heading else "paragraph"

                elements.append(ContentElement(
                    content=text,
                    doc_type=doc_type,
                    metadata={"file_path": file_path, "file_name": file_name},
                ))

                # 段落内嵌图片
                images = block._element.xpath('.//pic:pic')
                for img in images:
                    for img_id in img.xpath('.//a:blip/@r:embed'):
                        part = doc.part.related_parts.get(img_id)
                        if isinstance(part, ImagePart):
                            pil_img = Image.open(BytesIO(part._blob))
                            ocr_text = ocr_image(np.array(pil_img))
                            if ocr_text:
                                elements.append(ContentElement(
                                    content=ocr_text,
                                    doc_type="image",
                                    metadata={"file_path": file_path, "file_name": file_name},
                                ))

            elif isinstance(block, Table):
                for row in block.rows:
                    cells_text = []
                    for cell in row.cells:
                        parts = [p.text.strip() for p in cell.paragraphs if p.text.strip()]
                        cells_text.append(" ".join(parts))
                    row_text = " | ".join(cells_text)
                    if row_text.strip():
                        elements.append(ContentElement(
                            content=row_text,
                            doc_type="table_row",
                            metadata={"file_path": file_path, "file_name": file_name},
                        ))

        return elements

    def _iter_blocks(self, parent):
        """按文档原始顺序 yield 段落和表格。"""
        from docx.document import Document as _DocumentType
        from docx.table import _Cell
        from docx.oxml.table import CT_Tbl
        from docx.oxml.text.paragraph import CT_P
        from docx.text.paragraph import Paragraph
        from docx.table import Table

        if isinstance(parent, _DocumentType):
            parent_elm = parent.element.body
        elif isinstance(parent, _Cell):
            parent_elm = parent._tc
        else:
            raise ValueError(f"不支持的类型: {type(parent)}")

        for child in parent_elm.iterchildren():
            if isinstance(child, CT_P):
                yield Paragraph(child, parent)
            elif isinstance(child, CT_Tbl):
                yield Table(child, parent)


class DocLoader(DocumentLoader):
    """.doc 旧格式加载器：antiword → LibreOffice 两级 fallback。"""

    @property
    def supported_extensions(self) -> List[str]:
        return [".doc"]

    def load(self, file_path: str) -> List[ContentElement]:
        # 第一级：antiword（快速，纯文本）
        text = self._try_antiword(file_path)
        if text:
            paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
            file_name = os.path.basename(file_path)
            return [ContentElement(
                content=p,
                doc_type="paragraph",
                metadata={"file_path": file_path, "file_name": file_name},
            ) for p in paragraphs]

        # 第二级：LibreOffice 转 .docx 后复用 DocxLoader
        return self._convert_and_load(file_path)

    def _try_antiword(self, file_path: str) -> str:
        try:
            result = subprocess.run(
                ["antiword", file_path],
                capture_output=True, text=True, timeout=30,
            )
            if result.returncode == 0:
                return result.stdout.strip()
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass
        return ""

    def _convert_and_load(self, file_path: str) -> List[ContentElement]:
        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                subprocess.run(
                    ["libreoffice", "--headless", "--convert-to", "docx",
                     "--outdir", tmpdir, file_path],
                    capture_output=True, timeout=60,
                )
                docx_files = [f for f in os.listdir(tmpdir) if f.endswith(".docx")]
                if docx_files:
                    return DocxLoader().load(os.path.join(tmpdir, docx_files[0]))
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass

        raise RuntimeError(
            f"无法解析 .doc 文件: {file_path}。"
            "请安装 antiword (brew install antiword) 或 LibreOffice。"
        )
