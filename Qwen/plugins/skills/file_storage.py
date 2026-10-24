"""Atomic file persistence and OS-owned locks; no database or daemon required."""

from __future__ import annotations

import json
import os
import re
import sys
import tempfile
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterator


def atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=".write-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        if sys.platform != "win32":
            directory_fd = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
    finally:
        Path(temporary).unlink(missing_ok=True)


def json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2) + "\n").encode()


@contextmanager
def file_lock(path: Path, *, blocking: bool = True) -> Iterator[None]:
    """Locks release on process exit, including a crash; never delete lock files."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as stream:
        if sys.platform == "win32":
            import msvcrt

            stream.seek(0, os.SEEK_END)
            if stream.tell() == 0:
                stream.write(b"\0")
                stream.flush()
            stream.seek(0)
            try:
                msvcrt.locking(stream.fileno(), msvcrt.LK_LOCK if blocking else msvcrt.LK_NBLCK, 1)
            except OSError as exc:
                raise RuntimeError("file is locked by another operation") from exc
            try:
                yield
            finally:
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            try:
                fcntl.flock(stream, fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB))
            except BlockingIOError as exc:
                raise RuntimeError("file is locked by another operation") from exc
            try:
                yield
            finally:
                fcntl.flock(stream, fcntl.LOCK_UN)


class RunStorage:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()

    def directory(self, graph_id: str) -> Path:
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", graph_id):
            raise ValueError("invalid graph id")
        directory = self.root / "runs" / graph_id
        if not directory.resolve().is_relative_to(self.root):
            raise ValueError("run path escapes state directory")
        return directory

    def execution_lock(self, graph_id: str) -> Any:
        return file_lock(self.directory(graph_id) / ".execute.lock", blocking=False)

    @staticmethod
    def _read(directory: Path) -> dict[str, Any] | None:
        path = directory / "run.json"
        return json.loads(path.read_text()) if path.exists() else None

    @staticmethod
    def _project(directory: Path, record: dict[str, Any]) -> None:
        # run.json is authoritative; these human-readable views can always be rebuilt.
        atomic_write(directory / "graph.json", json_bytes(record["graph"]))
        atomic_write(directory / "state.json", json_bytes(record["state"]))
        trace = b"".join(
            json_bytes(event).replace(b"\n", b"") + b"\n"
            for event in record["state"].get("trace", [])
        )
        atomic_write(directory / "trace.jsonl", trace)

    def save_run(self, graph_id: str, graph: dict[str, Any], state: dict[str, Any]) -> None:
        if graph.get("id") != graph_id or state.get("graph_id") != graph_id:
            raise ValueError("run identity mismatch")
        if graph.get("version") != state.get("graph_version"):
            raise ValueError("run graph/state revision mismatch")
        directory = self.directory(graph_id)
        with file_lock(directory / ".write.lock"):
            previous = self._read(directory) or {}
            record = {"graph": graph, "state": state, "feedback": previous.get("feedback", [])}
            atomic_write(directory / "run.json", json_bytes(record))
            self._project(directory, record)

    def load_run(self, graph_id: str) -> tuple[dict[str, Any], dict[str, Any]] | None:
        directory = self.directory(graph_id)
        if not (directory / "run.json").exists():
            return None
        with file_lock(directory / ".write.lock"):
            record = self._read(directory)
            assert record is not None
            self._project(directory, record)
            return record["graph"], record["state"]

    def record_feedback(self, skill_id: str, node_id: str, success: bool, details: Any) -> None:
        graph_id = details["graph_id"]
        directory = self.directory(graph_id)
        with file_lock(directory / ".write.lock"):
            record = self._read(directory)
            if record is None:
                raise KeyError(graph_id)
            record["feedback"].append(
                {
                    "skill_id": skill_id,
                    "node_id": node_id,
                    "success": success,
                    "created": datetime.now(UTC).isoformat(),
                    "details": details,
                }
            )
            atomic_write(directory / "run.json", json_bytes(record))

    def episodes(self) -> list[dict[str, Any]]:
        episodes = []
        for path in sorted((self.root / "runs").glob("*/run.json")):
            record = json.loads(path.read_text())
            state, graph = record["state"], record["graph"]
            if state["status"] not in {"succeeded", "failed"}:
                continue
            episodes.append(
                {
                    "task": graph["task"],
                    "trajectory": [
                        node["skill"]["id"]
                        for node in graph["nodes"]
                        if node.get("skill") and state["nodes"][node["id"]]["status"] == "succeeded"
                    ],
                    "success": state["status"] == "succeeded",
                }
            )
        return episodes

    def feedback(self) -> list[dict[str, Any]]:
        records = []
        for path in sorted((self.root / "runs").glob("*/run.json")):
            records.extend(json.loads(path.read_text()).get("feedback", []))
        return sorted(records, key=lambda row: (row["created"], row["details"]["graph_id"]))
