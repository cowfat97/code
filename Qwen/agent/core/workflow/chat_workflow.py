"""聊天请求的流程编排入口。"""

from agent.core.hook_runtime import HookRuntime
from .agent_builder import build_agent
from .request_processor import process_request
from .core_loop import chat


def orchestrate_chat(user_text, *, runtime=None):
    """核心只触发生命周期；入口装配可选的观察插件。"""
    runtime = runtime if runtime is not None else HookRuntime()
    with runtime.stage("orchestrate_chat", user_text) as workflow:
        with runtime.stage("process_request", user_text) as stage:
            request = process_request(user_text)
            stage.set_output(request)
        with runtime.stage("build_agent", request) as stage:
            agent = build_agent(request)
            stage.set_output(agent)
        with runtime.stage("chat", agent) as stage:
            result = chat(agent)
            stage.set_output(result)
        workflow.set_output(result)
        return result
