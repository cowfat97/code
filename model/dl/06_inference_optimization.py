# ============================================================
# 深度学习复习 — 推理优化 / 量化 / 部署
# ============================================================

# ── 1. 为什么需要推理优化 ──
# 7B 模型：FP32 = 28GB，FP16 = 14GB，INT4 = 4GB
# 你的 5060 Ti 16G：FP16 刚好能跑 7B，INT4 能跑 13B
# 推理速度：不优化时 7B 的 token 生成速度可能只有 ~20 tok/s

# ── 2. 量化 ──
# 原理：用低精度表示权重和激活值 → 省显存 + 加速
# PTQ（训练后量化）：不需要重新训练，直接量化
# GPTQ：基于 Hessian 矩阵的权重量化，保留重要权重精度
# AWQ：只保护 1% 的关键权重通道，其他量化
# GGUF（llama.cpp）：CPU 推理 + 混合精度，Mac 上跑 LLM 的标配
# bitsandbytes：QLoRA 用的 NF4 量化

# ── 3. Flash Attention ──
# 问题：标准 Attention 的 O(n²) 内存瓶颈来自 softmax(QK^T)
# 解法：分块计算 + kernel fusion，避免把整个注意力矩阵写回 HBM
# 效果：长序列推理显著加速，显存占用降低
# Flash Attention 2：更优的分块策略

# ── 4. KV Cache ──
# 为什么需要：自回归推理时，已生成的 token 的 KV 不用重算
# 实现：每步只算新 token 的 QKV，更新 KV Cache
# 显存占用：2 × num_layers × num_heads × head_dim × len × dtype
# PagedAttention（vLLM）：把 KV Cache 分页管理，解决碎片化

# ── 5. 推理框架 ──
# vLLM：PagedAttention、连续批处理，吞吐量高
# llama.cpp：CPU + Metal 推理，Mac 最佳选择
# Ollama：llama.cpp 的封装，一行命令跑模型
# SGLang：RadixAttention + 结构化生成

# ── 6. 练习 ──
# 用 Ollama 跑 Qwen2.5-7B，对比 FP16 vs Q4_K_M 的速度和显存
# 用 llama.cpp 在 MacBook 上跑 7B 量化模型
