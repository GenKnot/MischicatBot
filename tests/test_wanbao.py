"""万宝阁拍卖会功能测试。

改过三处：竞价改乐观抢占、寄售的物品和手续费同事务原子扣、流拍罚金不扣成负数。
顺带守住 server_default —— 建场走的是没列全字段的裸 INSERT，新库上撞过 NOT NULL。
"""

import asyncio
import json

import pytest

from tests.conftest import make_player
from utils.events.public import wanbao
from utils.events.public.wanbao import (AUCTION_COMMISSION, LISTING_FEE,
                                        MAX_PLAYER_LOTS, can_list_item,
                                        get_or_create_auction, list_item,
                                        place_bid, settle_lot)


@pytest.fixture
async def auction(db):
    """建一场拍卖会并置为 active，返回 auction dict。"""
    a = await get_or_create_auction("2026-09-03")
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        from sqlalchemy import text
        await s.execute(
            text("UPDATE wanbao_auctions SET status='active', current_lot=0 "
                 "WHERE auction_id=:aid"), {"aid": a["auction_id"]})
        await s.execute(
            text("UPDATE wanbao_lots SET status='active' "
                 "WHERE auction_id=:aid AND lot_index=0"), {"aid": a["auction_id"]})
        await s.commit()
    return a


@pytest.fixture
async def bidders(db):
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        for uid in ("a", "b"):
            s.add(make_player(D, uid, stones=100_000))
        await s.commit()
    return ["a", "b"]


async def _stones(db, uid):
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        return (await s.get(D.Player, uid)).spirit_stones


async def _lot(db, auction_id, index=0):
    D = db["db_async"]
    from sqlalchemy import text
    async with D.AsyncSessionLocal() as s:
        row = (await s.execute(
            text("SELECT * FROM wanbao_lots WHERE auction_id=:aid AND lot_index=:i"),
            {"aid": auction_id, "i": index})).fetchone()
    return dict(row._mapping) if row else None


# --- 建场（守住 server_default）----------------------------------------------

async def test_全新库上能创建拍卖会(db):
    """回归 CONVENTIONS #3：ORM 建的表若缺 SQL 默认值，这里会撞 NOT NULL。"""
    a = await get_or_create_auction("2026-09-03")

    assert a["auction_id"]
    assert a["status"] == "pending"
    assert a["current_lot"] == 0        # 来自 server_default
    assert a["data"] == "{}"            # 来自 server_default


async def test_同一天重复创建返回同一场(db):
    first = await get_or_create_auction("2026-09-03")
    second = await get_or_create_auction("2026-09-03")
    assert first["auction_id"] == second["auction_id"]


async def test_建场会生成官方拍品(db):
    a = await get_or_create_auction("2026-09-03")
    lots = await wanbao.get_lots(a["auction_id"])
    assert len(lots) > 0
    assert all(l["seller_id"] is None for l in lots), "官方拍品不应有卖家"


# --- 寄售 --------------------------------------------------------------------

async def test_寄售扣物品与手续费(db, auction):
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        s.add(make_player(D, "seller", stones=1000))
        s.add(D.Inventory(discord_id="seller", item_id="灵芝草", quantity=5))
        await s.commit()

    ok, msg = await list_item(auction["auction_id"], "seller", "灵芝草", 2, 500)

    assert ok, msg
    assert await _stones(db, "seller") == 1000 - LISTING_FEE
    assert (await db["inventory"].get_inventory("seller")).get("灵芝草") == 3


async def test_物品不足时不扣手续费(db, auction):
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        s.add(make_player(D, "seller", stones=1000))
        s.add(D.Inventory(discord_id="seller", item_id="灵芝草", quantity=1))
        await s.commit()

    ok, msg = await list_item(auction["auction_id"], "seller", "灵芝草", 5, 500)

    assert not ok
    assert await _stones(db, "seller") == 1000, "失败时手续费不该被扣走"
    assert (await db["inventory"].get_inventory("seller")).get("灵芝草") == 1


async def test_灵石不足时不扣物品(db, auction):
    """回归：原先两条裸 UPDATE 都没有条件，能把库存和灵石都扣成负数。"""
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        s.add(make_player(D, "poor", stones=10))
        s.add(D.Inventory(discord_id="poor", item_id="灵芝草", quantity=5))
        await s.commit()

    ok, msg = await list_item(auction["auction_id"], "poor", "灵芝草", 2, 500)

    assert not ok
    assert await _stones(db, "poor") == 10, "灵石不能被扣成负数"
    assert (await db["inventory"].get_inventory("poor")).get("灵芝草") == 5, "失败时物品要退回"


async def test_每人寄售数量有上限(db, auction):
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        s.add(make_player(D, "seller", stones=100_000))
        s.add(D.Inventory(discord_id="seller", item_id="灵芝草", quantity=99))
        await s.commit()

    for _ in range(MAX_PLAYER_LOTS):
        ok, _ = await list_item(auction["auction_id"], "seller", "灵芝草", 1, 500)
        assert ok
    ok, msg = await can_list_item("seller", auction["auction_id"])
    assert not ok and "最多上架" in msg


# --- 竞价 --------------------------------------------------------------------

async def test_出价成功记录最高价(db, auction, bidders):
    lot = await _lot(db, auction["auction_id"])
    ok, msg = await place_bid(auction["auction_id"], "a", lot["start_price"])

    assert ok, msg
    after = await _lot(db, auction["auction_id"])
    assert after["current_bid"] == lot["start_price"]
    assert after["bidder_id"] == "a"


async def test_低于最低价被拒(db, auction, bidders):
    lot = await _lot(db, auction["auction_id"])
    ok, msg = await place_bid(auction["auction_id"], "a", lot["start_price"] - 1)

    assert not ok and "不得低于" in msg


async def test_灵石不足时不能出价(db, auction, db_poor_bidder):
    lot = await _lot(db, auction["auction_id"])
    ok, msg = await place_bid(auction["auction_id"], "poor", lot["start_price"])
    assert not ok and "灵石不足" in msg


@pytest.fixture
async def db_poor_bidder(db):
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        s.add(make_player(D, "poor", stones=1))
        await s.commit()


async def test_抢占最高价时读到旧值会失败(db, auction, bidders):
    """乐观并发控制的核心性质：拿着过期的 current_bid 去抢，必须失败。

    这条直接测 `claim_highest_bid`，而不是靠 `asyncio.gather` 去撞时序 ——
    走整条 place_bid 路径时两个调用往往实际是串行的，第二个会先被
    min_bid 检查挡下，于是即便去掉原子条件测试也照样通过（曾经如此）。
    """
    D = db["db_async"]
    lot = await _lot(db, auction["auction_id"])
    lot_id, base = lot["lot_id"], lot["current_bid"] or 0

    async with D.AsyncSessionLocal() as s:
        # a 先抢到，current_bid 变成 base+100
        assert await wanbao.claim_highest_bid(s, lot_id, base, base + 100, "a")
        await s.commit()

    async with D.AsyncSessionLocal() as s:
        # b 手里还是抢占前读到的旧值 —— 必须被拒
        assert not await wanbao.claim_highest_bid(s, lot_id, base, base + 200, "b")
        await s.commit()

    after = await _lot(db, auction["auction_id"])
    assert after["bidder_id"] == "a", "过期的抢占不能覆盖已有的最高价"
    assert after["current_bid"] == base + 100


async def test_拿着最新值可以正常抬价(db, auction, bidders):
    """反面用例：确认上一条不是因为"总是失败"才通过的。"""
    D = db["db_async"]
    lot = await _lot(db, auction["auction_id"])
    lot_id, base = lot["lot_id"], lot["current_bid"] or 0

    async with D.AsyncSessionLocal() as s:
        assert await wanbao.claim_highest_bid(s, lot_id, base, base + 100, "a")
        await s.commit()
    async with D.AsyncSessionLocal() as s:
        assert await wanbao.claim_highest_bid(s, lot_id, base + 100, base + 200, "b")
        await s.commit()

    after = await _lot(db, auction["auction_id"])
    assert after["bidder_id"] == "b" and after["current_bid"] == base + 200


async def test_两人同时出价最终只有一个最高价(db, auction, bidders):
    """端到端补充：不论调度如何，账面上只能有一个最高价持有者。"""
    lot = await _lot(db, auction["auction_id"])
    price = lot["start_price"] + 100

    results = await asyncio.gather(
        place_bid(auction["auction_id"], "a", price),
        place_bid(auction["auction_id"], "b", price),
    )

    assert sum(ok for ok, _ in results) == 1
    after = await _lot(db, auction["auction_id"])
    assert after["bidder_id"] in ("a", "b")


async def test_不能对自己的拍品出价(db, auction):
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        s.add(make_player(D, "seller", stones=100_000))
        s.add(D.Inventory(discord_id="seller", item_id="灵芝草", quantity=5))
        await s.commit()
    await list_item(auction["auction_id"], "seller", "灵芝草", 1, 500)

    # 把刚上架的那件设为当前拍品
    from sqlalchemy import text
    D2 = db["db_async"]
    async with D2.AsyncSessionLocal() as s:
        row = (await s.execute(
            text("SELECT lot_index FROM wanbao_lots WHERE seller_id='seller'"))).fetchone()
        await s.execute(text("UPDATE wanbao_lots SET status='pending' WHERE lot_index=0 AND auction_id=:a"),
                        {"a": auction["auction_id"]})
        await s.execute(text("UPDATE wanbao_lots SET status='active' WHERE seller_id='seller'"))
        await s.execute(text("UPDATE wanbao_auctions SET current_lot=:i WHERE auction_id=:a"),
                        {"i": row[0], "a": auction["auction_id"]})
        await s.commit()

    ok, msg = await place_bid(auction["auction_id"], "seller", 99999)
    assert not ok and "自己" in msg


# --- 结算 --------------------------------------------------------------------

async def test_成交后买家付款卖家收款(db, auction, bidders):
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        s.add(make_player(D, "seller", stones=100_000))
        s.add(D.Inventory(discord_id="seller", item_id="灵芝草", quantity=5))
        await s.commit()
    await list_item(auction["auction_id"], "seller", "灵芝草", 1, 500)
    seller_before = await _stones(db, "seller")

    from sqlalchemy import text
    async with D.AsyncSessionLocal() as s:
        await s.execute(text("UPDATE wanbao_lots SET current_bid=1000, bidder_id='a', "
                             "status='active' WHERE seller_id='seller'"))
        await s.commit()
        row = (await s.execute(text("SELECT * FROM wanbao_lots WHERE seller_id='seller'"))).fetchone()
    lot = dict(row._mapping)

    buyer_before = await _stones(db, "a")
    result = await settle_lot(lot)

    commission = int(1000 * AUCTION_COMMISSION)
    assert result["winner_id"] == "a"
    assert result["final_price"] == 1000
    assert result["seller_income"] == 1000 - commission
    assert await _stones(db, "a") == buyer_before - 1000
    assert await _stones(db, "seller") == seller_before + 1000 - commission
    assert (await db["inventory"].get_inventory("a")).get("灵芝草") == 1


async def test_流拍时罚金不会把灵石扣成负数(db, auction):
    """回归：原先是无条件减，卖家灵石会变成负数。"""
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        s.add(make_player(D, "broke", stones=0))
        await s.commit()

    lot = {"lot_id": "L1", "auction_id": auction["auction_id"], "bidder_id": None,
           "seller_id": "broke", "item_name": "灵芝草", "quantity": 1,
           "item_type": "item", "current_bid": 0, "eq_data": None}
    await settle_lot(lot)

    assert await _stones(db, "broke") == 0, "灵石不能被罚成负数"


async def test_扣手续费失败时物品会退回(db, auction, monkeypatch):
    """覆盖原子扣的回滚分支。

    直接用"灵石不够的玩家"测不到这里 —— `list_item` 开头有一个独立
    session 的预检查，会先把他拦下。这里改为让扣款本身失败，
    确保已经扣掉的物品被回滚。
    """
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        s.add(make_player(D, "seller", stones=100_000))
        s.add(D.Inventory(discord_id="seller", item_id="灵芝草", quantity=5))
        await s.commit()

    async def _always_fail(session, uid, amount):
        return False
    monkeypatch.setattr(wanbao, "spend_stones", _always_fail)

    ok, msg = await list_item(auction["auction_id"], "seller", "灵芝草", 2, 500)

    assert not ok
    inventory = await db["inventory"].get_inventory("seller")
    assert inventory.get("灵芝草") == 5, "扣款失败时物品必须原样退回"
