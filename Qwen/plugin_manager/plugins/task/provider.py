"""Task-owned, bounded OpenAI-compatible HTTP client; no shared planner dependency."""

from __future__ import annotations

import json
import math
import os
import re
from typing import Any
from urllib.parse import urlsplit

import httpx


class OpenAIProvider:
    def __init__(self, config: dict[str, Any]) -> None:
        if set(config) - {"base_url", "model", "api_key_env", "timeout"}:
            raise ValueError("Unknown task llm configuration")
        base = config.get("base_url")
        if not isinstance(base, str):
            raise TypeError("Task llm base_url is required")
        try:
            parsed = urlsplit(base)
            port = parsed.port
        except ValueError:
            raise ValueError("Invalid task llm base_url") from None
        if (
            base != base.strip()
            or any(c.isspace() or ord(c) < 32 for c in base)
            or parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or "?" in base
            or "#" in base
            or "\\" in base
            or port == 0
        ):
            raise ValueError("Invalid task llm base_url")
        self.base_url = base.rstrip("/")
        model = config.get("model")
        if not isinstance(model, str) or not model.strip():
            raise ValueError("Task llm model is required")
        self.model = model
        timeout = config.get("timeout", 60.0)
        if (
            isinstance(timeout, bool)
            or not isinstance(timeout, (int, float))
            or not math.isfinite(timeout)
            or timeout <= 0
        ):
            raise ValueError("Task llm timeout must be positive and finite")
        self.timeout = float(timeout)
        key_env = config.get("api_key_env")
        if key_env is not None and (
            not isinstance(key_env, str)
            or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key_env)
        ):
            raise ValueError("api_key_env must be an environment variable name")
        self.key_env = key_env

    async def complete(self, prompt: str) -> str:
        headers = {"Accept-Encoding": "identity"}
        if self.key_env is not None:
            key = os.environ.get(self.key_env)
            if key is None or not key.strip():
                raise RuntimeError("Task llm API key environment variable is missing")
            headers["Authorization"] = f"Bearer {key}"
        try:
            async with (
                httpx.AsyncClient(
                    timeout=self.timeout, trust_env=False, follow_redirects=False
                ) as client,
                client.stream(
                    "POST",
                    self.base_url + "/chat/completions",
                    headers=headers,
                    json={
                        "model": self.model,
                        "messages": [{"role": "user", "content": prompt}],
                        "stream": False,
                    },
                ) as response,
            ):
                if not 200 <= response.status_code < 300:
                    raise RuntimeError(f"Task llm HTTP status {response.status_code}")
                body = bytearray()
                async for chunk in response.aiter_bytes(chunk_size=16384):
                    body.extend(chunk)
                    if len(body) > 1_000_000:
                        raise ValueError("Task llm response too large")
        except httpx.TimeoutException:
            raise TimeoutError("Task model request timed out") from None
        except httpx.HTTPError:
            raise RuntimeError("Task model request failed") from None
        value = json.loads(body)
        try:
            content = value["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ValueError("Invalid task llm response") from exc
        if not isinstance(content, str) or not content.strip():
            raise ValueError("Task llm content must be nonempty text")
        return content
