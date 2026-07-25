# ============================================================
# 微调复习 — 训练流程 / 数据 / 评估
# ============================================================

# ── 1. SFT（Supervised Fine-Tuning）──
# 指令微调：给 QA 对，教模型按照人类期望回答
# 数据格式：{"instruction": "...", "input": "...", "output": "..."}
# 只对 output 部分计算 loss（instruction 和 input 不参与）
# loss_mask：把 input token 的 label 设为 -100

# ── 2. 数据准备 ──
# 数据量：SFT 通常几千到几万条
# 数据质量 > 数据量：一条脏数据比十条好数据的破坏力大
# chat_template：apply_chat_template 把对话格式化为模型训练格式
# 系统 prompt：统一加在对话开头
# 数据增强：同义词替换、回译、prompt 模板多样化

# ── 3. 训练超参 ──
# learning_rate：LoRA 通常 1e-4 ~ 5e-4（比全量微调大）
# batch_size + gradient_accumulation：有效 batch = batch × accumulation
# epochs：SFT 通常 1-3 epoch，多了一定过拟合
# warmup_ratio：前 N% 步线性增加 lr，避免前期震荡
# max_seq_length：截断或 padding 到这个长度
# fp16/bf16 混合精度训练

# ── 4. 评估 ──
# loss 下降 ≠ 效果好（loss 只测下一个 token 的预测准确率）
# 人工评估：在验证集上对比基座模型和微调模型的输出
# 自动评估：GPT-4 当裁判打分
# 任务特定指标：分类=F1，生成=BLEU/ROUGE。但都不如 GPT-4 打分准
# 过拟合信号：loss 持续降但验证集评分不再提升

# ── 5. 常见问题 ──
# 灾难性遗忘：微调后模型忘了以前的通用能力
#   解决：混合通用数据、小 lr、少 epoch
# 生成重复：模型开始胡言乱语或重复
#   解决：减少 epoch、加 KL 散度正则化

# ── 6. 练习 ──
# 准备 10 条 SFT 数据（instruction + output），跑一次 LoRA 微调
# 观察 loss 曲线判断是否过拟合
