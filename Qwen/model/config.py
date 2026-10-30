"""Environment configuration for the independent HTTP model client."""

import math
import os
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import dotenv_values


class ModelError(Exception):
    """Base error; messages never include credentials or server bodies."""


class ModelConfigError(ModelError, ValueError):
    """Invalid model configuration."""


@dataclass(frozen=True)
class ModelConfig:
    base_url: str
    model_name: str
    api_key: str = field(default="", repr=False)
    timeout: float = 60.0
    max_response_bytes: int = 2_000_000

    def __post_init__(self) -> None:
        try:
            if not isinstance(self.base_url, str) or any(
                ord(c) <= 32 or ord(c) == 127 or c == "\\" for c in self.base_url
            ):
                raise ValueError
            url = urlsplit(self.base_url)
            if (
                url.scheme not in ("http", "https")
                or not url.hostname
                or url.username is not None
                or url.password is not None
                or url.query
                or url.fragment
                or "?" in self.base_url
                or "#" in self.base_url
                or url.port == 0
                or url.netloc.endswith(":")
            ):
                raise ValueError
            if not isinstance(self.model_name, str) or not self.model_name.strip():
                raise ValueError
            if (
                not isinstance(self.api_key, str)
                or not self.api_key.isascii()
                or any(ord(c) < 32 or ord(c) == 127 for c in self.api_key)
            ):
                raise ValueError
            if (
                isinstance(self.timeout, bool)
                or not isinstance(self.timeout, (int, float))
                or not math.isfinite(self.timeout)
                or self.timeout <= 0
            ):
                raise ValueError
            if type(self.max_response_bytes) is not int or self.max_response_bytes <= 0:
                raise ValueError
        except (ValueError, TypeError, OverflowError):
            raise ModelConfigError("Invalid model configuration") from None

    @classmethod
    def from_env(cls, env_file: str | Path | None = None) -> "ModelConfig":
        path = (
            Path(env_file) if env_file is not None else Path(__file__).with_name(".env")
        )
        try:
            if env_file is not None and not path.is_file():
                raise ModelConfigError("Explicit model environment file does not exist")
            values = dotenv_values(path, interpolate=False)

            def get(key: str, default: str = "") -> str:
                value = os.environ.get(key, values.get(key, default))
                return value if value is not None else default

            raw_limit = get("MODEL_MAX_RESPONSE_BYTES", "2000000")
            if not raw_limit.isascii() or not raw_limit.isdecimal():
                raise ValueError
            return cls(
                base_url=get("MODEL_BASE_URL").strip(),
                model_name=get("MODEL_NAME").strip(),
                api_key=get("MODEL_API_KEY"),
                timeout=float(get("MODEL_TIMEOUT", "60")),
                max_response_bytes=int(raw_limit),
            )
        except (OSError, ValueError, TypeError):
            raise ModelConfigError("Unable to load valid model configuration") from None
