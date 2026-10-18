"""仅此适配层知道 SDK 的 span 与 scope。"""

import atexit
import logging
import os
from functools import lru_cache
from threading import Lock

logger = logging.getLogger(__name__)
_client_lock = Lock()


def _flush(client):
    try:
        client.flush()
    except Exception as exc:
        logger.warning("Langfuse 退出刷新失败（%s）", type(exc).__name__)


@lru_cache(maxsize=4)
def _create_client(public_key, secret_key, base_url):
    from langfuse import Langfuse

    client = Langfuse(public_key=public_key, secret_key=secret_key, base_url=base_url)
    atexit.register(_flush, client)
    return client


def _get_client():
    public_key = os.getenv("LANGFUSE_PUBLIC_KEY")
    secret_key = os.getenv("LANGFUSE_SECRET_KEY")
    if not public_key or not secret_key:
        logger.warning("Langfuse 未启用：缺少 PUBLIC_KEY 或 SECRET_KEY")
        return None
    try:
        with _client_lock:
            return _create_client(public_key, secret_key,
                                  os.getenv("LANGFUSE_BASE_URL", "http://127.0.0.1:3000"))
    except Exception as exc:
        logger.warning("Langfuse 初始化失败（%s）", type(exc).__name__)
        return None


class LangfuseObserver:
    def __init__(self, client):
        self._client = client

    def on_stage_start(self, event):
        scope = self._client.start_as_current_observation(
            as_type="span", name=event.name, input=event.input,
            metadata={"request_id":event.request_id, "stage_id":event.stage_id,
                      "parent_stage_id":event.parent_stage_id})
        span = scope.__enter__()
        return scope, span

    def on_stage_end(self, event, token, result):
        scope, span = token
        try:
            fields = {"metadata":{"request_id":event.request_id,"stage_id":event.stage_id,
                                  "parent_stage_id":event.parent_stage_id,
                                  "duration_ns":result.duration_ns}}
            if result.status == "success":
                fields["output"] = result.output
            else:
                fields.update(level="ERROR",
                              status_message=f"{result.error_type}: {result.error_message}")
            span.update(**fields)
        finally:
            # 业务异常由运行时原样传播；SDK 只接收错误摘要。
            scope.__exit__(None, None, None)
