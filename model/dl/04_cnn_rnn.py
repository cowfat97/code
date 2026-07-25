# ============================================================
# 深度学习复习 — CNN / RNN（Transformer 之前的霸主）
# ============================================================

# ── 1. CNN 核心概念 ──
# 卷积 (Conv2d)：kernel 在输入上滑窗，局部感受野
# 为什么 CV 用 CNN：参数共享（同一 kernel 扫全图）、平移不变性
# Padding：保持输入输出尺寸一致
# Stride：控制下采样
# Pooling：MaxPool（取最大值）、AvgPool（取平均），降维 + 防止过拟合

# ── 2. CNN 经典架构 ──
# VGG：简单堆叠 3×3 Conv + 2×2 MaxPool
# ResNet：残差连接 F(x) + x → 解决了深层网络的梯度消失
# MobileNet：深度可分离卷积 → 轻量化

# ── 3. Batch Normalization ──
# 在 batch 维度归一化 → 加速训练、允许更大 lr
# 训练时用 batch 的均值和方差，推理时用全局统计量
# LayerNorm vs BatchNorm：NLP 用 LN（时序长度不一），CV 用 BN

# ── 4. RNN / LSTM / GRU ──
# RNN：h_t = f(W·x_t + U·h_{t-1})，串行、梯度消失
# LSTM：加了三个门——遗忘门、输入门、输出门，缓解梯度消失
# GRU：LSTM 简化版——两个门（重置门、更新门），参数更少
# 为什么被 Transformer 替代：RNN 串行无法并行、长距离仍衰减

# ── 5. Dropout ──
# 训练时随机丢弃神经元 → 防止过拟合（每轮训不同的子网络）
# 推理时关闭 dropout
# Dropout 率：全连接 0.5，CNN 0.1-0.2，Transformer 0.1

# ── 6. 练习 ──
# 用 PyTorch 手写一个 ResNet 的 BasicBlock（两个 Conv + 残差连接）
# 用 LSTM 做文本情感分类
