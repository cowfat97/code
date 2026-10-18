# PostgreSQL 全局记忆

CLI、Web 和重启后的程序共用 PG 中同一份历史，不区分会话。
每轮开始读取历史，整轮成功后保存；持久化提交成功才返回回答。
memory_search 继续检索此前提交历史中的用户消息。

## 启动与初始化

首次部署：
    uv pip install --python .venv\Scripts\python.exe -r requirements.txt
    .venv\Scripts\python.exe -m agent.infrastructure.memory_store

常规聊天：
    .venv\Scripts\python.exe quick_start.py

HTTP 接口：
    .venv\Scripts\python.exe -m agent.web.controller

默认连接本机 127.0.0.1:5433，数据库 dev，用户 dev。
可通过 PGHOST、PGPORT、PGDATABASE、PGUSER 覆盖。
密码由 PGPASSWORD 或 libpq 标准密码文件提供，不写进源码或 plugins.json。
Windows 标准密码文件为 %APPDATA%\postgresql\pgpass.conf；
该文件应仅本人可访问，不纳入仓库。
切换 PostgreSQL 数据库不会自动迁移旧数据库的记忆。

初始化只创建 qwen schema 和 qwen.memory 表，不清空已有历史。
表只有 id=1 一行；messages 是 JSONB 历史快照，revision 是并发控制版本。
尚无历史时不预先创建空行，首次成功聊天创建该行。

## 内部数据库操作

agent.infrastructure.postgres.Postgres 提供：
- transaction()：连接/事务上下文，成功提交、异常回滚，结束释放连接。
- fetch_all(sql, params)：参数化查询。
- execute(sql, params)：执行内部 SQL，返回影响行数。

PgMemoryStore.load() 返回 MemorySnapshot(messages, revision)。
PgMemoryStore.save(expected_revision, messages) 检查版本、提交并返回新版本。
这些都是内部 Python 接口，不是模型可以调用的 SQL 工具。

模型或工具执行期间不持有数据库连接。
数据库不可用、未初始化或保存失败时明确报错，不静默改用内存。
并发进程读取同一版本后，只允许其中一个保存；另一个报告冲突，不覆盖新历史，
也不自动重放可能产生副作用的工具。
数据库事务只能回滚记忆，无法撤销工具已经产生的外部副作用。

## 验证

在 Windows PowerShell：
    $env:QWEN_TEST_PG = "1"
    .venv\Scripts\python.exe -B -X utf8 -m unittest discover -s tests

PG 集成测试自动创建 qwen_memory_test_<随机值> 数据库，结束后删除该测试库。
测试账号需有创建数据库权限；实际 qwen.memory 不会被测试清空。
未设置 QWEN_TEST_PG 时跳过真实 PG 测试，普通单元测试使用隔离存储替身。

Agent 的安全文件插件测试需要 POSIX 接口，另在 WSL 执行：
    python -B -m unittest discover -s agent/tests

历史仍完整增长；摘要、向量检索、归档和裁剪尚未加入。
旧进程内尚未保存的历史不会自动迁入 PG。
