"""聊天请求的流程编排入口。"""

from agent.core.observability import observe_stage, record_output

from .agent_builder import build_agent
from .request_processor import process_request
from .vllm_chat import chat


def orchestrate_chat(user_text):
    """依次执行请求处理、Agent 构建和核心 Agent Loop。"""
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
