# grasp-metaskills 0.1.0 实现规格与复现设计

本文描述当前代码行为。目标读者是需要独立重建项目的开发者或代码生成 AI。实现时以字段、步骤、公式和失败条件为约束，不补入未定义的自动化能力。

配套文件 [reproduction-data.json](reproduction-data.json) 提供 17 个统一契约模型和 4 个原生文档模型的 JSON Schema、实际 SQLite DDL、844 段 Rust 字符分类闭区间、完整 GraSP Golden 输入/期望图、停用词及 18 个源码模块 SHA-256。复现需要本文与该数据文件；不需要原 Python 源码才能理解核心算法。上游归属见第 22 节。

## 1. 实现范围与组件关系

环境：Python >=3.12；Pydantic >=2.8,<3；jsonschema >=4.23,<5；packaging >=24。标准库提供 SQLite、asyncio、hashlib、json、random、subprocess、fcntl。SQLite 必须支持 FTS5；仅启用 Git 存储时需要系统 git。包没有默认 shell 技能执行器，不启动 JS/Rust 进程。

文件职责如下；保持一个包、一个 Registry，不建立平行技能存储服务。

| 文件 | 必须实现的对象或函数 |
|---|---|
| contracts.py | Skill、SkillContract、SkillNode、DependencyEdge、ExecutionGraph、NodeResult、VerificationResult、NodeState、GraphState、ExecutionContext、ExecutionTrace、SearchResult、修复模型 |
| providers.py | 五个可注入 Protocol，见第 3 节 |
| metaskills_spec.py | 原生 SkillSpec 规范化、Markdown 编译、双向映射、原生内容哈希 |
| registry.py | 单一 SQLite Registry、不可变版本、全文/向量/混合检索、导入导出、反馈、运行快照 |
| registry_storage.py | RegistryStorageMixin，在同一个 SQLite 连接上适配存储事务，不是第二个 Registry |
| metaskills_storage.py | GitArchive、StorageBackend Protocol、TxManager |
| metaskills_dependencies.py | 能力依赖闭包、循环检测、排序和加载级别 |
| metaskills_composition.py | extends/includes 合并和警告 |
| metaskills_search.py | hash embedding、VectorIndex、f32 RRF、过滤 |
| metaskills_recommendation.py | reward、Beta/Thompson bandit、上下文修正 |
| registry_recommendation.py | 从 feedback 重放 bandit；应用层候选评分策略 |
| retrieval.py | GraSP 的任务/历史混合检索分布、置信度和路由标签 |
| compiler.py | 目标反向规划、实例化、图构建、依赖扩展、Schema 兼容检查 |
| verification.py | 前置条件、输入 Schema、输出 Schema、效果检查 |
| runtime.py | 并发批次调度、状态、重试、取消、恢复、缓存、反馈 |
| repair.py | 五种修复操作、补丁验证、版本增加、局部失效和审计 |
| adapters.py | GraSP manifest 和有限 frontmatter 适配 |
| __init__.py | 公开主要模型、Protocol、Registry、Compiler、Runtime、RepairEngine 和搜索/原生转换工具 |

主调用链：

```text
register / register_spec
    → 一个 SQLite Registry
    → search 调整候选优先级
    → GraphCompiler.compile(task, goal)
    → 固定 Skill 快照的 ExecutionGraph
    → GraphRuntime.execute
    → 内置验证 + 可选自定义验证
    → failed 时 RepairEngine
    → 新图版本 + 局部重执行
    → GraphState + SQLite snapshots + feedback + episodes
```

`task` 是召回文本；`goal` 是显式谓词列表。系统不负责把任意自然语言任务自动翻译成可靠目标，也不内置业务执行能力。

## 2. 统一数据模型

### 2.1 基础规则

统一契约继承 `BaseModel`，`extra='forbid'`。集合字段均使用 default_factory，避免实例间共享。`Skill` 设置 `frozen=True`，但其内部 dict/list 仍可变；跨编译、执行和修复边界必须深拷贝，不能仅依靠 frozen。

JSON Schema 使用 Draft 2020-12。创建 SkillContract 时对两个 Schema 调用 `Draft202012Validator.check_schema`，并拒绝重复参数名。Schema 字段类型为 dict，不接受布尔 Schema 作为顶层字段。

### 2.2 字段定义

| 模型 | 字段及默认值 |
|---|---|
| SkillDependency | id:str；version:str='*' |
| SkillContract | params:list[str]=[]；preconditions:list[str]=[]；effects:list[str]=[]；input_schema:dict={}；output_schema:dict={}；validators:list[str]=[] |
| Skill | id:str（非空）；name:str；version='1.0.0'；description=''；content=''；metadata:dict={}；source=''；dependencies:list[SkillDependency]=[]；contract=SkillContract()；content_hash='' |
| InputBinding | node_id:str；output_key:str |
| SkillNode | id:str；skill:Skill或None；kind:'src'/'skill'/'snk'，默认skill；args:list[str]=[]；preconditions=[]；effects=[]；bindings:dict[str,InputBinding]={}；input_values:dict={}；repair_budget:int=2，>=0 |
| DependencyEdge | source:str；target:str；type:'state'/'data'/'order'；label='' |
| ExecutionGraph | id=UUID4字符串；version=1且>=1；task=''；goal=[]；initial_conditions=[]；nodes=[]；edges=[]；metadata={} |
| NodeResult | output:dict={}；observed_effects:list[str]=[]；evidence:list[str]=[] |
| VerificationResult | passed:bool；category=''；message=''；details:dict={} |
| NodeState | status='pending'；attempt=0；result=None；verification=None；error=None；idempotency_key=None；cache_key=None；recovery_retry=False |
| GraphState | graph_id:str；graph_version=1；status='pending'；nodes:dict[str,NodeState]={}；facts:list[str]=[]；trace:list[ExecutionTrace]=[]；repair_attempts:dict[str,int]={}；repair_audit:list[dict]=[] |
| ExecutionContext | graph_id:str；node_id:str；idempotency_key:str；facts:tuple[str,...]=() |
| ExecutionTrace | node_id:str或None；event:str；details={}；timestamp=UTC ISO 8601 当前时间 |
| SearchResult | skill:Skill；score:float |
| RepairOperation | type 为五个实际操作之一；node_id:str；args:list[str]或None；replacement:Skill或None；prerequisites:list[SkillNode]=[]；edge:DependencyEdge或None |
| RepairEvent | node_id:str；type:str；message=''；state:list[str]=[]；args:list[str]或None |
| RepairResult | repaired:bool；graph:ExecutionGraph；state:GraphState；operation:RepairOperation或None；reason='' |

NodeState.status 和 GraphState.status 当前是字符串，合法状态由运行流程约定，不是模型枚举校验。不要在复现规格中声称其有独立的强制状态转换表。

### 2.3 图模型方法

- `node(id)`：顺序查找，找不到抛 KeyError。
- `topological_order()`：按 nodes 顺序初始化零入度队列，Kahn 算法；每条边独立增加入度，包括同一对节点的不同边。未知端点抛 ValueError；出队数量不等于节点数时报告 cycle。
- `descendants(roots)`：反复扫描所有边扩展可达集合，结果包含 roots 本身。
- `validate_graph()`：收集重复节点 ID、拓扑错误、kind=skill 但缺少 Skill 快照、绑定来源不存在、绑定缺少同源同目标 data 边。返回错误字符串列表，不检查所有领域契约，也不校验快照是否与 Registry 的完整文档逐字段一致。

`SkillNode.preconditions/effects` 是参数绑定后的调用事实；`Skill.contract` 保留定义模板。输入值不会通过字符串参数绑定自动替换，必须通过 input_values/bindings 提供。

## 3. 可注入接口及权限边界

接口签名必须与调用方一致：

```python
class LLMProvider(Protocol):
    async def complete(self, prompt: str) -> str: ...

class EmbeddingProvider(Protocol):
    def embed(self, texts: list[str]) -> list[list[float]]: ...

class SkillProposer(Protocol):
    async def propose(self, *, task: str, skills: list[Skill],
                      goal: list[str]) -> list[dict[str, Any]]: ...

class SkillExecutor(Protocol):
    async def execute(self, node: SkillNode, inputs: dict[str, Any],
                      context: ExecutionContext) -> NodeResult: ...

class SkillVerifier(Protocol):
    async def verify(self, node: SkillNode, inputs: dict[str, Any],
                     result: NodeResult,
                     context: ExecutionContext) -> VerificationResult: ...
```

Executor 是实际执行能力的唯一入口；调用方负责网络、文件、模型请求、认证和外部幂等。它接收节点、输入、上下文的深拷贝。Skill.content 是数据，不会自动交给 shell。EmbeddingProvider 是同步批量接口，当前搜索会在调用线程中运行它。LLMProvider 仅定义边界，没有默认云端实现，也没有隐式调用。

SkillProposer 仅在 task 非空、proposer 已注入且 proposal 未显式传入时调用。返回 proposal 后仍必须经过编译检查。

## 4. MetaSkills 原生文档映射

### 4.1 原生结构

原生四类模型设置 `extra='allow'`，保留未知扩展字段：

- SkillBlock：id、content 必填；block_type 默认 text，当前类型是 str。
- SkillSection：id、title 必填；blocks 默认空。
- SkillMetadata 按声明顺序：id=''、name=''、version=''、description=''、tags=[]、requires=[]、provides=[]、platforms=[]、author=None、license=None、context={}。
- SkillSpec 按声明顺序：format_version='1.0'、metadata 必填、sections=[]、extends=None、replace_rules=False、replace_examples=False、replace_pitfalls=False、replace_checklist=False、includes=[]。

当前 Python 对缺省 sections/block_type 比原生 serde 反序列化宽松；复现现代码需保留该便利默认值，不能称为逐项原生输入校验等价。

### 4.2 normalize_spec

1. 用 SkillSpec 校验并 `model_dump(mode='json')`。
2. 删除值为 None 的 extends；删除值为 False 的四个 replace 标记。
3. 空 includes 删除；非空时每项缺省 position='append'，prefix/sections 为 None 时删去这两个键。
4. metadata.context 仅保留值为 truthy 的项；结果为空则删除 context。
5. 不排序对象键。已声明字段按模型声明顺序输出，未知字段保留为扩展。

原生哈希：

```text
spec_digest = SHA256(
  UTF8(json.dumps(normalize_spec(spec),
                  ensure_ascii=False, separators=(',', ':')))
).hexdigest()
```

这与统一 Skill.content_hash、运行缓存 cache_key 是三种不同算法输入，不得混用。扩展字段也参与原生哈希；不宣称含未知映射字段时与所有 Rust 序列化顺序都相同。

### 4.3 原生文档 → Skill

`skill_from_spec(spec, contract=None, source='')`：

1. 规范化；显式 contract 写入顶层 grasp_contract；否则读取已有 grasp_contract；都没有则空契约。
2. metadata 先复制 grasp_metadata，再用原生 metadata 覆盖同名键。
3. 移除 id/name/version/description 作为 Skill 身份；其余仍留在 Skill.metadata。
4. metadata.metaskills_spec 保存规范化文档，metaskills_spec_hash 保存原生哈希。这是原始结构溯源，不是第二套实时依赖权威。
5. 原生版本为空时临时使用 0.1.0，并记录 metaskills_declared_version=''；最终注册版本映射见第 6 节。
6. dependencies 从 grasp_dependencies 显式解析。source 优先 grasp_source，其次 source 参数，最后 `metaskills://skills/<id>`。
7. content 优先 grasp_content，否则使用 Markdown 渲染结果。

`requires/provides` 只放入 metadata，不转为 preconditions/effects。

### 4.4 Skill → 原生文档

`spec_from_skill` 从 metaskills_spec 原文深拷贝；没有原文时建立空 metadata/sections。覆盖实时 id/name/description，以及 metaskills_declared_version 或 Skill.version。tags/requires/provides/platforms/author/license/context 从实时 metadata 投影。

将普通技能的执行语义写入显式扩展：

| 扩展 | 内容 |
|---|---|
| grasp_contract | 完整 SkillContract；已有该键或契约非空时写入 |
| grasp_dependencies | 显式 ID/version 依赖；非空或原文已有时写入 |
| grasp_metadata | 非原生、非溯源的自定义 metadata |
| grasp_source | 显式来源；原生默认 metaskills:// 来源不回写 |
| grasp_content | 不能由原生章节渲染重建的正文，或原文已有该键 |

grasp_metadata 排除 metaskills_spec、metaskills_spec_hash、metaskills_declared_version、source_layer；避免递归嵌套和存储层级污染原生哈希。未知原文顶层扩展继续保留。

### 4.5 Markdown 渲染

输出 `# <name>\n\n`，description 非空则追加 `<description>\n\n`；逐 section 输出 `## <title>\n\n`。普通 block 输出 content 加两个换行。code block 对 content.rstrip()；若 lstrip 后以三反引号开头则原样加两个换行，否则包裹三反引号。渲染不执行代码，也不解析任意 YAML。

## 5. SQLite 数据库与 Registry

### 5.1 初始化

`SkillRegistry(path=':memory:', *, embedding_provider=HashEmbeddingProvider(), git_path=None)`。使用 sqlite3.connect，row_factory=sqlite3.Row。相对路径按进程 cwd 解析；不会自动创建数据库父目录。

依次设置 foreign_keys=ON、journal_mode=WAL、synchronous=NORMAL、cache_size=-64000、mmap_size=268435456、temp_store=MEMORY、busy_timeout=5000。内存库不保证实际进入 WAL。

执行配套数据文件 sqlite_ddl。核心表如下：

```sql
CREATE TABLE versions (
  skill_id TEXT NOT NULL, version TEXT NOT NULL, document TEXT NOT NULL,
  content_hash TEXT NOT NULL, created TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY(skill_id,version));
CREATE TABLE active (
  skill_id TEXT PRIMARY KEY, version TEXT NOT NULL,
  FOREIGN KEY(skill_id,version) REFERENCES versions(skill_id,version));
CREATE VIRTUAL TABLE skills_fts USING fts5(
  skill_id UNINDEXED, name, description, content);
CREATE TABLE feedback (
  id INTEGER PRIMARY KEY, skill_id TEXT NOT NULL, version TEXT NOT NULL,
  node_id TEXT NOT NULL, success INTEGER NOT NULL, details TEXT NOT NULL,
  created TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY(skill_id,version) REFERENCES versions(skill_id,version));
CREATE TABLE runs (
  sequence INTEGER PRIMARY KEY, graph_id TEXT NOT NULL,
  graph_version INTEGER NOT NULL, graph TEXT NOT NULL, state TEXT NOT NULL,
  created TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE INDEX runs_graph ON runs(graph_id,sequence);
CREATE TABLE episodes (id INTEGER PRIMARY KEY, document TEXT NOT NULL);
CREATE TABLE metaskills_tx_log (
  id TEXT PRIMARY KEY, phase TEXT NOT NULL, document TEXT NOT NULL);
CREATE TABLE metaskills_archive_state (
  skill_id TEXT PRIMARY KEY, archive_path TEXT NOT NULL, digest TEXT NOT NULL,
  layer TEXT NOT NULL DEFAULT 'project');
CREATE TABLE metaskills_pending (
  skill_id TEXT PRIMARY KEY, document TEXT NOT NULL, layer TEXT NOT NULL);
```

创建时使用 IF NOT EXISTS。archive_state 的旧表若缺 layer，用 ALTER TABLE 增加该列和 project 默认值。没有复用原 Rust 数据库的十二次迁移；不能直接打开上游数据库并声称兼容。

### 5.2 统一 Skill 哈希与写入

`_prepare(skill)`：Version(skill.version) 必须有效；取 model_dump(mode='json')，把 content_hash 置空；对 `json.dumps(...ensure_ascii=False, sort_keys=True, separators=(',', ':'))` 的 UTF-8 求 SHA256。传入非空 content_hash 且不匹配时拒绝。返回携带正确哈希的新 Skill。

`_register(skill, staged)` 在调用方 SQLite 事务内：

1. 同 (id,version) 已存在且完整模型不相等则报 immutable version。
2. 拒绝显式 self dependency；每个依赖先查 staged 对应 ID 的兼容版本，再查历史 resolve；都无结果则失败。
3. INSERT OR IGNORE versions；UPSERT active；删除该 ID 的旧 FTS 行，再插入 name/description/content。
4. 调用方执行 `_check_cycles()`：对 active 根沿显式 ID/version 依赖做 DFS，以 (id,version) 为访问键。能力依赖不在这一步校验。

无 Git 的 register 在一个 `with db` 中完成上述操作。启用 Git 后转换原生 spec，经过第 16 节的事务；显式 Python version 改内容仍禁止，不自动借原生映射绕过。

### 5.3 查询、依赖、删除

- list：active JOIN versions，按 skill_id 排序。
- get(id)：读取 active；get(id,version)：精确历史读取；找不到且参数含 `<>=!~*` 才尝试 resolve；找不到抛 KeyError。
- history：全部历史按 packaging.Version 排序。该顺序不是注册时间。
- dependencies：只遍历 Skill.dependencies，按 (id,version) 去重；recursive=True 递归。
- capability_dependencies：第 10 节的原生能力计划，使用同一 active 列表。
- dependents：其他 active 技能显式依赖该 ID，或 requires 与该 active 技能 provides 相交。
- delete：有 active dependents 则拒绝。无 Git 只删 active 和 FTS，历史定义/反馈保留；有 Git 则先走归档删除事务。

删除隐藏技能不会抹去历史；精确历史 get/resolve 仍可能返回它。不要把 delete 实现为 DELETE versions。

### 5.4 持久化 API

save_run 每次 INSERT 完整 graph/state JSON，不覆盖旧行。load_run 按 graph_id 取 sequence DESC 第一条；run_history 按 sequence 升序。不存在返回 None。运行事件通常附带一次完整快照写入。

record_feedback 校验该历史版本存在，再写 success 的 0/1 和 details JSON。feedback 按 id 返回，并还原 bool/details。record_episode 写 `{task,trajectory,success:0或1}`；episodes 按 id 返回。

## 6. 原生版本映射与版本选择

### 6.1 原生注册

`register_spec(spec, layer='project', contract=None)` 先规范化，必要时写 grasp_contract。无 Git 直接 finalize；有 Git 加锁并调用 write_skill_with_layer。最终返回 active Skill 的深拷贝。

`_skill_for_spec` 的精确规则：

1. declared=规范化 metadata.version；digest=原生 spec 哈希。
2. skill_from_spec；metadata 记录 declared 和 source_layer。
3. declared 为空：base='0.1.0'；合法 PEP440：base=str(Version(declared))；非法：base='0.1.0+ms.'+digest。
4. 构造/prepare base 版本。若同 ID/base 未存在，直接使用。
5. 已存在且其原生投影 hash=digest、source_layer 相同，复用旧 Skill。
6. 否则新版本为 `Version(base).public + '+ms.' + digest + '.layer.' + SHA256(layer)[:16]`，重新 prepare。

原生声明版本、spec 哈希和 Python 本地版本是三个字段。layer 变化也产生不可变本地版本，但不改变原生导出/hash。不要按 digest 的大小判断修订先后。

### 6.2 resolve(id, requirement='*')

requirement 为 ''/'*' 接受所有；包含 `<>=!~` 时原样用 SpecifierSet；否则补 `==`。非法要求转 ValueError。选历史兼容候选中 Version 最大项 winner。

若与 winner 的 `.public` 字符串相同的候选包含 `+ms.`：该组若含 active 版本，选 active；否则按 versions.rowid DESC 取第一个组内版本。普通版本仍按 Version 排序。不同 public 版本之间不为 active 无条件降级。

`.public` 的分组当前是字符串相等，不是完整语义规范化；复现时不要默认为按注册时间选择所有版本。

### 6.3 导入导出

export_json 默认输出 active Skill JSON 列表；include_history=True 输出所有版本，按 skill_id/version 文本排序。它不是完整数据库备份，不包含 active 指针备份、删除状态、运行和反馈。

无 Git import_json：要求列表，全部校验/prepare，staged 按 ID 保存最后一项；在一个 SQL 事务中逐项 _register，末尾 _check_cycles，失败整体回滚。

有 Git import_json：先 SAVEPOINT 内试写全部并验环，然后 rollback；逐轮选择显式依赖已可 resolve 的项，调用 register，逐技能归档；无进展报 unresolved version dependencies。返回结果保持原输入索引。它不是整个批次跨 Git/SQL 原子提交，后项 I/O 失败可留下前项成功结果。

## 7. MetaSkills 召回与推荐

### 7.1 Registry.search

签名 `search(query, mode='keyword', limit=20, filters=None) -> list[SearchResult]`。mode 仅允许 keyword/fulltext/semantic/hybrid；limit<0 报 ValueError；每次调用清空 last_search_signals。

1. 取全部 active Skill，按 ID 建候选字典。
2. 用 Unicode `re.findall(r'\w+', query)` 提取 lexical token。各 token 加双引号，用 OR 连接成 FTS 表达式；不开放用户原始 FTS 运算符。
3. 执行 `SELECT skill_id,bm25(skills_fts) AS rank ... MATCH ? ORDER BY rank,skill_id`。对外 score=-rank。
4. query 无 token 且为 keyword/fulltext：所有 ID 排序，score=0；semantic/hybrid 此时 lexical 为空。
5. semantic/hybrid 要求 provider 非 None。一次批量 embed：第一条 query；然后按 ID 排序的每个技能的 `name+'\n'+description+'\n'+content`。每次搜索重新计算，不使用持久向量缓存。
6. 检查返回数量等于文本数量、query vector 非空、所有维度相同且所有值有限；否则 ValueError。
7. 每个技能与 query 求第 7.2 节的 f32 cosine，按 (-score,id) 排序。
8. keyword/fulltext 直接用 lexical；semantic 用 cosine；hybrid 调用第 7.3 节融合。
9. 融合/排序后过滤，再截取 limit。last_search_signals 只保存最终返回项：bm25、embedding 或两者。

检索过滤不改变 Registry.list；GraphCompiler 当前仅拿召回结果排序，仍可使用未召回或默认被过滤的技能。过滤不是编译器的严格许可名单。

### 7.2 默认 hash embedding 与 VectorIndex

f32(x) 定义为 `unpack('<f', pack('<f', x))[0]`，每次乘加、除法、范数结果按下述位置舍入。

分词：text.lower() 后逐字符；属于配套 JSON 的 Rust alphanumeric 闭区间或字符 '+'/'#' 就累加 token，否则结束 token。保留重复和单字；不使用 GraSP ASCII 停用词分词器。Python lower 的 Unicode 版本可能与 Rust 的特定版本有差异，区间表对应原审计 rustc 字符分类。

FNV-1a 64：初值 0xCBF29CE484222325；逐 UTF-8 字节执行 `(h XOR b)*0x100000001B3 & 0xFFFFFFFFFFFFFFFF`。salted hash 对 `struct.pack('<QQ', seed, dimension_index)` 再做 FNV-1a。

设 d 默认 384。先按原 token 顺序处理权重 1 的 unigram，再按相邻顺序处理以单个空格拼接、权重 0.5 的 bigram。每个 token：

```text
seed = fnv1a(UTF8(token))
对 i=0..d-1：
  bits = salted_hash(seed,i) & 0xFFFF
  feature = f32(f32(bits / 32767.5) - 1)
  vector[i] = f32(vector[i] + f32(feature * weight))
```

点积逐项累积 `sum=f32(sum+f32(f32(x)*f32(y)))`。L2 范数 `norm=f32(sqrt(dot(v,v)))`；norm>0 时每项 `f32(v[i]/norm)`。空文本输出零向量；d=0 返回空列表，d<0 报错。

cosine：维度不同返回 0；na/nb 是 f32 范数；任一为 0 返回 0，否则 `f32(dot(a,b)/f32(na*nb))`。

VectorIndex 只是公开的内存工具，不是 Registry 的后台 ANN 服务。insert 维度不符返回 False，否则 f32 化后覆盖；remove 返回旧向量或 None；search 维度不符返回 []，否则用 dot 排序并截断 max(0,limit)。同分保持插入顺序。

### 7.3 RRF

RrfConfig 默认 k=60、bm25_weight=1、semantic_weight=1。分别按输入排名从 1 开始贡献：

```text
contribution = f32(f32(weight) / f32(f32(k)+f32(rank)))
score[id] = 首次 contribution；后续 f32(score[id]+contribution)
```

低层RrfConfig未额外限制k/weight；分母为0时，0/0产生NaN，非零分子产生带符号Infinity，其余除法转f32。默认正常参数不会触发该分支。

先 lexical 后 semantic 遍历。HybridResult 保留双方 rank/原 score。重复 ID 的每次出现都贡献分数，rank/原 score 字段以最后一次为准。结果按 score 降序；相同分数按首次插入顺序。它不直接相加 BM25 原分与 cosine，也不是取两者最大。

### 7.4 过滤

SearchFilters：tags=[]、layer=None、min_quality=None、include_deprecated=False。min_quality 限制到 [0,1] 后 f32 化。layer 规范化：system/base→base；global/org→org；local/user→user；project→project；未知过滤层级报错。

按顺序检查弃用、层级、质量、标签。标签是任意一个匹配即可。Registry 将技能标签小写，但直接构造 SearchFilters(tags=...) 不自动小写查询标签；parse_tags('A,B') 才小写并 strip。

Registry 映射层级用 metadata.source_layer，其次 metadata.layer，默认 project；质量用 quality_score，其次 quality，默认0；弃用用 is_deprecated，其次 deprecated，默认False。

dict filters 中的 source keys 为 tags/layer/min_quality/include_deprecated。剩余键取 Skill 属性或 metadata 同名项；expected 是 list/set/tuple 时检查 actual in expected，否则相等。当前没有通用的数组交集过滤实现。

### 7.5 推荐与可学习信号

八个信号：bm25、embedding、trigger、freshness、project_match、file_type_match、command_pattern、user_history。每个 BanditArm 默认 successes=failures=0、estimated_prob=.5、decay=.99、ucb=0；先验 Beta(1,1)。observe 时将两个计数乘 clamp(decay,0,1)，按二值 success/failure 加1，然后：

```text
estimated_prob = (prior.alpha+successes) /
                 (prior.alpha+prior.beta+successes+failures)
```

BanditConfig默认exploration_factor=.1、observation_decay=.99、min_observations=10、use_context=True、persist_frequency=10。后两个计数配置中的min_observations/persist_frequency目前不驱动额外门槛或自动保存。Beta.sample遇到非有限或<=0的alpha/beta分别回退到1。

select_weights 对每个信号采样 Beta(prior+counts)，应用上下文修正并归一化，total_selections+=1。estimated_weights 用 estimated_prob，不采样、不增加 selection。总权重<=0 时八信号均匀分配。Python random.Random 可注入；不要求 Rust 随机序列逐样本一致。

上下文键顺序为 tech_stack/time_of_day/project_size/activity_pattern，值非 None 才使用。每个 ContextModifier 保存 multiplier（默认1）、bonus（默认0）、observation_count。应用 `max(0,base*multiplier+bonus)`；成功 bonus+=.05、失败-=.05，限制[-.5,.5]。一次 update 使相关 modifier.observation_count+=1；arm 更新 last_selected 和 `ucb=clamp(estimated_prob+sqrt(log(max(total_selections,1))/max(observations,1))*.1,0,1)`。选择仍依据 Beta 采样，不读取 UCB。

feedback_bandit 每次按 SQLite feedback.id 重放，仅读 details.recommendation_signals 明确归因的有效信号，去重；可选 recommendation_context 只接受上述四个字符串字段。未归因反馈不更新所有信号。运行时默认只记录检索信号，不自动推断 tech stack/context。

Registry.recommend 的应用层策略：用当前技能 name/description/content 拼 query，分别召回全部 lexical 和 semantic 候选；按原排名设置 feature=1/rank，排除自身。加入显式 dependencies 和 dependents，project_match=1。使用重放 bandit 的 estimated_weights，分数为 sum(weight*feature)，按 (-score,id) 排序。该候选聚合策略是新增逻辑；普通 search 的 RRF 权重仍固定默认值，不受 bandit 自动调节。

### 7.6 数值奖励

compute_reward 以下涉及 f32 的每步运算均舍入：

| feedback.kind | reward |
|---|---|
| explicit_helpful | 1 |
| explicit_not_helpful / unloaded_quickly | 0 |
| loaded_only | .3 |
| ignored | .1 |
| used_duration | minutes>5 为 .8；否则 .4+min(minutes/5,1)*.4；minutes须适合u32 |
| rating | (stars-1)/4；stars须适合u8，不裁剪到1..5 |
| task_completed | 失败 .2；成功 .7+(1-min(duration_seconds/600,1))*.2；时长不可负 |

contextual_reward：context_match>.7 乘1.1，<.3乘.9，否则乘1；top suggestion 且 base>.5 再乘1.1；最终只限制上界1。aggregate 是加权平均；helpful/not_helpful 权重2，rating/task_completed=1.5，used_duration=1，loaded/unloaded=.8，ignored=.5；空列表=.5。二值 bandit 更新与连续 reward 分开，不隐式设置阈值转换。

## 8. GraSP 历史混合检索

此算法独立于第7节，是编译 metadata 的置信度来源；不能将两种 tokenizer 合并。

GraSP tokenize：小写，用 `[^a-z0-9_]+` 切分，去配套数据的停用词，结果为集合。token_sim 为 Jaccard；任一集合为空则0。

设技能数 n，默认 k=5、m=5、mixing=.5、eta=.7、epsilon=.001：

1. `d_i=Jaccard(task, id+' '+name+' '+description+' '+join(effects))+.001`，归一化为 p_dir。
2. 历史按 Jaccard(task,episode.task) 降序取前 k，再过滤 rho<=0。rhoBar 是保留项平均相似度，没有项时0。
3. `u_i=sum(rho_e*count(skill_id,episode.trajectory))+.001`，归一化为 p_mem。
4. `p=normalize(mixing*p_dir+(1-mixing)*p_mem)`；取 p 最高 m 个 ID。
5. margin=最大p-次大p（只有一项时次大视为0）。有相关历史时 agreement=1-JSD(p_dir,p_mem)，否则0。JSD 使用自然对数：M=(P+Q)/2，JSD=.5*KL(P||M)+.5*KL(Q||M)。
6. coverage=目标谓词名称中被所选技能 effects 名称覆盖的比例；空目标为1。名称用 `^([a-z_]+)\(` 匹配，不比较参数值。
7. `z=1.2*rhoBar+agreement+.8*margin+1.8*coverage-2`；learned=sigmoid(z)。historical 为相关 episode.success 的未加权平均，没有历史为.5。
8. confidence=.7*learned+.3*historical。

route：confidence<.40→react-fallback；>.65→full-dag；边界值和中间区间→full-dag-boosted-repair；None 也是后者。没有技能返回空分布、confidence=0、react-fallback。

当前编译器只将这些标签及 policy='deterministic-explicit-goal' 放入 metadata；不会真的执行 ReAct，也不会把 p 的前 m 项当成全部规划库。

## 9. GraphCompiler 精确流程

### 9.1 输入与发现

构造：`GraphCompiler(registry, proposer=None, *, strict_preconditions=True, discovery_mode='keyword')`。compile 为 async，参数 goal 必填，task=''，proposal=None，initial_conditions=None，order_hints=None，inputs=None。registry.list/search 可返回同步值或 awaitable。

1. 读取全部 active 技能，保留 Registry.list 的 ID 顺序。
2. task 非空才计算第8节，保存 retrieval/routing；search(task,limit=全部技能数,mode=配置)；深拷贝 last_search_signals 为 recommendation_signals_by_skill，保存 registry_discovery/discovery_mode。
3. 按召回名次稳定排序全部技能，未召回项排在后面；没有硬截断。
4. 满足第3节条件时调用 proposer。
5. 每次 append 创建 `<skill_id>:<调用计数>`，从1开始，深拷贝 Skill。

### 9.2 谓词解析与参数绑定

parse_pred 只识别整个字符串 `([a-z_]+)\(([^)]*)\)`，参数按逗号分隔、strip、丢弃空项。没有嵌套逻辑表达式解析、否定或删除效果。

bind_skill 要求 args 数量等于 contract.params；用所有形参名构建一个 `\b(?:p1|p2|...)\b` 正则，一次替换 preconditions/effects。必须单次替换，避免实参恰好是另一个形参时被再次捕获。不替换 Schema、input_values 或 content。

### 9.3 自动目标求解

无 proposal 时，对每个 goal 调用 achieve(predicate,active_path)：

1. predicate 已在 initial，或任一已选节点 effects 中，成功返回。
2. predicate 已在当前路径则失败；路径深度>128 或当前节点数>10000 抛 expansion limit。
3. 按候选技能顺序和该技能 effects 顺序尝试。effect 字符串完全相等可匹配；否则谓词名和参数个数相等才继续。
4. effect 参数是声明形参时绑定目标实参，重复形参必须一致；非形参的常量必须完全相等；所有 params 必须得到值，否则跳过。
5. 保存 nodes/counts，绑定该调用，递归满足所有前置条件。全部成功后 append 当前调用并返回；失败恢复保存的 nodes/counts，继续候选路径。
6. 无候选成功则False。任一 goal 失败抛 CompilationError('goal unreachable',details=缺失目标)。

精确字符串相等分支不会自行推断尚未绑定的形参；参数化技能通常需要目标提供具体实参，或显式 proposal。该算法只对事实规划回溯，不对之后 Schema/能力依赖检查失败做全局回溯。

### 9.4 显式 proposal

每项包含 skill、args（默认[]），可含 version。version 存在则从历史 get。未知技能/不存在版本、arity 不符只记入 metadata.rejected 并跳过；其他目标检查仍可最终失败。

目标归一化：收集已选调用中与目标同谓词名/arity的效果。如果目标不是其中已有的具体效果，且目标全部参数名属于任一注册技能 params，则使用第一个具体匹配效果替代目标。

backward_filter：kept={}，produced=initial，needed=goal-produced；循环按 nodes 顺序，对未保留且 effects 与 needed 相交的节点，加入kept，produced加入effects，needed加入preconditions-produced；直到稳定。needed 不移除已经满足项；返回原顺序中的kept节点。不做最短图或最优计划搜索。

### 9.5 补齐两类声明依赖

反向过滤后仍需保留能力/显式依赖，即使其不直接产出目标事实。

显式 Skill.dependencies：逐节点扩展，对每个 ID/version 从候选列表和 registry.resolve 找匹配版本，按 Version 选择；复用已存在相同 ID/version 的调用，否则要求该依赖无 params，自动规划其前置条件（仅无proposal模式），再追加。记录 provider→consumer 的 data 边，label='skill dependency'；这条边表示执行依赖，不等于已绑定某个值。

能力依赖：以全部 active 技能为视图，被选历史快照覆盖相同 ID；对各已选节点运行第10节计划。missing/cycles 使编译失败。闭包内所有 provider 必须纳入，新增 provider 同样不允许未给参数。记录 provider→consumer 的 order 边，label='capability:<name>'。闭包新增节点可能有显式依赖，重复两类扩展直到节点数不增长；总节点数>10000 失败。

原生能力图是每ID一个定义；同一执行图包含同ID不同版本时，临时视图采用后写快照，并不是完整多版本能力约束求解器。

### 9.6 边推导与循环

infer_edges 对每对不同调用：每个第一节点 effect 与第二节点 precondition 精确相等就建 state 边，label=该谓词。若共同谓词解析后只有一个参数，且等于第二节点某个 args 值，则再建 data hint，label='<arg> → <target_id>'。该提示本身不会填充 bindings。

order_hints 接受 from/to 或 source/target，默认 label='order'。infer_edges 的 add 会跳过自环和完全重复边；声明依赖单独追加，未统一去重。

检查所有边端点有效。硬边为所有非order边，以及 label以capability:开头的order边。硬边有环立即失败；其余order边依原顺序逐条试加，导致循环则丢弃，不能删除硬能力边。

### 9.7 完备性与类型绑定

- produced=initial与全部选中effects并集；缺goal报 goal completeness failed。
- 每个precondition若不在initial，且无其他节点声明产出，则计入 missing_preconditions；strict=True时报错，False保留给运行检查/修复。
- 节点 input_values=inputs[node.id] 的浅复制，默认{}。
- 对 input_schema.required 的每个键：已有字面值则用该属性 Schema 校验；否则沿图边找全部祖先，从其中输出 Schema 声明同名属性的节点找生产者。
- 生产者数量必须恰好1；然后 schema_compatible 必须成立；设置 bindings[key]=(生产者ID,key)，补一条 label=key 的data边。
- 不自动猜测不同名称之间的映射，也不在编译阶段全面校验非required输入；运行时校验完整输入对象。

加入 src（effects=initial）和 snk（preconditions=goal）。无入边技能由src连接order/start；无出边或其效果与goal相交的技能连接snk order/goal。无技能时src直连snk。创建 ExecutionGraph，最终validate_graph失败则CompilationError。

### 9.8 schema_compatible 的支持范围

target为空或source==target直接True。其余按以下顺序执行：

1. source type集合必须包含在target type集合中；target允许number时也允许source integer。target有type而source无type则False。
2. target.const要求source.const相等；target.enum要求source.enum或source.const的所有值属于目标enum。
3. target.required必须包含于source.required。
4. target.properties：source存在同名属性则递归；source缺属性且该键required，或source.additionalProperties不是False，则False。
5. target.items存在时两边items必须是dict且递归兼容。
6. target各minimum/exclusiveMinimum/minLength/minItems/minProperties，source必须有且数值>=；各maximum/exclusiveMaximum/maxLength/maxItems/maxProperties，source必须有且<=。
7. title/description/$schema/default/examples不参与；其他未处理的target关键字要求source同键值相等。

这是当前保守比较规则，不是完整JSON Schema逻辑蕴含证明。实际输入输出始终运行 Draft202012Validator。

## 10. 原生能力依赖算法

输入 Skill.metadata.requires/provides 必须是 list[str]，否则ValueError。CapabilityEdge.source是消费者，target是provider；编译执行边方向与它相反。

建立 nodes[id]=skill；providers[cap]追加skill.id。一个序列反复出现相同ID时，nodes覆盖但旧provider索引条目仍保留；Registry正常list不会重复ID。按消费者ID、requires、providerID排序生成每个能力到每个非自身provider的边。自身provides也能满足自身requires，但不生成自边。

resolve_dependencies 默认 root_disclosure=standard、mode=auto、max_depth=100：

1. mode=off直接返回仅root，不遍历输入。
2. 从root按层BFS；每层展开所有requires的全部provider。cap不在providers索引时记录 MissingCapability(required_by,capability)。超过max_depth静默截断。
3. 对闭包按ID排序起DFS；使用visited/active/path发现回边，把path中环段记录入cycles（不额外追加首节点）。
4. 有环时ordered仅按ID排序，plan.has_issues=True；无环时对消费者→provider的边做Kahn排序，再整体reverse，得到provider先于consumer。相同就绪节点的最终顺序可能反字母序。
5. root保留请求的disclosure；依赖在mode=full时full，其余非off模式overview。DisclosureLevel支持minimal/overview/standard/full/complete；DependencyLoadMode支持off/auto/full/overview。

未知root在底层函数可返回仅root的计划；Registry.capability_dependencies会先get，故Registry入口拒绝未知ID。计划返回ordered、missing、cycles。编译器发现issues直接失败，不会拿有环排序继续执行。

## 11. 原生继承与组合

compose_spec 从Registry当前list/get_spec构造只读瞬时字典，调用resolve_full；返回解析结果，不自动注册新定义，也不自动合并执行契约。

### 11.1 extends

单继承。沿extends检测重复ID；缺父节点ValueError。递归先解析父，再合并子；inheritance_chain是父到子。深度>5只产生DeepInheritance警告，不终止。

合并：复制父定义；id用子id，format_version用子值或1.0；name/description/version/tags/requires/provides/platforms/context仅当子值truthy时覆盖；author/license当子不是None时覆盖。清extends、四个replace标志；includes只保留子自己的列表。

section按id合并：新section直接追加；已有section按block_type分组，先继承父block再处理子block。rule/code/pitfall/checklist对应replace标志为True时，每处理一个子block都清空该类型组，最终只剩该类型最后一个子block；必须保留这个实际行为。最后顺序text/rule/code/command/pitfall/checklist，再附加未知类型。子title非空覆盖父title。

普通未知顶层扩展没有通用的子覆盖规则：当前_merge从父深拷贝，仅处理上述已列字段，不能据此宣称对子grasp_contract等扩展进行语义合并。

### 11.2 includes

完整环检测同时遍历extends和includes引用。每个include包含skill、into，position默认append，可有prefix/sections。目标映射：rules→rule、examples→code、pitfalls→pitfall、checklist→checklist、context→text。

递归resolve_full来源；缺来源记录IncludedSkillNotFound并继续。sections为非None时按来源section.id或title匹配；空列表匹配不到任何section。收集对应block_type，复制后给content加prefix。没有block不创建section；否则并入ID=into的section，按prepend/append插入，不按block.id去重。included_from记录直接include ID，可重复；子来源警告向上传递。

同一目标超过3个include记录ManyIncludes。结束将includes置空。该模块处理内容文档；能力依赖和可执行契约仍由统一Skill实时字段决定。

## 12. 运行状态机与调度

构造：`GraphRuntime(registry, executor, verifier=None, repair_engine=None, concurrency=4, retries=0, timeout=30)`。concurrency<1、retries<0、timeout<=0拒绝。retry次数表示首次之外的额外尝试。

### 12.1 执行入口与不变式

execute 对同runtime实例中的graph.id加运行标记，重入RuntimeError；finally移除。进入_execute时深拷贝graph/state，不原地改变调用方对象。检查validate_graph和graph_id/graph_version匹配；每个技能版本必须能在registry.get(id,version)中查到。但这里仅检查版本存在，不逐字段比较传入Skill快照与库文档；外部手工图不是自动获得可信签名。

没传state时创建GraphState，facts=initial。为每个图节点补默认NodeState。状态包含running表示进程中断，改outcome-unknown；存在任一unknown时立即记录reconciliation_required、持久化并返回，不继续调度。

处理第14节缓存失效，然后从initial以及所有succeeded/bypassed结果的observed_effects重建facts；state.status='running'，记录started。

### 12.2 节点状态转换

```text
pending → ready → running → verifying → succeeded
                    │           └────→ failed
                    ├─明确异常──→ 再次running 或 failed
                    └─未知结果──→ outcome-unknown

依赖失败：pending/ready → blocked
取消尚未执行项：pending/ready → cancelled
验证中取消：保持 verifying，保留原始结果
修复失效：相关节点 → pending（保留attempt计数）
已观测结果足够的Bypass：目标 → bypassed
```

succeeded/bypassed是_DONE，满足调度依赖。ready节点必须处于pending/ready/verifying，且所有入边来源都_DONE。kind与边类型不改变这个统一依赖条件。

每轮按graph.nodes顺序取前concurrency个ready节点，create_task后gather等待整批完成，再决定修复/失败传播/下一批。不是动态补位的工作窃取调度器；一批中的慢任务会阻止下一批提早加入。

### 12.3 单节点执行

1. inputs=deepcopy(input_values)；逐bindings读state.nodes[source].result.output[output_key]，深拷贝覆盖同名literal。缺结果/键失败，category=input_binding，记录failed并返回；此分支当前不写skill feedback。
2. verify_input（第13节）失败：status=failed，保存verdict/error、feedback及failed事件，不调用Executor。
3. 创建ExecutionContext，facts是此刻state.facts快照，key先用旧key或空。
4. 如果ns.status=verifying，跳过外部执行直接进入第13节；否则置ready并记录事件。
5. 循环retry=0..retries。置running；普通新尝试attempt+=1，key=`grasp:idem:<graph_id>:<node_id>:<attempt>`。恢复重试recovery_retry=True时保留原attempt/key，仅在key缺失时按该attempt生成，然后清recovery_retry。
6. context.key更新；计算cache_key；记录running（此时就持久化）。
7. src/snk不调用Executor，结果为NodeResult(observed_effects=当前facts)；普通节点用asyncio.wait_for执行executor.execute(deep copies)，timeout为配置值；结果经NodeResult.model_validate并深拷贝。
8. 保存ns.result，置verifying，记录result_persisted，在任何自定义验证之前持久化原始结果。
9. 执行结果验证，最终置succeeded/failed。成功时facts并入完整observed_effects并排序；不只并入声明effects。写feedback及完成事件。

并发节点的context.facts按开始时点取快照，不保证看到同批其他节点稍后产生的事实。state.facts是共享单事件循环内的事实并集，应用必须把必要因果关系建成边。

### 12.4 异常、超时、取消

明确Exception保存错误和VerificationResult；TimeoutError分类timeout，其他为execution。普通异常按retries重试，最终failed；不会自动退避。超时且Skill.metadata.idempotent不为True时直接outcome-unknown，禁止自动重试/自动修复。显式idempotent=True才允许配置的超时重试；库不验证外部能力是否真的幂等。

外部执行阶段CancelledError：普通skill置outcome-unknown，结构节点置cancelled，持久化后重抛到批次层。批次层调用cancel(graph.id)，取消全部同批任务并等待清理。循环发现cancel标记，把未开始pending/ready标cancelled，graph status=cancelled。

自定义验证阶段取消保持verifying，不重复外部副作用。验证器异常/超时转换failed，category=verification，不进入Executor重试循环。

### 12.5 批次后的修复与终止

逐批次节点顺序扫描failed。如果配置repair_engine，将其verdict.category映射到precondition/postcondition/execution/timeout；不属于这四种的一律按postcondition选择修复顺序。调用repair，采用返回graph/state并持久化。一次修复成功后立即跳出该扫描、进入下一调度循环。

否则，对failed/outcome-unknown节点的后代，将pending/ready改blocked。没有ready时退出。非cancelled最终状态：有unknown则outcome-unknown；否则全部NodeState均_DONE且goal包含于facts才succeeded，其他failed。不会只看到一个目标事实就忽略图中仍失败的节点。

记录finished和完整快照。随后record_episode(task, 按图顺序列出的_DONE技能ID, status是否succeeded)。每次完整execute调用都会记录episode；重复resume已完成图会追加episode，不做episode去重。execute返回GraphState；自动修复后的新Graph通过Registry.load_run取回。

## 13. 验证顺序与结果归因

verify_input：先比较node.preconditions-set(facts)，缺失category=precondition；之后对整个inputs应用Skill.contract.input_schema，首个错误category=input_schema。通过返回passed=True。

verify_result：先对result.output验证完整output_schema，首错category=output_schema；再比较node.effects-set(result.observed_effects)，缺失category=postcondition。空Schema允许任意对象。evidence目前只保存，不被内置逻辑解释。

内置结果通过后：contract.validators非空但无注入verifier，返回custom_validator失败；有verifier且kind=skill时，无论validators是否为空都会调用它。自定义verdict不能覆盖内置失败；返回不通过则最终failed。

SkillVerifier负责理解validators中名称并执行所需外部验证，库不按字符串动态加载函数。声明effects不是执行证据；Executor报告observed_effects仍是宿主的可信输入，库没有自动核实外部世界真实性的通用机制。

每个技能成功/失败的常规feedback.details为error、attempt、graph_id、graph_version、recommendation_signals。signal从编译图捕获的skill-ID映射读取；替换技能未在该图召回信号中时为空，不能凭空归因。

## 14. 缓存、幂等与恢复

### 14.1 cache_key

```text
SHA256(UTF8(json.dumps({
  'node': node.model_dump(mode='json'),
  'inputs': 完整本次输入
}, sort_keys=True)))
```

此处沿用json.dumps默认ensure_ascii和分隔符，与Skill哈希不同。只有_DONE且有cache_key才重新计算对比；绑定结果缺失或key不一致时标记stale。使graph.descendants(stale)全部置新NodeState，保留旧attempt，清结果、验证、key和错误。无key的已成功状态不会自动按内容重新鉴别。

缓存是同一图/恢复过程中的节点结果保留，不是跨所有任务的全局内容缓存。key不包含外部文件系统状态、时间、数据库变更或全局facts；这些因素需要显式输入/版本或应用失效策略。

### 14.2 resume

读取最新持久化graph/state；不存在KeyError。running→outcome-unknown。retry_unknown=False时unknown保持并在execute入口阻止继续；True时unknown→pending，recovery_retry=True，加入recovered_roots。cancelled→pending也加入roots。对这些roots的后代，仅blocked状态恢复pending；其他已验证结果保留。清runtime.cancel标记，再execute。

结果已保存但验证未完成时，状态verifying使执行器不重跑，只重新做输入/结果/自定义验证。retry_unknown=True重用原idempotency_key和attempt，宿主Executor必须使用该key做去重或结果查询。没有恰好一次外部副作用保证，也没有跨进程graph租约。

## 15. 局部修复完整规格

构造：`RepairEngine(registry, *, l_max=3, e_max=5, max_repairs=8, operator_order=None)`；三个预算不能负。每节点预算在SkillNode.repair_budget，默认2。operation.type只允许Bypass/Rebind/InsertPrereq/Substitute/Rewire。

### 15.1 操作选择

| 失败类型 | 默认顺序 |
|---|---|
| precondition及未知类型 | InsertPrereq, Rebind, Substitute, Rewire, Bypass |
| postcondition | Substitute, Rebind, Rewire, Bypass, InsertPrereq |
| execution | Substitute, Rebind, Rewire, Bypass |
| timeout | Substitute, Bypass |

operator_order=None才使用默认；[]代表禁用全部。repair不查全文/向量排名，直接每次读取最新registry.list，以该顺序尝试候选。不能把当前自动修复写成LLM补图或语义检索优化算法。

`facts=initial ∪ state.facts ∪ event.state`；event.state由调用者提供并被当作观测证据。runtime传当前facts，不凭声明生成。

`downstream_required(node)`：收集graph.goal和每个直接出边目标的preconditions，与node.effects取交集。它不是任意深度的完整行为等价判定。

参数derive：比较候选effect和具体缺失事实的谓词名/arity；形参绑定、重复一致、常量相等；必须绑定全部params。无括号事实只允许无params的精确匹配。

- Bypass：downstream_required包含于facts才尝试。
- Rebind：event.args非None才尝试；runtime生成的默认RepairEvent不含args，因此不会自己猜新参数。
- Substitute：需要非空downstream_required；遍历不同技能ID，无params用[]，有params对每个需要效果derive；绑定effects覆盖全部需要效果才尝试apply，失败记录原因后继续候选。
- InsertPrereq：对每个不在facts的target.precondition，在库中找第一个derive成功的生产者，创建最小未占用`<id>:<count>`节点。一次收集后尝试，不做无限递归先修前置技能。
- Rewire：precondition失败且仍有缺失事实时不尝试；否则移除目标的一个入order边。

### 15.2 apply 原子可见步骤

先检查state.graph_id/version匹配，节点尝试次数<该节点预算且sum(repair_attempts)<max_repairs，否则RepairError('local-exhausted')。深拷贝graph/state；touched最初包含目标ID。没有成功apply前不改变输入对象。

| 操作 | 副本上的具体修改 |
|---|---|
| Bypass | 再查downstream_required已观测；所有消费者绑定的数据键必须在目标旧result.output存在；清目标preconditions、effects改为下游所需集合 |
| Rebind | target有skill且args非None；绑定同技能新参数，更新args/preconditions/effects，保留原输入绑定和值 |
| Substitute | replacement存在且不同skill.id；绑定args或[]，要求覆盖下游效果；换skill快照/args/preconditions/effects；保留原输入绑定和值。没有bindings时先校验完整替代输入Schema |
| InsertPrereq | prerequisites非空；每个ID不得已存在，深拷贝加入nodes/touched；为匹配目标preconditions的effect建state边，有src则加src→新节点order/repair |
| Rewire | 使用operation.edge或首个目标入order边；必须存在、类型order且target一致；仅删该边，不任意改State/Data |

Rebind/Substitute/InsertPrereq后，删除所有与touched相连的旧state边；按所有skill节点对重新建立涉及touched的精确effect/precondition state边。保留其他边、真实bindings、order，不根据谓词文本伪造值绑定。结构节点不参与这轮state重建。

计算新增节点ID集合和新增完整边JSON集合，分别限制<=l_max/e_max；限制的是新集合差，不是净数量变化。再运行15.3验证。

### 15.3 补丁验证

1. validate_graph，无效引用/绑定/循环拒绝。
2. `_missing(graph)`按拓扑祖先实际可声明提供的effects计算每个节点缺失precondition。新missing减旧missing不能引入新项；touched节点的缺失也要检查。已在facts中的项可以忽略，兼容旧strict=False不完整图的增量修复。
3. 对新图每个skill检查能力requires在图内provides中存在；图内每个相关非自身provider必须是消费者祖先。不会自动在补丁里加载新capability provider，不满足则拒绝。
4. 每个显式ID/version依赖必须有兼容图内Skill且为当前节点严格祖先。
5. required输入键必须在bindings或input_values中；逐literal属性验证；绑定源不能是结构节点，源output_schema必须声明output_key，且与目标属性schema_compatible。

### 15.4 新版本与局部失效

```text
affected = old_graph.descendants(touched∩old_ids)
           ∪ patched_graph.descendants(touched)
patched.version += 1
state.graph_version = patched.version
state.status = pending
state.repair_attempts[target] += 1
```

affected各节点换成新NodeState，保留原attempt，其余结果保留。Bypass目标改bypassed，保留旧output（没有则{}），observed_effects取downstream_required。facts从initial和仍_DONE结果重建。

审计包含operator/node_id/from_version/to_version/affected/added_nodes/added_edges/完整operation，加入repair_audit及trace.event='repair'。返回RepairResult(repaired=True,new_graph,new_state,operation)。调用者必须采用返回对象，不能继续旧图。

repair耗尽预算返回repaired=False、reason='local-exhausted'并记录repair-exhausted，不再次加attempt。所有操作失败时目标attempt计数加1，记录local-failed、rejected原因和repair-failed事件，不造新图版本。runtime不会对同一个failed节点原地无限循环修复；只有后续调度/明确再次调用才可能再次尝试。

## 16. GitArchive 与跨存储事务

### 16.1 归档目录及安全检查

GitArchive初始化resolve(root)，创建Git仓库（不存在.git时git init）及skills/by-id、skills/by-source、builds、bundles/published目录。普通运行不使用这些空目录承诺额外bundle能力。

技能目录为skills/by-id/<id>。ID不可空、不可为'.'、不可包含'..'，每个字符必须Python isalnum或-_.。所有读写路径resolve后须在root下；删除前检查后代路径，拒绝越界软链接。进程调用固定参数列表且shell=False。

write_skill写七个文件：metadata.yaml（JSON indent=2，合法YAML）、skill.spec.json（规范化JSON indent=2）、SKILL.md、spec.lens.json='{}'、evidence.json='{}'、slices.json='[]'、保留或创建usage-log.jsonl；创建evidence/tests空目录。后三个辅助文件是原生归档布局的内容初始化，不代表实现完整证据/切片业务。

只git add这些所属路径；commit使用`--only --allow-empty -m 'Update skill <id>' -- <paths>`和本地身份ms/ms@localhost，不能把其他已暂存文件带入该提交。每次写可产生新commit，即便定义幂等。

read_skill无revision读工作树；有revision先rev-parse --verify '<revision>^{commit}'取得OID，再git show OID:path。history用git log --format=%H -- <skill_dir>，失败返回[]。

delete_skill将技能目录移动到root/tombstones/<id>_<uuidhex>，add -A只包含旧/新目录，提交Tombstone skill。SQLite仍保留版本历史。

### 16.2 事务记录与阶段

事务工作目录默认<git_root>/.ms：tx/*.json、ms.lock、tombstones/tx/*。采用POSIX fcntl.flock独占锁；公共Registry.register_spec在锁内调用write_skill_with_layer。底层write_skill_with_layer自身不加锁；write_skill_locked、batch、delete和recover加锁。

写事务记录字段：id UUID4、entity_type='skill'、entity_id、phase='prepare'、payload_json（规范化紧凑JSON字符串）、created_at UTC、layer、digest、undo（旧pending投影或None）；Git提交后增加git_commit。元数据日志同时写SQLite metaskills_tx_log和文件；文件flush+fsync，不宣称目录fsync。

严格顺序：

1. db.prepare_tx并提交 → 写prepare文件日志。
2. db.upsert_pending：SAVEPOINT试写最终Skill/_check_cycles后回滚验证结果，再单独保存pending spec/layer；不更改confirmed active。
3. phase=pending，先更新SQL日志，再fsync文件。
4. git.write_skill得到OID。
5. phase=committed，先SQL后文件。
6. db.finalize：校验digest；layer优先pending，其次archive_state，默认project；准备不可变版本；同一SQL事务写versions/active/FTS/archive_state，删pending。
7. phase=complete，然后清理：删除SQL事务行，文件移入事务tombstones。

无Git register_spec直接finalize，显式传layer。layer是查询投影，不写进原生spec哈希。重放finalize时pending可能已删，必须从archive_state恢复layer，不能退回project。

### 16.3 恢复判据

构造Registry有Git时自动recover，也可显式调用。返回rolled_back/completed/orphaned_files计数。在独占锁中按SQL日志rowid处理，包含complete行：

- complete：清理。
- 普通write且phase为pending/committed：只有matching_commit成功才finalize并计completed，否则rollback_pending并清理、计rolled_back。
- prepare即使Git当前有旧同ID也回滚pending，不凭ID存在认定提交完成。
- matching_commit要求HEAD中的该spec规范化hash等于事务digest；候选是记录OID或该技能history；候选必须是HEAD祖先且该候选spec hash也等于digest。
- rollback只恢复旧pending投影；confirmed从未被pending替换，所以保留旧confirmed。它不自动回滚Git工作树内容。
- 扫完SQL后剩余tx/*.json均隔离到事务tombstones，计orphaned_files，不无条件从孤立文件重放数据。

delete事务先记录before_commit和prepare，再Git tombstone commit，记录committed，删除SQL active/FTS/archive_state/pending，记录complete并清理。恢复要求HEAD不同于before，before是HEAD祖先，记录删除OID（无记录则HEAD）也是HEAD祖先，且删除OID和HEAD均没有该spec；成立才删SQL。否则计rolled_back并清理，但不会把已移动的Git工作树目录自动移回。数据库删除异常必须抛出，不能吞掉后假装事务完成。

### 16.4 额外整库快照

Registry.commit_git是单独的集成API：导出所有历史Skill到git_root/skills.json；仅该路径暂存有变化才提交，git_history仅查看skills.json提交。它不同于逐技能原生archive，不能用该JSON文件冒充完整SQLite/Git备份。

## 17. GraSP 来源适配器

manifest_skills读取manifest['skills']，每项id必填；name默认id，description空，version='1.0.0'，source='grasp-manifest'；把params/precondition/effect映射成contract.params/preconditions/effects。完整原定义放metadata.upstream。不自动把manifest任意字段解释为执行器。

frontmatter只识别以`---`开头、独立换行包裹的首段。逐行解析`key: value`，忽略空行/注释/不能识别的行；两个及以上空白缩进视作当前子对象字段；空value建立根子对象；支持inline数组、true/false、简单十进制数和去外层引号的字符串。不是通用YAML解析器。

inline数组解析逐字符跟踪引号及圆/方括号深度，只在深度0且不在引号内时按逗号切分，因此`at(agent,sink)`不会被拆成两项。不提供复杂转义语法。

frontmatter_skills接受name/content文件列表，仅grasp或GraSP块含precondition/effect时注册；否则返回skipped(name,reason='no grasp: block')。ID由文件名小写后非[a-z0-9_]转下划线并去两端下划线。保留全文和metadata.upstream。不存在隐式LLM契约推断。

## 18. 错误与行为边界清单

| 层 | 失败方式 | 调用者应做的事 |
|---|---|---|
| 模型 | Pydantic ValidationError / 无效JSON Schema错误 | 修正结构，不把它当可修复执行故障 |
| Registry | 无定义KeyError；非法版本/哈希/不可变冲突/依赖ValueError | 显式修订或注册所需依赖 |
| Search | 无provider、维度/数量/有限性不符、非法mode/filter为ValueError | 修正provider或配置，不能伪造语义分数 |
| Compiler | CompilationError携带details | 检查缺goal/precondition/capability/cycle/类型/输入歧义 |
| Runtime入口 | graph无效、state版本不符ValueError；重入RuntimeError | 使用同一graph/state对并避免并发执行同图 |
| Executor/Verifier | 常规异常转NodeState/verdict；unknown单独处理 | 检查持久化状态，按幂等策略恢复 |
| 显式repair.apply | RepairError，输入对象不变 | 改候选/参数或停止 |
| 自动repair.repair | RepairResult.repaired=False和原因/审计 | 停止或由上层显式安排新尝试 |
| Git/SQL | subprocess/SQLite/I/O错误可抛出 | 保留日志并recover，不吞掉后报告成功 |

当前代码的事实模型是单调正事实并集，没有负事实、删除效果、互斥资源锁、分布式事务、跨进程执行租约。node result.output必须是dict；不支持任意流式结果。技能和运行数据应能JSON序列化，Pydantic内的Any不代表任意Python对象都可持久化。

Registry使用同步SQLite默认线程归属和同步provider；async仅用于编译接口/Executor/Verifier/批次执行。不要宣称整个存储与召回是非阻塞异步I/O。

## 19. 可运行的最小集成样例

下面样例应在复现完成后直接执行。它同时覆盖：注册显式Schema契约、task召回、goal反向规划、状态和数据两种边、实际输入绑定、执行效果验证。期待emit输出3、scale输出6、图状态succeeded。

<!-- executable-example: start -->
```python
import asyncio
from grasp_metaskills import (
    GraphCompiler, GraphRuntime, NodeResult, Skill, SkillContract, SkillRegistry,
)

NUMBER = {
    "type": "object",
    "properties": {"value": {"type": "integer"}},
    "required": ["value"],
    "additionalProperties": False,
}

class Executor:
    async def execute(self, node, inputs, context):
        if node.skill.id == "emit":
            return NodeResult(output={"value": 3}, observed_effects=["seed(x)"])
        if node.skill.id == "scale":
            value = inputs["value"] * 2
            return NodeResult(
                output={"value": value},
                observed_effects=["ready(x)"] if value == 6 else [],
            )
        raise ValueError("unknown executor capability: " + node.skill.id)

async def main():
    with SkillRegistry() as registry:
        registry.register(Skill(
            id="emit", name="emit integer", description="provide integer seed",
            contract=SkillContract(effects=["seed(x)"], output_schema=NUMBER),
        ))
        registry.register(Skill(
            id="scale", name="scale integer", description="multiply seed by two",
            contract=SkillContract(
                preconditions=["seed(x)"], effects=["ready(x)"],
                input_schema=NUMBER, output_schema=NUMBER,
            ),
        ))
        graph = await GraphCompiler(registry, discovery_mode="hybrid").compile(
            task="scale integer seed", goal=["ready(x)"],
        )
        assert graph.validate_graph() == []
        assert graph.node("scale:1").bindings["value"].node_id == "emit:1"
        state = await GraphRuntime(registry, Executor()).execute(graph)
        assert state.status == "succeeded"
        assert state.nodes["scale:1"].result.output == {"value": 6}
        saved_graph, saved_state = registry.load_run(graph.id)
        assert saved_state["status"] == "succeeded"
        assert saved_graph["version"] == graph.version
        print(state.status, state.nodes["scale:1"].result.output)

if __name__ == "__main__":
    asyncio.run(main())
```
<!-- executable-example: end -->

原生接入使用同一个Registry：

```python
skill = registry.register_spec({
    "metadata": {
        "id": "prepare", "name": "Prepare", "version": "release-A",
        "description": "Prepare an artifact", "provides": ["artifact-preparation"],
    },
    "sections": [],
}, layer="global", contract=SkillContract(effects=["prepared(x)"]))
```

此时版本映射为合法本地版本，原生get_spec仍输出release-A；source_layer=global影响检索，provides不会自动产生prepared(x)。没有Executor能力时，注册/编译可以成功但无法凭空执行外部动作。

## 20. 复现验收用例与精确断言

不要只测试函数返回非空。以下必须作为确定性行为/不变量检查；UUID、时间戳只检查格式和跨对象一致性。

### 20.1 注册和存储

1. 相同Python(id,version)不同正文注册失败；清旧hash并提升version后成功；get旧版本不变。
2. 错误content_hash拒绝，不能静默重新覆盖用户提供的非空hash。
3. 显式依赖不存在、自依赖、依赖环失败；SQLite bulk import失败不留下半批记录。
4. 原生相同声明版本更新正文生成新本地版本；get_spec保持原声明；连续First/Second/Third修订的resolve取当前Third，不按哈希字典序回退。
5. layer=global的技能匹配layer=org/global，不匹配project；相同spec+layer复用版本；仅layer变化生成历史版本，原生spec/hash不变。
6. 原生roundtrip保留sections和未知扩展；普通Skill roundtrip保留content/source/dependencies/contract/custom metadata，不嵌套增长metaskills_spec。
7. 删除有dependent的provider失败；删除普通技能后list/search不可见，但历史仍可get。
8. Git开启后的JSON导入为每个技能创建可读归档，先导入其依赖；导入结果后delete能正常tombstone。

### 20.2 检索和数值Golden

hash_embedding维度8的源程序期望，先将下面十进制数转换f32后逐位比较：

| 文本 | 向量 |
|---|---|
| git commit workflow | [0.20871884,-0.4684707,0.20871885,-0.039634146,0.09459979,0.7039198,-0.33423674,0.27508327] |
| C++ C# R | [0.038870182,-0.8507257,0.03887019,0.14347723,0.038870182,0.14347719,-0.45823127,0.1434772] |
| 你好 Rust | [-0.49753815,0.18553059,0.59565216,-0.31869534,0.11155966,-0.0040796907,0.40604186,0.2904025] |
| 三个空格 | [0,0,0,0,0,0,0,0] |

RRF：双排名都第一项的贡献为f32(f32(1/61)+f32(1/61))；只在一侧第一为f32(1/61)。重复项也贡献，测试保留原score/rank字段。过滤必须在融合之后、limit之前。

reward：used_duration(3)=f32(.64)；contextual(上述,.9,top=True)=f32(.7744)；aggregate(helpful,used3)=f32(.87999994)；成功任务0/60/600秒分别f32(.9/.88/.7)。

BanditArm decay=.5先成功再失败，successes=.5、failures=1、estimated_prob=1.5/3.5。未归因feedback不改变BM25 arm；重开数据库重放后的权重相同。Beta(8,2)统计样本均值接近.8，不要求与Rust随机流相同。

### 20.3 GraSP Golden 图

使用配套JSON的golden_grasp_apple作为完整输入：它含8个完整Skill、7个proposal调用、task、goal、initial_conditions、相关episode及完整期望图。测试库list保持该fixture顺序，不提供search/episodes；strict_preconditions=False。图ID在比较前固定为golden-apple，其余结构可逐字段对比。

关键数据：find(object)产生knows_loc(object)；open()产生open(fridge)；pick(object)要求knows_loc(object)/open(fridge)，产生holding(object)；goto(loc)产生at(agent,loc)；clean(object)要求holding(object)/at(agent,sink)，产生clean(object)；put(object,loc)要求holding(object)/at(agent,loc)，产生on(object,loc)。另外注册heat/slice以验证反向过滤。task='clean an apple and put it on the countertop'，goal为clean(apple)/on(apple,countertop)，initial仅at(agent,fridge)。

应保留find/open/pick/clean/put，按拓扑顺序得到这五个ID；state边集合find→pick、open→pick、pick→clean、pick→put；data边集合find→pick、pick→clean、pick→put。missing_preconditions恰好是clean缺at(agent,sink)、put缺at(agent,countertop)。这是一张允许缺事实以验证局部修复的兼容图，默认strict=True应拒绝，不能直接当作执行成功样例。

对配套完整技能列表调用retrieve，空历史confidence四位小数为.4831；使用配套相关episode后为.9009且mode=full-dag。unrelated cooking recipe应为react-fallback。不要用省略过名称/描述/效果的技能列表重算并要求同值。

未知proposal技能和arity错误记录rejected。绑定实参恰好等于另一形参名时不发生串联捕获。hard环拒绝；造成环的soft order跳过，mandatory capability环拒绝。

### 20.4 编译、能力、类型

- 自动从ready(x)找到scale和emit，不需要手工节点列表；图无环、边端点有效。
- 多条候选路径时第一条缺前置事实可回溯尝试后一条；不宣称在Schema失败后也回溯。
- 一个requires能力由两个skill提供时，两个provider都进入图并早于consumer；只自身提供时不生成self边。
- 原生requires不出现在facts；missing/cycle报CompilationError。
- required输入缺生产者、多生产者或integer→string冲突失败；唯一同名兼容祖先产生InputBinding。
- proposal中的历史Skill版本和显式dependency的兼容版本固定到节点，不被active更新替换。

### 20.5 运行与恢复

- 使用async barrier证明同一批独立节点同时进入Executor；测慢节点造成批次等待，避免误实现成串行或动态补位。
- 前置条件缺失时Executor调用次数为0；Schema/observed effect失败有明确category。
- 普通异常重试次数=retries+1；每次新attempt改变key；非幂等timeout只执行一次并unknown。
- retry_unknown恢复保留key/attempt；未受影响成功节点不再调用；blocked后代回pending。
- 外部动作阶段取消为unknown；验证阶段取消保留raw result且恢复只调用verifier。
- 修改literal或绑定数据后cache_key改变并失效后代。
- 图结束时持久快照与返回GraphState相符；重开SQLite可恢复已确认结果。
- 注册库运行中更新技能版本，已编译节点的version和执行内容保持原快照。

### 20.6 修复与Git崩溃窗口

- Substitute成功后graph.version+1，失败节点和后代pending，独立分支结果保持逐字段相等。
- 缺required input/Schema不兼容/缺能力provider/版本依赖不匹配的替换拒绝，原图JSON不变。
- 缺at(agent,sink)时InsertPrereq用goto(loc)提供at(agent,loc)，派生loc=sink；原始测试图中新增goto和两条边；l_max=0禁止插入。
- Bypass必须已有下游事实和必要输出，不能制造数据；Rewire只移除合法order边；空operator_order禁用；budget耗尽有审计。
- Git失败发生在pending后时confirmed仍旧；recover回滚pending，不因HEAD存在旧同ID误完成。
- Git已commit但phase更新失败时recover通过内容hash/OID祖先证据finalize；finalize后complete记录失败时layer仍保留。
- 删除目录移动但未commit，不能认定已删除；已commit删除可完成SQL删除。
- Git写/删技能不带入无关暂存文件；越界软链接/非法ID拒绝。

### 20.7 生成式不变量

用Hypothesis生成链、DAG、独立分支和缺失事实，至少检查：成功编译无环、引用有效、缺前置条件不能执行、无效修复不改变原图、独立结果可复用、版本固定、恢复不更改已确认结果。不要把生成试验次数计为独立pytest数量。

当前项目基准为181个pytest用例：unit90、integration59、golden28、property目录4；integration另含2个Hypothesis函数。该数量是本设计所描述快照的基线，不是允许删测试后维持数字的目标。

## 21. 工程实现与验收顺序

1. 创建pyproject.toml，hatchling构建，src布局，py.typed；先实现第2、3节模型/协议。
2. 实现spec映射、Registry核心表/版本/哈希/CRUD，验证双向roundtrip。
3. 按配套字符表与公式实现hash/RRF/filter，接入Registry.search；实现GraSP独立retrieval。
4. 实现能力依赖与内容组合；不要创建另一份可变registry。
5. 实现编译器：绑定→目标回溯/proposal过滤→依赖闭包→边→循环→目标/前置条件→Schema绑定→src/snk。
6. 实现验证、运行状态、快照；先保证单节点与恢复，再保证并发批次。
7. 实现五操作与补丁验证、局部失效、budget和审计，再接入runtime。
8. 实现GitArchive和TxManager，以StorageBackend接回同一Registry；做每个故障窗口测试。
9. 实现bandit/reward、feedback重放和recommend；检索信号在编译时冻结，执行时归因。
10. 实现manifest/frontmatter；导出公共API；运行样例、完整测试、lint、类型和安装验证。

必要命令：

```bash
python3.12 -m venv "$HOME/.venvs/grasp-metaskills"
source "$HOME/.venvs/grasp-metaskills/bin/activate"
python -m pip install -e '.[dev]'
pytest -q
ruff check src tests examples
mypy src/grasp_metaskills
python examples/offline.py
```

pyproject pytest配置asyncio_mode='auto'、addopts='--import-mode=importlib'、testpaths=['tests']；Ruff line-length=100且选择E/F/I；mypy python_version=3.12、strict=True、packages=['grasp_metaskills']。dev依赖pytest、pytest-asyncio、hypothesis、ruff、mypy、types-jsonschema。wheel只装src/grasp_metaskills；sdist含src/tests/examples/docs/许可证/README/pyproject。许可证文件通过license-files打包。

本机iCloud同步目录可能给虚拟环境.pth文件添加hidden标志，导致editable路径被跳过；验证环境放同步目录之外。不是项目逻辑的一部分。

复现验收优先比较业务结果、图结构、状态/审计不变式和上述数值；UUID/时间戳、随机Beta序列、Tantivy对FTS5的分数不要求字节相等。当前功能不含ANN数据库、神经embedding默认模型、云端LLM连接、业务题库、评测器或插件市场。

## 22. 源码归属与明确未实现能力

| 来源 | 固定版本 | 本实现使用的机制 |
|---|---|---|
| luyu020816-droid/skill-dag | e8eaf48522950a9148cb30b9672e1aeca0ba82e6 | retrieval/bindSkill/backwardFilter/inferEdges/循环与src-snk/strict verify/五个repair操作/scheduler基本语义/metadata adapters |
| Dicklesworthstone/meta_skill | dcd3fb55cabb438dc200f9b7c784ca14c08135ce，历史标准MIT | core/skill、dependencies、resolution；search/embeddings/hybrid/context/filters；suggestions/bandit；storage/git/sqlite/tx机制 |
| 新增集成 | grasp-metaskills 0.1.0 | 统一Pydantic契约、JSON Schema、自动目标解析、不可变版本、SQLite统一schema、并发、unknown恢复、缓存指纹、事务化补丁、反馈推荐聚合 |

两份上游MIT版权/许可必须保留。MetaSkills后续707002f4及之后增加了许可限制，本项目只使用前述历史MIT快照，不以此文档声称获准使用后续受限代码。辅助Ericbai06/SkillDAG、wondelai/skills没有被拿来替代主项目算法。

未实现：完整原生CLI/TUI、宿主DSH/MCP/agent集成、软LLM YES/NO放宽验证、自然语言自动契约推断、远程sync冲突、完整tombstone restore/purge产品流程、挖掘/质量/模拟、meta-skill TOML切片bundler/tech-stack索引、ONNX推理和持久向量缓存。底层Git tombstone存在不代表上述整套产品流程已实现。原生ONNX接口在审计版本本身未完成，不编造神经模型结果。

与上游不同：SQLite FTS5代替Tantivy；原生mutable定义映射immutable版本；严格验证不自动把声明effects当执行事实；恢复用精确hash/commit证据而非旧ID存在；状态/图局部修复和并发有安全扩展。GraSP源代码声明但未真正实现的h半径/pMax全局重规划，本项目也不虚构为已移植算法。

本规格不授权扩大技能系统执行权限。完成复现的标准是第20节行为可验证、模型/SQL/公式与配套数据一致，并保留这些明确边界。
