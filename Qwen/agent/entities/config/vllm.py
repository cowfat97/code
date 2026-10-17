"""vLLM 客户端连接配置的数据载体，不负责读取环境变量。"""

from dataclasses import dataclass


@dataclass(frozen=True)
class VllmConfig:
    """不可变的连接配置，由 get_vllm_config 读取并交给聊天后端使用。"""

    base_url: str  # OpenAI 兼容 API 根地址，通常以 /v1 结尾。
    model: str  # 服务公开的模型名称，应与 /v1/models 中的 id 一致。
    api_key: str  # 客户端使用的认证值；无鉴权本地服务使用非空占位值。
    timeout: float  # HTTP 请求超时，单位为秒；读取配置时要求大于零。
