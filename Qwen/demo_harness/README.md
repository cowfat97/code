# Demo Harness

Python 3.11 独立演示模块。核心仅依赖标准库，通过 `Backend` 协议调用外部能力；只有 `bridge.py` 引用 model 和插件。不修改其他模块配置，不启动 MCP，不执行业务工具。

在 Qwen 目录执行：

```sh
python -m pip install -r demo_harness/requirements.txt
python -m demo_harness
```

先配置同级 `model/.env`，然后打开 `http://127.0.0.1:8765`。模型未配置时明确失败，不返回模拟结果。图使用现有 Skills，不能保证任意需求都可编译。

唯一业务入口：

```python
from demo_harness import Harness

harness = Harness(your_backend)  # 实现 ports.Backend，适配其他插件无需改核心
response = await harness.chat("用户任务")
response = await harness.chat("补充要求", response["session_id"])
response = await harness.chat(
    "",
    response["session_id"],
    action="confirm",
    expected_revision=response["artifacts"]["task"]["draft"]["revision"],
)
```

本机默认组装使用 `await demo_harness.bridge.LocalBackend.create()`；退出时调用 `await backend.aclose()`。网页调用同一入口，展示对话、任务 JSON、真实 DAG 节点与依赖，并下载产物 JSON。

会话只存内存，重启丢失；图快照保存到本模块 `state/graphs`。最多 100 个会话，每会话 100 轮。只对当前草稿显式确认，模型不能代替用户确认。生成失败保留已确认任务，再次确认可重试编图。仅限本机演示，未提供身份认证和生产部署能力。

## 初始事实与输入

`config/request.json` 默认 `{}`。可以配置调用方已核实的 `initial_conditions`、`inputs` 和 `context`；每个新会话先将它们交 Task 审查，确认后传 Graph。这里只接收声明，不证明事实；模型不能凭空补齐初始前置条件。配置变化只影响随后新建的会话，用户输入优先。

例如公司已确认需要金融定量评测时，可以声明 `initial_conditions` 包含 `task_requested(finance)` 和 `quantitative_selected(finance)`。`inputs` 必须符合所用 Skill 的真实输入契约；现有 Graph Skills 目录 `eval_requirements/examples/finance_quantitative.json` 提供虚构验证资料示例，可取其中 `initial_conditions`、`inputs` 字段放入本配置，不复制其固定 `goal`。不同业务配置不同事实，不应把金融前提用于法律任务。配置不足则编图明确失败；不会自动制造事实。
