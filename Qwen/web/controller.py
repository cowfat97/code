# controller.py —— HTTP 控制层：只负责接请求，业务逻辑在别的层
#
# 依赖在根 requirements.txt（统一管理，装最新）：
#   cd ~/Desktop/学习/code/Qwen && ~/.local/bin/uv pip install -r requirements.txt --python ~/Desktop/workSpace/envs/python/llm/bin/python
# 启动（两种方式等价）：
#   python controller.py          ← 在 web 目录运行，不在本进程加载模型
#   uvicorn controller:app --host 127.0.0.1 --port 8001
# 先启动 vLLM 服务（默认 http://127.0.0.1:8000/v1），可通过 VLLM_BASE_URL 配置。
# 验证：
#   curl -X POST http://127.0.0.1:8001/chat -H "Content-Type: application/json" -d '{"message": "你好"}'
import logging
import sys
import time
from pathlib import Path

from fastapi import FastAPI
from pydantic import BaseModel

# vllm_chat.py 在上一级目录
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from logging_config import setup_logging

setup_logging()
from vllm_chat import chat  # 通过 API 调用 vLLM，复用 ReAct 循环和会话记忆

logger = logging.getLogger("controller")

app = FastAPI(title="Qwen 学习项目")


class ChatRequest(BaseModel):
    """POST /chat 的请求体"""

    message: str


@app.post("/chat")
def chat_endpoint(req: ChatRequest):
    # 同步客户端会阻塞等待 vLLM，使用普通 def 让 FastAPI 在线程池执行。
    # 内部流式接收，当前接口仍返回完整 JSON 回复。
    start = time.time()
    logger.info("收到请求：%s…", req.message[:50])
    reply, count, chars = chat(req.message)  # 调核心函数（ReAct 循环），记忆在其内部完成
    logger.info("回复 %d 字，耗时 %.1f 秒", len(reply), time.time() - start)
    return {"reply": reply, "count": count, "chars": chars}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8001)
