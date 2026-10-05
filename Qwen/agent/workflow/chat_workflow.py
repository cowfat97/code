"""聊天请求的流程编排入口。"""

from .agent_builder import build_agent
from .request_processor import process_request
from .vllm_chat import chat


def orchestrate_chat(user_text):
    """依次执行请求处理、Agent 构建和核心 Agent Loop。"""
    request = process_request(user_text)
    agent = build_agent(request)
    return chat(agent)
