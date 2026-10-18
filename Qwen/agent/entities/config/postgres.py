"""PG 连接配置；密码由 libpq 环境变量或密码文件提供。"""

from dataclasses import dataclass


@dataclass(frozen=True)
class PostgresConfig:
    host: str = "127.0.0.1"
    port: int = 5433
    dbname: str = "dev"
    user: str = "dev"
    connect_timeout: int = 5
    statement_timeout_ms: int = 5000
