# ============================================================
# OCR 复习 — PaddleOCR 三阶段管线
# ============================================================

# ── 1. PaddleOCR 架构总览 ──
# 三阶段管线：检测 → 方向分类 → 识别
# 为什么不是端到端：检测和识别对分辨率要求不同
# 检测要高分定位边界，识别要低分理解语义，一个模型做不到

# ── 2. 文字检测（DB）──
# 全称：Differentiable Binarization
# 核心公式：B = 1 / (1 + e^(-k(P-T)))
# 输入：图片 → CNN backbone → 特征图
# 输出：probability map P（每个像素是文字的概率）+ threshold map T（每个像素的阈值）
# 将 P 和 T 带入公式得到近似二值图 B → 收缩 → 膨胀 → bbox
# 为什么叫"可微"：传统二值化不可导，DB 用 sigmoid 近似使整个流程可端到端训练

# ── 3. 方向分类（Cls）──
# 轻量 CNN（MobileNetV3），只做四分类：0°/90°/180°/270°
# 为什么需要：手机拍照方向随机、扫描仪放纸方向不一

# ── 4. 文字识别（CRNN + CTC）──
# CRNN = CNN（提取视觉特征） + RNN（序列建模）
#   CNN backbone：特征图 [C, 1, W/4]
#   → 沿宽度切分成 W/4 个时间步
#   → BiLSTM 双向捕捉上下文
#   → 每个时间步输出字符集概率分布
# CTC = Connectionist Temporal Classification
#   解决帧-字符不对齐（8 帧 → "你好" 2 个字）
#   引入空白符 ε → 去重 → 去空 → 得到最终文本
#   训练：前向-后向算法最大化所有合法路径概率和
#   推理：贪心解码或 prefix beam search

# ── 5. CKIP vs Tesseract ──
# Tesseract：传统 CV + 固定阈值 → 怕阴影/倾斜/模糊
# PaddleOCR：DB 自适阈值 + CNN → 抗干扰强
# 核心差别：Tesseract 假设输入是干净扫描件，PaddleOCR 假设输入是手机拍的歪斜发票
# RAG 场景选 PaddleOCR：银行扫描件底色淡、文字密、方向不一

# ── 6. 练习 ──
# 用 PaddleOCR 识别一张中文图片
# 对比调整 det_db_thresh=0.3 vs 0.15 的检测效果
