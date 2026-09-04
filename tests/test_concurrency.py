"""并发安全回归测试。

按钮连点会让两次操作并发跑进同一段「读 → 判断 → 写」，物品和灵石被复制。
每个用例用 asyncio.gather 同时发起多次，断言成功次数和最终账面守恒。
"""

import asyncio

import pytest

from tests.conftest import make_player


async def _seed(db, *players, inventory=None):
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        for uid, stones in players:
            s.add(make_player(D, uid, stones))
        for (uid, item), qty in (inventory or {}).items():
            s.add(D.Inventory(discord_id=uid, item_id=item, quantity=qty))
        await s.commit()


async def _stones(db, uid) -> int:
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        return (await s.get(D.Player, uid)).spirit_stones


async def _qty(db, uid, item) -> int:
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        row = await s.get(D.Inventory, (uid, item))
        return row.quantity if row else 0


# --------------------------------------------------------------------------
# 背包
# --------------------------------------------------------------------------

async def test_并发消耗同一件物品只成功一次(db):
    """连点使用最后一颗丹药：只能有一次成功，且不会扣成负数。"""
    await _seed(db, ("u", 0), inventory={("u", "pill"): 1})

    results = await asyncio.gather(*[
        db["inventory"].remove_item("u", "pill", 1) for _ in range(8)
    ])

    assert sum(results) == 1, f"8 次并发消耗应只成功 1 次，实际 {sum(results)} 次"
    assert await _qty(db, "u", "pill") == 0


async def test_并发消耗数量不足时不扣减(db):
    await _seed(db, ("u", 0), inventory={("u", "herb"): 3})

    results = await asyncio.gather(*[
        db["inventory"].remove_item("u", "herb", 2) for _ in range(5)
    ])

    assert sum(results) == 1          # 3 个只够扣一次 2
    assert await _qty(db, "u", "herb") == 1


# --------------------------------------------------------------------------
# 交易坊
# --------------------------------------------------------------------------

async def test_两人并发购买同一挂单只成交一次(db):
    """核心回归：修复前两个买家都会拿到物品，卖家收两次钱。"""
    await _seed(db, ("buyerA", 10_000), ("buyerB", 10_000), ("seller", 0),
                inventory={("seller", "herb"): 1})
    listing = await db["market"].list_item("seller", "herb", 1, 1_000)
    assert listing["ok"]

    results = await asyncio.gather(
        db["market"].buy_listing("buyerA", listing["listing_id"]),
        db["market"].buy_listing("buyerB", listing["listing_id"]),
    )

    succeeded = [r for r in results if r["ok"]]
    assert len(succeeded) == 1, "同一件商品不能被卖出两次"

    # 物品守恒：全世界只有 1 个 herb
    total_items = await _qty(db, "buyerA", "herb") + await _qty(db, "buyerB", "herb")
    assert total_items == 1

    # 灵石守恒：买家总共只付了一次钱
    spent = 20_000 - (await _stones(db, "buyerA") + await _stones(db, "buyerB"))
    assert spent == 1_000
    # 卖家只收一次货款（扣 8% 手续费）
    assert await _stones(db, "seller") == 1_000 - max(1, int(1_000 * 0.08))


async def test_灵石不足时购买不会占掉挂单(db):
    """买不起时挂单必须回到 active，否则商品会凭空消失。"""
    await _seed(db, ("poor", 10), ("seller", 0), inventory={("seller", "herb"): 1})
    listing = await db["market"].list_item("seller", "herb", 1, 1_000)

    result = await db["market"].buy_listing("poor", listing["listing_id"])

    assert not result["ok"]
    active = await db["market"].get_active_listings()
    assert [l["listing_id"] for l in active] == [listing["listing_id"]]


async def test_并发上架同一批物品只成功一次(db):
    await _seed(db, ("u", 0), inventory={("u", "herb"): 1})

    results = await asyncio.gather(*[
        db["market"].list_item("u", "herb", 1, 500) for _ in range(4)
    ])

    assert sum(1 for r in results if r["ok"]) == 1
    assert await _qty(db, "u", "herb") == 0


# --------------------------------------------------------------------------
# 每日配额
# --------------------------------------------------------------------------

async def test_并发赌博不会超出每日上限(db):
    limit = db["gamble"].DAILY_LIMIT
    await _seed(db, ("u", 1_000_000))

    results = await asyncio.gather(*[
        db["gamble"].do_gamble("u", 100) for _ in range(limit + 5)
    ])

    assert sum(1 for r in results if r["ok"]) == limit


async def test_并发转盘不会超出每日上限(db):
    limit = db["roulette"].DAILY_LIMIT
    await _seed(db, ("u", 1_000_000))

    results = await asyncio.gather(*[
        db["roulette"].do_roulette("u") for _ in range(limit + 5)
    ])

    assert sum(1 for r in results if r["ok"]) == limit


async def test_每日配额跨日归零(db):
    """回归 utils/jobs.py 曾有的 bug：计数只加不清，次日起每天只剩一次。"""
    import time
    D, A = db["db_async"], db["atomic"]
    await _seed(db, ("u", 0))
    now = time.time()

    async with D.AsyncSessionLocal() as s:
        today = [await A.claim_daily_quota(
            s, "u", D.Player.gamble_daily_count, D.Player.gamble_daily_reset, 3, now=now
        ) for _ in range(4)]
        await s.commit()
    assert today == [1, 2, 3, None]

    async with D.AsyncSessionLocal() as s:
        tomorrow = [await A.claim_daily_quota(
            s, "u", D.Player.gamble_daily_count, D.Player.gamble_daily_reset, 3,
            now=now + 86_400,
        ) for _ in range(4)]
        await s.commit()
    assert tomorrow == [1, 2, 3, None], "跨日后必须重新从 1 开始计数"


async def test_并发签到只发一次奖励(db):
    await _seed(db, ("u", 0))

    results = await asyncio.gather(*[db["checkin"].do_checkin("u") for _ in range(6)])

    assert sum(1 for r in results if r["ok"]) == 1


# --------------------------------------------------------------------------
# 钱庄
# --------------------------------------------------------------------------

async def test_并发存款不会凭空吞掉灵石(db):
    """并发存入时余额若互相覆盖，玩家会白扣灵石。守恒必须成立。"""
    await _seed(db, ("u", 10_000))

    results = await asyncio.gather(*[
        db["bank"].deposit_demand("u", 1_000) for _ in range(5)
    ])

    ok_count = sum(1 for r in results if r["ok"])
    account = await db["bank"].get_bank_account("u")
    assert await _stones(db, "u") == 10_000 - ok_count * 1_000
    assert account["demand_balance"] == ok_count * 1_000


async def test_并发取出定期存款只结算一次(db):
    await _seed(db, ("u", 100_000))
    dep = await db["bank"].deposit_term("u", 20_000, 10)
    assert dep["ok"]
    before = await _stones(db, "u")

    results = await asyncio.gather(*[
        db["bank"].withdraw_term("u", dep["deposit_id"]) for _ in range(4)
    ])

    assert sum(1 for r in results if r["ok"]) == 1
    assert await _stones(db, "u") == before + 20_000   # 未到期只退本金


async def test_并发转账不会超额转出(db):
    await _seed(db, ("sender", 10_000), ("r1", 0), ("r2", 0))

    results = await asyncio.gather(
        db["bank"].transfer("sender", "r1", 9_000),
        db["bank"].transfer("sender", "r2", 9_000),
    )

    assert sum(1 for r in results if r["ok"]) == 1
    assert await _stones(db, "sender") >= 0


# --------------------------------------------------------------------------
# 成组扣减（炼丹配方 / 锻造材料）
# --------------------------------------------------------------------------

async def test_成组扣材料时任一不足则整组不扣(db):
    """炼丹一次要扣好几味药，缺一味就不能只扣掉前面几味。"""
    from utils.views.alchemy import _consume_all

    await _seed(db, ("u", 0), inventory={("u", "甲"): 5, ("u", "乙"): 1})

    ok = await _consume_all("u", {"甲": 2, "乙": 3})   # 乙 不够

    assert ok is False
    assert await _qty(db, "u", "甲") == 5, "整组失败时不能扣掉已经扣过的那味药"
    assert await _qty(db, "u", "乙") == 1


async def test_成组扣材料并发只成功一次(db):
    from utils.views.alchemy import _consume_all

    await _seed(db, ("u", 0), inventory={("u", "甲"): 2, ("u", "乙"): 2})

    results = await asyncio.gather(*[
        _consume_all("u", {"甲": 2, "乙": 2}) for _ in range(4)
    ])

    assert sum(results) == 1
    assert await _qty(db, "u", "甲") == 0
    assert await _qty(db, "u", "乙") == 0


async def test_原子增减支持多个字段(db):
    D, A = db["db_async"], db["atomic"]
    await _seed(db, ("u", 100))

    async with D.AsyncSessionLocal() as s:
        await A.increment_player(s, "u", spirit_stones=50, reputation=3, cultivation=10)
        await s.commit()
        player = await s.get(D.Player, "u")

    assert (player.spirit_stones, player.reputation, player.cultivation) == (150, 3, 10)


async def test_原子增减并发不丢更新(db):
    """任务奖励发放：10 次并发发放，总额必须精确累加。"""
    D, A = db["db_async"], db["atomic"]
    await _seed(db, ("u", 0))

    async def give():
        async with D.AsyncSessionLocal() as s:
            await A.increment_player(s, "u", spirit_stones=10)
            await s.commit()

    await asyncio.gather(*[give() for _ in range(10)])

    assert await _stones(db, "u") == 100


async def test_原子增减拒绝不存在的字段(db):
    D, A = db["db_async"], db["atomic"]
    await _seed(db, ("u", 0))

    async with D.AsyncSessionLocal() as s:
        with pytest.raises(AttributeError):
            await A.increment_player(s, "u", 不存在的字段=1)
