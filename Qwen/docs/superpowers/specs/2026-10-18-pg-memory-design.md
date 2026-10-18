# PostgreSQL 记忆持久化设计

日期：2026-10-18
状态：已实现并通过本机 PostgreSQL 集成验证
范围：内部 PG 操作模块与全局记忆持久化。
用户已确认：数据库工具仅供代码内部使用；不需要区分会话。

## 1. 目标

当前 core_loop._messages 是进程内单份历史，程序重启丢失。
将这份历史存入 PostgreSQL，CLI、Web 以及后续启动的程序共用同一份记忆。
不引入 session_id、用户隔离、会话列表或切换功能。
保持 memory_search 的现有语义：检索此前成功提交的真实用户消息。

## 2. 职责与目录

- agent/infrastructure/postgres.py：内部 PG 工具，封装短连接、参数化执行、
  事务及连接/语句超时，不注册为模型可调用的 ToolSpec。
- agent/infrastructure/memory_store.py：PgMemoryStore，固定 SQL 读写全局历史。
- agent/entities/memory.py：MemorySnapshot、MemoryConflictError、MemoryStorageError。
- agent/common/config.py：读取 PostgreSQL 连接配置。
- agent/core/workflow/core_loop.py：读取历史、运行本轮、成功后保存，不直接写 SQL。
- migrations/001_memory.sql：可重复执行的初始化 SQL。
- tests/：存储、核心流程和实际 PG 集成测试。

内部接口：
- load() -> MemorySnapshot(messages, revision)
- save(expected_revision, messages) -> new_revision
- chat(agent, *, store=None)，正常运行使用 PG，测试显式注入内存替身。

不通过监控 hooks 保存记忆：监控失败可以忽略，权威历史保存失败必须明确报错。
不依赖模型主动调用保存工具，避免模型遗漏保存或半轮历史提前落库。

## 3. 数据模型

沿用本机 PostgreSQL 的 dev 数据库，在 qwen schema 创建 memory 表：
- id SMALLINT PRIMARY KEY CHECK (id = 1)：固定为 1，保证全表只有一份记忆。
- revision BIGINT NOT NULL CHECK (revision > 0)
- messages JSONB NOT NULL CHECK (jsonb_typeof(messages) = 'array')
- updated_at TIMESTAMPTZ NOT NULL DEFAULT now()

messages 保存完整已提交历史快照，延续 role/content 字符串协议，
包括 system、真实用户输入、assistant 行动和工具观察。
尚无记录时 load 返回 messages=[]、revision=0。
第一版保持完整历史，不增加向量检索、消息分页、摘要或自动裁剪。

## 4. 数据库工具与配置

使用 psycopg[binary]>=3.2,<4。
连接上下文负责事务提交/回滚和连接释放；模型运行期间不持有数据库连接。
所有值采用驱动参数绑定，不把用户内容拼进 SQL。
默认连接超时与 statement_timeout 均为 5 秒。
凭据不写入源码、日志或 Git，沿用本机现有配置或受保护的凭据文件。

配置：
- PGHOST：默认 127.0.0.1
- PGPORT：默认 5433
- PGDATABASE：默认 dev
- PGUSER：默认 dev
- PGPASSWORD：由环境变量或受保护凭据文件提供

初始化通过显式命令执行 migration，不在每轮聊天执行 DDL。
不自动安装或升级数据库服务，不修改 Hindsight 或其他服务的表。

## 5. 读取与提交时机

1. 每轮开始从 PG 读取唯一历史及 revision，构造工作副本。
2. 工具绑定此前已提交的历史；当前用户输入随后加入工作副本。
3. 执行模型和工具；本轮变化暂不落库。
4. 最终回答、工具结果序列化和附注全部成功后，事务保存完整历史。
5. 提交成功才返回 reply/count/chars，统计语义维持不变。

模型、工具或附注失败不提交本轮历史。
数据库不可用或保存失败则明确报错，不静默退回进程内存。
数据库事务不能回滚工具已造成的外部副作用。

## 6. 多进程并发

不区分会话不等于允许覆盖：多个程序可能同时基于旧历史回答。
使用 revision 乐观并发控制，不在等待模型期间持有数据库锁：
- 初次写入 id=1；若其他进程已创建记录，则报告冲突。
- 后续 UPDATE 仅在 revision 与读取值一致时提交并原子递增。
- 版本不匹配抛 MemoryConflictError，不覆盖最新历史，也不自动重放工具。

原有进程锁可保留；跨进程一致性由 PG 检查。
若数据库已提交但客户端丢失提交响应，本轮明确报告状态不确定，不盲目重试写入；
后续读取以 PG 实际结果为准。

## 7. 入口与迁移

CLI、Web 和 chat_workflow 不增加会话参数，默认读取同一份历史。
移除全局 _messages 作为历史事实来源，测试改为显式注入存储。
不读取或迁移其他已运行 Python 进程内的旧历史。
migration 只创建项目 schema 和表，不删除或覆盖现有数据。

## 8. 验证

- 进程 A 保存，进程 B 能读取同一份历史，memory_search 命中先前用户消息。
- CLI 与 Web 读取同一份历史，无会话 ID 配置。
- 模型、工具、序列化或附注失败，不提交新历史。
- 数据库连接或保存失败明确报错，不返回“已保存”的假象。
- 并发旧版本写入只有一个成功，另一个报告冲突。
- 参数绑定正确处理中文、引号和类似 SQL 的文本。
- 实际 PG 验证事务提交、异常回滚、连接释放与超时。
- 测试使用独立临时数据库或隔离测试 schema，不修改实际全局记忆；
  生产 SQL 表名固定，测试通过独立数据库或测试迁移隔离，不能删除真实 id=1。
- 原有工具、监控 hooks、CLI/Web 回归通过。

## 9. 已知边界

所有调用共享一份历史，这是用户要求的单份记忆行为。
历史增长、跨设备同步、检索算法升级及外部工具副作用回滚不在本次范围内。
