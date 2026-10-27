"""Explicit-origin HTTP access without redirect or environment proxy behavior."""

from typing import Any
from urllib.parse import urlsplit

import httpx


def origin(url: str) -> str:
    parts = urlsplit(url)
    if (
        parts.scheme not in {"http", "https"}
        or not parts.hostname
        or parts.username is not None
        or parts.password is not None
    ):
        raise ValueError("URL must use http/https with a host and no userinfo")
    if any(c.isspace() or ord(c) < 32 for c in url) or "\\" in url:
        raise ValueError("invalid URL")
    port = (
        parts.port
        if parts.port is not None
        else (443 if parts.scheme == "https" else 80)
    )
    if port == 0:
        raise ValueError("URL port must be positive")
    host = parts.hostname.lower()
    return f"{parts.scheme}://{host}:{port}"


class HTTPTools:
    def __init__(self, allowed_origins: list[str], max_bytes: int):
        self.allowed = set()
        for value in allowed_origins:
            parsed = urlsplit(value)
            if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
                raise ValueError("http_allowed_origins must contain origins only")
            self.allowed.add(origin(value))
        self.max_bytes = max_bytes

    async def http_request(
        self,
        url: str,
        method: str = "GET",
        headers: dict[str, str] | None = None,
        body: str | None = None,
    ) -> dict[str, Any]:
        """Call an explicitly allowed origin; redirects are returned, never followed."""
        if origin(url) not in self.allowed:
            raise PermissionError(
                "HTTP origin is not configured in http_allowed_origins"
            )
        if method.upper() not in {
            "GET",
            "POST",
            "PUT",
            "PATCH",
            "DELETE",
            "HEAD",
            "OPTIONS",
        }:
            raise ValueError("unsupported HTTP method")
        if headers and any(key.lower() == "host" for key in headers):
            raise ValueError("Host header overrides are not allowed")
        request_headers = {"Accept-Encoding": "identity", **(headers or {})}
        content = body.encode("utf-8") if body is not None else None
        if content is not None and len(content) > self.max_bytes:
            raise ValueError("request body exceeds max_response_bytes")
        async with (
            httpx.AsyncClient(trust_env=False, follow_redirects=False) as client,
            client.stream(
                method.upper(), url, headers=request_headers, content=content
            ) as response,
        ):
            chunks = bytearray()
            async for chunk in response.aiter_bytes(
                chunk_size=min(self.max_bytes + 1, 65536)
            ):
                chunks.extend(chunk)
                if len(chunks) > self.max_bytes:
                    raise ValueError("HTTP response exceeds max_response_bytes")
            return {
                "url": str(response.url),
                "status_code": response.status_code,
                "headers": dict(response.headers),
                "text": bytes(chunks).decode(
                    response.encoding or "utf-8", errors="replace"
                ),
            }
