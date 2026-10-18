import unittest
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import patch

from agent.entities.config.postgres import PostgresConfig
from agent.entities.memory import MemoryStorageError
from agent.infrastructure.memory_store import PgMemoryStore
from agent.infrastructure.postgres import Postgres, DatabaseError


class StorageFailureTests(unittest.TestCase):
    def test_commit_failure_cannot_return_saved_revision(self):
        class DriverError(Exception): pass
        class Connection:
            def __enter__(self): return self
            def execute(self, *args):
                return SimpleNamespace(fetchone=lambda: (1,))
            def __exit__(self, *args):
                raise DriverError("password=must-not-be-exposed")
        driver=SimpleNamespace(Error=DriverError,connect=lambda **kw: Connection())
        store=PgMemoryStore(Postgres(PostgresConfig()))
        with patch.dict("sys.modules",{"psycopg":driver}):
            with self.assertRaises(MemoryStorageError) as caught:
                store.save(0,[])
        self.assertNotIn("must-not-be-exposed",str(caught.exception))
        self.assertIsInstance(caught.exception.__cause__,DatabaseError)

    def test_corrupted_database_history_is_not_used(self):
        database=SimpleNamespace(fetch_all=lambda *a: [([{"role":"user","content":17}],1)])
        with self.assertRaises(MemoryStorageError):
            PgMemoryStore(database).load()

    def test_missing_driver_is_explicit(self):
        with patch.dict("sys.modules",{"psycopg":None}):
            with self.assertRaisesRegex(DatabaseError,"psycopg"):
                Postgres(PostgresConfig()).fetch_all("SELECT 1")
