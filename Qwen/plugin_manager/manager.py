"""Loop-local lifecycle management of independent configured child plugins.

Configured and explicitly registered factories are loaded only when started. Callbacks should
cooperate with cancellation; stop waits for admitted invocations to finish before
closing resources. A failed cleanup retains its instance: stop or aclose retries
cleanup, whereas start refuses to replace it. Closing is terminal even on failure.
"""

from __future__ import annotations

import asyncio
import inspect
import math
from collections.abc import Callable, Mapping
from contextvars import ContextVar
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Self

from .contracts import (
    DuplicatePluginError,
    EventLoopError,
    InvalidPluginNameError,
    InvalidPluginResultError,
    InvalidTimeoutError,
    ManagerClosedError,
    Plugin,
    PluginInfo,
    PluginState,
    PluginStateError,
    ReentrantLifecycleError,
    UnknownPluginError,
)
from .loader import load_factories

_callbacks: ContextVar[frozenset[object]] = ContextVar(
    "plugin_callbacks", default=frozenset()
)


@dataclass
class _Entry:
    name: str
    factory: Callable[[], Plugin]
    state: PluginState = PluginState.REGISTERED
    instance: Plugin | None = None
    error_type: str | None = None
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    calls: set[asyncio.Task[dict[str, Any]]] = field(default_factory=set)
    lifecycle: asyncio.Task[None] | None = None
    batch_owner: object | None = None


class PluginManager:
    """Explicit registry. Construct/register outside a loop or use on one loop only.

    Cancelling start cancels startup and waits for resource cleanup. Cancelling a
    stop/close waiter leaves the owned operation running; later callers can await
    it. Callback exceptions propagate unchanged; combined failures form a group.
    All lifecycle recursion from this manager's callbacks is rejected, including
    inherited callback contexts, to prevent lock and self-drain deadlocks.
    """

    def __init__(
        self,
        *,
        default_timeout: float = 30.0,
        load_builtin: bool = True,
        config_file: str | Path | None = None,
    ) -> None:
        self._timeout = self._validate_timeout(default_timeout)
        self._entries: dict[str, _Entry] = {}
        self._loop: asyncio.AbstractEventLoop | None = None
        self._closed = False
        self._close_task: asyncio.Task[None] | None = None
        self._batch_task: asyncio.Task[None] | None = None
        if not isinstance(load_builtin, bool):
            raise TypeError("load_builtin must be boolean")
        if load_builtin:
            path = (
                Path(config_file)
                if config_file is not None
                else Path(__file__).parent / "config/plugins.json"
            )
            for name, factory in load_factories(path):
                self.register(name, factory)

    @staticmethod
    def _validate_timeout(value: float) -> float:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise InvalidTimeoutError("timeout must be a positive finite number")
        try:
            number = float(value)
        except OverflowError as exc:
            raise InvalidTimeoutError("timeout must be positive and finite") from exc
        if not math.isfinite(number) or number <= 0:
            raise InvalidTimeoutError("timeout must be positive and finite")
        return number

    def _check_loop(self, *, required: bool = False) -> None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            if required or self._loop is not None:
                raise EventLoopError(
                    "use the manager on its owning event loop"
                ) from None
            return
        if self._loop is None:
            self._loop = loop
        elif self._loop is not loop:
            raise EventLoopError("use the manager on its owning event loop")

    def _open(self) -> None:
        if self._closed:
            raise ManagerClosedError("manager is closed")

    def _lifecycle_check(self) -> None:
        self._check_loop(required=True)
        if self in _callbacks.get():
            raise ReentrantLifecycleError(
                "lifecycle calls from plugin callbacks are forbidden"
            )

    @staticmethod
    def _name(name: str) -> None:
        if not isinstance(name, str) or not name or any(c.isspace() for c in name):
            raise InvalidPluginNameError(
                "plugin name must be nonempty and contain no whitespace"
            )

    def _entry(self, name: str) -> _Entry:
        self._name(name)
        try:
            return self._entries[name]
        except KeyError:
            raise UnknownPluginError(name) from None

    def register(self, name: str, factory: Callable[[], Plugin]) -> None:
        """Register a synchronous factory without constructing an instance."""
        self._check_loop()
        self._open()
        self._name(name)
        if name in self._entries:
            raise DuplicatePluginError(name)
        if not callable(factory) or inspect.iscoroutinefunction(factory):
            raise TypeError("factory must be callable")
        self._entries[name] = _Entry(name, factory)

    def unregister(self, name: str) -> None:
        """Remove only entries without an instance or an ongoing lifecycle."""
        self._check_loop()
        entry = self._entry(name)
        if entry.batch_owner is not None:
            raise PluginStateError("plugin belongs to an active start_all operation")
        if entry.instance is not None or (
            entry.lifecycle and not entry.lifecycle.done()
        ):
            raise PluginStateError("stop the plugin successfully before unregistering")
        del self._entries[name]

    def status(self, name: str) -> PluginInfo:
        self._check_loop()
        entry = self._entry(name)
        return PluginInfo(entry.name, entry.state, len(entry.calls), entry.error_type)

    def list_plugins(self) -> list[PluginInfo]:
        """Return immutable snapshots in registration order."""
        self._check_loop()
        return [self.status(name) for name in self._entries]

    @staticmethod
    def _observe(task: asyncio.Task[None]) -> None:
        # Retrieve failures even when the sole waiter was cancelled.
        if not task.cancelled():
            task.exception()

    def _own(self, entry: _Entry, work: Any) -> asyncio.Task[None]:
        task = asyncio.create_task(work)
        task.add_done_callback(self._observe)
        entry.lifecycle = task
        return task

    async def _cleanup_callback(self, entry: _Entry) -> None:
        assert entry.instance is not None
        token = _callbacks.set(_callbacks.get() | {self})
        try:
            await entry.instance.aclose()
        except BaseException as exc:
            entry.error_type = type(exc).__name__
            raise
        else:
            entry.instance = None
        finally:
            _callbacks.reset(token)

    async def _cleanup(self, entry: _Entry) -> None:
        task = asyncio.create_task(self._cleanup_callback(entry))
        cancelled = False
        while not task.done():
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                cancelled = True
        task.result()
        if cancelled:
            raise asyncio.CancelledError

    async def _start(self, entry: _Entry) -> None:
        async with entry.lock:
            token = _callbacks.set(_callbacks.get() | {self})
            try:
                instance = entry.factory()
                if inspect.isawaitable(instance):
                    if inspect.iscoroutine(instance):
                        instance.close()
                    raise TypeError("factory must return a plugin synchronously")
                if not all(
                    callable(getattr(instance, method, None))
                    for method in ("start", "invoke", "aclose")
                ):
                    raise TypeError("plugin must implement start, invoke, and aclose")
                entry.instance = instance
                await entry.instance.start()
            except BaseException as exc:
                if entry.state != PluginState.STOPPING:
                    entry.state = PluginState.FAILED
                entry.error_type = type(exc).__name__
                if entry.instance is not None:
                    try:
                        await self._cleanup(entry)
                    except BaseException as cleanup:  # noqa: BLE001 - preserve cancellation with cleanup failure
                        raise BaseExceptionGroup(
                            "startup and cleanup failed", [exc, cleanup]
                        ) from None
                raise
            else:
                if entry.state == PluginState.STARTING:
                    entry.state = PluginState.RUNNING
                entry.error_type = None
            finally:
                _callbacks.reset(token)

    async def start(self, name: str) -> None:
        await self._start_named(name)

    async def _start_named(self, name: str, owner: object | None = None) -> None:
        self._lifecycle_check()
        self._open()
        entry = self._entry(name)
        if entry.batch_owner is not None and entry.batch_owner is not owner:
            raise PluginStateError("plugin belongs to an active start_all operation")
        if entry.state == PluginState.STARTING:
            assert entry.lifecycle is not None
            task = entry.lifecycle
        elif entry.state == PluginState.RUNNING:
            return
        else:
            if entry.instance is not None or (
                entry.lifecycle and not entry.lifecycle.done()
            ):
                raise PluginStateError("plugin still owns resources or is stopping")
            entry.state = PluginState.STARTING
            entry.error_type = None
            task = self._own(entry, self._start(entry))
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            if not task.cancelling():
                task.cancel()
            # A second cancellation must not interrupt the owned cleanup.
            while not task.done():
                try:
                    await asyncio.shield(task)
                except asyncio.CancelledError:
                    continue
                except BaseException:  # noqa: BLE001 - owned failure is already observed
                    break
            if entry.state == PluginState.RUNNING:
                cleanup = self._begin_stop(entry)
                if cleanup is not None:
                    while not cleanup.done():
                        try:
                            await asyncio.shield(cleanup)
                        except asyncio.CancelledError:
                            continue
                        except BaseException:  # noqa: BLE001 - cleanup failure is recorded
                            break
            if entry.state == PluginState.STARTING and task.cancelled():
                entry.state = PluginState.FAILED
                entry.error_type = "CancelledError"
            raise

    async def start_all(self) -> None:
        """Start a snapshot in order; failure rolls back only this batch's entries."""
        self._lifecycle_check()
        self._open()
        if self._batch_task is None or self._batch_task.done():
            entries = [
                e for e in self._entries.values() if e.state != PluginState.RUNNING
            ]
            if any(
                e.state in (PluginState.STARTING, PluginState.STOPPING) for e in entries
            ):
                raise PluginStateError("another lifecycle operation is active")
            owner = object()
            for entry in entries:
                entry.batch_owner = owner
            self._batch_task = asyncio.create_task(self._start_batch(entries, owner))
            self._batch_task.add_done_callback(self._observe)

            def release(done: asyncio.Task[None]) -> None:
                for entry in entries:
                    if entry.batch_owner is owner:
                        entry.batch_owner = None

            self._batch_task.add_done_callback(release)
        task = self._batch_task
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            if not task.cancelling():
                task.cancel()
            while not task.done():
                try:
                    await asyncio.shield(task)
                except asyncio.CancelledError:
                    continue
                except BaseException:  # noqa: BLE001 - owned task failure is retrieved below
                    break
            failure = None if task.cancelled() else task.exception()
            if failure is not None:
                raise BaseExceptionGroup(
                    "batch cancellation and rollback failed",
                    [
                        asyncio.CancelledError(),
                        failure,
                    ],
                )
            raise

    async def _start_batch(self, entries: list[_Entry], owner: object) -> None:
        attempted: list[_Entry] = []
        try:
            for entry in entries:
                # Failed retained instances belong to earlier operations, not this batch.
                if entry.instance is not None:
                    raise PluginStateError("plugin still owns resources")
                attempted.append(entry)
                await self._start_named(entry.name, owner)
        except BaseException as original:
            errors: list[BaseException] = [original]
            for entry in reversed(attempted):
                task = self._begin_stop(entry)
                if task is None:
                    continue
                while not task.done():
                    try:
                        await asyncio.shield(task)
                    except asyncio.CancelledError:
                        continue
                    except BaseException:  # noqa: BLE001 - owned task failure is retrieved below
                        break
                try:
                    task.result()
                except BaseException as exc:  # noqa: BLE001 - preserve cleanup failures and cancellation
                    errors.append(exc)
            if len(errors) > 1:
                raise BaseExceptionGroup(
                    "batch startup and rollback failed", errors
                ) from None
            raise
        finally:
            for entry in entries:
                entry.batch_owner = None

    async def _stop(self, entry: _Entry, previous: asyncio.Task[None] | None) -> None:
        if previous is not None and not previous.done():
            try:
                await asyncio.shield(previous)
            except BaseException:  # noqa: BLE001, S110 - startup owns and reports its failure
                pass  # Retry any retained resources below.
        async with entry.lock:
            entry.state = PluginState.STOPPING
            calls = list(entry.calls)
            for task in calls:
                task.cancel()
            if calls:
                await asyncio.gather(*calls, return_exceptions=True)
            if entry.instance is not None:
                try:
                    await self._cleanup(entry)
                except BaseException:
                    entry.state = PluginState.FAILED
                    raise
            entry.state = PluginState.STOPPED
            entry.error_type = None

    def _begin_stop(self, entry: _Entry) -> asyncio.Task[None] | None:
        if entry.state == PluginState.STOPPING:
            return entry.lifecycle
        if entry.instance is None and entry.state != PluginState.STARTING:
            entry.state = PluginState.STOPPED
            entry.error_type = None
            return None
        previous = entry.lifecycle
        if (
            entry.state == PluginState.STARTING
            and previous is not None
            and not previous.cancelling()
        ):
            previous.cancel()
        entry.state = PluginState.STOPPING
        return self._own(entry, self._stop(entry, previous))

    async def stop(self, name: str) -> None:
        self._lifecycle_check()
        entry = self._entry(name)
        if entry.batch_owner is not None:
            raise PluginStateError("plugin belongs to an active start_all operation")
        task = self._begin_stop(entry)
        if task is not None:
            await asyncio.shield(task)

    async def _invoke(
        self, entry: _Entry, operation: str, payload: Mapping[str, Any], timeout: float
    ) -> dict[str, Any]:
        token = _callbacks.set(_callbacks.get() | {self})
        try:
            assert entry.instance is not None
            async with asyncio.timeout(timeout):
                result = await entry.instance.invoke(operation, payload)
            if not isinstance(result, Mapping):
                raise InvalidPluginResultError("plugin result must be a mapping")
            return deepcopy(dict(result))
        finally:
            _callbacks.reset(token)

    async def call(
        self,
        name: str,
        operation: str,
        payload: Mapping[str, Any],
        *,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        self._check_loop(required=True)
        self._open()
        entry = self._entry(name)
        if entry.state != PluginState.RUNNING:
            raise PluginStateError("plugin must be running before call")
        if not isinstance(operation, str) or not operation.strip():
            raise ValueError("operation must be a nonempty string")
        seconds = self._timeout if timeout is None else self._validate_timeout(timeout)
        if not isinstance(payload, Mapping):
            raise TypeError("payload must be a mapping")
        copied = deepcopy(dict(payload))
        task = asyncio.create_task(self._invoke(entry, operation, copied, seconds))
        entry.calls.add(task)
        task.add_done_callback(entry.calls.discard)
        try:
            return await task
        finally:
            if task.done():
                entry.calls.discard(task)

    async def _close(self) -> None:
        errors: list[BaseException] = []
        if self._batch_task is not None and not self._batch_task.done():
            if not self._batch_task.cancelling():
                self._batch_task.cancel()
            batch_results = await asyncio.gather(
                self._batch_task, return_exceptions=True
            )
            errors.extend(
                error
                for error in batch_results
                if isinstance(error, BaseException)
                and not isinstance(error, asyncio.CancelledError)
            )
        tasks = [
            task
            for entry in self._entries.values()
            if (task := self._begin_stop(entry)) is not None
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        errors.extend(result for result in results if isinstance(result, BaseException))
        if errors:
            raise BaseExceptionGroup("plugin cleanup failed", errors)

    async def aclose(self) -> None:
        """Terminal close. Concurrent callers share work; subsequent calls retry failures."""
        self._lifecycle_check()
        self._closed = True
        if self._close_task is None or (
            self._close_task.done()
            and any(e.instance is not None for e in self._entries.values())
        ):
            self._close_task = asyncio.create_task(self._close())
            self._close_task.add_done_callback(self._observe)
        await asyncio.shield(self._close_task)

    async def __aenter__(self) -> Self:
        self._check_loop(required=True)
        self._open()
        return self

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
        await self.aclose()
