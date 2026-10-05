"""命令行聊天接口。"""

from agent.core.logging import setup_logging
from agent.workflow.chat_workflow import orchestrate_chat


def main():
    """启动命令行接口，所有请求统一进入流程编排函数。"""
    setup_logging()
    print("vLLM HTTP 聊天（quit/exit 退出）")
    while True:
        try:
            user_text = input("你: ")
            if user_text.strip().lower() in {"quit", "exit"}:
                break
            reply, count, chars = orchestrate_chat(user_text)
            print(f"模型: {reply}\n[记忆状态] {count} 条消息，共 {chars} 字符")
        except (EOFError, KeyboardInterrupt):
            break
        except (RuntimeError, ValueError) as exc:
            print(f"请求失败：{exc}")


if __name__ == "__main__":
    main()
