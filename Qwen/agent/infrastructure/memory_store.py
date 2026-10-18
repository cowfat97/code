"""全局唯一历史的 PostgreSQL 存储，不依赖监控插件。"""

import copy
import json
from pathlib import Path

from agent.entities.memory import MemorySnapshot, MemoryConflictError, MemoryStorageError
from .postgres import DatabaseError, Postgres


def _validate(messages):
    if not isinstance(messages, list) or any(
        not isinstance(message, dict) or set(message) != {"role", "content"}
        or message["role"] not in ("system", "user", "assistant")
        or not isinstance(message["content"], str)
        for message in messages
    ):
        raise MemoryStorageError("记忆数据无效：历史必须为 role/content 字符串消息数组")


class PgMemoryStore:
    def __init__(self, database=None):
        self.database = database if database is not None else Postgres()

    def load(self):
        try:
            rows = self.database.fetch_all("SELECT messages, revision FROM qwen.memory WHERE id = 1")
        except DatabaseError as exc:
            raise MemoryStorageError("读取 PG 记忆失败，请检查数据库连接及初始化状态") from exc
        if not rows:
            return MemorySnapshot([], 0)
        messages, revision = rows[0]
        _validate(messages)
        if type(revision) is not int or revision < 1:
            raise MemoryStorageError("记忆版本无效")
        return MemorySnapshot(copy.deepcopy(messages), revision)

    def save(self, expected_revision, messages):
        if type(expected_revision) is not int or expected_revision < 0:
            raise MemoryStorageError("记忆版本必须为非负整数")
        _validate(messages)
        try:
            payload = json.dumps(messages, ensure_ascii=False, allow_nan=False)
        except (ValueError, TypeError) as exc:
            raise MemoryStorageError("记忆无法序列化") from exc
        try:
            with self.database.transaction() as connection:
                if expected_revision == 0:
                    cursor = connection.execute(
                        "INSERT INTO qwen.memory (id, revision, messages) VALUES (1, 1, %s::jsonb) "
                        "ON CONFLICT (id) DO NOTHING RETURNING revision", (payload,))
                else:
                    cursor = connection.execute(
                        "UPDATE qwen.memory SET messages = %s::jsonb, revision = revision + 1, "
                        "updated_at = clock_timestamp() WHERE id = 1 AND revision = %s RETURNING revision",
                        (payload, expected_revision))
                row = cursor.fetchone()
                if row is None:
                    raise MemoryConflictError("记忆已被其他进程更新，本轮未保存；请重新提问")
                revision = row[0]
        except DatabaseError as exc:
            raise MemoryStorageError("保存 PG 记忆失败或提交状态无法确认；请检查数据库后重试") from exc
        return revision


def get_memory_store():
    return PgMemoryStore()


def initialize(database=None):
    """显式初始化；不创建、替换或清空实际历史记录。"""
    database = database if database is not None else Postgres()
    migration = Path(__file__).resolve().parents[2] / "migrations" / "001_memory.sql"
    with database.transaction() as connection:
        connection.execute(migration.read_text(encoding="utf-8-sig"))


if __name__ == "__main__":
    try:
        initialize()
    except (DatabaseError, ValueError, OSError) as exc:
        raise SystemExit(str(exc))
    print("PG 记忆表已初始化，已有历史保持不变。")
