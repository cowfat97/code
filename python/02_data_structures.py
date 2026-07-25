# ============================================================
# Python 复习 — 列表 / 元组 / 集合 / 字典
# ============================================================

# ── 1. 列表 ──
# 创建：[]、list()、列表推导式
# 增：append、insert、extend（区别）
# 删：pop、remove、del（区别）
# 查：索引 [n]、切片 [start:end:step]、in 判断
# 排序：sort() 原地 vs sorted() 返回新列表、reverse、key 参数
# 去重：set(list)
# 列表推导式：[x for x in range(10) if x % 2 == 0]

# ── 2. 元组 ──
# 不可变 vs 列表可变
# 创建、单元素元组的逗号陷阱 (1,) vs (1)
# 拆包：a, b = (1, 2)、*rest 收集剩余
# namedtuple

# ── 3. 集合 ──
# 去重、交集 &、并集 |、差集 -、对称差 ^
# add、remove、discard（区别：remove 抛异常）
# 集合推导式

# ── 4. 字典 ──
# 创建、增删改查、get 安全取值 vs [] 抛 KeyError
# 遍历：.items() .keys() .values()
# 合并：{**d1, **d2}、| 运算符 (3.9+)
# 字典推导式
# defaultdict、Counter、OrderedDict

# ── 5. 综合练习 ──
# 给一个列表 [1,2,2,3,3,3,4]，用集合去重后排序
# 统计字符串中每个字符出现次数（用字典/Counter）
