# 编排阶段监控

`orchestrate_chat` 创建一个根 span，依次包含 `process_request`、`build_agent`、`chat` 三个子 span，记录各阶段输入、输出、时间和异常。`chat` 的输出保留原有 `(reply, count, chars)` 结构。

默认连接本地部署 `http://192.168.1.177:3000`，不改变模型服务地址。当前只监控编排的三个阶段，不拆分 chat 内部的模型调用和工具步骤。

本地部署同样需要项目 API Key。在 Langfuse 项目 Settings → API Keys 创建密钥，然后在启动项目的终端设置：

```bash
export LANGFUSE_BASE_URL=http://192.168.1.177:3000
export LANGFUSE_PUBLIC_KEY='你的项目 Public Key'
export LANGFUSE_SECRET_KEY='你的项目 Secret Key'
python quick_start.py
```

CLI 和 Web 都通过相同编排入口记录监控。环境变量应在进程启动前配置，配置后重启进程。未配置 Key 或 SDK 初始化失败时会提示监控未启用，聊天继续运行。监控会向上述服务发送用户输入、阶段输出和异常信息。

SDK 使用后台批量上传并在进程正常退出时关闭导出器。查看失败请求时，对应失败阶段和根 span 会标记异常；后续阶段不会执行。

SDK 接入依据：[Langfuse 官方 Python SDK 文档](https://langfuse.com/docs/observability/sdk/overview)。本项目使用 SDK v3，服务端需为兼容的 Langfuse v3 部署。
