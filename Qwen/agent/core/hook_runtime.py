"""通用阶段生命周期：分发 hooks，不依赖任何插件实现。"""

import copy
import json
import logging
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import replace
from time import monotonic_ns
from uuid import uuid4

from agent.entities.hooks import StageEvent, StageResult

logger = logging.getLogger(__name__)


def _snapshot(value):
    try:
        return json.loads(json.dumps(value, ensure_ascii=False, allow_nan=False))
    except Exception as exc:
        logger.warning("Hook 数据快照失败（%s）", type(exc).__name__)
        return "<unavailable>"


def _error_message(error):
    try:
        return str(error)
    except Exception:
        return "<unavailable>"


class StageHandle:
    def __init__(self, enabled):
        self._enabled = enabled
        self._output = None

    def set_output(self, output):
        self._output = _snapshot(output) if self._enabled else None


class HookRuntime:
    """每请求独立实例；上下文中的阶段栈亦隔离线程与异步任务。"""

    def __init__(self, hooks=(), *, request_id=None):
        self._hooks = tuple(hooks)
        self.request_id = request_id or uuid4().hex
        self._parent = ContextVar("hook_parent", default=None)

    @contextmanager
    def stage(self, name, input):
        event = StageEvent(self.request_id, uuid4().hex, self._parent.get(), name,
                           _snapshot(input) if self._hooks else None)
        parent_token = self._parent.set(event.stage_id)
        started = []
        handle = StageHandle(bool(self._hooks))
        start = monotonic_ns()
        error = None
        try:
            for hook in self._hooks:
                try:
                    token = hook.on_stage_start(copy.deepcopy(event))
                    started.append((hook, token))
                except Exception as exc:
                    logger.warning("Hook 开始失败 plugin=%s stage=%s (%s)",
                                   hook.id, name, type(exc).__name__)
            yield handle
        except BaseException as exc:
            error = exc
            raise
        finally:
            result = StageResult(
                "success" if error is None else
                ("error" if isinstance(error, Exception) else "cancelled"),
                handle._output if error is None else None,
                type(error).__name__ if error is not None else None,
                _error_message(error) if error is not None else None,
                monotonic_ns() - start,
            )
            try:
                for hook, token in reversed(started):
                    try:
                        hook.on_stage_end(copy.deepcopy(event), token, copy.deepcopy(result))
                    except Exception as exc:
                        logger.warning("Hook 结束失败 plugin=%s stage=%s (%s)",
                                       hook.id, name, type(exc).__name__)
            finally:
                self._parent.reset(parent_token)
