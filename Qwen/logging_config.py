# logging_config.py —— 项目统一日志配置
import logging
from pathlib import Path


def setup_logging():
    """日志同时输出到终端和 log/qwen.log。"""
    log_dir = Path(__file__).resolve().parent / "log"
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
