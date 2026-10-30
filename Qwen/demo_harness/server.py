"""Local-only demonstration transport, not a production service."""

from __future__ import annotations

import asyncio
import json
import threading
from collections.abc import Callable, Coroutine
from concurrent.futures import TimeoutError as FutureTimeout
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from .bridge import LocalBackend
from .engine import Harness
from .ports import Backend


def serve(
    port: int = 8765,
    *,
    backend_factory: Callable[[], Coroutine[Any, Any, Backend]] = LocalBackend.create,
    server_factory: Callable[..., ThreadingHTTPServer] = ThreadingHTTPServer,
) -> None:
    if type(port) is not int or not 1 <= port <= 65535:
        raise ValueError("invalid port")
    loop = asyncio.new_event_loop()
    thread = threading.Thread(target=loop.run_forever, daemon=True)
    thread.start()
    backend = None
    server = None
    try:
        startup = asyncio.run_coroutine_threadsafe(backend_factory(), loop)
        try:
            backend = startup.result(60)
        except BaseException:
            startup.cancel()
            raise
        harness = Harness(backend)
        origin = f"http://127.0.0.1:{port}"

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, format: str, *args: Any) -> None:
                pass

            def respond(self, status: int, data: bytes, content_type: str) -> None:
                self.send_response(status)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.send_header(
                    "Content-Security-Policy",
                    "default-src 'self'; script-src 'self'; style-src 'self'; frame-ancestors 'none'",
                )
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self) -> None:
                files = {
                    "/": ("index.html", "text/html; charset=utf-8"),
                    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
                    "/style.css": ("style.css", "text/css; charset=utf-8"),
                }
                if (
                    self.headers.get("Host") != origin.removeprefix("http://")
                    or self.path not in files
                ):
                    self.respond(404, b"Not found", "text/plain")
                    return
                name, mime = files[self.path]
                self.respond(
                    200, (Path(__file__).parent / "static" / name).read_bytes(), mime
                )

            def do_POST(self) -> None:
                if (
                    self.path != "/chat"
                    or self.headers.get("Host") != origin.removeprefix("http://")
                    or self.headers.get("Origin") != origin
                ):
                    self.respond(403, b"Forbidden", "text/plain")
                    return
                future = None
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                    if not 0 < length <= 100000 or self.headers.get(
                        "Transfer-Encoding"
                    ):
                        raise ValueError("invalid request size")
                    self.connection.settimeout(10)
                    value = json.loads(self.rfile.read(length))
                    if not isinstance(value, dict) or set(value) - {
                        "message",
                        "session_id",
                        "action",
                        "expected_revision",
                    }:
                        raise ValueError("invalid request")
                    future = asyncio.run_coroutine_threadsafe(
                        harness.chat(**value), loop
                    )
                    result = future.result(180)
                    self.respond(
                        200,
                        json.dumps(result, ensure_ascii=False).encode(),
                        "application/json; charset=utf-8",
                    )
                except FutureTimeout:
                    if future is not None:
                        future.cancel()
                    self.respond(
                        504, b'{"error":"request timed out"}', "application/json"
                    )
                except Exception:  # noqa: BLE001 - HTTP boundary must not leak remote errors
                    self.respond(
                        400,
                        b'{"error":"invalid request or unavailable session"}',
                        "application/json",
                    )

        server = server_factory(("127.0.0.1", port), Handler)
        server.daemon_threads = True
        print(f"Demo Harness: {origin}")
        server.serve_forever()
    finally:
        try:
            if server is not None:
                server.server_close()
            if backend is not None:
                asyncio.run_coroutine_threadsafe(backend.aclose(), loop).result(30)
        finally:

            async def drain() -> None:
                tasks = [
                    task
                    for task in asyncio.all_tasks()
                    if task is not asyncio.current_task()
                ]
                for task in tasks:
                    task.cancel()
                if tasks:
                    await asyncio.gather(*tasks, return_exceptions=True)

            try:
                asyncio.run_coroutine_threadsafe(drain(), loop).result(10)
            finally:
                loop.call_soon_threadsafe(loop.stop)
                thread.join(timeout=5)
                if not thread.is_alive():
                    loop.close()
