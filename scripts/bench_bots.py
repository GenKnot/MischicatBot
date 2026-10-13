"""机器人规模压测：在临时库里放 N 个机器人，量『生成』和『一次每日结算』要多久（U1·江湖百态 P0）。

    .venv/bin/python scripts/bench_bots.py 2000
    .venv/bin/python scripts/bench_bots.py 5000 --no-settle

用的是临时数据库（DB_PATH 指到临时目录），不会碰 game.db。
"""

import asyncio
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


async def main(n: int, settle: bool) -> None:
    from utils import bot_settle, bot_world
    from utils.db_async import Base, engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    t0 = time.time()
    left, made = n, 0
    while left > 0:
        k = min(left, bot_world.MAX_PER_BATCH)
        res = await bot_world.generate_bots(k)
        if not res["ok"]:
            print("生成失败：", res["reason"])
            return
        made, left = made + len(res["created"]), left - k
    gen = time.time() - t0
    print(f"生成 {made} 个：{gen:.1f} 秒（{gen / made * 1000:.1f} 毫秒 / 个）")
    from collections import Counter
    from sqlalchemy import select
    from utils.db_async import AsyncSessionLocal, BotTie
    async with AsyncSessionLocal() as session:
        kinds = Counter(k for (k,) in (await session.execute(select(BotTie.kind))).all())
    print(f"初始关系 {sum(kinds.values())} 条（平均每人 {2 * sum(kinds.values()) / made:.1f} 条）：{dict(kinds)}")
    if settle:
        t1 = time.time()
        summary = await bot_settle.run_settlement(force=True)
        dt = time.time() - t1
        print(f"一次每日结算：{dt:.1f} 秒（{dt / made * 1000:.1f} 毫秒 / 个）；摘要：{dict(list(summary.items())[:6])}")
        print(f"每日社交：{summary.get('social')}")


if __name__ == "__main__":
    if not os.environ.get("DB_PATH"):
        os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(prefix="mischicat-bench-"), "bench.db")
    count = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else 2000
    asyncio.run(main(count, "--no-settle" not in sys.argv))
