"""Task-owned MCP session actor; optional SDK imports stay inside connection."""

import asyncio
from contextlib import AsyncExitStack
from dataclasses import dataclass
from typing import Any

from .config import MCPServerConfig


@dataclass
class _Request:
    name: str
    arguments: dict[str, Any]
    future: asyncio.Future[Any]
    cancel: asyncio.Event


class MCPConnection:
    def __init__(self, config: MCPServerConfig) -> None:
        self.config = config
        self.queue: asyncio.Queue[_Request | None] = asyncio.Queue()
        self.task: asyncio.Task[None] | None = None
        self.ready: asyncio.Future[list[Any]] | None = None
        self.closed = False
        self._slots = asyncio.Semaphore(128)

    async def start(self) -> list[Any]:
        self.ready = asyncio.get_running_loop().create_future()
        self.task = asyncio.create_task(self._run())
        try:
            return await asyncio.wait_for(
                asyncio.shield(self.ready), self.config.connection_timeout
            )
        except BaseException:
            await self.aclose()
            if self.ready.done() and not self.ready.cancelled():
                self.ready.exception()
            raise

    async def _run(self) -> None:
        assert self.ready is not None
        current: _Request | None = None
        try:
            from mcp import ClientSession, StdioServerParameters
            from mcp.client.stdio import stdio_client

            async with AsyncExitStack() as stack:
                cfg = self.config
                streams = await stack.enter_async_context(
                    stdio_client(
                        StdioServerParameters(
                            command=cfg.command, args=cfg.args, env=cfg.env, cwd=cfg.cwd
                        )
                    )
                )
                session = await stack.enter_async_context(ClientSession(streams[0], streams[1]))
                await session.initialize()
                discovered = []
                cursor = None
                seen = set()
                while True:
                    page = await session.list_tools(cursor=cursor)
                    discovered.extend(page.tools)
                    cursor = page.nextCursor
                    if cursor is None:
                        break
                    if cursor in seen:
                        raise ValueError("MCP discovery returned a repeated cursor")
                    seen.add(cursor)
                self.ready.set_result(discovered)
                while True:
                    request = await self.queue.get()
                    current = request
                    if request is None:
                        break
                    if request.future.cancelled():
                        continue
                    call = asyncio.create_task(session.call_tool(request.name, request.arguments))
                    cancelled = asyncio.create_task(request.cancel.wait())
                    try:
                        done, _ = await asyncio.wait(
                            (call, cancelled), return_when=asyncio.FIRST_COMPLETED
                        )
                        if cancelled in done:
                            call.cancel()
                            await asyncio.gather(call, return_exceptions=True)
                        else:
                            try:
                                result = call.result()
                            except Exception as exc:  # noqa: BLE001
                                if not request.future.done():
                                    request.future.set_exception(exc)
                            else:
                                if not request.future.done():
                                    request.future.set_result(result)
                    finally:
                        cancelled.cancel()
                        call.cancel()
                        await asyncio.gather(call, cancelled, return_exceptions=True)
        except BaseException as exc:  # noqa: BLE001
            self.closed = True
            if current is not None and not current.future.done():
                current.future.set_exception(RuntimeError("MCP connection closed"))
            if not self.ready.done():
                self.ready.set_exception(exc)
            while not self.queue.empty():
                request = self.queue.get_nowait()
                if request is not None and not request.future.done():
                    request.future.set_exception(RuntimeError("MCP connection closed"))
        finally:
            self.closed = True

    async def call(self, name: str, arguments: dict[str, Any]) -> Any:
        async with self._slots:
            if self.closed:
                raise RuntimeError("MCP connection closed")
            future = asyncio.get_running_loop().create_future()
            request = _Request(name, arguments, future, asyncio.Event())
            self.queue.put_nowait(request)
            try:
                return await future
            except asyncio.CancelledError:
                request.cancel.set()
                future.cancel()
                raise

    async def aclose(self) -> None:
        if self.task and not self.task.done():
            self.task.cancel()
        if self.task:
            await asyncio.gather(self.task, return_exceptions=True)
