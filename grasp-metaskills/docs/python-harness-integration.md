# Python 函数组装适配器

本接入层是普通 Python 模块，不是某个 Harness 的插件。它只依赖标准库和 `grasp_metaskills` 的公开模型，没有特定 Harness SDK、插件发现、全局客户端、服务端口或自动安装钩子。

## 1. 文件与依赖方向

| 文件 | 用途 |
|---|---|
| [adapter.py](../examples/python_harness/adapter.py) | 可独立复制的函数执行与命名验证规则适配器 |
| [demo.py](../examples/python_harness/demo.py) | 两个普通异步函数组成实际技能图的可运行样例 |
| [test_adapter.py](../examples/python_harness/test_adapter.py) | 白名单、版本、验证及运行时恢复的真实测试 |

```text
你的 Python 应用 / Harness 的组装代码
    ├─ 创建 Registry、Compiler、Runtime
    ├─ 提供普通 async 函数与验证规则
    └─ 创建适配器并注入 Runtime
                  ↓
          grasp_metaskills 公开接口
```

适配器不反向调用你的 Harness 全局对象。需要调用 SDK 时，由你创建一个闭包或对象方法，再把它作为普通函数注入。多个 Harness 可以复制使用同一适配器，也可以在同一进程建立相互隔离的映射实例。

技能定义、函数实现、映射关系分开维护：定义存在 Registry；函数属于你的应用；映射只在组装代码中建立。正文或元数据不能自动获得执行权限。

## 2. 执行函数协议

注入函数签名：

```python
async def tool(inputs: dict, context: ExecutionContext) -> NodeResult:
    ...
```

inputs 是已通过内置输入 Schema/前置条件检查的实际输入。context 含 graph_id、node_id、idempotency_key、facts。没有 Harness client、插件管理器或模型实例参数；这些对象可以通过函数闭包注入。

调用方显式提供版本映射：

```python
executor = PythonHarnessExecutor({
    (skill.id, skill.version): tool,
})
runtime = GraphRuntime(registry, executor)
```

使用 `registry.register(...)` 或 `register_spec(...)` 返回的版本建立映射，特别是原生相同声明版本更新后可能得到本地修订号。不会按技能名称、描述、任意版本或字符串路径动态加载函数；没有匹配项就拒绝执行。

适配器复制映射。建立实例后修改原始字典不会改变该实例的权限映射；要改变函数版本绑定，显式创建新适配器。函数内部可变状态仍由应用负责，并不因映射只读而被冻结。

Executor 返回值用 NodeResult 校验；支持 NodeResult 或符合其字段的对象字典。output 是实际输出，observed_effects 由函数在动作成功且有证据后报告。不要把 `node.effects` 原样当作未执行动作的成功证明。

## 3. 自定义验证规则

规则函数签名：

```python
async def rule(node, inputs, result, context) -> VerificationResult:
    ...
```

技能通过 `SkillContract(validators=['rule-name'])` 引用规则；组装时提供：

```python
verifier = PythonHarnessVerifier({'rule-name': rule})
runtime = GraphRuntime(registry, executor, verifier=verifier)
```

规则按契约列表顺序执行，首个失败即返回。未知规则名称明确失败。规则异常/超时交由 GraphRuntime 转为验证失败。内置输入/输出 Schema、前置条件与效果检查仍由 Runtime 先做，自定义规则不能放行内置失败。

不要在 validator 中重复产生外部副作用：恢复 `verifying` 状态会再次验证已持久化的结果。规则应只读、可重复执行。

## 4. 安装与运行

项目目录中：

```bash
python -m pip install -e '.[dev]'
python examples/python_harness/demo.py --value 21
python -m pytest -q examples/python_harness/test_adapter.py
```

预期 status=succeeded，output={"value":42}。样例先把输入文本解析为整数，再通过数据绑定交给倍增函数，最后实际检查偶数规则。修改 `--value` 可以得到不同结果；它不依赖云端模型、固定 Harness 或外部服务。

持久化运行：

```bash
python examples/python_harness/demo.py --value 7 --db /tmp/python-harness-demo.db
```

这会真实写入 SQLite。数据库父目录应已存在；需要 Git 时由组装代码显式设置 Registry.git_path，适配器无需改变。

使用独立接入包时，先安装包内 wheel（会安装声明的 Python 依赖）：

```bash
python -m pip install ./grasp_metaskills-0.1.0-py3-none-any.whl
python -m pip install pytest pytest-asyncio
python examples/python_harness/demo.py --value 21
python -m pytest -q examples/python_harness/test_adapter.py
```

复制 `adapter.py` 到你自己的模块目录即可使用，不要求保留 examples 的路径；demo.py 与 adapter.py 同目录时可直接运行。包内测试能在同目录找到适配器。

## 5. 在已有异步 Harness 中组装

如果应用已经运行事件循环，直接 await，不能再嵌套 asyncio.run：

```python
from adapter import PythonHarnessExecutor
from grasp_metaskills import GraphCompiler, GraphRuntime

async def run_job(registry, skill, tool, task, goal, inputs):
    executor = PythonHarnessExecutor({(skill.id, skill.version): tool})
    graph = await GraphCompiler(registry).compile(
        task=task, goal=goal, inputs=inputs,
    )
    state = await GraphRuntime(registry, executor).execute(graph)
    return state
```

一个图使用多个技能时，映射必须覆盖每个可执行节点；src/snk 不调用外部函数。上例是单技能组装函数，不会替你从 Harness 全局工具列表自动导入其他函数。

需要宿主 SDK 时采用应用侧闭包：

```python
from grasp_metaskills import NodeResult

def bind_existing_function(existing_async_function):
    async def tool(inputs, context):
        response = await existing_async_function(
            inputs, idempotency_key=context.idempotency_key,
        )
        return NodeResult.model_validate(response)
    return tool
```

这里 `existing_async_function` 是你应用已实现的函数，必须满足示出的调用约定；不是声称某个 Harness 自带这个 SDK API。不支持该约定时，只改这个应用侧闭包，不修改公共适配器。

## 6. 取消与恢复

运行中的同一 Runtime 对象可以取消指定图：

```python
job = asyncio.create_task(runtime.execute(graph))
# 应用在用户取消事件发生时调用：
runtime.cancel(graph.id)
state = await job
```

上面只演示 API；不要在创建任务后立即无条件 cancel。业务代码应等待实际取消事件。取消尚未开始的节点为 cancelled；取消外部执行中的节点可能是 outcome-unknown，不代表动作没有发生。

恢复时重新打开同一数据库、重建相同历史版本的函数映射和验证规则：

```python
with SkillRegistry('runs.db') as registry:
    executor = PythonHarnessExecutor(versioned_tools)
    verifier = PythonHarnessVerifier(named_rules)
    runtime = GraphRuntime(registry, executor, verifier=verifier)
    state = await runtime.resume(graph_id)
```

`versioned_tools`/`named_rules` 是应用保存并能重建的配置，不存放在 SQLite 的函数指针。若存在 outcome-unknown，普通 resume 不会盲目重跑。应用确认可用幂等 key 去重或已完成对账后，才使用 `resume(graph_id,retry_unknown=True)`；该恢复会保留原 attempt 和 idempotency_key。

本适配器不实现通用幂等缓存。对于外部支付、写文件、发送请求等动作，在实际动作执行系统中按 key 保存/查询结果，或提供同等可靠的去重机制；仅进程内字典不能保证进程崩溃后的恰好一次。

## 7. 超时、重试、修复的归属

| 能力 | 归属 |
|---|---|
| 技能定义、版本、图、运行快照 | grasp_metaskills |
| 函数精确白名单、规则名称分发 | adapter.py |
| 超时、重试次数、批次并发、取消、恢复 | GraphRuntime |
| 选哪种模型、SDK认证、调用权限、资源清理、外部去重 | 应用/函数 |
| 替代技能能否满足图契约、局部失效 | RepairEngine |

适配器不再加第二层重试，以免请求次数相乘。普通异常向外抛出；GraphRuntime 决定重试和失败状态。普通异常的新尝试会生成新 idempotency_key；仅 unknown 首次显式恢复保留原 key。已有外部副作用但抛出异常的调用，不能仅靠新 key 避免重复，接入方应选择不自动重试或在外部操作层按稳定业务标识对账。非幂等超时可能 unknown；只有明确的 idempotent 元数据才能允许配置的超时重试，但元数据不替代实际幂等保障。

启用 `GraphRuntime(..., repair_engine=RepairEngine(registry))` 时，可能选择替代技能；替代版本也必须在映射中，否则依旧拒绝执行。长期运行应保留旧版本函数实现，不把新实现偷偷绑到旧版本 key。

## 8. 同步函数与资源生命周期

默认协议是 async。可以在应用侧用 `asyncio.to_thread` 包装同步函数，但取消等待不会停止底层线程；执行副作用仍可能继续，不应据此声称已终止外部动作。

SDK客户端、数据库会话和连接池由应用创建/关闭。实例字段或闭包可持有客户端；不要让适配器导入你的应用全局初始化模块。Registry 必须在运行任务完全结束后关闭，不能在仍有节点任务运行时提前关闭 SQLite。

这里的白名单是分发边界，不是 Python 进程沙箱。已注入的函数具有自身进程权限。并发图与函数线程安全由应用负责，核心没有跨进程执行租约。

## 9. 实际验证

2026-10-22：适配器独立测试5项通过；与项目原有测试一起执行186项通过；Ruff全项目通过；严格mypy检查18个核心模块和2个示例模块通过。独立只读评审未发现阻断问题。

真实覆盖：精确版本拒绝且不调用函数、映射快照、上下文key透传、非法输出拒绝、验证规则顺序/未知/失败、Registry→Compiler→Runtime实际执行与重试、取消后unknown及保留原key恢复。

命令：`python -m pytest -q tests examples/python_harness/test_adapter.py`；`ruff check src tests examples`；`mypy src/grasp_metaskills examples/python_harness/adapter.py examples/python_harness/demo.py`。核心实现未修改。
