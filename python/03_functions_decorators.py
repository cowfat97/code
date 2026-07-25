# ============================================================
# Python 复习 — 函数 / 闭包 / 装饰器 / lambda
# ============================================================

# ── 1. 函数基础 ──
# 定义、参数（位置、默认、关键字）、返回值、类型注解
# *args（可变位置参数）、**kwargs（可变关键字参数）
# 传参顺序：位置参数 → *args → 关键字参数 → **kwargs

# ── 2. 作用域 ──
# LEGB 规则：Local → Enclosing → Global → Built-in
# global、nonlocal 关键字
# 闭包：外层函数返回内层函数，内层函数引用外层变量

# ── 3. lambda ──
# 语法、和 def 的区别（单表达式 vs 语句块）
# 常用场景：sort key、map、filter

# ── 4. 装饰器 ──
# 本质：接收函数，返回函数
# 手写一个计时装饰器 @timer
# 带参数的装饰器（三层嵌套）
# functools.wraps 保留原函数元信息
# 类装饰器 __call__

# ── 5. 内置高阶函数 ──
# map、filter、reduce(functools)
# sorted 的 key 参数
# zip、enumerate

# ── 6. 练习 ──
# 写一个 @retry(n) 装饰器，函数失败后自动重试 n 次
# 用 map 和 lambda 把列表所有元素平方
