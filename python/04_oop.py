# ============================================================
# Python 复习 — 面向对象
# ============================================================

# ── 1. 类与对象 ──
# class 定义、__init__ 构造、self 的含义
# 实例属性 vs 类属性
# 实例方法、类方法 @classmethod、静态方法 @staticmethod

# ── 2. 继承 ──
# 单继承、多继承、MRO（方法解析顺序）__mro__ / mro()
# super() 调用父类方法
# isinstance、issubclass

# ── 3. 魔术方法 ──
# __str__ vs __repr__：用户友好 vs 开发者调试
# __eq__、__lt__、__hash__（实现后可排序/去重）
# __len__、__getitem__、__setitem__（实现容器类）
# __enter__ / __exit__（上下文管理器）
# __call__（让实例可调用）

# ── 4. 属性控制 ──
# @property 把方法变属性
# @xxx.setter、@xxx.deleter
# __slots__ 限制实例属性、节省内存

# ── 5. 抽象类 ──
# ABC、@abstractmethod
# 和接口的区别

# ── 6. 练习 ──
# 写一个 Vector 类，实现 __add__、__mul__、__eq__、__repr__
# 写一个 FileManager 上下文管理器类，自动关闭文件
