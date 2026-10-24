# 金融与法律评测 Skills 接入指南

适用当前文件存储版本。所有路径示例以 `plugins/` 为边界，不依赖指定 Harness。目标是复用公司已有 Skills 和评测代码，尽量不修改原文件。

## 1. 先区分三件事

| 内容 | 作用 | 是否必需 |
|---|---|---|
| 原有 `SKILL.md` 与资源文件 | 告诉 Meta 技能的用途、步骤和限制 | 导入技能需要 |
| 显式契约 | 声明输入输出、前置条件与完成效果 | 参与图编译和验证需要 |
| 执行工具 | 真正读取数据、调用被测模型、计算指标、生成结果 | 实际执行需要 |

技能说明中的文字步骤不会自动变成可执行代码。Meta 的 LLM 负责规划，当前并没有通用的“阅读 SKILL.md 后自主执行全部步骤”执行器。

不重写现有指标、评分规则和评测程序。先给旧程序加窄接口，再把该接口绑定到 Skill。

## 2. 两种接入方式

### 方式 A：完全不修改原 Skills 目录

保留所有原文件，在 `config/skills.json` 中逐项声明路径、工具绑定和契约。路径相对该配置文件。

```json
{
  "skills": [
    {
      "path": "../skills/library/finance_accuracy",
      "id": "finance_accuracy",
      "tool": "finance_accuracy",
      "contract": {
        "params": ["batch"],
        "preconditions": ["answers_ready(batch)"],
        "effects": ["accuracy_checked(batch)"],
        "input_schema": {
          "type": "object",
          "properties": {
            "batch_id": {"type": "string"},
            "answers_path": {"type": "string"}
          },
          "required": ["batch_id", "answers_path"],
          "additionalProperties": false
        },
        "output_schema": {
          "type": "object",
          "properties": {"accuracy_report_path": {"type": "string"}},
          "required": ["accuracy_report_path"],
          "additionalProperties": false
        }
      }
    }
  ]
}
```

这是一份可被当前配置模型接受的例子。目录必须真实存在，并且包含 `SKILL.md`。

原 Skills 可以位于其他目录，配置使用指向该目录的相对路径即可，不强制复制到 `skills/library/`。`config/plugin.json` 的 `skills_dir` 默认仍会自动扫描 `../skills/library`。

一个目录条目带 `id` 时必须恰好导入一个 `SKILL.md`。对多个技能不要使用同一个条目绑定同一份业务契约，应逐个配置。

### 方式 B：不改原文件，只新增旁路文件

当允许在技能目录增加文件时，可把同一份契约放到 `contract.json`：

```text
skills/library/
└── finance_accuracy/
    ├── SKILL.md          # 原文件保持不变
    ├── references/       # 原资源保持不变
    └── contract.json     # 新增适配信息
```

```json
{
  "id": "finance_accuracy",
  "name": "金融准确性评测",
  "description": "复用现有流水线评测已生成的金融问答结果",
  "tool": "finance_accuracy",
  "contract": {
    "params": ["batch"],
    "preconditions": ["answers_ready(batch)"],
    "effects": ["accuracy_checked(batch)"],
    "input_schema": {
      "type": "object",
      "properties": {
        "batch_id": {"type": "string"},
        "answers_path": {"type": "string"}
      },
      "required": ["batch_id", "answers_path"],
      "additionalProperties": false
    },
    "output_schema": {
      "type": "object",
      "properties": {"accuracy_report_path": {"type": "string"}},
      "required": ["accuracy_report_path"],
      "additionalProperties": false
    }
  }
}
```

默认 `skills_dir` 已指向 `skills/library/`，放在此处的技能不需要再列入 `skills.json`。外部目录可使用仅包含 `path` 的导入条目。

两种方式任选一种。配置条目的 `contract`、`tool` 会覆盖技能文件中的对应定义，避免重复维护不同真相来源。

## 3. 契约怎么提取

逐个核对真实旧代码，不要根据技能标题猜测：

| 项目 | 确定方法 |
|---|---|
| 输入 | 旧函数真正接收哪些参数，哪些必填，数据格式是什么 |
| 输出 | 实际返回哪些结果，后续技能需要哪些字段 |
| 前置条件 | 什么已确认状态成立后才能开始 |
| 效果 | 哪项可核验工作完成后才能宣告成立 |
| 依赖 | 是否必须存在另一项技能定义；是否存在真正的数据或状态依赖 |
| 工具 | 现有代码中哪个函数可以完成此技能 |
| 完成验证 | 文件存在、内容完整、样本数量一致、评分无缺项等实际标准 |

金融、法律是业务标签，不自动决定执行顺序。只有真实依赖成立时，才声明先后关系。

例如金融准确性检查和法律合规检查可以都依赖 `answers_ready(batch)`，分别产生 `accuracy_checked(batch)` 和 `compliance_checked(batch)`；汇总技能要求这两个效果。输入输出兼容且没有额外顺序约束时，两个检查才有机会并行。

`dependencies` 表示技能定义的依赖，不要把它当成数据字段绑定。数据流仍依靠输入输出契约和编译器解析。

效果应表达“完成检查”，不要用“检查通过”代替：发现不合规是有效评测结果，不应直接当作工具执行失败。

## 4. 包装并注册现有评测函数

在 `tools/local/finance.py` 新增窄适配函数。下面的 `existing_evaluation` 是公司已有代码的示例名称，需要换成真实模块、函数和返回字段：

```python
from existing_evaluation import evaluate_finance


def finance_accuracy(batch_id: str, answers_path: str) -> dict:
    result = evaluate_finance(answers_path=answers_path)
    report_path = result["report_path"]
    return {
        "output": {"accuracy_report_path": report_path},
        "observed_effects": [f"accuracy_checked({batch_id})"]
    }
```

前提：旧函数正常返回代表检查已完整完成。若它可能返回部分结果或错误标记，包装器必须检查并抛出异常，不能无条件宣告效果。报告完成标准以实际业务定义为准。

在 `tools/local/__init__.py` 加入已有工具映射：

```python
from .finance import finance_accuracy

TOOLS["finance_accuracy"] = finance_accuracy
```

保留原来的 `register_tools()`。同步和异步函数都可注册。不要给函数增加未经约束的任意命令执行能力。

当前 `ToolSkillExecutor` 要求工具返回包含 `output` 的节点结果；输出 Schema 验证的是 `output` 内容，而不是整个返回信封。

## 5. 参数和节点输入不是一回事

契约里的 `params: ["batch"]` 用于把事实中的 `batch` 绑定成 `batch_001`。它不会自动向工具传入 `batch_id`，也不会从自然语言中自动得到数据路径。

显式调用示例：

```python
from plugins.api import Plugin

async with Plugin() as plugin:
    result = await plugin.run({
        "goal": ["accuracy_checked(batch_001)"],
        "initial_conditions": ["answers_ready(batch_001)"],
        "proposal": [{"skill": "finance_accuracy", "args": ["batch_001"]}],
        "inputs": {
            "finance_accuracy:1": {
                "batch_id": "batch_001",
                "answers_path": "evaluation_data/batch_001.jsonl"
            }
        }
    })
```

该例需要上面的技能与真实工具已经接入。`finance_accuracy:1` 是当前编译器第一次实例化该技能时的节点 ID；复杂计划、多次实例化同一技能时编号会变化，不应把这个单节点例子当作通用输入路由。

`answers_ready(batch_001)` 必须先由调用方确认，不要为了让图编译成功伪造事实。输入里的 `batch_id` 必须与事实绑定值一致；当前代码不会自动校验二者的业务对应关系。

`answers_path` 是业务工具参数，其相对路径由该工具决定，不会因为配置目录变化而自动转换。

## 6. 分批验收，不要一次导入后直接跑完整流水线

1. 对原 `SKILL.md` 和资源文件计算哈希，迁移后复核原文件未变。
2. 使用 `skills.get` 确认 ID、契约、工具绑定；使用 `tools.list` 确认工具已注册。
3. 使用 `tools.call` 验证真实工具的参数和返回结构，此步骤不验证完整技能图效果。
4. 使用显式目标完成单技能图执行，核对 `status`、`outputs`、`verification` 和真实报告。
5. 测试缺少输入、类型错误、数据不存在、旧程序异常、评测部分失败等边界。
6. 接入第二项技能，检查字段兼容性、状态依赖和汇总行为。
7. 最后使用自然语言 `task` 验证 Meta 选技和规划，不把 LLM 可生成计划当作业务准确性通过。
8. 比较新旧流水线在同一冻结数据、同一模型和配置下的逐样本结果，事先定义允许的非确定性偏差。

仅新增或调整技能文件时，可调用：

```python
await plugin.call("skills.reload")
```

新增或修改 Python 工具代码后，重启宿主进程。当前注册表不归档技能历史版本；执行图保留当次技能快照，原始技能及规则历史需由业务侧用 Git 或发布目录管理。

## 7. 给其他 AI 的实施清单

交给实施 AI 的资料只需包含：Skills 目录、旧评测代码入口、实际输入输出样例、依赖和结果验收规则。不需要把公司数据复制到公共仓库。

要求其交付：

- 原文件不变的哈希核对结果。
- 每个 Skill 对应的配置条目或 `contract.json`，二选一维护。
- 复用旧代码的执行工具及注册映射。
- Skill ID、工具名、输入输出、前置条件和效果对照表。
- 单技能与组合执行的真实结果，以及未适配的部分。

不要要求其虚构旧 Skills 未提供的流程；遇到没有代码执行器的文字技能，明确记录需要实现的执行能力。
