"""项目运行配置。"""

import os
from agent.entities import VllmConfig


def get_vllm_config():
    """读取 vLLM 连接配置，每次调用均重新读取环境变量。

    VLLM_TIMEOUT 为正数秒数；格式错误或非正数会抛出 ValueError。
    其余配置缺省时使用下方默认值，地址末尾的斜杠会被移除。
    """
    timeout = float(os.getenv("VLLM_TIMEOUT", "120"))
    if timeout <= 0:
        raise ValueError("VLLM_TIMEOUT 必须大于 0")
    return VllmConfig(
        base_url=os.getenv("VLLM_BASE_URL", "http://127.0.0.1:8000/v1").rstrip("/"),
        model=os.getenv("VLLM_MODEL", "qwen-local"),
        # OpenAI 客户端要求非空 key；本地无鉴权服务用 EMPTY 占位。
        api_key=os.getenv("VLLM_API_KEY") or "EMPTY",
        timeout=timeout,
    )

def get_postgres_config():
    """按调用读取 PG 标准配置，不读取或输出密码。"""
    from agent.entities.config.postgres import PostgresConfig

    port = int(os.getenv("PGPORT", "5433"))
    if not 1 <= port <= 65535:
        raise ValueError("PGPORT 必须在 1 至 65535 之间")
    fields = {name: os.getenv(env, default) for name, env, default in (
        ("host", "PGHOST", "127.0.0.1"),
        ("dbname", "PGDATABASE", "dev"),
        ("user", "PGUSER", "dev"),
    )}
    if any(not value.strip() for value in fields.values()):
        raise ValueError("PGHOST、PGDATABASE、PGUSER 不能为空")
    return PostgresConfig(port=port, **fields)
