# ============================================================
# Python 复习 — 变量 / 数据类型 / 控制流
# ============================================================

# ── 1. 变量与数据类型 ──
# int、float、str、bool 四种基本类型
# type() 查看类型、isinstance() 判断类型
# 变量命名规范：snake_case、不能数字开头、避开关键字

# ── 2. 字符串操作 ──
# 拼接：+、join
# 格式化：f-string f"{name} is {age}"、format()、% 旧式
# 切片：s[start:end:step]
# 常用方法：strip、split、replace、upper/lower、startswith/endswith、find
# 字符串不可变 vs 列表可变

# ── 3. 列表 ──
# 创建：[1, 2, 3]、list(range(10))
# 增：append、extend、insert
# 删：pop、remove、del
# 查：索引、切片、in、index
# 排序：sort() vs sorted()、reverse
# 列表推导式：[x*2 for x in range(10) if x % 2 == 0]

# ── 4. 字典 ──
# 创建：{"key": "value"}、dict()
# 增删改查：d["new"] = 1、d.get("key", default)、del、pop
# 遍历：.items()、.keys()、.values()
# 字典推导式：{k: v*2 for k, v in d.items()}

# ── 5. 条件判断 ──
# if / elif / else
# 比较运算符：== != > < >= <=
# 逻辑运算符：and or not
# 三元表达式：x if condition else y（不用写太复杂）

# ── 6. 循环 ──
# for 循环遍历可迭代对象
# range(start, stop, step)
# while 循环（注意死循环）
# break（跳出循环）、continue（跳过本次）
# for-else 和 while-else（循环正常结束才执行 else）

# ── 7. 练习 ──
# FizzBuzz：1-100，3的倍数输出Fizz，5的倍数输出Buzz，15的倍数输出FizzBuzz
# 统计一个字符串中每个字符的出现次数，用字典
