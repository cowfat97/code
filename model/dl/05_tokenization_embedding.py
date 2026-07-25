# ============================================================
# 深度学习复习 — Tokenization / Embedding
# ============================================================

# ── 1. Tokenization 分词 ──
# 作用：文本 → 数字序列（token ids）
# 为什么 LLM 不能直接读文本：矩阵运算只接受数字
# Vocab Size：词表大小，常见 32K / 64K / 128K

# ── 2. 三种分词算法 ──
# BPE（GPT 系列）：统计字符对频率 → 合并最高频对 → 迭代
#   "low" → "l" "o" "w" → "lo" "w" → "low"
# WordPiece（BERT）：和 BPE 类似，但用语言模型概率选合并对
#   "un"+"##affordable" → "unaffordable"
# SentencePiece（T5/LLaMA）：直接在原始文本上训练，不依赖预分词
#   统一处理所有语言（不像 BPE 对中文不友好）

# ── 3. Tokenization 实战 ──
# 中文分词的特殊性：字级（每个字一个 token）、词级（需要分词器）
# 中文 token 效率：英文 1 token ≈ 0.75 词，中文 1 token ≈ 0.5-1.5 字
# Special tokens：[CLS]、[SEP]、[PAD]、[UNK]、[BOS]、[EOS]

# ── 4. Embedding ──
# Token ID → one-hot × embedding matrix → dense vector
# 本质：查表（token_id 行号 → embedding 矩阵的第 n 行）
# Embedding 维度：BERT 768、GPT-3 12288、BGE-M3 1024
# Position Embedding：给 embedding 加上位置信号

# ── 5. Embedding 模型的评估 ──
# MTEB 基准：分类、聚类、配对、重排序、检索、STS、摘要
# 中文基准：C-MTEB
# BGE-M3 为什么强：支持多语言，稠密 + 稀疏双输出，1024 维
# 对比：text2vec（轻量）、Cohere（贵）、OpenAI（不可本地部署）

# ── 6. 练习 ──
# 用 tiktoken 看 "Hello world" vs "你好世界" 的 token 数量
# 加载 BGE-M3 给两句话生成 embedding，算余弦相似度
