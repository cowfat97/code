"""Executable coverage for ../../docs/python-harness-integration.md."""
import asyncio
import importlib.util
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from grasp_metaskills import GraphCompiler, GraphRuntime, Skill, SkillContract, SkillRegistry
from grasp_metaskills.contracts import ExecutionContext, NodeResult, SkillNode, VerificationResult


def adapter():
    path = Path(__file__).with_name('adapter.py')
    assert path.exists(), 'Python Harness adapter is not implemented'
    spec = importlib.util.spec_from_file_location('python_harness_adapter', path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def node(validators=()):
    return SkillNode(id='work:1', skill=Skill(id='work', name='Work', version='1.0.0',
        contract=SkillContract(effects=['done(x)'], validators=list(validators))))


def context():
    return ExecutionContext(graph_id='g', node_id='work:1', idempotency_key='stable-key')


@pytest.mark.asyncio
async def test_exact_capability_snapshot_and_context():
    calls = []
    async def run(inputs, ctx):
        calls.append((inputs, ctx.idempotency_key))
        return {'output': inputs, 'observed_effects': ['done(x)']}
    tools = {('work', '1.0.0'): run}
    executor = adapter().PythonHarnessExecutor(tools)
    tools.clear()
    assert (await executor.execute(node(), {'n': 3}, context())).output == {'n': 3}
    assert calls == [({'n': 3}, 'stable-key')]
    wrong = node()
    wrong.skill = wrong.skill.model_copy(update={'version': '2.0.0'})
    with pytest.raises(LookupError):
        await executor.execute(wrong, {}, context())
    with pytest.raises(LookupError):
        await executor.execute(SkillNode(id='none'), {}, context())
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_invalid_result_is_rejected():
    async def invalid(inputs, ctx):
        return {'unknown': True}
    with pytest.raises(ValidationError):
        await adapter().PythonHarnessExecutor({('work', '1.0.0'): invalid}).execute(
            node(), {}, context())


@pytest.mark.asyncio
async def test_rule_order_failure_unknown_and_snapshot():
    calls = []
    async def passed(n, inputs, result, ctx):
        calls.append('pass')
        return VerificationResult(passed=True)
    async def failed(n, inputs, result, ctx):
        calls.append('fail')
        return VerificationResult(passed=False, category='custom_validator', message='bad value')
    rules = {'pass': passed, 'fail': failed}
    verifier = adapter().PythonHarnessVerifier(rules)
    rules.clear()
    result = await verifier.verify(node(['pass', 'fail', 'pass']), {}, NodeResult(), context())
    assert not result.passed and result.message == 'bad value'
    assert calls == ['pass', 'fail']
    unknown = await verifier.verify(node(['missing']), {}, NodeResult(), context())
    assert not unknown.passed and unknown.category == 'custom_validator'
    assert 'missing' in unknown.message
    assert (await verifier.verify(node(['pass']), {}, NodeResult(), context())).passed


@pytest.mark.asyncio
async def test_real_registry_compiler_runtime_and_retries():
    attempts = []
    validations = []
    async def run(inputs, ctx):
        attempts.append(ctx.idempotency_key)
        if len(attempts) == 1:
            raise ValueError('temporary failure')
        return NodeResult(output={'value': 7}, observed_effects=['done(x)'])
    async def check(n, inputs, result, ctx):
        validations.append(result.output['value'])
        return VerificationResult(passed=result.output['value'] == 7)
    module = adapter()
    with SkillRegistry() as registry:
        registry.register(node(['check']).skill)
        graph = await GraphCompiler(registry).compile(goal=['done(x)'])
        runtime = GraphRuntime(registry, module.PythonHarnessExecutor({('work', '1.0.0'): run}),
            verifier=module.PythonHarnessVerifier({'check': check}), retries=1)
        state = await runtime.execute(graph)
        assert state.status == 'succeeded'
        assert len(attempts) == 2 and attempts[0] != attempts[1]
        assert validations == [7]


@pytest.mark.asyncio
async def test_cancel_unknown_recovery_reuses_idempotency_key():
    started = asyncio.Event()
    keys = []
    async def run(inputs, ctx):
        keys.append(ctx.idempotency_key)
        if len(keys) == 1:
            started.set()
            await asyncio.Event().wait()
        return NodeResult(observed_effects=['done(x)'])
    with SkillRegistry() as registry:
        registry.register(node().skill)
        graph = await GraphCompiler(registry).compile(goal=['done(x)'])
        runtime = GraphRuntime(registry, adapter().PythonHarnessExecutor({('work', '1.0.0'): run}))
        running = asyncio.create_task(runtime.execute(graph))
        await asyncio.wait_for(started.wait(), 2)
        runtime.cancel(graph.id)
        state = await running
        assert any(n.status == 'outcome-unknown' for n in state.nodes.values())
        assert (await runtime.resume(graph.id)).status == 'outcome-unknown'
        assert len(keys) == 1
        assert (await runtime.resume(graph.id, retry_unknown=True)).status == 'succeeded'
        assert keys[0] == keys[1]
