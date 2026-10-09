"""后台任务的两个小工具：循环体保护、发了就不管的任务。

两者针对同一类问题 —— **一次意外就让某件事永远停了，而且没人知道**：

- `discord.ext.tasks` 的循环体里抛出非网络类异常，循环会**永久停止**（`is_running()` 变 False、
  `failed()` 变 True），要重启 bot 才恢复。闭关 / 采集 / 任务的结算、灵雨与拍卖的调度全靠这样的循环，
  一次数据库抖动就让所有人的结算停摆（ISSUES.md B17、B24）。
- `asyncio.create_task(...)` 发出去就不管：异常只会在任务被回收时打一条
  "Task exception was never retrieved"，而且**事件循环只持有任务的弱引用**，
  没人保存引用的话任务可能在执行中途被回收（B26）。
"""

import asyncio
import functools
import logging

_background_tasks: set[asyncio.Task] = set()


def loop_guard(log: logging.Logger, what: str):
    """给 `@tasks.loop` 的循环体加整体保护：这一轮出错记 ERROR，下一轮照常再来。

        @tasks.loop(minutes=1)
        @loop_guard(log, "闭关结算")
        async def _notifier(self): ...

    注意它只兜**整轮**。循环体里处理多行数据时，还要给**每一行**单独 try/except ——
    否则某一行的数据稳定出错，循环每分钟都卡在同一行，排在后面的行永远轮不到。
    """
    def decorate(fn):
        @functools.wraps(fn)
        async def wrapper(*args, **kwargs):
            try:
                await fn(*args, **kwargs)
            except Exception:
                log.exception("%s 本轮出错，下一轮重试", what)
        return wrapper
    return decorate


def spawn(coro, *, log: logging.Logger, name: str) -> asyncio.Task:
    """发出一个后台任务：保存引用（防止被回收）、异常记 ERROR。返回任务，需要时可以取消。"""
    task = asyncio.get_running_loop().create_task(coro, name=name)
    _background_tasks.add(task)

    def _done(t: asyncio.Task):
        _background_tasks.discard(t)
        if t.cancelled():
            return
        exc = t.exception()
        if exc is not None:
            log.error("后台任务 %s 出错", name, exc_info=exc)
    task.add_done_callback(_done)
    return task
