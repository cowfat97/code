# grasp-metaskills

Python 3.12+、Harness 无关的技能图编译与执行包。实际移植 MIT 许可
`luyu020816-droid/skill-dag` 的核心机制，统一显式技能契约、注册检索、图编译、
异步执行、验证、局部修复及持久化。

基于两个真实源码快照：GraSP `e8eaf485` 和 MetaSkills 的历史标准 MIT 版本
`dcd3fb55`。MetaSkills 后续版本增加了限制条款，本项目未使用这些版本；许可证
与版权保留在 `licenses/`、`NOTICE`。参见 [许可审计](docs/license-audit.md)。

核心能力包括 GraSP 检索公式、反向相关性过滤、State/Data/Order DAG 与五种局部修复；
MetaSkills 原生 SkillSpec、能力依赖、继承/组合、离线 hash embedding、f32 RRF、
过滤、bandit/reward 和 SQLite/Git 分阶段事务。二者直接共享一个 SkillRegistry、
显式执行契约、固定版本图快照及持久化反馈。FTS5 替代 Tantivy、不可变版本映射、
并发执行和严格验证属于明确记录的兼容重构或集成扩展。

完整范围与差异见 [源码映射](docs/source-mapping.md)、
[兼容性](docs/compatibility.md) 和 [未实现部分](docs/limitations.md)。这不是上游完整
CLI/TUI/同步/挖掘应用的逐项复刻，也不声称适用于后续受限 MetaSkills 版本。

## 安装和验证

```bash
cd grasp-metaskills
python3.12 -m venv "$HOME/.venvs/grasp-metaskills"
source "$HOME/.venvs/grasp-metaskills/bin/activate"
python -m pip install -e '.[dev]'
python -m pytest -q
ruff check src tests examples
mypy src/grasp_metaskills
python examples/offline.py
```

实际验证：181 项测试通过；Ruff 和严格 mypy（18 个源码模块）通过。
详细数量、命令及上游基准记录见 [验证记录](docs/verification.md)。

运行依赖是 Pydantic v2、jsonschema、packaging 和 Python 标准库。
SQLite 需 FTS5 支持。只有显式开启 Git 历史时需要系统 `git`；不需要 Node、
JavaScript、Rust、特定 Harness 或云端 API。开发期曾运行上游 JS 测试核对基准，
这些进程不是 Python 包的运行或测试依赖。

本机同步目录会给虚拟环境内 `.pth` 文件自动设置 macOS `hidden` 标记，导致 Python 跳过 editable 路径；因此上面把虚拟环境放在同步目录外。干净环境的 editable 安装和测试均已实跑。

## 公共 API

```python
import asyncio
from grasp_metaskills import (
    Skill, SkillContract, SkillRegistry, GraphCompiler, GraphRuntime, NodeResult,
)

class Executor:
    async def execute(self, node, inputs, context):
        # Real work is deliberately injected. Only report effects actually observed.
        value = 2 + 3
        return NodeResult(output={"value": value},
                          observed_effects=["ready(x)"] if value == 5 else [])

async def main():
    with SkillRegistry() as registry:
        registry.register(Skill(id="add", name="Add constants",
            contract=SkillContract(effects=["ready(x)"])))
        graph = await GraphCompiler(registry).compile(goal=["ready(x)"])
        result = await GraphRuntime(registry, executor=Executor()).execute(graph)
        print(result.status)

asyncio.run(main())
```

多技能自动发现、类型绑定和执行的完整离线用法见
[examples/offline.py](examples/offline.py)。前置条件与效果是显式谓词字符串；输入输出
使用 JSON Schema，Markdown 自然语言描述不会自动成为可验证的类型。

编译器会固定技能版本和来源。更改注册库不会替换已编译节点的快照。独立就绪节点
并发运行；超时、重试、验证错误及持久化恢复均有明确状态和轨迹。Executor 是注入
接口，包不会自动把技能内容交给 shell 执行。

`RepairEngine(registry)` 可传给 `GraphRuntime(..., repair_engine=...)`。真实修复操作
为 `Bypass`、`Rebind`、`InsertPrereq`、`Substitute`、`Rewire`；提交前检查合法性，
生成新版本，仅失效受影响子图，保留独立分支已验证结果。修复次数有界，失败会终止。

## MetaSkills 原生定义与 Git

```python
from grasp_metaskills import SkillRegistry, SkillContract

with SkillRegistry("skills.db", git_path="skill-history") as registry:
    skill = registry.register_spec({
        "metadata": {"id": "prepare", "name": "Prepare", "version": "1.0.0",
                     "description": "Prepare an artifact", "provides": ["prepared"]},
        "sections": [],
    }, contract=SkillContract(effects=["ready(x)"]))
    candidates = registry.search("prepare", mode="hybrid")  # 无云端 API
    original = registry.get_spec(skill.id)
    commits = registry.git_archive.history(skill.id)
```

`requires/provides` 是能力依赖，编译器会加载所有 provider；它们不会隐式转为执行
事实。自然语言也不会成为类型契约。显式契约使用 `contract=` 或原生文档的
`grasp_contract` 扩展。`compose_spec` 实跑上游继承/组合规则。
原生相同声明版本的更新映射为不可变本地修订，已编译图保持原快照。

默认离线 HashEmbeddingProvider 移植真实上游特征算法；可注入其他 embedding。
它是未训练的确定性特征，不冒充神经模型推理。可选 Git 使用逐技能原生归档和
恢复日志；初始化自动恢复未完成事务。JSON 批量导入预检全部约束后逐技能提交，
不是跨 SQLite/Git 的原子事务。更多 API 见 [API 文档](docs/api.md)。

## 文档与源码

- [Python 函数组装适配器](docs/python-harness-integration.md)：独立于具体 Harness SDK 和插件接口的可运行接入代码。

- [详细实现规格与复现设计](docs/detailed-design.md)：字段、SQL、算法、状态机、修复及测试断言；附 [机器可读复现数据](docs/reproduction-data.json)。

- [架构](docs/architecture.md)：统一模型、依赖权威、执行和修复边界。
- [源码映射](docs/source-mapping.md)：原文件/函数、Python 对应实现、测试、来源分类。
- [兼容性](docs/compatibility.md)：忠实保留与主动加强的行为。
- [限制](docs/limitations.md)：未移植和无法验证部分。
- [验证记录](docs/verification.md)：实际运行命令和结果。

源码在 `src/grasp_metaskills/`，单元、集成、Golden 和 Hypothesis 测试在 `tests/`。
MIT 版权和许可保留于 `LICENSE`、`NOTICE`、`licenses/skill-dag-MIT.txt` 和
`licenses/meta-skill-MIT.txt`。
