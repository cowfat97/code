"""Local PostgreSQL MCP server. Credentials use libpq's PG* environment/pgpass."""

import asyncio
import os
from contextlib import contextmanager
from typing import Any

from mcp.server.fastmcp import FastMCP

server = FastMCP("pgmcp")
_database_slots = asyncio.Semaphore(4)


@contextmanager
def transaction(*, readonly: bool):
    timeout = int(os.environ.get("PGMCP_STATEMENT_TIMEOUT_MS", "10000"))
    if not 1 <= timeout <= 300000:
        raise ValueError("PGMCP_STATEMENT_TIMEOUT_MS must be between 1 and 300000")
    # This server never supplies a default password or silently changes databases.
    if not os.environ.get("PGDATABASE") or not os.environ.get("PGUSER"):
        raise ValueError("configure PGDATABASE and PGUSER before calling pgmcp")
    try:
        import psycopg
    except ImportError:
        raise RuntimeError("install tools/requirements-mcp.txt to enable PostgreSQL") from None
    try:
        with psycopg.connect(connect_timeout=5) as connection:
            with connection.transaction():
                if readonly:
                    connection.execute("SET TRANSACTION READ ONLY")
                connection.execute(
                    "SELECT set_config('statement_timeout', %s, true)", (str(timeout),)
                )
                yield connection
    except psycopg.Error:
        # Do not forward credentials, query parameters or connection diagnostics to the model.
        raise RuntimeError("PostgreSQL operation failed; transaction rolled back") from None


def limit_value(value: int) -> int:
    if isinstance(value, bool) or not 1 <= value <= 1000:
        raise ValueError("max_rows must be between 1 and 1000")
    return value


def run_sql(
    sql: str,
    parameters: list[Any] | dict[str, Any] | None,
    *,
    readonly: bool,
    max_rows: int,
) -> dict[str, Any]:
    if not sql.strip():
        raise ValueError("sql must not be blank")
    max_rows = limit_value(max_rows)
    with transaction(readonly=readonly) as connection:
        # Extended protocol rejects multiple statements, even when no parameters are supplied.
        cursor = connection.execute(sql, parameters or (), prepare=True)
        columns = [c.name for c in cursor.description] if cursor.description else []
        rows = cursor.fetchmany(max_rows + 1) if columns else []
        return {
            "columns": columns,
            "rows": [list(row) for row in rows[:max_rows]],
            "truncated": len(rows) > max_rows,
            "rowcount": cursor.rowcount,
        }


async def _database_call(sql, parameters, *, readonly, max_rows):
    # Cancelling an MCP request cannot kill a DB thread. Retain capacity until it ends.
    async with _database_slots:
        worker = asyncio.create_task(
            asyncio.to_thread(run_sql, sql, parameters, readonly=readonly, max_rows=max_rows)
        )
        try:
            return await asyncio.shield(worker)
        except asyncio.CancelledError:
            await asyncio.gather(worker, return_exceptions=True)
            raise


@server.tool()
async def query(
    sql: str, parameters: list[Any] | dict[str, Any] | None = None, max_rows: int = 100
) -> dict[str, Any]:
    """Execute one parameterized SQL statement in a read-only transaction."""
    return await asyncio.to_thread(run_sql, sql, parameters, readonly=True, max_rows=max_rows)


@server.tool()
async def execute(
    sql: str, parameters: list[Any] | dict[str, Any] | None = None, max_rows: int = 100
) -> dict[str, Any]:
    """Execute one write statement; commit success or roll back failure. No automatic retries."""
    return await asyncio.to_thread(run_sql, sql, parameters, readonly=False, max_rows=max_rows)


@server.tool()
async def list_tables(schema: str = "public") -> dict[str, Any]:
    """List tables in a schema, up to 1000 rows."""
    return await query(
        "SELECT table_schema,table_name,table_type FROM information_schema.tables "
        "WHERE table_schema=%s ORDER BY table_name",
        [schema],
        1000,
    )


@server.tool()
async def describe_table(table: str, schema: str = "public") -> dict[str, Any]:
    """Read column names, types, nullability and defaults for one table."""
    return await query(
        "SELECT column_name,data_type,is_nullable,column_default "
        "FROM information_schema.columns WHERE table_schema=%s AND table_name=%s "
        "ORDER BY ordinal_position",
        [schema, table],
        1000,
    )


if __name__ == "__main__":
    server.run(transport="stdio")
