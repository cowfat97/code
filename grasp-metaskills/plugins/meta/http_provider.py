"""Internal, stateless HTTP adapter for OpenAI-compatible chat endpoints."""

from __future__ import annotations

import os

import httpx

from .models import LLMConfig
from .planner import MetaProviderError, MetaProviderUnavailable, MetaTimeoutError


class OpenAICompatibleProvider:
    def __init__(self, config: LLMConfig) -> None:
        self.config = config.model_copy(deep=True)

    async def complete(self, prompt: str) -> str:
        headers: dict[str, str] = {}
        if self.config.api_key_env is not None:
            key = os.environ.get(self.config.api_key_env)
            if key is None or not key.strip():
                raise MetaProviderUnavailable(
                    f"LLM API key environment variable is missing: {self.config.api_key_env}"
                )
            headers["Authorization"] = f"Bearer {key}"
        try:
            async with httpx.AsyncClient(
                timeout=self.config.timeout, trust_env=False, follow_redirects=False
            ) as client:
                response = await client.post(
                    self.config.base_url.rstrip("/") + "/chat/completions",
                    headers=headers,
                    json={
                        "model": self.config.model,
                        "messages": [{"role": "user", "content": prompt}],
                        "stream": False,
                    },
                )
            if not 200 <= response.status_code < 300:
                raise MetaProviderError("model endpoint returned an unsuccessful HTTP status")
            data = response.json()
            choices = data.get("choices") if isinstance(data, dict) else None
            if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
                raise MetaProviderError("model endpoint returned an invalid response")
            message = choices[0].get("message")
            content = message.get("content") if isinstance(message, dict) else None
            if not isinstance(content, str) or not content.strip():
                raise MetaProviderError("model endpoint returned invalid text content")
            return content
        except httpx.TimeoutException:
            raise MetaTimeoutError("model request timed out") from None
        except MetaProviderError:
            raise
        except Exception:
            raise MetaProviderError("model endpoint request failed") from None
