""".pdf — PyMuPDF 逐页提取文字层 + 扫描页大图 OCR + 跨页处理。"""

import os
import re
from difflib import SequenceMatcher
from typing import List

import numpy as np
from PIL import Image

from .base import ContentElement, DocumentLoader
from .ocr import ocr_image

PDF_IMAGE_SIZE_THRESHOLD = 0.6
HEADER_FOOTER_RATIO = 0.08      # 页面顶部/底部 8% 区域视为页眉页脚
SENTENCE_ENDS = frozenset({"。", "！", "？", ".", "!", "?", "：", ":", "；", ";"})
TABLE_HEADER_SIMILARITY = 0.7   # 表头相似度阈值，超过即视为重复表头
PAGE_NUM_PATTERN = re.compile(
    r"^\s*(第\s*\d+\s*页|Page\s*\d+|[-]?\s*\d+\s*[-]?)\s*$"
)


def _is_page_number(text: str) -> bool:
    return bool(PAGE_NUM_PATTERN.match(text.strip()))


def _similarity(a: str, b: str) -> float:
    """两段文本的相似度（0~1）。"""
    return SequenceMatcher(None, a, b).ratio()


class PdfLoader(DocumentLoader):
    """PDF 加载器：文字提取 + 图片 OCR + 跨页拼接 + 页眉页脚过滤。

    电子页 → get_text("blocks") 按坐标过滤页眉页脚 → paragraph
    扫描页 → get_image_info() 大图 → OCR → image
    同一份 PDF 中两类页面可混合存在。

    逐页处理完成后做跨页拼接：
    - 段落尾不是句末标点 → 与下一页首段拼接
    - 表格行首行与第一页表头相似 → 跳过重复表头
    """

    @property
    def supported_extensions(self) -> List[str]:
        return [".pdf"]

    def load(self, file_path: str) -> List[ContentElement]:
        try:
            import fitz
        except ImportError:
            raise ImportError("请安装 PyMuPDF: pip install pymupdf")

        doc = fitz.open(file_path)
        elements: List[ContentElement] = []
        file_name = os.path.basename(file_path)

        for page_idx, page in enumerate(doc):
            page_num = page_idx + 1
            self._extract_text_blocks(page, file_path, file_name, page_num, elements)
            self._extract_images(doc, page, file_path, file_name, page_num, elements)

        doc.close()

        # ── 跨页处理 ──
        elements = self._merge_cross_page_paragraphs(elements)
        elements = self._merge_cross_page_tables(elements)

        return elements

    # ── 文字提取 ──────────────────────────

    def _extract_text_blocks(self, page, file_path: str, file_name: str,
                             page_num: int, elements: List[ContentElement]):
        """用 get_text("blocks") 逐块提取，过滤页眉页脚。"""
        try:
            blocks = page.get_text("blocks")
        except Exception:
            return

        text_lines: List[str] = []
        for block in blocks:
            if len(block) < 5:
                continue
            x0, y0, x1, y1, text, *_ = block
            text = text.strip()
            if not text:
                continue

            if self._is_header_or_footer(y0, y1, page.rect.height):
                continue
            if _is_page_number(text):
                continue

            text_lines.append(text)

        if text_lines:
            # 合并块为段落——块之间通常是自然换行
            full = "\n".join(text_lines)
            for para in re.split(r"\n\s*\n", full):
                para = para.strip()
                if para:
                    elements.append(ContentElement(
                        content=para,
                        doc_type="paragraph",
                        metadata={
                            "file_path": file_path,
                            "file_name": file_name,
                            "page": page_num,
                        },
                    ))

    def _is_header_or_footer(self, y0: float, y1: float, page_h: float) -> bool:
        margin = page_h * HEADER_FOOTER_RATIO
        return y1 < margin or y0 > page_h - margin

    # ── 图片 OCR ──────────────────────────

    def _extract_images(self, doc, page, file_path: str, file_name: str,
                        page_num: int, elements: List[ContentElement]):
        try:
            img_infos = page.get_image_info(xrefs=True)
        except Exception:
            return

        for img_info in img_infos:
            xref = img_info.get("xref")
            if not xref:
                continue

            bbox = img_info["bbox"]
            img_w = bbox[2] - bbox[0]
            img_h = bbox[3] - bbox[1]
            page_w = page.rect.width
            page_h = page.rect.height

            if (img_w / page_w < PDF_IMAGE_SIZE_THRESHOLD
                    and img_h / page_h < PDF_IMAGE_SIZE_THRESHOLD):
                continue

            pix = fitz.Pixmap(doc, xref)  # noqa — fitz 在方法内 import

            if int(page.rotation) != 0:
                img_array = np.frombuffer(pix.samples, dtype=np.uint8).reshape(
                    pix.height, pix.width, -1
                )
                pil_img = Image.fromarray(img_array)
                rotated = pil_img.rotate(360 - page.rotation, expand=True)
                img_array = np.array(rotated)
            else:
                img_array = np.frombuffer(pix.samples, dtype=np.uint8).reshape(
                    pix.height, pix.width, -1
                )

            ocr_text = ocr_image(img_array)
            if ocr_text:
                elements.append(ContentElement(
                    content=ocr_text,
                    doc_type="image",
                    metadata={
                        "file_path": file_path,
                        "file_name": file_name,
                        "page": page_num,
                    },
                ))

    # ── 跨页段落拼接 ──────────────────────

    def _merge_cross_page_paragraphs(self,
                                     elements: List[ContentElement]) -> List[ContentElement]:
        """检测相邻且跨页被截断的段落，拼接回完整句子。

        判断逻辑：前一个段落的最后一个非空白字符不是句末标点 → 被截断。
        """
        if not elements:
            return elements

        merged: List[ContentElement] = []

        for el in elements:
            if el.doc_type != "paragraph":
                merged.append(el)
                continue

            if not merged or merged[-1].doc_type != "paragraph":
                merged.append(el)
                continue

            prev = merged[-1]
            prev_ends_sentence = self._ends_with_sentence_end(prev.content)
            prev_page = self._page_num(prev)
            curr_page = self._page_num(el)

            # 前一页的最后一段，且不以句末标点结尾 → 被截断
            if prev_page != curr_page and not prev_ends_sentence:
                prev.content = prev.content.rstrip() + el.content
                prev.metadata["page"] = f"{prev_page}-{curr_page}"
                continue

            merged.append(el)

        return merged

    def _ends_with_sentence_end(self, text: str) -> bool:
        stripped = text.rstrip()
        return len(stripped) > 0 and stripped[-1] in SENTENCE_ENDS

    def _page_num(self, el: ContentElement) -> int:
        p = el.metadata.get("page", 1)
        if isinstance(p, int):
            return p
        # "3-4" 取起始页
        return int(str(p).split("-")[0])

    # ── 跨页表格合并 ──────────────────────

    def _merge_cross_page_tables(self,
                                 elements: List[ContentElement]) -> List[ContentElement]:
        """检测跨页表格：下一页开头的行与第一行高度相似 → 重复表头 → 跳过。

        同时为相邻的 table_row 建立"表头行"引用，方便下游识别同一张表。
        """
        if not elements:
            return elements

        merged: List[ContentElement] = []
        table_header: ContentElement | None = None  # 当前表格的第一行（表头）

        for el in elements:
            if el.doc_type != "table_row":
                table_header = None
                merged.append(el)
                continue

            if table_header is None:
                # 开始一张新表格
                table_header = el
                merged.append(el)
                continue

            prev = merged[-1]
            prev_page = self._page_num(prev)
            curr_page = self._page_num(el)

            if prev.doc_type == "table_row" and prev_page != curr_page:
                if _similarity(el.content, table_header.content) > TABLE_HEADER_SIMILARITY:
                    # 跨页后第一行是重复表头 → 跳过
                    continue

            merged.append(el)

        return merged
