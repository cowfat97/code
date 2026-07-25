# ============================================================
# 深度学习复习 — GPT / BERT / Qwen 架构对比
# ============================================================

# ── 1. Encoder-Decoder vs Decoder-Only vs Encoder-Only ──
# Encoder-Decoder（T5/BART）：适合 seq2seq（翻译、摘要）
# Decoder-Only（GPT/LLaMA/Qwen）：适合自回归生成
# Encoder-Only（BERT）：适合理解（分类、NER）
# 当前 LLM 主流：Decoder-Only

# ── 2. GPT 系列 ──
# GPT-2 关键设计
# LayerNorm 在 Attention 和 FFN 之前（Pre-LN）
# 残差连接：x = x + Attention(LN(x))、x = x + FFN(LN(x))
# 自回归生成：第 n 个 token 只看前 n-1 个（因果注意力，causal mask）
# Token 嵌入 + 位置嵌入 = 输入
# 输出层：hidden → vocab_size，logits → softmax → 采样

# ── 3. BERT 关键区别 ──
# 双向 Attention（不是 causal）→ 看到上下文
# MLM 预训练：随机 mask 15% token，80% [MASK] / 10% 随机替换 / 10% 不变
# NSP（Next Sentence Prediction）：后删了，对下游任务贡献不大
# [CLS] token 的输出做分类、[SEP] 分隔句子
# 只适合理解，不适合生成

# ── 4. Qwen/Llama 的现代改进 ──
# RoPE 旋转位置编码（比正弦/可学习更好）
# RMSNorm（比 LayerNorm 少了中心化，更快）
# SwiGLU 激活（比 GELU/ReLU 更好）
# Pre-Norm 架构
# GQA（Grouped Query Attention）：KV 头数 < Q 头数，省显存

# ── 5. 推理 vs 训练的区别 ──
# 训练：Teacher Forcing（输入真实上文，并行算所有位置 loss）
# 推理：自回归（逐个 token 生成，用 KV Cache 加速）
# KV Cache：已生成的 KV 不复算，每次只算新 token 的 QKV

# ── 6. 练习 ──
# 手写 causal mask（上三角矩阵 −inf）
# 手写 KV Cache 推理循环（生成一个 token，更新 cache，再生成下一个）
