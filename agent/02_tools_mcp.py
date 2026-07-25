# ============================================================
# Agent 复习 — 工具调用 / MCP 协议
# ============================================================

# ── 1. Tool 定义 ──
# @tool 装饰器：函数 → Tool 对象
# StructuredTool：Pydantic 模型定义参数 schema
# Tool 的描述字段：Agent 根据 description 判断何时用
# args_schema：自动从函数签名或 Pydantic 生成

# ── 2. Agent 如何调用工具 ──
# AgentExecutor：ReAct 循环（思考 → 行动 → 观察）
# bind_tools / with_structured_output：模型侧绑定工具
# ToolMessage：工具执行结果返回模型
# 工具调用错误处理：InvalidToolCall、超时重试

# ── 3. MCP（Model Context Protocol）──
# 是什么：模型和外部工具之间的标准通信协议
# Client-Server 架构：Agent 是 Client，工具提供方是 Server
# 传输层：stdio（本地进程）、SSE/HTTP（远程服务）
# 核心接口：tools/list、tools/call、resources/read
# 一个 MCP Server = 一组工具的集合，独立进程运行

# ── 4. MCP 实战 ──
# 启动 MCP Server：npx 命令或 Python 脚本
# 注册到 Agent：MCPToolkit 或手动管理生命周期
# 和普通 Tool 的区别：进程隔离、跨语言、动态发现
# 安全：参数白名单、权限校验、沙盒执行

# ── 5. A2A（Agent-to-Agent）──
# 和 MCP 的区别：A2A 管 Agent 之间协作，MCP 管 Agent 调用工具
# 统一消息格式、任务分发、结果汇聚
# 使用场景：多个专职 Agent 分工协作

# ── 6. 练习 ──
# 定义两个 @tool：一个查天气、一个算汇率
# 写一个 Agent 自动选择工具回答用户问题
