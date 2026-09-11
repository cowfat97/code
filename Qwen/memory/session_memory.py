# memory/session_memory.py —— 记忆模块 + 终端实验入口（一个文件）
#
# 两种用法：
#   1. 被 import：记忆方法——qwen_chat.chat 通过这里读写记忆
#   2. 直接运行：终端实验——python memory/session_memory.py，循环调 chat 观察记忆
#      （import qwen_chat 放在 __main__ 里，避免模块间循环 import）
import logging
import sys
from pathlib import Path

# 兼容直接运行 `python memory/session_memory.py`。
# 根目录路径必须在导入 prompts 前加入。
project_root = str(Path(__file__).resolve().parent.parent)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from logging_config import setup_logging
from prompts import REACT_SYSTEM_PROMPT

logger = logging.getLogger("memory.session_memory")

messages = []  # 会话记忆的全部存储：一个列表，模块级状态


def remember(user_text):
    """记忆方法：用户消息写入记忆。被 chat 核心函数内部调用。

    会话第一条消息前自动写入系统提示（只写一次），
    让模型每轮生成都看到「思考/行动」格式要求。
    """
    if not messages:
        messages.append({"role": "system", "content": REACT_SYSTEM_PROMPT})
    messages.append({"role": "user", "content": user_text})
    logger.debug("记忆 +1 条：%s…", user_text[:50])


def inject(text):
    """流程内部注入一条 user 消息（观察结果等），不触发系统提示首插。"""
    messages.append({"role": "user", "content": text})


def search(keyword):
    """按关键词检索真实对话记忆，返回命中文本列表。

    只搜干净的用户消息：排除 system 提示、[观察] 注入行、模型 <think> 段、
    以及当前这条问题本身（messages 里它紧挨着，含关键词会假命中）。
    """
    # search() 在模型已经生成 assistant 回复后执行，所以 messages[-1]
    # 并不是当前问题。先取出所有干净的用户消息，再排除最后一条才准确。
    user_messages = [
        m["content"] for m in messages
        if m["role"] == "user"
        and not m["content"].startswith("[观察]")
        and "<think>" not in m["content"]
    ]
    return [text for text in user_messages[:-1] if keyword in text]


def as_list():
    """当前记忆快照（供模型生成用）。返回拷贝，防流程层误改状态。"""
    return list(messages)


def record(turns):
    """模型生成后把完整对话写回记忆（含新增的 assistant 回复）。"""
    global messages
    messages = list(turns)


def stats():
    """记忆统计：返回 (条数, 总字符数)，供调用方展示。"""
    return len(messages), sum(len(m["content"]) for m in messages)


def _run_terminal_experiment():
    """终端实验：循环调 chat，观察 ReAct 每步日志和记忆状态。"""
    setup_logging()
    from qwen_chat import chat

    print("会话记忆实验·本地模型（quit/exit 退出）")
    rounds = 0
    while True:
        user_text = input("你: ")
        if user_text.lower() in {"quit", "exit"}:
            break
        rounds += 1
        reply, count, chars = chat(user_text)  # 记忆在 ReAct 循环内部完成
        print(f"模型: {reply}")
        print(f"[记忆状态] {count} 条消息，共 {chars} 字符")  # 步骤 3 观察

    logger.info("实验结束，共 %d 轮", rounds)


if __name__ == "__main__":
    _run_terminal_experiment()
