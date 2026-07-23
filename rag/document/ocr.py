"""OCR 引擎 — PaddleOCR (RapidOCR) 单例。

优先 rapidocr_paddle（GPU），fallback rapidocr_onnxruntime（CPU）。
所有 Loader 通过 get_ocr() 复用同一个实例。
"""

from typing import Optional
import logging

logger = logging.getLogger(__name__)

_ocr_instance: Optional[object] = None


def get_ocr(use_gpu: bool = True) -> object:
    """获取 OCR 单例。首次调用时初始化，后续复用。

    Args:
        use_gpu: 是否尝试 GPU 加速（PaddlePaddle），失败时自动回退 CPU
    """
    global _ocr_instance
    if _ocr_instance is not None:
        return _ocr_instance

    if use_gpu:
        try:
            from rapidocr_paddle import RapidOCR
            _ocr_instance = RapidOCR(
                det_use_cuda=True,
                cls_use_cuda=True,
                rec_use_cuda=True,
            )
            logger.info("OCR 引擎: rapidocr_paddle (GPU)")
            return _ocr_instance
        except (ImportError, Exception):
            logger.warning("rapidocr_paddle 不可用，回退到 CPU")

    try:
        from rapidocr_onnxruntime import RapidOCR
        _ocr_instance = RapidOCR()
        logger.info("OCR 引擎: rapidocr_onnxruntime (CPU)")
        return _ocr_instance
    except ImportError:
        raise ImportError(
            "未安装 OCR 引擎。请执行: pip install rapidocr-onnxruntime"
        )


def ocr_image(image) -> str:
    """对单张图片执行 OCR，返回识别文本。

    Args:
        image: numpy array (H, W, C) 或 文件路径字符串

    Returns:
        提取的文本，多行用 \\n 连接。识别失败返回空字符串。
    """
    ocr = get_ocr()
    result, _ = ocr(image)
    if not result:
        return ""
    # result 格式: [[bbox, text, confidence], ...]
    # 按行取 text 即可
    return "\n".join(line[1] for line in result if line[1])
