import copy
import json
import unittest
from unittest.mock import patch

from agent.core.workflow import core_loop
from agent.entities.memory import MemorySnapshot, MemoryConflictError, MemoryStorageError


class Store:
    def __init__(self, messages=(), revision=0):
        self.messages = copy.deepcopy(list(messages))
        self.revision = revision
        self.saves = 0

    def load(self):
        return MemorySnapshot(copy.deepcopy(self.messages), self.revision)

    def save(self, revision, messages):
        if revision != self.revision:
            raise MemoryConflictError("conflict")
        self.messages = copy.deepcopy(messages)
        self.revision += 1
        self.saves += 1
        return self.revision


def answer(text="ok"):
    return json.dumps({"thought":"","action":"answer","argument":text})


class PersistentChatTests(unittest.TestCase):
    def test_fresh_calls_restore_store_and_memory_search(self):
        store = Store()
        with patch.object(core_loop,"_generate",return_value=answer()):
            core_loop.chat("apple",store=store)
        seen = []
        def generate(turns, tools, allowed_actions):
            seen.append(tools["memory_search"].execute("apple"))
            return answer()
        with patch.object(core_loop,"_generate",side_effect=generate):
            reply, count, chars = core_loop.chat("next",store=store)
        self.assertEqual(seen,[{"matches":["apple"],"found":True}])
        self.assertEqual((reply,count),("ok",5))
        self.assertEqual(store.revision,2)
        self.assertEqual(chars,sum(len(m["content"]) for m in store.messages))

    def test_generation_failure_does_not_save(self):
        store=Store([{"role":"user","content":"committed"}],1)
        with patch.object(core_loop,"_generate",side_effect=RuntimeError("model failed")):
            with self.assertRaises(RuntimeError):
                core_loop.chat("new",store=store)
        self.assertEqual(store.messages,[{"role":"user","content":"committed"}])
        self.assertEqual(store.saves,0)

    def test_load_failure_never_calls_model(self):
        store=Store()
        with patch.object(store,"load",side_effect=MemoryStorageError("offline")), patch.object(
                core_loop,"_generate") as generate:
            with self.assertRaises(MemoryStorageError):
                core_loop.chat("new",store=store)
        generate.assert_not_called()
        self.assertEqual(store.saves,0)

    def test_save_failure_never_returns_success_or_changes_memory(self):
        for error in [MemoryStorageError("offline"),MemoryConflictError("changed")]:
            store=Store()
            with patch.object(core_loop,"_generate",return_value=answer()), patch.object(
                    store,"save",side_effect=error):
                with self.assertRaises(type(error)) as caught:
                    core_loop.chat("new",store=store)
            self.assertIs(caught.exception,error)
            self.assertEqual(store.messages,[])

    def test_default_uses_pg_store_factory(self):
        store=Store()
        with patch.object(core_loop,"get_memory_store",return_value=store), patch.object(
                core_loop,"_generate",return_value=answer()):
            self.assertEqual(core_loop.chat("new")[0],"ok")
        self.assertEqual(store.saves,1)
