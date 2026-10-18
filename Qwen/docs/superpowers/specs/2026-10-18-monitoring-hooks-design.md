# 监控插件与生命周期 Hooks 设计

日期：2026-10-18
状态：已按本设计实现；服务端 trace 入库验收待实际环境验证。
范围：将现有流程监控迁移为插件，通过通用 hooks 调用，保持聊天行为和已有工具插件兼容。

## 1. 目标与边界

核心负责执行流程并声明生命周期；监控属于外围插件。核心不能导入 Langfuse SDK、插件实现或 span 类型。
第一版保留现有 orchestrate_chat、process_request、build_agent、chat 四层监控。
不增加模型调用或单次工具执行事件，不增加异步事件队列、插件市场、自动发现或远程插件。
监控是观察者，不作为模型可调用工具，不参与 action schema，不计入工具调用次数。

## 2. 目录与依赖

agent/
  entities/
    hooks.py                  # StageEvent、StageResult、HookSpec 协议
    plugins/spec.py           # 保持现有工具协议，新增 HookPluginSpec
  core/
    hook_runtime.py           # 阶段作用域、钩子分发、异常隔离
    workflow/                 # 通过通用阶段作用域触发 hooks
  plugins/
    loader.py                 # 工具插件装配，保留原有语义
    hooks_loader.py           # 监控插件校验、加载和请求级实例化
    langfuse/
      plugin.py               # PLUGIN 声明及 create_hooks 工厂
      observer.py             # SDK 客户端与 span 生命周期
    plugins.json              # 同一配置文件，分别声明工具和 hook 插件
  web/
    controller.py

移除 agent/infrastructure/observability.py，确认无其他内容后删除空 infrastructure 包。
协议实体不得依赖 SDK；core/hook_runtime.py 不依赖 plugins 包。
编排入口接收 hooks 参数；默认装配逻辑放在 plugins/hooks_loader.py。
Web 与 CLI 入口装配请求级 hooks，再传给编排；直接调用编排默认使用空 hooks。

## 3. 插件声明与配置兼容

保留 PluginSpec(id, api_version, create_tools) 的名称、参数顺序和版本 1，兼容现有插件。
新增 HookPluginSpec(id, api_version, create_hooks)，独立表达观察能力，不强迫监控返回工具。

plugins.json 保持 schema_version=1，新增可选顶层 hook_plugins 数组。
plugins 数组继续只表达工具插件；hook_plugins 每项沿用 id/module/enabled/config。
旧配置未提供 hook_plugins 时按空数组处理。两类 ID 在整个配置中要求唯一。
启用和禁用配置均进行结构校验；禁用插件绝不导入模块。

示例：
{
  "schema_version": 1,
  "plugins": [],
  "hook_plugins": [
    {
      "id": "langfuse",
      "module": "agent.plugins.langfuse.plugin",
      "enabled": true,
      "config": {}
    }
  ]
}

两类加载器共用配置解析与路径选择，继续支持 QWEN_PLUGINS_CONFIG 和显式路径。
工具插件工厂仍按每轮历史快照装配，保持原有时机；监控工厂在编排开始前装配。
配置格式错误保留现有明确报错行为，不静默吞掉；结构校验后的监控导入、
声明、初始化和回调失败则告警并跳过该插件。工具插件失败策略保持不变。

## 4. Hooks 协议

StageEvent 为冻结的数据类：
- request_id：入口为每次请求生成的唯一 ID。
- stage_id：每个阶段唯一 ID。
- parent_stage_id：根阶段为 None，子阶段指向父阶段。
- name：阶段名。
- input：只供观察的数据快照。

StageResult 为冻结的数据类：
- status：success、error 或 cancelled。
- output：成功输出的数据快照；失败时为空。
- error_type / error_message：失败摘要，不包含业务异常对象和 traceback。
- duration_ns：使用 monotonic 时钟计算的阶段耗时。

HookSpec 提供两个同步回调：
- on_stage_start(event) -> token
- on_stage_end(event, token, result) -> None

开始与成功/失败结束构成完整生命周期，不另设重复的 success/error 回调。
token 是插件自己的阶段状态，可持有 SDK scope/span，只由分发器原样交还。
插件回调返回值不能改变业务输入、输出或控制流程。

输入输出在分发前转换成 JSON 兼容快照，不向插件传递业务可变对象。
快照转换失败时使用安全占位，不能阻断业务；每个插件接收独立副本。
此隔离用于避免意外修改，不构成对可信 Python 插件的安全沙箱。

## 5. 调用与生命周期

入口为每次请求创建独立 HookRuntime。实例在调用栈中显式传递，不使用全局可变 span 栈。
HookRuntime.stage(name, input) 提供上下文管理器；yield 的 StageHandle 只提供 set_output，
不暴露 Langfuse span。嵌套阶段保留相同 request_id 和显式 parent_stage_id。

示意（接口设计，不是实现）：
with runtime.stage("orchestrate_chat", user_text) as root:
    with runtime.stage("process_request", user_text) as stage:
        request = process_request(user_text)
        stage.set_output(request)
    # build_agent、chat 同理
    root.set_output(result)
    return result

开始回调按配置顺序执行，结束回调按逆序执行，适配 SDK 嵌套上下文的栈式退出。
仅对开始成功的插件调用结束，即使 token 为 None 也视为开始成功。
一个插件开始失败不妨碍其他插件；结束失败不妨碍剩余插件结束。
阶段结束至多分发一次；空 hooks 是合法的无操作运行模式。

业务异常仍传播原始异常对象。取消、KeyboardInterrupt 等同样执行清理并继续传播。
框架捕获监控回调抛出的普通 Exception；不会吞掉进程级 BaseException。
插件必须采用有界耗时的本地回调，不在 hooks 同步执行网络上传；SDK 使用后台导出。
第一版不承诺可强制超时或中止任意 Python 插件回调。

## 6. Langfuse 插件

create_hooks(config) 创建请求级观察实例，SDK 客户端可在进程级复用。
on_stage_start 使用 SDK 当前 observation 作用域，保存 scope/span 到 token。
on_stage_end 写入输出或错误标记并退出 scope；确保更新失败时仍尝试退出。
不得读取或改变对话历史、重试业务、执行工具或替换返回值。

沿用 LANGFUSE_PUBLIC_KEY、LANGFUSE_SECRET_KEY、LANGFUSE_BASE_URL。
本机默认地址使用 http://127.0.0.1:3000，配置可覆盖；密钥不写入 plugins.json。
未设置密钥时告警并禁用该插件，不阻断聊天；禁用时不要求安装 SDK。
SDK 上传保持后台批处理，入口进程正常退出时统一 flush，不逐阶段 flush。
错误日志包含插件 ID、阶段名及错误类型，不打印密钥。

现有输入输出记录语义保持；后台上传是否成功需独立集成验证，不能用 mock 测试代替。

## 7. 迁移范围

1. 新增 hooks 协议与运行时。
2. 扩展配置解析并新增 HookPluginSpec、hooks loader，保留工具插件兼容。
3. 将现有 Langfuse 封装迁入 plugins/langfuse，去掉核心对它的直接导入。
4. Web、CLI 入口创建请求级 runtime，chat_workflow 接收并触发生命周期。
5. 将现有监控测试拆为 runtime 行为测试和 Langfuse 适配测试，更新导入与文档。
6. 删除旧 observability 模块，禁止以兼容包装器继续让核心依赖 SDK。
不顺带修改 vLLM 模型名称、工具执行策略或其他服务配置。

## 8. 验收

- 未启用监控时，返回值、会话提交、异常对象与现有行为一致。
- 四个阶段的顺序、输入输出、父子 ID 和开始/结束次数正确。
- 阶段失败时不执行后续阶段；父子阶段均有错误结束事件。
- 多插件开始顺序和逆序结束正确；开始失败不会错误调用结束。
- 插件导入、初始化、start、end 和序列化失败均不替换业务异常。
- 并发请求的 token、request_id 和父子关系不串线。
- 插件修改收到的快照不影响业务数据或其他插件。
- 旧配置和工具插件回归通过，监控不进入工具列表。
- 禁用监控时不导入 Langfuse，缺少密钥时仍可完成聊天。
- 模拟 SDK 验证正常及异常场景的 scope 退出。
- 本地 Langfuse 集成验证嵌套 trace、错误标记与退出 flush。
- 运行项目与 Agent 全套测试，并验证 Web 和 CLI 装配入口。

## 9. 取舍

采用独立 HookPluginSpec 和 hook_plugins 配置，避免更改现有工具插件的失败语义。
阶段上下文比散落的 before/after 调用更容易确保异常清理。
暂不引入通用中间件、优先级、事件订阅 DSL 和异步插件接口；出现真实需求再扩展。