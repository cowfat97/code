"""聊天请求的流程编排入口。"""

from agent.core.observability import observe_stage, record_output

from .agent_builder import build_agent
from .request_processor import process_request
from .core_loop import chat


def orchestrate_chat(user_text):
    """依次处理输入、构建 Agent 并执行核心循环，返回回复和会话统计。

    各阶段输出交给下一阶段，并在可用时写入嵌套监控跨度。
    业务异常保持向上传播，由应用入口统一处理。
    """
    with observe_stage("orchestrate_chat", user_text) as workflow:
        with observe_stage("process_request", user_text) as stage:
            request = process_request(user_text)
            record_output(stage, request)
        with observe_stage("build_agent", request) as stage:
            agent = build_agent(request)
            record_output(stage, agent)
        with observe_stage("chat", agent) as stage:
            result = chat(agent)
            record_output(stage, result)
        record_output(workflow, result)
        return result
