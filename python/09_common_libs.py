# ============================================================
# Python 复习 — re / datetime / collections / typing
# ============================================================

# ── 1. re（正则表达式）──
# re.search（找第一个）、re.match（行首匹配）
# re.findall（找所有）、re.finditer（迭代器）
# re.sub（替换）
# 分组 ()：group(1) 提取、命名分组 (?P<name>...)
# 常用模式：\d \w \s . * + ? ^ $ [abc] \b
# compile 预编译（重复使用时更快）

# ── 2. datetime ──
# datetime.now()、strftime（datetime → string）、strptime（string → datetime）
# timedelta（时间加减）
# dateutil.parser（智能解析各种日期格式）
# 时区：pytz / zoneinfo（Python 3.9+）

# ── 3. collections ──
# defaultdict（带默认值的字典）
# Counter（计数器，统计频次、most_common）
# OrderedDict（保持插入顺序，3.7+ dict 已默认有序）
# deque（双端队列，两端 O(1) 操作）
# namedtuple（有名字的元组，像轻量类）

# ── 4. typing ──
# List、Dict、Tuple、Set、Optional、Union
# Callable（标注函数类型）
# TypeVar（泛型）
# Literal（限定值范围，3.8+）
# 运行时检查 vs 静态分析（mypy）

# ── 5. random ──
# random()、randint、choice、shuffle、sample
# seed 固定随机种子（可复现）

# ── 6. 练习 ──
# 用 re 从一段日志中提取所有 IP 地址和日期时间
# 用 Counter 统计一篇文章的词频 Top-10
