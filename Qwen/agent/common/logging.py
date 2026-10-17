"""统一日志初始化，同时配置终端输出和项目日志文件。"""
import logging
from pathlib import Path


def setup_logging():
    """将根日志配置为 INFO，并输出到终端和项目 log/qwen.log。

    日志路径相对于本模块推导，不依赖进程工作目录。
    force=True 会替换已有根日志处理器，适合在应用入口初始化时调用。
    """
    log_dir = Path(__file__).resolve().parents[2] / "log"
    log_dir.mkdir(exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(log_dir / "qwen.log", encoding="utf-8"),
        ],
        force=True,
    )
