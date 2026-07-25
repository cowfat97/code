# ============================================================
# Python 复习 — NumPy / Pandas（LLM 开发必备）
# ============================================================

# ── 1. NumPy 核心 ──
# ndarray 创建：np.array、np.zeros、np.ones、np.arange
# 形状操作：reshape、flatten、T（转置）
# 切片和索引（和 Python 列表的异同）
# 广播（broadcasting）：不同形状数组的运算规则
# 常用函数：np.dot（点积）、np.linalg.norm（向量模长）、np.mean、np.std
# 为什么 embedding 运算离不开 NumPy：1024 维向量全是浮点数组

# ── 2. Pandas DataFrame ──
# 创建：pd.DataFrame(dict/list)
# 读取文件：pd.read_csv、pd.read_json
# 查看：head、info、describe、shape
# 选择：loc（标签索引）、iloc（位置索引）、布尔索引
# 缺失值：isna、fillna、dropna
# groupby 分组聚合
# apply 自定义函数

# ── 3. LLM 开发中的实际用途 ──
# 加载 embedding 结果到 DataFrame 分析
# 批量处理文档列表
# 评估指标计算（准确率、F1 等）
# 数据清洗和标注

# ── 4. 练习 ──
# 用 NumPy 实现余弦相似度计算（两个 1024 维向量）
# 用 Pandas 加载 CSV 文件，groupby 统计每类的平均值
