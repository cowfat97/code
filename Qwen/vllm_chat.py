"""vLLM HTTP 聊天后端；不导入 qwen_chat，不在本进程加载模型。

运行：python vllm_chat.py
配置：VLLM_BASE_URL（默认 http://127.0.0.1:8000/v1）、VLLM_MODEL、
VLLM_API_KEY（可选）、VLLM_TIMEOUT（秒，默认 120）。
服务需提前启动；与 qwen_chat 共用 session_memory 的进程内单会话记忆。
"""

import json
import logging
import os
import threading
from openai import OpenAI, APIConnectionError, APIStatusError, APIResponseValidationError

from logging_config import setup_logging
from memory.session_memory import as_list, inject, record, remember, stats
from output_parser import VllmActionOutput
from prompts import REACT_SYSTEM_PROMPT
from tool.registry import load_tools, action_schema

logger = logging.getLogger("vllm_chat")
_chat_lock = threading.Lock()


def _generate(turns, tools, allowed_actions):
    """调用 OpenAI 兼容接口，用 JSON Schema 约束行动输出。"""
    base_url = os.getenv("VLLM_BASE_URL", "http://127.0.0.1:8000/v1").rstrip("/")
    model = os.getenv("VLLM_MODEL", "Qwen/Qwen2.5-7B-Instruct-AWQ")
    timeout = float(os.getenv("VLLM_TIMEOUT", "120"))
    if timeout <= 0:
        raise ValueError("VLLM_TIMEOUT 必须大于 0")
    schema = action_schema(tools, allowed_actions)
    definitions = [tools[name].definition() for name in allowed_actions if name != "answer"]
    tool_context = "\n当前可用工具：\n" + json.dumps(definitions, ensure_ascii=False)
    # 仅在本次请求的副本中附加工具列表，不将动态列表写入会话记忆。
    turns = [dict(turn) for turn in turns]
    if turns and turns[0]["role"] == "system":
        turns[0]["content"] += tool_context
    else:
        turns.insert(0, {"role": "system", "content": REACT_SYSTEM_PROMPT + tool_context})
    payload = {
        "model": model,
        "messages": turns,
        # max_tokens：单次生成的 token 上限（正整数），不是字符数或会话总长度。
        # 还受服务端上下文容量限制；过小可能截断 JSON，过大会增加潜在耗时。
        "max_tokens": 512,
        # stream：True 分块接收，False 一次接收；不改变采样模式。
        # 当前程序会拼接完整内容后返回，Web 接口并非逐字输出。
        "stream": True,
        # temperature：控制采样随机性，不控制流式输出，也不保证答案正确。
        # 使用非负值；0 为贪心解码，正值越低越保守、越高越多样。
        # 1 表示不进行温度缩放，不代表“100% 随机”。
        # 常用参考（不是硬性边界或质量保证）：
        #   0       ：分类、抽取等偏向稳定选择的任务。
        #   0.1–0.3 ：规则执行、工具选择、严谨问答；当前使用 0.3。
        #   0.4–0.7 ：普通聊天、解释、改写。
        #   0.8–1.0 ：创意文案、故事、多方案生成。
        #   >1.0    ：随机性更强，也更容易跑题或出错，谨慎使用。
        # 实际效果还受模型、提示词、top_p/top_k 和 Schema 约束影响。
        "temperature": 0.5,
        # top_p：核采样，按累计概率保留候选 token；范围 (0, 1]。
        # 1 禁用此过滤；越小候选通常越少。0.9 是概率阈值，不是保留 90% 词汇。
        "top_p": 0.9,
        # presence_penalty：按 token 在已生成文本中是否出现施加惩罚；范围 [-2, 2]。
        # 0 不惩罚，正值鼓励新 token，负值鼓励重复；不按出现次数累加。
        "presence_penalty": 0.5,
        # frequency_penalty：按 token 在已生成文本中的出现次数惩罚；范围 [-2, 2]。
        # 0 不惩罚，正值抑制高频重复，负值鼓励重复；过强可能影响术语和公式。
        "frequency_penalty": 0.5,
        # seed：整数随机种子；固定值便于相同输入和配置下做对照。
        # 不保证跨硬件/版本/调度完全复现；会话历史变化后也不是相同输入。
        # 无需固定种子时可删除此字段。
        "seed": 42,
        # vLLM 扩展参数通过 extra_body 传递。
        "extra_body": {
            # top_k：只保留概率最高的 K 个候选；正整数，0 或 -1 禁用（vLLM 0.28）。
            # 1 只留最高概率候选；与 top_p 同时设置时会共同限制候选集合。
            "top_k": 50,
            # min_p：相对最高 token 概率的最低阈值；范围 [0, 1]，0 禁用。
            # 例如 0.1 表示过滤概率低于最高概率 10% 的 token，不是绝对概率 0.1。
            "min_p": 0.0,
            # repetition_penalty：对提示词及已生成文本中出现过的 token 施加重复惩罚。
            # 必须 >0；1 中性，>1 抑制重复，0<值<1 鼓励重复。
            # 与上面的两种加性惩罚不同，此项按比例调整 logits；过强会影响必要重复。
            "repetition_penalty": 1.0,
        },
        # response_format：以 ActionOutput 的 JSON Schema 约束输出结构，非采样参数。
        # 约束字段和类型，不保证内容真实；仍需完整接收后进行本地校验。
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "action_output",
                "schema": schema,
            },
        },
    }
    try:
        # 本地 vLLM 未开启鉴权时，SDK 仍需要一个非空占位 key。
        with OpenAI(
            base_url=base_url,
            api_key=os.getenv("VLLM_API_KEY") or "EMPTY",
            timeout=timeout,
            max_retries=0,
        ) as client:
            result = client.chat.completions.create(**payload)
            if payload["stream"]:
                parts = []
                finish_reason = None
                with result:
                    for chunk in result:
                        if not chunk.choices:
                            continue
                        choice = chunk.choices[0]
                        text = choice.delta.content
                        if text is not None:
                            if not isinstance(text, str):
                                raise RuntimeError("vLLM 返回了非文本流式片段")
                            parts.append(text)
                        if choice.finish_reason is not None:
                            finish_reason = choice.finish_reason
                # 迭代结束后检查截断原因，不将非 stop 一律视为失败。
                if finish_reason == "length":
                    raise RuntimeError("vLLM 输出被长度限制截断，请增加 max_tokens 或缩短输出")
                content = "".join(parts)
            else:
                content = result.choices[0].message.content
    except APIStatusError as exc:
        raise RuntimeError(f"vLLM HTTP {exc.status_code}: {exc.response.text[:2048]}") from exc
    except APIConnectionError as exc:
        raise RuntimeError(f"无法连接 vLLM 或请求超时：{base_url}，请检查服务状态") from exc
    except (APIResponseValidationError, ValueError) as exc:
        raise RuntimeError("vLLM 返回的响应格式无效") from exc
    except (AttributeError, IndexError, TypeError) as exc:
        raise RuntimeError("vLLM 响应结构无效，无法读取回复内容") from exc
    if not isinstance(content, str) or not content.strip():
        raise RuntimeError("vLLM 返回了空回复或非文本回复")
    return content


def chat(user_text):
    """HTTP ReAct 聊天，返回 (reply, count, chars)。失败时回滚本轮记忆。

    同一后端的请求串行执行；本项目的全局记忆不支持多用户会话隔离。
    """
    if not isinstance(user_text, str) or not user_text.strip():
        raise ValueError("消息必须是非空字符串")
    with _chat_lock:
        previous = as_list()
        try:
            remember(user_text)
            tools = load_tools()
            calls = {name: 0 for name in tools}
            pending = None
            footers = {}
            for step in range(1, 6):
                logger.info("HTTP ReAct 第 %d/5 步", step)
                turns = as_list()
                allowed = ["answer"]
                allowed.extend(name for name, spec in tools.items() if calls[name] < spec.max_calls)
                if pending is not None:
                    allowed = [pending]
                model_output = _generate(turns, tools, allowed_actions=allowed)
                try:
                    output = VllmActionOutput.model_validate_json(model_output)
                except ValueError as exc:
                    raise RuntimeError("模型行动格式无效，停止本轮工具流程") from exc
                action, arg = output.action, output.argument
                if action not in allowed:
                    raise RuntimeError("模型行动不符合当前工具流程")
                turns.append({"role": "assistant", "content": model_output})
                record(turns)
                if action == "answer":
                    if not isinstance(arg, str) or not arg.strip():
                        raise RuntimeError("模型返回空回答")
                    reply = arg.strip()
                    if footers:
                        reply += "\n" + "\n".join(footers.values())
                    break
                spec = tools[action]
                calls[action] += 1
                footers.pop(action, None)
                try:
                    result = spec.execute(arg)
                except (ValueError, ArithmeticError) as exc:
                    logger.warning("工具 %s 失败：%s", action, exc)
                    if spec.require_success:
                        if calls[action] >= spec.max_calls:
                            raise RuntimeError(f"工具 {action} 重试耗尽：{exc}") from exc
                        pending = action
                    inject("[观察] " + json.dumps({"tool": action, "ok": False, "error": str(exc)}, ensure_ascii=False))
                    continue
                pending = None
                if spec.result_footer:
                    footers[action] = spec.result_footer(result)
                logger.info("工具 %s 执行成功", action)
                inject("[观察] " + json.dumps({"tool": action, "ok": True, "result": result}, ensure_ascii=False))
            else:
                raise RuntimeError("达到最大行动步数，未完成回答")
            count, chars = stats()
            return reply, count, chars
        except Exception:
            record(previous)
            raise


if __name__ == "__main__":
    setup_logging()
    print("vLLM HTTP 聊天（quit/exit 退出）")
    while True:
        try:
            text = input("你: ")
            if text.strip().lower() in {"quit", "exit"}:
                break
            reply, count, chars = chat(text)
            print(f"模型: {reply}\n[记忆状态] {count} 条消息，共 {chars} 字符")
        except (EOFError, KeyboardInterrupt):
            break
        except (RuntimeError, ValueError) as exc:
            print(f"请求失败：{exc}")
