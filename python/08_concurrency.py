# ============================================================
# Python 复习 — 并发：线程 / 进程 / 协程
# ============================================================

# ── 1. GIL（全局解释器锁）──
# 是什么：CPython 同一时刻只有一个线程执行 Python 字节码
# 影响：多线程对 CPU 密集型无效，对 IO 密集型有效
# 绕过：多进程（multiprocessing）、C 扩展、其他解释器（Jython）

# ── 2. threading ──
# Thread 创建和 start
# join 等待线程结束
# Lock / RLock 互斥锁
# 线程池：ThreadPoolExecutor（concurrent.futures）
# 适用场景：网络请求、文件读写

# ── 3. multiprocessing ──
# Process 创建
# Pool 进程池
# Queue、Pipe 进程间通信
# 适用场景：CPU 密集型计算

# ── 4. 线程 vs 进程 选择 ──
# IO 密集 → 线程（GIL 在 IO 时释放）
# CPU 密集 → 进程（绕过 GIL）
# 两者都不满意 → asyncio

# ── 5. asyncio ──
# async def / await
# 事件循环：asyncio.run()
# 并发执行：asyncio.gather、asyncio.create_task
# aiohttp（异步 HTTP 客户端）
# 适用场景：高并发网络服务、WebSocket、API 调用

# ── 6. 练习 ──
# 用 ThreadPoolExecutor 并发下载 3 个 URL
# 用 asyncio + aiohttp 做同样的事
# 对比两种方式的速度差异
