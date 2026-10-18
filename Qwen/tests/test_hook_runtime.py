import concurrent.futures
import threading
import unittest
from unittest.mock import patch

from agent.core.hook_runtime import HookRuntime
from agent.entities.hooks import HookSpec


class HookRuntimeTests(unittest.TestCase):
    def test_nested_events_order_and_outputs(self):
        calls = []
        def hook(name):
            return HookSpec(name, lambda e: calls.append((name, "start", e)) or None,
                            lambda e, t, r: calls.append((name, "end", e, r)))
        runtime = HookRuntime([hook("a"), hook("b")])
        with runtime.stage("root", {"v": 1}) as root:
            with runtime.stage("child", "x") as child:
                child.set_output(("reply", 2))
            root.set_output("done")
        self.assertEqual([(c[0], c[1], c[2].name) for c in calls],
                         [("a","start","root"),("b","start","root"),
                          ("a","start","child"),("b","start","child"),
                          ("b","end","child"),("a","end","child"),
                          ("b","end","root"),("a","end","root")])
        parent, child = calls[0][2], calls[2][2]
        self.assertIsNone(parent.parent_stage_id)
        self.assertEqual(child.parent_stage_id, parent.stage_id)
        self.assertEqual(child.request_id, parent.request_id)
        self.assertEqual(calls[4][3].output, ["reply", 2])
        self.assertEqual(calls[6][3].status, "success")
        self.assertGreaterEqual(calls[6][3].duration_ns, 0)

    def test_callback_failures_preserve_original_error_and_cleanup(self):
        ended = []
        def fail(*args): raise RuntimeError("monitor failed")
        good = HookSpec("good", lambda e: None, lambda e,t,r: ended.append(r))
        runtime = HookRuntime([HookSpec("start_fail", fail, fail), good,
                               HookSpec("end_fail", lambda e: None, fail)])
        error = ValueError("business failed")
        with self.assertLogs("agent.core.hook_runtime", level="WARNING"):
            with self.assertRaises(ValueError) as caught:
                with runtime.stage("root", None):
                    with runtime.stage("child", None):
                        raise error
        self.assertIs(caught.exception, error)
        self.assertEqual([r.status for r in ended], ["error", "error"])
        self.assertTrue(all(r.error_type == "ValueError" for r in ended))

    def test_cancelled_stage_cleans_up_and_propagates(self):
        ended = []
        runtime = HookRuntime([HookSpec("h", lambda e: None, lambda e,t,r: ended.append(r))])
        error = KeyboardInterrupt()
        with self.assertRaises(KeyboardInterrupt) as caught:
            with runtime.stage("root", None): raise error
        self.assertIs(caught.exception, error)
        self.assertEqual(ended[0].status, "cancelled")

    def test_snapshots_are_independent_even_between_start_and_end(self):
        seen = []
        def mutate(e):
            e.input["values"].append("bad")
            return None
        def mutate_end(e,t,r): r.output.append("bad")
        runtime = HookRuntime([HookSpec("observer", lambda e: seen.append(e.input), lambda e,t,r: seen.append((e.input,r.output))),
                               HookSpec("mutator", mutate, mutate_end)])
        source, output = {"values": []}, ["ok"]
        with runtime.stage("root", source) as stage:
            source["values"].append("business")
            stage.set_output(output)
        self.assertEqual(source, {"values": ["business"]})
        self.assertEqual(output, ["ok"])
        self.assertEqual(seen, [{"values":[]}, ({"values":[]}, ["ok"])])

    def test_unserializable_values_do_not_break_business(self):
        results = []
        cyclic = []
        cyclic.append(cyclic)
        runtime = HookRuntime([HookSpec("h", lambda e: results.append(e.input),
                                       lambda e,t,r: results.append(r.output))])
        with self.assertLogs("agent.core.hook_runtime", level="WARNING"):
            with runtime.stage("root", cyclic) as stage:
                stage.set_output(object())
        self.assertTrue(all(isinstance(v, str) for v in results))

    def test_error_with_broken_str_is_preserved(self):
        class Broken(ValueError):
            def __str__(self): raise RuntimeError("broken str")
        error = Broken()
        with self.assertRaises(Broken) as caught:
            with HookRuntime().stage("root", None): raise error
        self.assertIs(caught.exception, error)

    def test_concurrent_requests_do_not_share_parent_or_tokens(self):
        barrier = threading.Barrier(2)
        def run(value):
            events = []
            runtime = HookRuntime([HookSpec("h", lambda e: e.stage_id,
                lambda e,t,r: events.append((e,t)))])
            with runtime.stage("root", value):
                barrier.wait(timeout=5)
                with runtime.stage("child", value): pass
            return events
        with concurrent.futures.ThreadPoolExecutor(2) as pool:
            first, second = list(pool.map(run, (1,2)))
        self.assertNotEqual(first[0][0].request_id, second[0][0].request_id)
        for child, root in (first, second):
            self.assertEqual(child[0].parent_stage_id, root[0].stage_id)
            self.assertEqual(child[1], child[0].stage_id)

    def test_empty_runtime_and_business_values(self):
        with HookRuntime().stage("root", None) as stage:
            stage.set_output("ok")

    def test_end_failure_does_not_replace_success(self):
        def fail(*args): raise RuntimeError("end failed")
        with self.assertLogs("agent.core.hook_runtime", level="WARNING"):
            with HookRuntime([HookSpec("h", lambda e: None, fail)]).stage("root", None) as stage:
                stage.set_output("ok")

    def test_disabled_runtime_does_not_serialize_output(self):
        with patch("agent.core.hook_runtime._snapshot", side_effect=AssertionError("serialized")):
            with HookRuntime().stage("root", object()) as stage:
                stage.set_output(object())
