# ============================================================
# Python 复习 — 异常处理 / 上下文管理器
# ============================================================

# ── 1. 异常基础 ──
# try / except / else / finally 的执行顺序
# except 捕获多个异常类型、捕获所有 Exception
# 获取异常信息：as e
# raise 重新抛出、raise from 异常链
# 常见内置异常：ValueError、TypeError、KeyError、IndexError、FileNotFoundError

# ── 2. 自定义异常 ──
# 继承 Exception
# 添加自定义属性和 __str__

# ── 3. 上下文管理器 ──
# with 语句的作用：自动调用 __enter__ / __exit__
# __exit__ 的三个参数：exc_type, exc_val, exc_tb
# 异常在 __exit__ 中返回 True 则吞掉异常

# ── 4. contextlib ──
# @contextmanager 装饰器 + yield（比写 __enter__/__exit__ 简单）
# yield 前 = __enter__，yield 后 = __exit__
# 常见用法：临时切换目录、计时器、数据库连接

# ── 5. 实战 ──
# 打开文件的标准写法：with open
# 数据库连接、网络请求的自动关闭
# 嵌套上下文管理器

# ── 6. 练习 ──
# 写一个 @contextmanager 计时器，进入时 start=time.time()，退出时打印耗时
# 自定义异常 InvalidAgeError，年龄 < 0 或 > 150 时抛出
