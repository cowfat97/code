"""生命周期 hooks 的共享协议，不依赖监控 SDK。"""

from dataclasses import dataclass
from typing import Callable, Literal


@dataclass(frozen=True)
class StageEvent:
    request_id: str
    stage_id: str
    parent_stage_id: str | None
    name: str
    input: object


@dataclass(frozen=True)
class StageResult:
    status: Literal["success", "error", "cancelled"]
    output: object
    error_type: str | None
    error_message: str | None
    duration_ns: int


@dataclass(frozen=True)
class HookSpec:
    id: str
    on_stage_start: Callable[[StageEvent], object]
    on_stage_end: Callable[[StageEvent, object, StageResult], None]
