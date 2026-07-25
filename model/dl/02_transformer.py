# ============================================================
# 深度学习复习 — Transformer 架构
# ============================================================

# ── 1. 为什么需要 Transformer ──
# RNN/LSTM 的问题：串行计算（无法并行）、长距离依赖衰减
# Transformer 的核心创新：Self-Attention 并行计算、直接建模任意距离依赖
# "Attention Is All You Need" (2017)

# ── 2. Self-Attention 机制 ──
# Q（Query）、K（Key）、V（Value）三个矩阵
# Attention(Q,K,V) = softmax(Q·K^T / √d_k) · V
# √d_k 的作用：防止点积过大 → softmax 梯度消失
# 直观理解：Q 问 "我跟谁相关"，K 答 "我是谁"，V 给信息
# 代码：Q = x @ W_q, K = x @ W_k, V = x @ W_v

# ── 3. Multi-Head Attention ──
# 为什么要多头：不同头关注不同子空间（语法/语义/位置）
# 实现：h 组独立的 QKV，各自算 Attention → concat → 线性变换
# head_dim = d_model // num_heads（常见 64 或 128）

# ── 4. Transformer Block ──
# 输入 → Multi-Head Self-Attention → Add & Norm
#      → Feed Forward（两层 MLP，中间 dim ×4）→ Add & Norm
# LayerNorm：不是 BatchNorm，沿特征维度归一化
# Pre-LN vs Post-LN：现代模型用 Pre-LN（更稳定）

# ── 5. Position Encoding ──
# 为什么需要：Attention 不感知位置
# 正弦位置编码（原始）：PE(pos,2i)=sin(pos/10000^(2i/d))
# 可学习位置编码（BERT/GPT）
# RoPE（Qwen/LLaMA）：旋转位置编码，只作用于 QK 点积
# ALiBi：线性偏置，外推长度好

# ── 6. 练习 ──
# 手写 Scaled Dot-Product Attention（Q·K^T / √d → softmax → ×V）
# 手写 Multi-Head Attention（拆分 head → 各自 Attention → concat）
