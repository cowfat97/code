# Python Harness—适配器—技能图插件改造方案

状态：待实施的设计，2026-10-22。本文不表示以下新接口已经存在。

范围：打通插件核心与独立适配器；二者作为源码模块直接引入业务项目，不作为独立pip分发包。Harness 暂不指定，只定义通用 Python 接入协议。保留当前 GraSP/MetaSkills 算法与单一 Registry，不引入网络服务、插件市场或特定 Harness SDK。

交付与验收修正：不要求构建wheel、pip安装或从site-packages导入。测试应在包含插件/适配器源码的业务项目内，从真实组装入口开始。核心已有的分发包是历史交付产物，不是本轮改造要求。

## 1. 已确认的断点

当前仓库实际存在：

- `GraphCompiler`、`GraphRuntime`、`SkillRegistry` 等底层类，没有统一插件入口。
- `examples/python_harness/adapter.py` 仅将 `(skill_id,version)` 分发给普通 async 函数，适配器位于 examples，尚未进入业务可正式引用的模块入口。
- `demo.py` 自行创建 Registry、注册技能、建立函数映射、编译图和执行。它充当全部组装代码，不是一个真实 Harness 接入。
- 核心 `SkillExecutor.execute` 接口可用，但没有宿主能力描述、绑定预检、运行绑定清单、统一任务输入/结果及生命周期入口。
- 持久化有图、状态和技能快照，没有从插件门面恢复宿主工具绑定的协议。Python 函数引用不能被 SQLite 序列化恢复。

现有186项测试证明核心及函数样例有效，不证明任意真实 Harness 已接入。此前把两者混同的完成表述应收窄。

## 2. 目标调用链

```text
Harness / 普通 Python 应用
    │ 构造结构化 TaskRequest
    ▼
GraspPlugin.prepare / execute / status / cancel / resume
    │ Registry检索 → 编译 → 后端绑定预检 → 保存运行
    ▼
GraphRuntime
    │ 调用公开的 SkillExecutor / SkillVerifier
    ▼
PythonToolAdapter（实现执行后端和精确版本分发）
    │ SkillBinding → ToolCall → 输入转换
    ▼
ToolPort.describe / ToolPort.invoke
    │ 由应用注入的宿主执行端
    ▼
实际 Python 工具、Agent能力、SDK方法或模型客户端
    │ ToolResult
    ▼
显式结果转换 → NodeResult → 内置/自定义验证 → 持久化/反馈/修复
```

依赖方向：

- 插件只认识核心协议，不 import 具体适配器或 Harness。
- 适配器只认识核心公开模型、通用 ToolPort 和显式绑定，不 import 具体 Harness SDK。
- Harness 只需在应用侧提供 ToolPort，组装时注入。若宿主没有同名SDK方法，由宿主桥接对象转换；不要求修改宿主内部类。
- SDK客户端、认证、外部权限、连接池和工具实现由应用持有；Registry由调用方创建并在运行结束后关闭。

只有组装代码同时认识具体宿主、适配器和插件。现有函数适配器可成为 ToolPort 的本地函数实现，而不是继续充当整套插件入口。模块路径由业务项目布局决定；核心与适配器只使用约定的公开Python接口，组装模块负责导入双方。

## 3. 插件统一入口

新增公开 `GraspPlugin`，内部组合现有 Registry/Compiler/Runtime/RepairEngine，不复制算法。

建议接口：

```python
plugin = GraspPlugin(registry=registry, backend=adapter, options=options)
handle = await plugin.prepare(request)
report = await plugin.execute(handle.graph_id)
state = plugin.status(handle.graph_id)
plugin.cancel(handle.graph_id)
report = await plugin.resume(handle.graph_id, retry_unknown=False)
```

另提供 `await plugin.run(request)` 作为 prepare+execute 便利方法。需要并行取消/状态监控的宿主使用分离的prepare/execute，以便执行前拿到graph_id。

### 3.1 输入输出模型

| 模型 | 内容 |
|---|---|
| TaskRequest | task:str；goal:list[str]；initial_conditions:list[str]；node_inputs:dict[node_id,dict]；可选proposal/order_hints。保持与现编译器语义一致 |
| RunHandle | graph_id；初始graph_version；status='prepared' |
| RunReport | graph_id；最终graph_version；status；outputs:dict[node_id,dict]；node_errors；verification；repair_audit；trace或其持久查询引用 |
| PluginOptions | concurrency、timeout、retries、strict_preconditions、discovery_mode、repair预算。启动时验证，不从技能正文隐式读取 |

TaskRequest.goal和initial_conditions必须显式给出；不在本次改造中承诺任意自然语言自动变成可信契约。第一版保留按node_id提供输入，避免同时改造核心输入路由；Harness可以在自身任务构造层封装该细节。

RunReport不使用“最后一个节点输出”推断最终结果：多个分支的结果按节点ID返回。自动修复后的最终图/版本从最新持久化快照读取，不返回原始旧图版本冒充最新状态。

### 3.2 prepare

1. 校验TaskRequest，交给现有GraphCompiler。
2. 调用后端bind，验证已选技能及允许修复候选的执行绑定、工具revision、验证规则和转换器版本。
3. 将后端提供的可序列化绑定manifest深拷贝进graph.metadata.execution_manifest。
4. 创建pending GraphState，保存图/状态；绑定预检失败时不创建可执行运行，不把它混成某个工具业务失败。
5. 返回RunHandle。prepare只允许能力描述查询，不执行实际工具。

### 3.3 execute / resume / cancel

execute根据graph_id读取已保存图/状态，不能信任调用方临时修改的图对象。用保存manifest重新绑定执行后端，构建本次GraphRuntime，运行后返回RunReport。

resume读取同一图、技能版本和绑定manifest；宿主只提供新工具revision、旧版本不可用时明确报BindingUnavailable，不能静默换新实现。unknown保持当前核心的显式恢复政策和原key复用。

插件维护graph_id→活动Runtime的进程内映射，cancel找到该对象调用Runtime.cancel；没有活动任务时返回明确状态，不伪称中断了外部动作。相同插件实例拒绝同图重入。每个运行有自己的绑定快照，不能更新全局executor来改变已开始运行的图。

不加入分布式租约；第一版限定一个Python进程管理某运行。Registry关闭前必须等待活动任务结束；可提供aclose用于等待/取消任务，但不替调用方擅自关闭共享Registry。

## 4. 核心与适配器之间增加“绑定后端”协议

核心新增公开协议和值对象，放在providers.py或独立public integration_contracts模块，不能反向依赖adapter实现。

```python
class ExecutionBackend(Protocol):
    async def bind(
        self, graph: ExecutionGraph,
        *, manifest: dict | None = None,
    ) -> BoundExecution: ...
```

BoundExecution是进程内值对象：executor:SkillExecutor、verifier:SkillVerifier或None、manifest:可JSON序列化字典。executor/verifier是活对象，不进入数据库；只有manifest持久化。

没有manifest表示新运行绑定；有manifest表示严格恢复。插件只负责保存manifest与调用后端，不知道工具SDK、转换器实现或适配器内部结构。

后端预检同时解决当前“编译成功，执行时才发现函数没绑定”的缺口。配置错误与业务执行错误分别归因。

## 5. 通用 Harness 端口

以下是新定义的应用接入协议，不是任何现成 Harness 自带的 SDK API。

```python
class ToolPort(Protocol):
    async def describe(self, tool_id: str, revision: str) -> ToolDescriptor: ...
    async def invoke(self, call: ToolCall) -> ToolResult: ...
```

| 类型 | 字段 |
|---|---|
| ToolDescriptor | tool_id、revision、input_schema、output_schema、supports_idempotency。revision是调用方明确维护的实现身份，不从函数名猜测 |
| ToolCall | tool_id、revision、arguments、run_id、call_id、idempotency_key；可选无密钥的运行上下文 |
| ToolResult | payload:dict、observations:dict、evidence:list[str]；失败通过明确异常表达，不把失败字典当成功结果 |

ToolPort不接受SkillNode、SkillContract、GraphState，宿主不需要理解GraSP谓词。事实/效果转换留在适配器结果映射中。

`describe`只返回元数据，不能执行工具；`invoke`必须精确调用指定revision。宿主实际做不到版本分派时，要么仅绑定一个明确revision并冻结该能力，要么拒绝旧revision；不能忽略revision。

通用Python参考端口可用显式的`(tool_id,revision)→async callable`字典实现，不依赖任何宿主SDK。它用于协议验收，名称标为reference_tool_port，不标为某真实Harness已经接入。

调用实际Harness时，invoke应接其底层工具执行入口，不重新调用其顶层agent.run进行第二轮任务规划。插件工具自身及skill_graph.*等编排入口不允许出现在节点工具白名单，防止递归调用自身。若宿主工具分发持有会话锁，必须避免等待插件时又被插件反向请求同一锁；接工具执行入口，不重入整段会话循环。

## 6. 显式技能绑定与数据转换

新增BindingCatalog，保存“执行映射”，不保存另一套技能定义或依赖图。

```text
SkillBinding:
  skill_id
  skill_version
  skill_content_hash
  tool_id
  tool_revision
  input_mapper_id + input_mapper_revision
  result_mapper_id + result_mapper_revision
  validator_ids + revisions
```

转换器通过构造参数注入普通Python函数，注册键与revision不可变；不从字符串动态import任意模块。纯直通输入/结果也作为明确定义的默认转换器，不能根据字段名称随意猜测映射。

输入映射将核心inputs转换ToolCall.arguments；结果映射接受ToolResult和该调用上下文，返回NodeResult。必须根据实际payload/observations/evidence判断可确认的效果，不能无条件复制SkillContract.effects。绑定的输入输出Schema在prepare时做支持范围内的兼容预检，实际结果仍由核心完整Schema验证。

manifest记录SkillBinding和转换器身份等可序列化数据，不包含函数指针、客户端、Token或密钥。描述符可保存必要Schema摘要作为漂移检查；技能契约和依赖只从固定Skill版本读取，不重复维护。

绑定catalog改变时创建新快照；运行图保留旧tool_revision/转换器revision。恢复时需要宿主/应用仍提供这些历史实现；不能以“当前同名函数存在”为理由执行新版。

## 7. 修复、幂等与错误传播

### 7.1 修复候选必须可执行

仅为初始图节点绑定工具不够：Substitute/InsertPrereq可能引入其他技能。

新运行时manifest应同时包含显式允许的修复候选版本，并完成其工具/规则预检。给RepairEngine传一个只读候选视图：从同一Registry读取这些固定版本，list只暴露已绑定可执行的候选；它不是第二个Registry。

修复生成新图后沿用manifest已冻结的绑定，核心仍重新验证契约/依赖并局部失效。未获允许的新版本不在运行中自动获得执行能力；需要显式重新prepare/replan。空修复候选不影响原图执行。

### 7.2 幂等与取消

适配器把context.idempotency_key原样传到ToolCall，不另外生成key、不叠加重试。普通异常重试的key会变化；unknown的首次显式恢复复用原key。宿主若发生副作用后抛异常，必须有稳定业务标识去重/对账，不能只依赖新key。

外部动作的取消可能只停止等待，仍可能unknown；保留当前核心语义，不伪造回滚。ToolPort可以在自身实现中处理async取消及资源清理，本方案不要求底层服务一定支持强制终止。

### 7.3 错误分类

- BindingUnavailable：技能/工具/转换器/规则版本缺失，prepare或resume预检失败。
- ContractMismatch：绑定Schema或接口契约不兼容，执行前失败。
- ToolExecutionError：真实调用失败，进入Runtime的执行失败/修复路径。
- VerificationFailure：实际结果不满足Schema/效果/规则，沿当前verification路径。
- OutcomeUnknown：外部结果无法确认，不自动改成普通失败或成功。

日志用graph_id、node_id、skill_id/version、tool_id/revision、attempt/key关联三层；不把私密输入或SDK凭证默认写入trace。

## 8. 文件改造范围

| 路径 | 改造 |
|---|---|
| src/grasp_metaskills/contracts.py | TaskRequest、RunHandle、RunReport等可序列化公开模型 |
| src/grasp_metaskills/providers.py | ExecutionBackend、BoundExecution的公开边界 |
| src/grasp_metaskills/plugin.py | 新增统一门面，组合核心、管理运行生命周期 |
| src/grasp_metaskills/integration/contracts.py | ToolPort及中立调用/结果/描述符 |
| src/grasp_metaskills/integration/bindings.py | 显式BindingCatalog、版本快照和manifest校验 |
| src/grasp_metaskills/integration/adapter.py | 可直接import的后端、执行分发、数据转换与验证规则适配 |
| src/grasp_metaskills/__init__.py | 导出稳定插件入口；不导入具体Harness SDK |
| examples/python_integration/compose.py | 只做组装，不能继续自行散落Registry/Runtime重复流程 |
| tests/integration/test_plugin_adapter.py | 插件→适配器→真实参考端口的端到端测试 |
| tests/unit/test_bindings.py | 版本、白名单、manifest漂移和转换错误测试 |
| docs/python-harness-integration.md | 改为新公开入口，旧函数样例注明兼容/基础用途 |

原examples/python_harness/adapter.py可保留为兼容样例，但主要实现必须进入业务项目的正式源码模块，不依赖examples中的演示脚本。表中src路径是现仓库建议位置，复制进业务仓库时可以调整，需保持一致的导入命名空间。仍是一个项目、一个核心Registry、一套插件能力；不创建多个插件或插件市场。

GraSP编译/修复算法、MetaSkills存储检索不重写。必要的修复候选视图通过已有RepairLibrary.list协议注入；不要为了接入把核心绑定到某个SDK。

## 9. 实施顺序与完成门槛

1. 先固定公开模型/端口/版本规则，补失败用例。
2. 适配器进入src，实现bind/preflight/manifest，测试无SDK导入且在业务项目内可直接import和组装。
3. 实现GraspPlugin，统一prepare/execute/status/cancel/resume；去掉demo充当正式入口的做法。
4. 接修复候选绑定快照、恢复时版本检查、错误与关联轨迹。
5. 用真实Python参考端口跑完整插件链，并验证业务项目的模块导入、真实组装入口与数据库重开；保留已有186项作为回归基线。
6. 实际Harness后续接入时，仅实现ToolPort桥接并提供组装入口，另行执行真实宿主验收。

不以创建几个类或普通算术函数成功为三方集成完成。此轮可声称完成的边界是“插件核心与适配器已通过统一入口贯通，并提供经过参考端口验证的通用Harness协议”；不能声称所有Harness已接入。

## 10. 必须通过的端到端验收

- 从业务项目实际源码路径导入GraspPlugin和适配器，通过正式组装入口运行，不引用examples文件，不在测试里绕过插件手工创建GraphRuntime。导入不应自动创建数据库、SDK客户端或启动任务。
- 应用只创建Registry/ToolPort/BindingCatalog并注入；调用prepare+execute得到可查询RunReport。
- 普通运行中同一graph_id/node_id能关联到底层真实函数调用和最终结果。
- 缺绑定/错误tool revision/缺转换器在prepare失败，工具调用次数为0。
- 工具输出实际改变时，结果映射/验证真实通过或失败，不复制声明效果伪造成功。
- active技能和catalog更新不改变进行中的技能/tool/转换器版本。
- 真实失败触发已绑定替代技能；独立成功分支不重跑；未绑定候选不进入修复计划。
- 进程内取消可找到运行对象；unknown恢复保持原key；重开SQLite并重建端口后可恢复，不序列化函数指针。
- 历史tool revision不可用时resume明确失败，不能调用当前新版。
- 两个不同参考ToolPort实现使用同一插件/适配器通过相同契约测试；这证明协议可组装，不代表某个未接入框架已兼容。
- 引入实际Harness后，再补真实工具注册、任务入口、回调、取消/恢复、权限与会话重入测试；这些当前标为未接入。

模块组装额外检查：所有契约模型使用同一导入命名空间，不将同一核心文件分别以两个模块名加载；替换注入的ToolPort后不修改插件或适配器源码；在项目副本/干净工作目录按业务实际启动命令测试，排除开发机sys.path、全局单例或绝对路径依赖。
