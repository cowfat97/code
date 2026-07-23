""".jpg / .jpeg / .png — 纯图片文件 OCR，每种格式独立 Loader。"""

import os
from typing import List

from .base import ContentElement, DocumentLoader
from .ocr import ocr_image


class JpgLoader(DocumentLoader):
    """.jpg / .jpeg 图片加载器。"""

    @property
    def supported_extensions(self) -> List[str]:
        return [".jpg", ".jpeg"]

    def load(self, file_path: str) -> List[ContentElement]:
        ocr_text = ocr_image(file_path)
        if not ocr_text:
            return []
        return [ContentElement(
            content=ocr_text,
            doc_type="image",
            metadata={"file_path": file_path, "file_name": os.path.basename(file_path)},
        )]


class PngLoader(DocumentLoader):
    """.png 图片加载器。"""

    @property
    def supported_extensions(self) -> List[str]:
        return [".png"]

    def load(self, file_path: str) -> List[ContentElement]:
        ocr_text = ocr_image(file_path)
        if not ocr_text:
            return []
        return [ContentElement(
            content=ocr_text,
            doc_type="image",
            metadata={"file_path": file_path, "file_name": os.path.basename(file_path)},
        )]
