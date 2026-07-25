# ============================================================
# 深度学习复习 — 神经网络基础
# ============================================================

# ── 1. 感知机 → 神经网络 ──
# 单层感知机：线性分类、无法解决 XOR
# 多层感知机 (MLP)：隐藏层 + 激活函数 → 非线性
# 前向传播：输入 × 权重 → 激活 → 下一层
# 为什么需要激活函数：没有 = 多层等价于单层线性变换

# ── 2. 激活函数 ──
# Sigmoid：(0,1)，梯度消失、输出非零中心
# Tanh：(-1,1)，零中心、仍有梯度消失
# ReLU：max(0,x)，计算快、缓解梯度消失、Dying ReLU 问题
# GELU：x·Φ(x)，Transformer 标配，比 ReLU 平滑
# SwiGLU：LLaMA/Qwen 等现代模型使用

# ── 3. 损失函数 ──
# 分类：CrossEntropyLoss（log_softmax + NLLLoss，二合一）
# 回归：MSELoss、L1Loss（MAE）
# 训练目标：最小化损失函数

# ── 4. 反向传播 ──
# 链式法则求梯度：∂L/∂w = ∂L/∂y · ∂y/∂w
# 自动微分：PyTorch autograd，不需要手推梯度
# .backward() → .grad 拿到梯度
# 计算图：动态构建、反向传播后释放

# ── 5. 优化器 ──
# SGD：最基础，收敛慢
# SGD + Momentum：加入惯性项，加速收敛
# Adam：自适应学习率 + 动量，最常用
# AdamW：Adam + 权重衰减（解耦 weight decay 和自适应学习率）
# 学习率调度：StepLR、CosineAnnealingLR、Warmup

# ── 6. 练习 ──
# 用 PyTorch 手写一个 2 层 MLP，做 MNIST 分类
# 对比 SGD、Adam、AdamW 的收敛速度
