"""项目运行配置。"""

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class VllmConfig:
    """vLLM OpenAI 兼容接口配置。"""

    base_url: str
    model: str
    api_key: str
    timeout: float


def get_vllm_config():
    """读取 vLLM 配置，并允许通过环境变量覆盖默认值。"""
    timeout = float(os.getenv("VLLM_TIMEOUT", "120"))
    if timeout <= 0:
        raise ValueError("VLLM_TIMEOUT 必须大于 0")
    return VllmConfig(
        base_url=os.getenv("VLLM_BASE_URL", "http://127.0.0.1:8000/v1").rstrip("/"),
        model=os.getenv("VLLM_MODEL", "abl-14b"),
        api_key=os.getenv("VLLM_API_KEY") or "EMPTY",
        timeout=timeout,
    )
