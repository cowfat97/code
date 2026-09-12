# qwen_chat.py —— 核心编排层：chat 只负责流程（ReAct 循环）和模型交互（pipeline）
#
# 职责边界（每个文件功能独立）：
#   qwen_chat.py      本文件：ReAct 流程编排 + 模型交互
#   output_parser.py  模型输出协议：行动解析 + 格式漂移降级
#   memory/session_memory.py  记忆：messages 状态 + remember/search 记忆方法 + 终端实验入口
#   prompts.py        提示词：REACT_SYSTEM_PROMPT
#
# chat 是核心函数，内部调用记忆方法（remember/inject），调用方只依赖 chat：
#   web/controller.py        HTTP 控制层
#   memory/session_memory.py 终端实验（直接运行它即可）
#
# ReAct 循环（Thought → Action → Observation → ... → Final Answer）：
#   ① remember(user_text)  用户消息写入记忆（循环外第一步）
#   ② Thought              状态机约束模型输出 ActionOutput JSON
#   ③ Action               校验 JSON 并解析行动（answer / memory_search）
#   ④ Observation          执行行动得到观察，写入记忆，回到 ②
#   ⑤ Final Answer         行动为 answer 时，行动行内容就是最终回复
# 兜底：输出格式漂移（解析不出行动）降级为直接回答；超 3 步兜底返回最后输出。
import logging
import time

import outlines
from outlines.inputs import Chat
from transformers import AutoModelForCausalLM, AutoTokenizer

from logging_config import setup_logging
from memory.session_memory import as_list, inject, record, remember, search, stats
from output_parser import ActionOutput, fallback_reply, parse_action

logger = logging.getLogger("qwen_chat")  # 本文件统一用这个 logger，入口配置输出

model_name_or_path = "Qwen/Qwen3-4B"

# Outlines 根据 ActionOutput 生成状态机，在每个 token 采样前屏蔽非法候选。
model = AutoModelForCausalLM.from_pretrained(
    model_name_or_path,
    torch_dtype="auto",
    device_map="auto",
)
tokenizer = AutoTokenizer.from_pretrained(model_name_or_path)
generator = outlines.from_transformers(model, tokenizer)


def execute(action, arg):
    """执行行动，返回观察结果（Observation）。当前只支持 memory_search。

    检索命中内容全量给出，最多 3 条。后续新增工具（联网搜索、写文件等）
    就是往这里加分支 + 往 prompts.py 加行动说明。
    """
    if action == "memory_search":
        if not arg:
            return "memory_search 需要关键词参数"
        hits = search(arg)  # 检索逻辑在记忆模块，本层只做措辞组装
        if not hits:
            return f"记忆中没找到与「{arg}」相关的内容"
        return "检索结果：" + "；".join(hits[-3:])
    return f"未知行动：{action}"


def chat(user_text):
    """核心函数：ReAct 推理循环。只做流程编排 + 模型交互，记忆读写全走 memory.session_memory。

    返回 (reply, count, chars)：回复正文、记忆条数、记忆字符数。
    """
    start = time.time()
    remember(user_text)  # ① 记忆方法：用户消息入记忆（内部自动带系统提示）

    max_steps = 3   # 最多循环 3 步，防止模型空转
    max_search = 1  # memory_search 每轮最多执行 1 次（工具限次，防对话无限膨胀）
    search_count = 0
    for step in range(1, max_steps + 1):
        logger.info("ReAct 第 %d/%d 步：生成思考", step, max_steps)
        # ② Thought：模型只能生成符合 ActionOutput 的 JSON
        turns = as_list()
        model_output = generator(
            Chat(turns),
            output_type=ActionOutput,
            max_new_tokens=512,
        )
        turns.append({"role": "assistant", "content": model_output})
        logger.info("模型输出：%s", turns)
        record(turns)  # 生成结果写回记忆（含新增 assistant 回复）

        # ③ Action：从输出解析行动
        parsed = parse_action(model_output)
        if parsed is None:
            # 兜底 1：模型漏写了行动词（如「行动：你好」缺 answer）。
            # 只要写了「行动：」行，行后面的内容就是回复，抽出来用；
            # 连「行动：」都没有才把全文当回复。
            reply = fallback_reply(model_output)
            logger.warning("第 %d 步输出格式漂移，降级为直接回答", step)
            break
        action, arg = parsed
        logger.info("行动 = %s，参数 = %r", action, arg)

        if action == "answer":
            reply = arg or model_output
            break

        # 工具限次：超过次数不再执行，直接让模型下一轮必须收尾
        if search_count >= max_search:
            logger.warning("第 %d 步再次发起 %s，超过限次，拒绝执行", step, action)
            inject("[观察] 工具调用次数已达上限，下一步 JSON 的 action 必须是 answer")
            continue

        # ④ Observation：执行行动得到观察，写入记忆后进入下一轮。
        # 注入文本统一带 [观察] 前缀，供记忆模块检索时排除（防自我污染）；
        # 附「禁止再次检索」指令——小参数模型拿到检索结果后容易反复发 memory_search。
        search_count += 1
        observation = execute(action, arg)
        logger.info("观察 = %s…", observation[:50])
        inject(f"[观察] {observation}。下一步 JSON 的 action 必须是 answer，不要再次检索")
    else:
        # for 正常走完（3 步全是非 answer 行动）：兜底返回最后输出
        reply = as_list()[-1]["content"]
        logger.warning("达到最大步数 %d，兜底返回最后输出", max_steps)

    count, chars = stats()
    logger.info("本轮完成：耗时 %.1f 秒，记忆 %d 条", time.time() - start, count)
    return reply, count, chars


if __name__ == "__main__":
    # 单独跑本文件时的演示：两轮对话，观察 ReAct 循环日志
    setup_logging()
    reply, count, chars = chat("请用中文介绍一下大语言模型。")
    print(reply)
    print(f"[记忆状态] {count} 条消息，共 {chars} 字符")

    reply, count, chars = chat("用一句话总结。")
    print(reply)
    print(f"[记忆状态] {count} 条消息，共 {chars} 字符")
