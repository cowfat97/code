"""记忆快照与存储错误，不依赖数据库驱动。"""

from dataclasses import dataclass
from typing import Protocol


class MemoryStorageError(RuntimeError):
    """权威历史读取或保存失败。"""


class MemoryConflictError(MemoryStorageError):
    """其他进程已经提交更新；本轮不能覆盖。"""


@dataclass(frozen=True)
class MemorySnapshot:
    messages: list[dict[str, str]]
    revision: int


class MemoryStore(Protocol):
    def load(self) -> MemorySnapshot: ...
    def save(self, expected_revision: int, messages: list[dict[str, str]]) -> int: ...
