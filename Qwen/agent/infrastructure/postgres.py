"""代码内部的 PG 工具：短事务、参数绑定、超时和连接释放。"""

from contextlib import contextmanager
from agent.common.config import get_postgres_config


class DatabaseError(RuntimeError):
    """对调用方公开不含连接凭据的错误。"""


class Postgres:
    def __init__(self, config=None):
        self.config = config if config is not None else get_postgres_config()

    @contextmanager
    def transaction(self):
        try:
            import psycopg
        except ImportError as exc:
            raise DatabaseError("缺少 psycopg，请安装项目 requirements.txt 中的 PG 驱动") from exc
        try:
            with psycopg.connect(
                host=self.config.host, port=self.config.port,
                dbname=self.config.dbname, user=self.config.user,
                connect_timeout=self.config.connect_timeout,
                options=f"-c statement_timeout={self.config.statement_timeout_ms}",
            ) as connection:
                yield connection
        except psycopg.Error as exc:
            raise DatabaseError("PostgreSQL 操作失败，请检查连接配置、数据库状态或初始化 migration") from exc

    def fetch_all(self, query, params=()):
        with self.transaction() as connection:
            return connection.execute(query, params).fetchall()

    def execute(self, query, params=()):
        with self.transaction() as connection:
            return connection.execute(query, params).rowcount
