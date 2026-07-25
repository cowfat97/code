# ============================================================
# Agent 复习 — LangChain / LangGraph 核心
# ============================================================

# ── 1. LangChain 核心抽象 ──
# Chain：可组合的执行单元，pipe 串连
# PromptTemplate：模板化 prompt，input_variables 声明入参
# LLM / ChatModel：统一接口调用不同模型
# OutputParser：StrOutputParser、JsonOutputParser
# Runnable 接口：invoke、batch、stream（所有组件都实现）
# LCEL (LangChain Expression Language)：用 | 管道串联 chain

# ── 2. LCEL 管道 ──
# chain = prompt | llm | output_parser
# 为什么用管道：延迟执行、支持 batch/stream/async
# RunnablePassthrough：透传数据
# RunnableLambda：包装自定义函数
# RunnableParallel：并行执行多个子链

# ── 3. LangGraph 核心 ──
# StateGraph：有状态的图（vs LangChain 无状态链）
# State：TypedDict 或 Pydantic 模型，贯穿全流程
# Node：处理节点，读取 state 返回更新
# Edge：条件边 conditional_edges、普通边 add_edge
# 编译 graph.compile() → 返回可执行的 app

# ── 4. LangGraph 高级特性 ──
# checkpoint：保存中间状态到 sqlite/postgres
# interrupt / human-in-the-loop：人工审批节点
# send / Command：动态并行分发任务
# subgraph：嵌套子图

# ── 5. 练习 ──
# 用 LCEL 写一个链：输入 topic → prompt 包装 → LLM 生成 → 解析为 JSON
# 用 LangGraph 写一个双节点图：节点A生成→节点B润色
