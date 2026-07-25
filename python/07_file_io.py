# ============================================================
# Python 复习 — 文件 IO / 序列化
# ============================================================

# ── 1. 文件读写基础 ──
# open 模式：r/w/a/x、rb/wb（二进制）、r+/w+（读写）
# encoding 参数（中文必须 utf-8）
# read / readline / readlines 的区别
# with open 自动关闭

# ── 2. 路径操作 ──
# os.path：join、exists、basename、dirname、splitext
# pathlib（推荐）：Path 对象、/ 运算符拼接、.read_text() .write_text()
# 遍历目录：os.walk、Path.glob、Path.rglob

# ── 3. CSV ──
# csv.reader / csv.writer
# csv.DictReader / csv.DictWriter（以字典方式操作）
# 分隔符参数 delimiter

# ── 4. JSON ──
# json.dumps / json.loads（字符串 ↔ 对象）
# json.dump / json.load（文件 ↔ 对象）
# indent、ensure_ascii=False（中文不转义）
# 自定义 JSONEncoder 处理 datetime/Decimal 等特殊类型

# ── 5. pickle ──
# 序列化 Python 对象到二进制
# 安全问题：永远不要 unpickle 不可信数据

# ── 6. 练习 ──
# 读 CSV 文件 → 处理数据 → 写 JSON 文件
# 用 pathlib 遍历目录下所有 .py 文件并统计行数
