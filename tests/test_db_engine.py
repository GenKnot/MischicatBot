"""数据库引擎行为测试。

守住一条容易被"优化"掉的约定：别给每个事务加 BEGIN IMMEDIATE。
项目里十来处嵌套 session 会当场自锁，卡满 busy_timeout 后抛 database is locked。
"""

import time

from sqlalchemy import select

from utils import db_async, inventory


async def test_启用了_wal(db):
    """WAL 让读不阻塞写，是减少 'database is locked' 的关键。"""
    async with db_async.engine.connect() as conn:
        mode = (await conn.exec_driver_sql("PRAGMA journal_mode")).scalar()
        busy = (await conn.exec_driver_sql("PRAGMA busy_timeout")).scalar()

    assert mode == "wal"
    assert busy == db_async.SQLITE_BUSY_TIMEOUT_MS


async def test_嵌套_session_不会自锁(db):
    """外层事务开着时，内层新开 session 写入必须能立刻完成。

    这个用例失败通常意味着有人给引擎加了全局 BEGIN IMMEDIATE。
    """
    started = time.monotonic()
    async with db_async.AsyncSessionLocal() as outer:
        await outer.execute(select(db_async.Inventory))   # 外层开启事务
        await inventory.add_item("u", "pill", 1)          # 内层另开 session
        await outer.commit()
    elapsed = time.monotonic() - started

    assert elapsed < 1.0, (
        f"嵌套 session 耗时 {elapsed:.1f}s —— 说明在等写锁，"
        "检查是否给引擎加了全局 BEGIN IMMEDIATE"
    )
