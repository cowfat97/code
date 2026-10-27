# Harness 接入

Python 3.11+。将整个 `tools/` 目录放入项目，确保其父目录在 Python 模块搜索路径中。模块不依赖 Agent、Skills、插件或 Harness SDK，不启动 HTTP 服务。

## 目录

```text
tools/
├── __init__.py           # 公开接口
├── gateway.py            # 网关入口
├── core/                 # 注册表、数据契约、校验、FunctionCall 解析
├── builtin/              # 内置工具实现
│   ├── text.py
│   ├── text2sql.py
│   └── pgmcp/server.py
├── mcp/                  # 通用 stdio MCP 客户端
├── monitor/              # 事件协议与 SQLite 存储
├── config/
│   ├── gateway.json
│   └── mcp.json
├── docs/
└── state/                # 运行时生成，不提交 Git
```

## 安装

在 `tools/` 的父目录执行：

```bash
python -m pip install -r tools/requirements-mcp.txt
```

该清单包含基础依赖、MCP SDK 和 PostgreSQL 驱动。如果只用本地函数，安装 `tools/requirements.txt`，并使用 `ToolGateway(load_mcp=False)`。

## 最小调用

```python
import asyncio
from tools import ToolGateway

async def main():
    async with ToolGateway() as gateway:
        result = await gateway.call("count_chars", {"text": "hello"})
        print(result.data)  # 5

asyncio.run(main())
```

网关启动时注册内置函数、读取 MCP 配置、启动本地服务并发现工具。退出时停止接收调用，取消活动调用，等待尚未结束的同步函数，关闭 MCP 和监控数据库。建议一个 Harness 生命周期复用一个网关，不要每次工具调用都重新启动。

也可以显式调用 `await gateway.start()`，并在 `finally` 中 `await gateway.aclose()`。关闭可重复调用；关闭后不能重新启动该实例。

## 配置位置与覆盖顺序

`ToolGateway()` 自动读取模块旁边的 `config/gateway.json`：

```json
{
  "load_builtin": true,
  "load_mcp": true,
  "concurrency": 8,
  "timeout": 30.0,
  "mcp_file": "mcp.json",
  "monitor_file": "../state/events.sqlite3"
}
```

- 文件内的路径相对于该配置文件，不受 Harness 当前工作目录影响。
- 默认监控数据库为 `tools/state/events.sqlite3`。
- `monitor_file` 设为 `null` 可关闭内置 SQLite 持久化。
- 构造参数优先于配置文件，例如 `ToolGateway(concurrency=4, timeout=10)`。
- `ToolGateway.from_config("tools/config/gateway.json")` 可指定配置文件。
- 显式传入的 `mcp_config`、`monitor_path` 若为相对路径，则相对于当前进程工作目录。

## Harness 注册函数

```python
from tools import ToolGateway

def add(a: int, b: int) -> int:
    """计算两个整数之和。"""
    return a + b

async def use_tools():
    async with ToolGateway() as gateway:
        gateway.register(add, name="add")
        result = await gateway.call("add", {"a": 2, "b": 3})
        print(result.data)
        gateway.unregister("add")
```

支持同步和异步函数。建议明确标注参数、返回类型，以自动生成输入输出 Schema；也可在 `register()` 中显式传 `input_schema`、`output_schema`、`description`。自动生成 Schema 不支持位置专用参数和可变参数。

同名注册报错，不静默覆盖。函数也可以在启动前注册；启动时若与内置工具重名，同样报错。

## 模块自带函数

在 `builtin/` 下编写函数，在 `builtin/__init__.py` 导入并加入 `BUILTIN_TOOLS`：

```python
from .custom import custom_tool
BUILTIN_TOOLS["custom_tool"] = custom_tool
```

现有预置函数为 `count_chars`。修改清单后重启进程，不需要 Harness 重复注册。导入模块时不要执行业务动作或创建数据库连接。

## FunctionCall 接入模型循环

```python
# 将 definitions 交给 Harness 使用的模型客户端。
definitions = gateway.function_definitions()

# 收到模型返回的一条 tool_call 后调用。
message = await gateway.handle_function_call({
    "id": "call_001",
    "type": "function",
    "function": {
        "name": "count_chars",
        "arguments": "{\"text\": \"hello\"}"
    }
})
# message 是 role=tool、tool_call_id、content 组成的字典。
# Harness 将它追加到模型消息列表，自行决定是否继续请求模型。
```

网关不运行模型循环，也不自动消费模型回复。多个 tool_call 由 Harness 决定顺序执行或 `asyncio.gather()` 并发执行。

也可以使用：

```python
result = await gateway.function_call("count_chars", '{"text":"hello"}')
```

MCP 工具的公开名称带点，例如 `pgmcp.query`。模型 FunctionCall 名称受字符和长度限制，因此 `function_definitions()` 会为不兼容名称生成稳定别名。把模型实际返回的名称交给 `handle_function_call()`，网关会还原；不要自行拼接别名。直接 `call()` 仍使用 `pgmcp.query`。

## MCP 接入

当前只支持本地 stdio，不自动下载或安装服务。默认 `config/mcp.json` 已启用模块自带的 PG MCP：

```json
{
  "mcp_servers": {
    "pgmcp": {
      "command": "@builtin/pgmcp",
      "allowed_tools": ["query", "execute", "list_tables", "describe_table"]
    }
  }
}
```

`@builtin/pgmcp` 由网关解析为当前 Python 解释器和 `builtin/pgmcp/server.py`，不是需要下载安装的第三方同名项目。

自定义本地 MCP 服务支持 `command`、`args`、`cwd`、`env`、`allowed_tools`、`enabled`、`connection_timeout`。配置文件中的 `cwd` 相对于 `mcp.json`；未填时使用该配置所在目录，脚本参数按这一工作目录解析。

### 新增本地 MCP 服务

1. 获取服务源码，或按该服务的说明安装 Python 包。网关只负责启动与调用，不负责下载。
2. 将服务与网关分开放置，例如：

```text
项目/
├── tools/
│   └── config/mcp.json
└── mcp_servers/
    └── search/
        ├── server.py
        └── requirements.txt
```

3. 按服务实际提供的依赖清单安装依赖。若有 `requirements.txt`，在项目目录执行：

```bash
python -m pip install -r mcp_servers/search/requirements.txt
```

4. 编辑 `tools/config/mcp.json`，在 `mcp_servers` 中追加服务，保留原有配置。完整示例：

```json
{
  "mcp_servers": {
    "pgmcp": {
      "command": "@builtin/pgmcp",
      "allowed_tools": ["query", "execute", "list_tables", "describe_table"]
    },
    "search": {
      "command": "python",
      "args": ["server.py"],
      "cwd": "../../mcp_servers/search",
      "enabled": true,
      "allowed_tools": ["search"]
    }
  }
}
```

`command` 必须指向已安装服务依赖的解释器；`python` 取决于启动 Harness 时的 PATH，不保证与 Harness 自身解释器相同。独立虚拟环境应配置对应解释器。

`cwd` 从 `tools/config/` 解析，因此 `../../mcp_servers/search` 指向项目下的服务目录。`args` 必须与服务实际启动方式一致；若服务使用 `python -m 包名`，配置为 `"args": ["-m", "包名"]`。

5. 重启网关，检查发现的工具再调用：

```python
from tools import ToolGateway

async with ToolGateway() as gateway:
    print([tool.name for tool in gateway.list_tools()])
    result = await gateway.call("search.search", {"query": "内容"})
    if result.is_error:
        print(result.content)
    else:
        print(result.data)
```

前一个 `search` 是配置的服务名，后一个是服务实际暴露的工具名。参数必须符合该工具的 Schema；本例不代表模块已经内置搜索服务。

`allowed_tools` 省略时导入全部工具，设为 `[]` 时不导入工具，设为工具名列表时只导入列出的工具。`enabled: false` 可禁用服务。

服务必须使用 stdio MCP 协议：标准输出用于协议消息，日志应写到标准错误。单纯的 Python 函数文件不是 MCP 服务；普通函数使用 `register()` 接入。

### Harness 动态接入

Harness 也可以动态注册：

```python
await gateway.register_mcp("custom", {
    "command": "python",
    "args": ["server.py"],
    "cwd": "mcp_servers/custom",
    "allowed_tools": ["search"]
})
result = await gateway.call("custom.search", {"query": "内容"})
await gateway.unregister_mcp("custom")
```

动态注册的相对 `cwd` 相对于当前进程工作目录。注销 MCP 服务会移除它的全部工具；存在活动调用时拒绝注销，调用结束后再操作。单个 MCP 工具不能通过普通 `unregister()` 移除。

## PG 工具

启动 Harness 前设置 libpq 标准环境变量：`PGHOST`、`PGPORT`、`PGDATABASE`、`PGUSER`，密码使用 `PGPASSWORD` 或本机密码文件。必须提供数据库名和用户名；模块不猜测账号或密码。PG 服务与驱动都需要自行准备，工具发现成功不代表数据库连接已成功。

内置 PG MCP 启动时继承允许的 PG 环境变量；修改连接配置后重启网关。数据库连接在调用时建立，不在发现工具时建立。

```python
result = await gateway.call("pgmcp.list_tables", {"schema": "public"})
result = await gateway.call("pgmcp.describe_table", {
    "schema": "public", "table": "records"
})
result = await gateway.call("pgmcp.query", {
    "sql": "SELECT * FROM records WHERE id = %s",
    "parameters": [1], "max_rows": 100
})
```

写入接口：

```python
result = await gateway.call("pgmcp.execute", {
    "sql": "UPDATE records SET label = %s WHERE id = %s RETURNING id",
    "parameters": ["new label", 1]
})
```

表名和列名必须来自实际业务结构。以上 SQL 仅展示参数传递方式，不代表模块自带 `records` 表。

- `query` 使用只读事务；`execute` 使用可写事务。
- 每次调用执行一条 SQL，成功提交，失败回滚；不是跨多次调用的共享事务。
- 结果包含 `columns`、`rows`、`truncated`、`rowcount`。
- `max_rows` 为 1 至 1000，只限制返回行数，不保证限制数据库内部计算或驱动缓冲。
- 语句超时默认 10000 毫秒，可通过 `PGMCP_STATEMENT_TIMEOUT_MS` 设置，范围 1 至 300000。
- 写入超时、取消或连接中断时，结果可能未知，不能据此断言回滚；模块不会自动重试。

## Text2SQL

Text2SQL 是独立的本地工具，只生成 SQL 和参数，不连接或执行数据库。使用前由 Harness 注册模型提供方：

```python
from tools import OpenAIText2SQL

gateway.register_text2sql(OpenAIText2SQL(
    base_url="http://127.0.0.1:8000/v1",
    model="实际模型名称",
    api_key_env=None
))
result = await gateway.call("text2sql", {
    "question": "统计记录数量",
    "database_schema": "实际表结构文本"
})
statement = result.data  # {"sql": "...", "parameters": [...]}
```

接口兼容 OpenAI Chat Completions。需要鉴权时用 `api_key_env` 指定密钥环境变量名称。也可以实现 `SQLGenerator.generate(question, schema)`，返回 `SQLStatement`，替换模型厂商。

Harness 负责提供真实表结构、检查生成结果、决定调用 `pgmcp.query` 还是 `pgmcp.execute`。SQL 输出格式校验不等于业务语义正确或授权通过。模型不可用或输出无效时明确报错，不伪造 SQL。

## SQLite 监控

自动保存注册、注销、调用开始、成功、失败、超时、取消，以及 MCP 连接事件。记录时间、工具名、来源、调用 ID、耗时和错误类型；不保存工具参数、结果、SQL、密码或模型提示词。

```python
records = gateway.monitoring_events(name="count_chars", limit=100)
records = gateway.monitoring_events(kind="call_failed", limit=100)
records = gateway.monitoring_events(call_id="实际调用ID")
records = gateway.monitoring_events(after_id=100, limit=100)
```

返回按事件 ID 升序排列。`after_id` 用于增量查询；`limit` 范围 1 至 1000。进程重启不会删除既有事件。

可关闭内置持久化，并传入自己的同步、非阻塞事件接收器：

```python
gateway = ToolGateway(monitor_path=None, observers=[handle_event])
```

接收器异常与工具执行隔离，不会导致工具重复执行。检查 `gateway.monitoring_errors` 可发现本实例的监控故障；故障期间事件可能缺失，不承诺审计零丢失。SQLite 接收器独立位于 `monitor/`，不访问 PG 业务库。

## 返回与错误

`call()` 和 `function_call()` 返回 `ToolResult`，包括 `data`、`content`、`is_error`。MCP 服务返回的工具错误可能表现为 `is_error=True`，Harness 必须检查；参数校验、工具不存在、超时或本地执行失败则可能直接抛出异常。

```python
from tools import ToolError

try:
    result = await gateway.call("count_chars", {"text": "hello"})
    if result.is_error:
        pass  # 由 Harness 决定如何反馈工具错误，不盲目重试。
except ToolError as error:
    error_type = type(error).__name__
```

执行超时覆盖排队等待时间。同步函数在工作线程执行，超时或取消不能强杀线程，后台工作可能继续；关闭网关会等待它结束。注册表只在进程内保存，重启后由预置清单、配置和 Harness 重新注册；SQLite 只保存监控历史。

## 验证范围

已验证本地函数、动态注册、并发、超时、取消、FunctionCall、SQLite 持久化、真实 stdio MCP 工具发现和调用分发。Text2SQL 已验证 HTTP 请求/响应契约，未评估真实模型 SQL 正确率。当前环境无法连接目标 PG，真实数据库查询、提交和回滚仍需在可连接环境验证。

### 通用内置工具

默认注册 `read_file`、`list_files`、`parse_document`、`validate_json`、`write_artifact`、`http_request`，以及 `count_chars`。
`config/gateway.json` 的 `builtin` 控制权限：`read_roots` 为允许读取的目录（默认空），`artifact_dir` 为写入目录，`http_allowed_origins` 为 HTTP 源白名单（如 `https://api.example.com`，默认空）。相对路径均相对配置文件目录。
文件与产物上限由 `max_file_bytes` 控制，目录枚举上限为 `max_list_entries`，HTTP 请求体和响应上限为 `max_response_bytes`。目录链接不会被递归遍历，越界路径会被拒绝。产物路径必须是相对路径，默认禁止覆盖；HTTP 不跟随重定向、不读取环境代理配置。

```python
await gateway.call("read_file", {"path": "source.md"})
await gateway.call("list_files", {"path": ".", "recursive": True})
await gateway.call("parse_document", {"path": "source.pdf"})
await gateway.call("validate_json", {"value": {"id": 1}, "json_schema": {"type": "object"}})
await gateway.call("write_artifact", {"path": "results/dag.json", "content": "{}"})
await gateway.call("http_request", {"url": "https://api.example.com/status"})
```

PDF、Word 解析需要额外安装 `requirements-documents.txt`，按页/段落提取文字，无 OCR；TXT、Markdown、JSON、YAML 返回原始 UTF-8 文本。PDF 最多 500 页；DOCX 解压内容最多为文件限制的 10 倍。Schema 采用 Draft 2020-12，允许本地引用，不获取远程引用，最多返回 100 条错误。
