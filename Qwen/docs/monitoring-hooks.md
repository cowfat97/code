# 监控 Hooks

核心流程只依赖 agent.core.hook_runtime 和 agent.entities.hooks。
Web 与 CLI 入口通过 load_hook_runtime() 为每个请求装配监控。
直接调用 orchestrate_chat(text) 默认不加载监控；需要时显式传 runtime。

## 启用与禁用

在 agent/plugins/plugins.json 的 hook_plugins 数组设置 enabled。
关闭 Langfuse 不会导入其插件或 SDK；工具插件继续使用 plugins 数组。
可以用 QWEN_PLUGINS_CONFIG 指定替代配置，旧配置没有 hook_plugins 时不启用监控。

Langfuse 使用以下环境变量：
- LANGFUSE_PUBLIC_KEY
- LANGFUSE_SECRET_KEY
- LANGFUSE_BASE_URL（缺省 http://127.0.0.1:3000）

密钥缺失、SDK 缺失或初始化失败只告警。插件配置格式错误仍明确报错。
当前依赖维持 langfuse>=4.7,<5，与已安装的 SDK v4 保持兼容。
SDK 在后台导出，进程正常退出时刷新；不会在每个阶段强制上传。
不保证强制终止进程时尚未上传的数据完整。

## 编写观察插件

模块导出 PLUGIN = HookPluginSpec(id, 1, create_hooks)。
create_hooks(config) 返回 HookSpec 列表，未启用时可以返回空列表。
HookSpec(id, on_stage_start, on_stage_end) 的 id 与插件 id 相同。

on_stage_start(event) 返回私有 token；on_stage_end(event, token, result) 完成清理。
token 可以是 None。开始按配置顺序调用，结束逆序调用；开始失败不调用对应结束。
普通监控异常只记录日志，业务异常仍以原始对象传播。
钩子是同步的，不应在回调中执行网络上传或耗时工作。

事件提供 request_id、stage_id、parent_stage_id、name 和 input。
结果提供 status（success/error/cancelled）、output、error_type、
error_message、duration_ns。数据为每插件独立的 JSON 快照，无法序列化时为
"<unavailable>"。快照只用于观察，不用作业务返回值。

首版监控 orchestrate_chat、process_request、build_agent、chat 四个阶段。
模型与单次工具调用 hooks 暂未加入。

## 验证

Windows 项目环境：
    .venv\Scripts\python.exe -B -X utf8 -m unittest discover -s tests

Agent 的安全文件插件需要 POSIX 文件描述符接口，在 WSL 运行：
    python -B -m unittest discover -s agent/tests

test_langfuse_sdk 使用真实 SDK 与内存导出器，验证父子 span、错误标记和 flush，
不向服务器上传数据；它不代表已验证 Langfuse 页面收到 trace。
