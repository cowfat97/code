from transformers import AutoModelForCausalLM, AutoTokenizer
# transformers：HuggingFace 的模型库，Auto 系列会根据模型名自动匹配合适的模型类

model_name = "Qwen/Qwen3-4B"  # 4B 作为当前默认模型
# 模型名格式「机构/模型」，首次运行自动从 HuggingFace 下载到 ~/.cache/huggingface

# 加载模型和分词器
model = AutoModelForCausalLM.from_pretrained(
    model_name,
    torch_dtype="auto",   # 精度自动选：优先用模型默认精度，兼顾内存
    device_map="auto"     # 设备自动分配：Mac 上走 MPS（GPU 加速），没有就退回 CPU
)
tokenizer = AutoTokenizer.from_pretrained(model_name)
# 分词器做两件事：把文字切成数字 token；套用「对话模板」把消息拼成模型认识的格式

# 准备输入：构造一条用户消息
#prompt = "Give me a short introduction to large language models."
prompt = "请用中文介绍一下大语言模型。"
messages = [
    {"role": "user", "content": prompt},
]
text = tokenizer.apply_chat_template(
    messages,
    tokenize=False,             # 只拼文本不转数字，方便查看模板实际长什么样
    add_generation_prompt=True, # 末尾追加生成提示符，告诉模型「该你回答了」
    enable_thinking=False,       # 思考模式开关：True 会输出 <think> 思考过程
)
model_inputs = tokenizer([text], return_tensors="pt").to(model.device)
# 把拼好的文本转成数字张量（模型只认数字），并送到模型所在的设备

# 生成文本
generated_ids = model.generate(
    **model_inputs,
    max_new_tokens=512  # 最多生成 512 个新 token；原 32768 在 16GB 机器上极慢，先改小验证流程
)
output_ids = generated_ids[0][len(model_inputs.input_ids[0]):].tolist()
# 截掉输入部分，只留模型新生成的 token，转成 Python 列表方便查找

# 解析思考内容：</think> 的 token id 是 151668，之前是思考，之后是正文
try:
    # 从后往前找 </think>：思考内容里可能出现过类似标记，取最后一个最可靠
    index = len(output_ids) - output_ids[::-1].index(151668)
except ValueError:
    index = 0  # 没找到 </think>：模型没输出思考过程，全部按正文处理

thinking_content = tokenizer.decode(output_ids[:index], skip_special_tokens=True).strip("\n")
content = tokenizer.decode(output_ids[index:], skip_special_tokens=True).strip("\n")
# decode 把数字还原成文字；skip_special_tokens 过滤掉 <|im_end|> 这类特殊符号

print("thinking content:", thinking_content)
print("content:", content)
