"""文档加载模块 — 策略模式。

DocumentLoaderContext 持有所有 Loader 策略，根据扩展名分发。
扩展新格式只需：① 实现 DocumentLoader 子类 ② 注册到 Context。
"""

import os
from typing import List

from .base import ContentElement, DocumentLoader
from .text_loader import TxtLoader, MdLoader
from .pdf_loader import PdfLoader
from .word_loader import DocxLoader, DocLoader
from .ppt_loader import PptxLoader, PptLoader
from .excel_loader import XlsxLoader, CsvLoader
from .image_loader import JpgLoader, PngLoader


class DocumentLoaderContext:
    """策略上下文 — 管理所有 Loader 策略，根据文件扩展名分发。

    使用方式:
        ctx = DocumentLoaderContext()
        ctx.register(TxtLoader())
        elements = ctx.load("/path/to/file.txt")

        # 或批量注册所有内置 Loader:
        ctx = create_default_context()
        elements = ctx.load("/path/to/file.pdf")
    """

    def __init__(self):
        self._loaders: dict[str, DocumentLoader] = {}

    def register(self, loader: DocumentLoader) -> None:
        """注册一个 Loader 策略。同一扩展名重复注册会覆盖。"""
        for ext in loader.supported_extensions:
            self._loaders[ext.lower()] = loader

    def unregister(self, extension: str) -> None:
        """移除一个扩展名的 Loader。"""
        self._loaders.pop(extension.lower(), None)

    def load(self, file_path: str) -> List[ContentElement]:
        """加载单个文件，根据扩展名分发到对应策略。

        Raises:
            ValueError: 不支持的文件类型
        """
        ext = os.path.splitext(file_path)[1].lower()
        loader = self._loaders.get(ext)
        if loader is None:
            raise ValueError(f"不支持的文件类型: {ext} (file: {file_path})")
        return loader.load(file_path)

    def load_directory(self, directory_path: str) -> List[ContentElement]:
        """遍历目录加载所有支持格式的文件。单文件失败不中断整体流程。"""
        all_elements: List[ContentElement] = []
        supported = set(self._loaders.keys())

        for root, _, files in os.walk(directory_path):
            for fname in files:
                ext = os.path.splitext(fname)[1].lower()
                if ext not in supported:
                    continue
                file_path = os.path.join(root, fname)
                try:
                    all_elements.extend(self.load(file_path))
                except Exception as e:
                    print(f"[ERROR] 加载失败 {file_path}: {e}")

        return all_elements

    @property
    def supported_extensions(self) -> List[str]:
        return sorted(self._loaders.keys())


def create_default_context() -> DocumentLoaderContext:
    """创建包含所有内置 Loader 策略的 Context。"""
    ctx = DocumentLoaderContext()
    ctx.register(TxtLoader())
    ctx.register(MdLoader())
    ctx.register(PdfLoader())
    ctx.register(DocxLoader())
    ctx.register(DocLoader())
    ctx.register(PptxLoader())
    ctx.register(PptLoader())
    ctx.register(XlsxLoader())
    ctx.register(CsvLoader())
    ctx.register(JpgLoader())
    ctx.register(PngLoader())
    return ctx
