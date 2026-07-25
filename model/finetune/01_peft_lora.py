# ============================================================
# 微调复习 — PEFT / LoRA / QLoRA
# ============================================================

# ── 1. 为什么需要 PEFT ──
# 全量微调：7B 模型 14GB × 优化器状态 = 42GB+ 显存
# PEFT（Parameter-Efficient Fine-Tuning）：只调少量参数
# 典型场景：你的 5060 Ti 16G → LoRA 可微调 7B，全量微调不行

# ── 2. LoRA 原理 ──
# 核心思想：权重增量是低秩的（ΔW 可分解为两个小矩阵）
# W' = W + B·A（A: d×r, B: r×d, r << d）
# 训练时只更新 A 和 B，W 冻结
# 参数量：d×d → d×r + r×d = 2dr（r=8 时仅为原参数的 0.2%）
# α/r 控制 LoRA 的影响强度

# ── 3. LoRA 配置参数 ──
# r（rank）：低秩维度，通常 4/8/16，越大越强但越慢
# alpha：缩放因子，通常 = r × 2
# target_modules：哪些层加 LoRA（q_proj, v_proj 常见；qkv+o+gate+up+down 全加）
# dropout：防止过拟合，通常 0.05-0.1

# ── 4. QLoRA ──
# 在 LoRA 基础上 + 4-bit NormalFloat 量化 + 双重量化
# NF4：针对正态分布权重优化的 4-bit 格式
# 效果：7B 模型微调只需 ~6GB 显存
# bitsandbytes 库实现

# ── 5. 其他 PEFT 方法 ──
# Prefix Tuning：在每层前面加可学习的前缀向量
# Adapter：在 Transformer Block 中间插入小型网络
# IA3：只缩放 activations，参数更少
# 对比：LoRA 不增加推理延迟（可 merge 回原权重），其他方法会增加

# ── 6. LoRA 训练流程 ──
# load 基座模型 → 冻结全部参数 → 选 target_modules 挂 LoRA
# → Trainer/SFTTrainer → 保存 adapter（几 MB）
# → 推理时：load 基座 + load adapter，或 merge_and_unload

# ── 7. 练习 ──
# 用 peft 库给 Qwen2.5-0.5B 加 LoRA
# 对比不同 r 值（4/8/16）的可训练参数量
