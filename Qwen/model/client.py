"""Stateless asynchronous OpenAI-compatible chat transport."""

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

from .config import ModelConfig, ModelError


class ModelRequestError(ModelError):
    """Invalid request or unsuccessful HTTP transport/status."""


class ModelResponseError(ModelError):
    """Missing, malformed, or oversized model response."""


class ModelTimeoutError(ModelError, TimeoutError):
    """The HTTP request timed out."""


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments: str


@dataclass(frozen=True)
class ChatResponse:
    content: str | None
    tool_calls: tuple[ToolCall, ...] = ()
    model: str | None = None
    usage: Mapping[str, Any] = field(default_factory=dict)


_MAX_REQUEST_BYTES = 2_000_000
_ROLES = {"system", "developer", "user", "assistant", "tool"}


def _parse_response(data: Any) -> ChatResponse:
    try:
        if not isinstance(data, dict):
            raise TypeError
        choices = data["choices"]
        if not isinstance(choices, list) or not choices:
            raise ValueError
        message = choices[0]["message"]
        if not isinstance(message, dict):
            raise TypeError
        content = message.get("content")
        if content is not None and not isinstance(content, str):
            raise ValueError
        raw_calls = message.get("tool_calls", [])
        if not isinstance(raw_calls, list):
            raise TypeError
        calls = []
        for call in raw_calls:
            if not isinstance(call, dict) or call.get("type") != "function":
                raise ValueError
            function = call["function"]
            call_id, name, arguments = (
                call["id"],
                function["name"],
                function["arguments"],
            )
            if not all(isinstance(v, str) and v for v in (call_id, name)):
                raise ValueError
            if not isinstance(arguments, str):
                raise TypeError
            calls.append(ToolCall(call_id, name, arguments))
        if content is None and not calls:
            raise ValueError
        model, usage = data.get("model"), data.get("usage", {})
        if model is not None and not isinstance(model, str):
            raise ValueError
        if not isinstance(usage, dict):
            raise TypeError
        return ChatResponse(content, tuple(calls), model, usage)
    except (KeyError, IndexError, TypeError, ValueError):
        raise ModelResponseError("Malformed model response") from None


class ModelClient:
    """Caller owns history and tool execution; each call closes its HTTP client."""

    def __init__(
        self, config: ModelConfig | None = None, *, env_file: str | Path | None = None
    ) -> None:
        if config is not None and env_file is not None:
            raise ModelRequestError("Pass config or env_file, not both")
        self.config = config if config is not None else ModelConfig.from_env(env_file)
        if not isinstance(self.config, ModelConfig):
            raise ModelRequestError("config must be a ModelConfig")

    async def chat(
        self,
        messages: Sequence[Mapping[str, Any]],
        *,
        tools: Sequence[Mapping[str, Any]] | None = None,
        tool_choice: str | Mapping[str, Any] | None = None,
    ) -> ChatResponse:
        try:
            if (
                isinstance(messages, (str, bytes))
                or not isinstance(messages, Sequence)
                or not messages
            ):
                raise ValueError
            copied = []
            for message in messages:
                if (
                    not isinstance(message, Mapping)
                    or message.get("role") not in _ROLES
                ):
                    raise ValueError
                if "content" not in message or (
                    message["content"] is not None
                    and not isinstance(message["content"], str)
                ):
                    raise ValueError
                copied.append(dict(message))
            payload: dict[str, Any] = {
                "model": self.config.model_name,
                "messages": copied,
                "stream": False,
            }
            if tools is not None:
                if isinstance(tools, (str, bytes)) or not isinstance(tools, Sequence):
                    raise ValueError
                payload["tools"] = [dict(tool) for tool in tools]
            if tool_choice is not None:
                if not isinstance(tool_choice, (str, Mapping)):
                    raise ValueError
                payload["tool_choice"] = (
                    dict(tool_choice)
                    if isinstance(tool_choice, Mapping)
                    else tool_choice
                )
            body = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode(
                "utf-8"
            )
            if len(body) > _MAX_REQUEST_BYTES:
                raise ValueError
        except (ValueError, TypeError, OverflowError, RecursionError):
            raise ModelRequestError("Invalid or oversized model request") from None
        headers = {"Content-Type": "application/json", "Accept-Encoding": "identity"}
        if self.config.api_key:
            headers["Authorization"] = f"Bearer {self.config.api_key}"
        try:
            async with (
                httpx.AsyncClient(
                    timeout=self.config.timeout, trust_env=False, follow_redirects=False
                ) as client,
                client.stream(
                    "POST",
                    self.config.base_url.rstrip("/") + "/chat/completions",
                    content=body,
                    headers=headers,
                ) as response,
            ):
                if not 200 <= response.status_code < 300:
                    raise ModelRequestError(
                        f"Model HTTP request failed ({response.status_code})"
                    )
                chunks = bytearray()
                async for chunk in response.aiter_bytes(chunk_size=16384):
                    if len(chunks) + len(chunk) > self.config.max_response_bytes:
                        raise ModelResponseError("Model response exceeds size limit")
                    chunks.extend(chunk)
            try:
                data = json.loads(chunks)
            except (ValueError, UnicodeError, RecursionError):
                raise ModelResponseError("Model response is not valid JSON") from None
            return _parse_response(data)
        except httpx.TimeoutException:
            raise ModelTimeoutError("Model request timed out") from None
        except httpx.HTTPError:
            raise ModelRequestError("Model HTTP transport failed") from None

    async def complete(self, prompt: str) -> str:
        if not isinstance(prompt, str) or not prompt.strip():
            raise ModelRequestError("prompt must be a nonempty string")
        response = await self.chat([{"role": "user", "content": prompt}])
        if response.content is None or not response.content.strip():
            raise ModelResponseError("Model returned no text completion")
        return response.content
