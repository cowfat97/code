"""可选的 Langfuse 监控；监控故障不能改变聊天结果或异常。"""

import logging
import os
import sys
from contextlib import contextmanager
from functools import lru_cache

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def _get_client():
    public_key = os.getenv("LANGFUSE_PUBLIC_KEY")
    secret_key = os.getenv("LANGFUSE_SECRET_KEY")
    if not public_key or not secret_key:
        logger.warning("Langfuse 监控未启用：请配置 LANGFUSE_PUBLIC_KEY 和 LANGFUSE_SECRET_KEY")
        return None
    try:
        from langfuse import Langfuse

        return Langfuse(
            public_key=public_key,
            secret_key=secret_key,
            base_url=os.getenv("LANGFUSE_BASE_URL", "http://192.168.1.177:3000"),
        )
    except Exception as exc:
        logger.warning("Langfuse 初始化失败（%s），继续执行聊天", type(exc).__name__)
        return None


def record_output(span, output):
    if span is not None:
        try:
            span.update(output=output)
        except Exception as exc:
            logger.warning("Langfuse 记录输出失败（%s）", type(exc).__name__)


@contextmanager
def observe_stage(name, input):
    """SDK 自动记录时间和业务异常；嵌套作用域自动建立父子关系。"""
    client = _get_client()
    if client is None:
        yield None
        return
    try:
        scope = client.start_as_current_observation(as_type="span", name=name, input=input)
        span = scope.__enter__()
    except Exception as exc:
        logger.warning("Langfuse 创建阶段失败（%s）", type(exc).__name__)
        yield None
        return
    try:
        yield span
    finally:
        # 把业务异常交给 SDK 标记，但不允许监控吞掉或替换它。
        error = sys.exc_info()
        if error[1] is not None:
            try:
                span.update(level="ERROR", status_message=str(error[1]))
            except Exception as exc:
                logger.warning("Langfuse 记录异常失败（%s）", type(exc).__name__)
        try:
            scope.__exit__(*error)
        except Exception as exc:
            logger.warning("Langfuse 结束阶段失败（%s）", type(exc).__name__)
