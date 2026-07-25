# ============================================================
# Python 复习 — 迭代器 / 生成器 / 协程
# ============================================================

# ── 1. 可迭代对象 vs 迭代器 ──
# Iterable：有 __iter__，返回迭代器（list、dict、str）
# Iterator：有 __iter__ + __next__
# iter() 把可迭代对象转为迭代器
# for 循环的本质：iter() → 反复 next() → StopIteration 停止

# ── 2. 生成器 ──
# yield vs return：暂停 vs 结束
# 生成器表达式：(x for x in range(10)) vs 列表推导式 [x for x in range(10)]
# 内存对比：生成器惰性求值，不一次性创建所有元素
# send()、close()、throw()（了解即可）

# ── 3. yield from ──
# 委托给子生成器
# 和 for 循环 + yield 的区别

# ── 4. itertools ──
# count、cycle、repeat（无限迭代）
# chain、islice、takewhile/dropwhile
# product、permutations、combinations（排列组合）
# groupby

# ── 5. 实战场景 ──
# 逐行读取大文件（避免一次性加载内存）
# 数据流管道（生成器串联处理）
# 斐波那契生成器

# ── 6. 练习 ──
# 写一个生成器，yield 斐波那契数列前 n 个
# 用生成器逐行过滤一个大日志文件（只保留含 ERROR 的行）
