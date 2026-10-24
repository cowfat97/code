"""Observer contract independent of any logging or monitoring backend."""

from dataclasses import dataclass
from typing import Literal, Protocol

EventKind = Literal[
    "registered",
    "registration_failed",
    "unregistered",
    "unregistration_failed",
    "call_started",
    "call_succeeded",
    "call_failed",
    "call_timed_out",
    "call_cancelled",
    "mcp_connected",
    "mcp_connection_failed",
    "mcp_disconnected",
]


@dataclass(frozen=True)
class ToolEvent:
    kind: EventKind
    name: str
    timestamp: str
    source: str = "local"
    call_id: str | None = None
    duration_ms: float | None = None
    error_type: str | None = None


class Observer(Protocol):
    """Synchronous, nonblocking callback. Errors are isolated from execution."""

    def __call__(self, event: ToolEvent) -> object: ...
