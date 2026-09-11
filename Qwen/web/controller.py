# controller.py —— HTTP 控制层：只负责接请求，业务逻辑在别的层
#
# 依赖在根 requirements.txt（统一管理，装最新）：
#   cd ~/Desktop/学习/code/Qwen && ~/.local/bin/uv pip install -r requirements.txt --python ~/Desktop/workSpace/envs/python/llm/bin/python
# 启动（两种方式等价）：
#   python controller.py          ← 直接跑（启动会加载模型，几十秒属正常）
#   uvicorn controller:app        ← 标准方式
# 验证：
#   curl -X POST http://127.0.0.1:8000/chat -H "Content-Type: application/json" -d '{"message": "你好"}'
import logging
import sys
import time
from pathlib import Path

from fastapi import FastAPI
from pydantic import BaseModel

# qwen_chat.py 在上一级目录
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from logging_config import setup_logging

setup_logging()
from qwen_chat import chat  # 核心函数：ReAct 循环 + 记忆都在里面（import 即加载模型，启动慢属正常）

logger = logging.getLogger("controller")

app = FastAPI(title="Qwen 学习项目")


class ChatRequest(BaseModel):
    """POST /chat 的请求体"""

    message: str


@app.post("/chat")
def chat_endpoint(req: ChatRequest):
    # 普通 def 路由：模型推理是几十秒阻塞计算，FastAPI 自动扔线程池；
    # 写 async def 会卡死事件循环（线程 vs 协程的典型分界）
    start = time.time()
    logger.info("收到请求：%s…", req.message[:50])
    reply, count, chars = chat(req.message)  # 调核心函数（ReAct 循环），记忆在其内部完成
    logger.info("回复 %d 字，耗时 %.1f 秒", len(reply), time.time() - start)
    return {"reply": reply, "count": count, "chars": chars}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)
