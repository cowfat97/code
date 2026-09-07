from transformers import pipeline

model_name_or_path = "Qwen/Qwen3-1.7B"

# pipeline 是高层封装：加载模型 + 拼接对话模板 + 生成 + 解析，一条龙包办
# 对比 01_quick_start.py 手动四步（加载 → 拼模板 → 生成 → 切片解析），代码量省一大半
generator = pipeline(
    "text-generation",   # 任务类型：文本生成
    model_name_or_path,  # 模型名，首次运行从 HuggingFace 下载
    torch_dtype="auto",  # 精度自动选（同 01）
    device_map="auto",   # 设备自动分配：Mac 走 MPS，没有就退回 CPU（同 01）
)

# messages 直接传消息列表，pipeline 内部自动套 ChatML 模板
messages = [
    {"role": "user", "content": "请用中文介绍一下大语言模型。"},
]

# 返回的是完整对话历史 [{"role", "content"}, ...]，[0]["generated_text"] 取出来
# messages[-1]["content"] 是最后一条（助手回复）的正文
messages = generator(messages, max_new_tokens=512)[0]["generated_text"]
print(messages[-1]["content"])

# 第二轮：把新问题追加进对话历史再跑，模型「记得」第一轮（历史被拼进输入）
messages.append({"role": "user", "content": "用一句话总结。"})
messages = generator(messages, max_new_tokens=512)[0]["generated_text"]
print(messages[-1]["content"])
