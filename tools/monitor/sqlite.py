"""SQLite event sink; independent of tool execution and MCP transports."""

import sqlite3
import threading
from dataclasses import asdict
from pathlib import Path
from typing import Any

from .events import ToolEvent


class SQLiteMonitor:
    def __init__(self, path: str | Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self._lock = threading.RLock()
        self._connection: sqlite3.Connection | None = sqlite3.connect(
            str(path), timeout=5, check_same_thread=False
        )
        self._connection.execute("PRAGMA journal_mode=WAL")
        self._connection.execute("""CREATE TABLE IF NOT EXISTS tool_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL, kind TEXT NOT NULL, name TEXT NOT NULL,
            source TEXT NOT NULL, call_id TEXT, duration_ms REAL, error_type TEXT
        )""")
        self._connection.execute(
            "CREATE INDEX IF NOT EXISTS events_call_id ON tool_events(call_id)"
        )
        self._connection.commit()

    def __call__(self, event: ToolEvent) -> None:
        with self._lock:
            if self._connection is None:
                raise RuntimeError("SQLite monitor is closed")
            data = asdict(event)
            with self._connection:
                self._connection.execute(
                    "INSERT INTO tool_events "
                    "(timestamp,kind,name,source,call_id,duration_ms,error_type) "
                    "VALUES (:timestamp,:kind,:name,:source,:call_id,:duration_ms,:error_type)",
                    data,
                )

    def list_events(
        self,
        *,
        name: str | None = None,
        kind: str | None = None,
        call_id: str | None = None,
        after_id: int = 0,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        if not 1 <= limit <= 1000 or after_id < 0:
            raise ValueError("limit must be 1..1000 and after_id nonnegative")
        clauses = ["id > ?"]
        values: list[Any] = [after_id]
        for key, value in (("name", name), ("kind", kind), ("call_id", call_id)):
            if value is not None:
                clauses.append(f"{key} = ?")
                values.append(value)
        with self._lock:
            if self._connection is None:
                raise RuntimeError("SQLite monitor is closed")
            cursor = self._connection.execute(
                "SELECT id,timestamp,kind,name,source,call_id,duration_ms,error_type "
                "FROM tool_events WHERE " + " AND ".join(clauses) + " ORDER BY id LIMIT ?",
                [*values, limit],
            )
            columns = [item[0] for item in cursor.description]
            return [dict(zip(columns, row, strict=True)) for row in cursor.fetchall()]

    def close(self) -> None:
        with self._lock:
            if self._connection is not None:
                self._connection.close()
                self._connection = None

    def __enter__(self):
        return self

    def __exit__(self, *args: object) -> None:
        self.close()
