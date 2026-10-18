"""真实 PG 集成测试：仅操作本次创建的独立临时数据库。"""
import concurrent.futures
from dataclasses import replace
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from uuid import uuid4

from agent.common.config import get_postgres_config
from agent.entities.memory import MemoryConflictError, MemoryStorageError
from agent.infrastructure.memory_store import PgMemoryStore, initialize
from agent.infrastructure.postgres import Postgres, DatabaseError


@unittest.skipUnless(os.getenv("QWEN_TEST_PG") == "1", "set QWEN_TEST_PG=1 for isolated real PG tests")
class PgMemoryIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import psycopg
        from psycopg import sql
        cls.config=get_postgres_config()
        cls.test_db="qwen_memory_test_"+uuid4().hex
        kwargs=dict(host=cls.config.host,port=cls.config.port,user=cls.config.user,
                    dbname=cls.config.dbname,connect_timeout=5)
        cls.admin=psycopg.connect(**kwargs,autocommit=True)
        cls.addClassCleanup(cls.admin.close)
        cls.admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(cls.test_db)))
        cls.addClassCleanup(cls._drop_database)
        cls.database=Postgres(replace(cls.config,dbname=cls.test_db))
        initialize(cls.database)

    @classmethod
    def _drop_database(cls):
        from psycopg import sql
        # This name was generated here, never provided by the application.
        assert cls.test_db.startswith("qwen_memory_test_") and len(cls.test_db)==49
        cls.admin.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(cls.test_db)))

    def setUp(self):
        self.database.execute("DELETE FROM qwen.memory")
        self.store=PgMemoryStore(self.database)

    def test_roundtrip_unicode_quotes_and_new_store_instance(self):
        value=[{"role":"user","content":"苹果 ' ; DROP TABLE qwen.memory; --"}]
        self.assertEqual(self.store.load().revision,0)
        self.assertEqual(self.store.save(0,value),1)
        value[0]["content"]="mutated locally"
        loaded=PgMemoryStore(self.database).load()
        self.assertEqual(loaded.messages,[{"role":"user","content":"苹果 ' ; DROP TABLE qwen.memory; --"}])
        loaded.messages.clear()
        self.assertEqual(self.store.load().revision,1)
        self.assertEqual(len(self.store.load().messages),1)
        self.assertEqual(self.store.save(1,[]),2)

    def test_stale_insert_and_update_do_not_overwrite(self):
        self.store.save(0,[{"role":"user","content":"first"}])
        with self.assertRaises(MemoryConflictError):
            self.store.save(0,[{"role":"user","content":"wrong"}])
        self.store.save(1,[{"role":"user","content":"latest"}])
        with self.assertRaises(MemoryConflictError):
            self.store.save(1,[{"role":"user","content":"stale"}])
        self.assertEqual(self.store.load().messages,[{"role":"user","content":"latest"}])

    def test_concurrent_writers_have_exactly_one_winner(self):
        self.store.save(0,[])
        def save(value):
            try:
                PgMemoryStore(self.database).save(1,[{"role":"user","content":value}])
                return "saved"
            except MemoryConflictError:
                return "conflict"
        with concurrent.futures.ThreadPoolExecutor(2) as pool:
            result=list(pool.map(save,["first","second"]))
        self.assertEqual(sorted(result),["conflict","saved"])
        self.assertEqual(self.store.load().revision,2)

    def test_transaction_commit_and_rollback_release_connection(self):
        with self.database.transaction() as connection:
            connection.execute("CREATE TABLE qwen.transaction_test (value INTEGER)")
        self.assertTrue(connection.closed)
        error=ValueError("rollback")
        with self.assertRaises(ValueError) as caught:
            with self.database.transaction() as connection:
                connection.execute("INSERT INTO qwen.transaction_test VALUES (1)")
                raise error
        self.assertIs(caught.exception,error)
        self.assertTrue(connection.closed)
        self.assertEqual(self.database.fetch_all("SELECT value FROM qwen.transaction_test"),[])
        self.database.execute("INSERT INTO qwen.transaction_test VALUES (%s)",(2,))
        self.assertEqual(self.database.fetch_all("SELECT value FROM qwen.transaction_test"),[(2,)])

    def test_query_timeout_and_storage_error_are_explicit(self):
        short=Postgres(replace(self.database.config,statement_timeout_ms=50))
        with self.assertRaises(DatabaseError):
            short.fetch_all("SELECT pg_sleep(1)")
        missing=PgMemoryStore(Postgres(replace(self.database.config,dbname=self.test_db+"_absent")))
        with self.assertRaises(MemoryStorageError):
            missing.load()
        self.assertEqual(self.database.fetch_all("SELECT 1"),[(1,)])

    def test_invalid_input_does_not_change_history(self):
        for value in [None,{},[{"role":"user","content":1}],[{"role":"bad","content":"x"}]]:
            with self.assertRaises(MemoryStorageError):
                self.store.save(0,value)
        self.assertEqual(self.store.load().messages,[])
        for version in [-1,True,"1"]:
            with self.assertRaises(MemoryStorageError):
                self.store.save(version,[])

    def test_cross_process_save_restore_and_memory_search(self):
        env=dict(os.environ,PGDATABASE=self.test_db,PGHOST=self.config.host,
                 PGPORT=str(self.config.port),PGUSER=self.config.user)
        project=Path(__file__).resolve().parents[1]
        save="from agent.infrastructure.memory_store import get_memory_store; get_memory_store().save(0,[{'role':'user','content':'remember apple'}])"
        load=("import json; from agent.infrastructure.memory_store import get_memory_store; "
              "from agent.tools.memory.search import bind_history; "
              "print(json.dumps(bind_history(get_memory_store().load().messages).execute('apple')))")
        for code in [save,load]:
            result=subprocess.run([sys.executable,"-B","-c",code],cwd=project,env=env,
                                  capture_output=True,text=True,encoding="utf-8",timeout=20)
            self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(json.loads(result.stdout),{"matches":["remember apple"],"found":True})

    def test_initialize_is_idempotent_preserves_history(self):
        self.store.save(0,[{"role":"user","content":"keep"}])
        initialize(self.database)
        initialize(self.database)
        self.assertEqual(self.store.load().messages,[{"role":"user","content":"keep"}])

    def test_concurrent_first_insert_does_not_overwrite(self):
        def save(value):
            try:
                PgMemoryStore(self.database).save(0,[{"role":"user","content":value}])
                return "saved"
            except MemoryConflictError:
                return "conflict"
        with concurrent.futures.ThreadPoolExecutor(2) as pool:
            result=list(pool.map(save,["first","second"]))
        self.assertEqual(sorted(result),["conflict","saved"])
        self.assertEqual(self.store.load().revision,1)

    def test_cross_process_core_loop_recovers_committed_history(self):
        env=dict(os.environ,PGDATABASE=self.test_db,PGHOST=self.config.host,
                 PGPORT=str(self.config.port),PGUSER=self.config.user)
        project=Path(__file__).resolve().parents[1]
        save = """
import json
from unittest.mock import patch
from agent.core.workflow.chat_workflow import orchestrate_chat
answer=json.dumps({'thought':'','action':'answer','argument':'ok'})
with patch('agent.core.workflow.core_loop._generate',return_value=answer):
    orchestrate_chat('remember apple')
"""
        load = """
import json
from unittest.mock import patch
from agent.core.workflow.chat_workflow import orchestrate_chat
def generate(turns,tools,allowed_actions):
    matches=tools['memory_search'].execute('apple')
    assert matches == {'matches':['remember apple'],'found':True},matches
    return json.dumps({'thought':'','action':'answer','argument':'recovered'})
with patch('agent.core.workflow.core_loop._generate',side_effect=generate):
    print(json.dumps(orchestrate_chat('what did I say?')))
"""
        for code in [save,load]:
            result=subprocess.run([sys.executable,"-B","-c",code],cwd=project,env=env,
                                  capture_output=True,text=True,encoding="utf-8",timeout=20)
            self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(json.loads(result.stdout)[0],"recovered")
        self.assertEqual(self.store.load().revision,2)
