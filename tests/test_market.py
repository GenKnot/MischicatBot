"""交易坊逻辑（utils/market.py）。

B35 —— `delist`（下架 / 领回过期商品）先读到 active、再退还物品、最后才把状态改成 delisted，没有原子认领：
  · 同一件商品被并发下架两次（连点），物品退两份；
  · 下架与别人购买同时发生：买家付钱拿到货，卖家也把货退回了背包，货和钱都复制了。
B36 —— 交易坊只在 `MARKET_CITIES` 营业，但只有城市菜单入口检查，上架 / 购买的逻辑层不查，
  交易坊面板留在聊天里，人走了照样能买卖。
"""

import asyncio
import json
import time

import pytest

from tests.conftest import make_player
from utils import market
from utils.market import (FEE_RATE, LISTING_TTL, MARKET_CITIES, MAX_LISTINGS, buy_listing, delist,
                          expire_old_listings, get_active_listings, get_expired_unclaimed, get_my_listings,
                          list_equipment, list_item)

S, B = "1001", "1002"          # 卖家、买家
HERB = "灵芝草"


async def _add(db, uid, stones=100_000, city="灵虚城"):
    D = db["db_async"]
    p = make_player(D, uid, stones=stones)
    p.name = f"道友{uid}"
    p.current_city = city
    async with D.AsyncSessionLocal() as s:
        s.add(p)
        await s.commit()


async def stones(db, uid):
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        return (await s.get(D.Player, uid)).spirit_stones


async def inv(db, uid):
    return await db["inventory"].get_inventory(uid)


async def give_eq(db, uid=S, equip_id="eq000001", equipped=False, name="青锋剑"):
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        s.add(D.Equipment(equip_id=equip_id, discord_id=uid, name=name, slot="武器", quality="稀有", tier=1,
                          tier_req=0, stats=json.dumps({"attack": 5}), flavor="寒光", equipped=equipped))
        await s.commit()


async def eq_ids(db, uid):
    return [e["equip_id"] for e in await db["equipment_db"].get_equipment_list(uid)]


@pytest.fixture
async def world(db):
    await _add(db, S)
    await _add(db, B)
    await db["inventory"].add_item(S, HERB, 10)
    return db


async def set_listing(db, listing_id, **values):
    from sqlalchemy import update
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        await s.execute(update(D.MarketListing).where(D.MarketListing.listing_id == listing_id).values(**values))
        await s.commit()


async def status(db, listing_id):
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        return (await s.get(D.MarketListing, listing_id)).status


# --- 上架物品 -----------------------------------------------------------------

async def test_上架物品_成功_背包扣除_生成挂单(world):
    r = await list_item(S, HERB, 4, 500)
    assert r["ok"] and (await inv(world, S))[HERB] == 6
    [lst] = await get_active_listings()
    assert (lst["item_name"], lst["quantity"], lst["price"], lst["seller_id"], lst["item_type"]) == (HERB, 4, 500, S, "item")
    assert lst["expires_at"] - lst["listed_at"] == pytest.approx(LISTING_TTL)


@pytest.mark.parametrize("qty,price,reason", [(0, 100, "数量"), (-1, 100, "数量"), (1, 0, "价格"), (1, -5, "价格")])
async def test_上架物品_数量与价格必须为正(world, qty, price, reason):
    r = await list_item(S, HERB, qty, price)
    assert not r["ok"] and reason in r["reason"] and (await inv(world, S))[HERB] == 10


async def test_上架物品_背包不足_不建挂单(world):
    r = await list_item(S, HERB, 11, 100)
    assert r["reason"] == "背包物品不足。" and await get_active_listings() == []
    assert (await list_item(S, "不存在的东西", 1, 100))["reason"] == "背包物品不足。"


async def test_上架物品_名字取自物品表_未知物品用ID(world):
    await world["inventory"].add_item(S, "mystery", 1)
    await list_item(S, "mystery", 1, 10)
    assert [x["item_name"] for x in await get_active_listings()] == ["mystery"]


async def test_上架物品_同时在售上限(world):
    for _ in range(MAX_LISTINGS):
        assert (await list_item(S, HERB, 1, 100))["ok"]
    r = await list_item(S, HERB, 1, 100)
    assert "最多同时上架" in r["reason"] and (await inv(world, S))[HERB] == 10 - MAX_LISTINGS


async def test_上架物品_已售出的不占名额(world):
    for _ in range(MAX_LISTINGS):
        r = await list_item(S, HERB, 1, 100)
    await buy_listing(B, r["listing_id"])
    assert (await list_item(S, HERB, 1, 100))["ok"]


async def test_上架物品_并发上架不会超卖背包(world):
    results = await asyncio.gather(*[list_item(S, HERB, 6, 100) for _ in range(4)])
    assert len([r for r in results if r["ok"]]) == 1 and (await inv(world, S))[HERB] == 4


# --- 上架装备 -----------------------------------------------------------------

async def test_上架装备_成功_装备从背包移走(world):
    await give_eq(world)
    r = await list_equipment(S, "eq000001", 900)
    assert r["ok"] and await eq_ids(world, S) == []
    [lst] = await get_active_listings("equipment")
    snap = json.loads(lst["eq_data"])
    assert snap["name"] == "青锋剑" and snap["stats"] == {"attack": 5} and lst["quantity"] == 1


async def test_上架装备_各种拒绝(world):
    assert (await list_equipment(S, "nope", 10))["reason"] == "装备不存在。"
    await give_eq(world, B, "eq000002")
    assert (await list_equipment(S, "eq000002", 10))["reason"] == "装备不存在。"               # 别人的
    await give_eq(world, S, "eq000003", equipped=True)
    assert "先卸下" in (await list_equipment(S, "eq000003", 10))["reason"]
    await give_eq(world, S, "eq000004")
    assert "价格" in (await list_equipment(S, "eq000004", 0))["reason"]
    assert "eq000004" in await eq_ids(world, S) and await get_active_listings() == []


async def test_上架装备_并发上架同一件只成功一次(world):
    await give_eq(world)
    results = await asyncio.gather(*[list_equipment(S, "eq000001", 100) for _ in range(4)])
    assert len([r for r in results if r["ok"]]) == 1 and len(await get_active_listings()) == 1


async def test_上架装备_同时在售上限(world):
    for i in range(MAX_LISTINGS + 1):
        await give_eq(world, S, f"eq00001{i}")
    rs = [await list_equipment(S, f"eq00001{i}", 10) for i in range(MAX_LISTINGS + 1)]
    assert [r["ok"] for r in rs] == [True] * MAX_LISTINGS + [False]


# --- 购买 ---------------------------------------------------------------------

async def test_购买物品_钱货两清_手续费被收走(world):
    lid = (await list_item(S, HERB, 4, 1000))["listing_id"]
    r = await buy_listing(B, lid)
    fee = int(1000 * FEE_RATE)
    assert r == {"ok": True, "item_name": HERB, "price": 1000, "fee": fee}
    assert await stones(world, B) == 99_000 and await stones(world, S) == 100_000 + 1000 - fee
    assert (await inv(world, B))[HERB] == 4 and await status(world, lid) == "sold"


async def test_购买_手续费至少1(world):
    lid = (await list_item(S, HERB, 1, 5))["listing_id"]
    assert (await buy_listing(B, lid))["fee"] == 1
    assert await stones(world, S) == 100_000 + 4


async def test_购买装备_装备转到买家名下(world):
    await give_eq(world)
    lid = (await list_equipment(S, "eq000001", 800))["listing_id"]
    assert (await buy_listing(B, lid))["ok"]
    assert await eq_ids(world, B) == ["eq000001"] and await eq_ids(world, S) == []
    [e] = await world["equipment_db"].get_equipment_list(B)
    assert e["name"] == "青锋剑" and e["stats"] == {"attack": 5} and e["equipped"] is False


async def test_购买_各种拒绝(world):
    assert "已下架或不存在" in (await buy_listing(B, "nope"))["reason"]
    lid = (await list_item(S, HERB, 1, 100))["listing_id"]
    assert "不能购买自己" in (await buy_listing(S, lid))["reason"]
    await set_listing(world, lid, expires_at=time.time() - 1)
    assert "已过期" in (await buy_listing(B, lid))["reason"] and await status(world, lid) == "expired"
    assert await stones(world, B) == 100_000


async def test_购买_灵石不足_整笔回滚_商品仍在售(world):
    await _add(world, "1003", stones=50)
    lid = (await list_item(S, HERB, 2, 100))["listing_id"]
    r = await buy_listing("1003", lid)
    assert "灵石不足" in r["reason"] and await status(world, lid) == "active"
    assert await stones(world, "1003") == 50 and await stones(world, S) == 100_000 and "灵芝草" not in await inv(world, "1003")


async def test_购买_并发只有一个买家成交(world):
    for u in ("1003", "1004", "1005"):
        await _add(world, u)
    lid = (await list_item(S, HERB, 3, 1000))["listing_id"]
    results = await asyncio.gather(*[buy_listing(u, lid) for u in (B, "1003", "1004", "1005")])
    assert len([r for r in results if r["ok"]]) == 1
    assert sum([await stones(world, u) for u in (S, B, "1003", "1004", "1005")]) == 500_000 - int(1000 * FEE_RATE)
    owners = [u for u in (B, "1003", "1004", "1005") if (await inv(world, u)).get(HERB)]
    assert len(owners) == 1


# --- 下架 / 领回 --------------------------------------------------------------

async def test_下架_物品退回_状态改为delisted(world):
    lid = (await list_item(S, HERB, 4, 100))["listing_id"]
    r = await delist(S, lid)
    assert r == {"ok": True, "item_name": HERB} and (await inv(world, S))[HERB] == 10
    assert await status(world, lid) == "delisted" and await get_active_listings() == []


async def test_下架装备_退回原装备(world):
    await give_eq(world)
    lid = (await list_equipment(S, "eq000001", 100))["listing_id"]
    await delist(S, lid)
    assert await eq_ids(world, S) == ["eq000001"]


async def test_下架_拒绝(world):
    lid = (await list_item(S, HERB, 1, 100))["listing_id"]
    assert "不存在" in (await delist(B, lid))["reason"]               # 别人的
    assert "不存在" in (await delist(S, "nope"))["reason"]
    await buy_listing(B, lid)
    assert "已售出" in (await delist(S, lid))["reason"]
    assert (await inv(world, S))[HERB] == 9


async def test_领回过期商品(world):
    lid = (await list_item(S, HERB, 4, 100))["listing_id"]
    await set_listing(world, lid, expires_at=time.time() - 1)
    await expire_old_listings()
    assert [x["listing_id"] for x in await get_expired_unclaimed(S)] == [lid]
    assert (await delist(S, lid))["ok"] and (await inv(world, S))[HERB] == 10
    assert await get_expired_unclaimed(S) == []


async def test_下架_重复点击只退一次(world):
    """B35。"""
    lid = (await list_item(S, HERB, 4, 100))["listing_id"]
    results = await asyncio.gather(*[delist(S, lid) for _ in range(5)])
    assert len([r for r in results if r["ok"]]) == 1
    assert (await inv(world, S))[HERB] == 10


async def test_下架装备_重复点击不重复生成(world):
    await give_eq(world)
    lid = (await list_equipment(S, "eq000001", 100))["listing_id"]
    results = await asyncio.gather(*[delist(S, lid) for _ in range(4)], return_exceptions=True)
    assert not [r for r in results if isinstance(r, BaseException)], results
    assert len([r for r in results if isinstance(r, dict) and r["ok"]]) == 1 and await eq_ids(world, S) == ["eq000001"]


async def test_下架与购买同时发生_货和钱不复制(world):
    """B35：以前买家付钱拿货，卖家同时把货退回背包 —— 货和钱都复制了。"""
    lid = (await list_item(S, HERB, 4, 1000))["listing_id"]
    d, b = await asyncio.gather(delist(S, lid), buy_listing(B, lid))
    held = (await inv(world, S)).get(HERB, 0) + (await inv(world, B)).get(HERB, 0)
    assert held == 10                                                       # 货只有一份
    assert d["ok"] != b["ok"]                                               # 要么下架成功，要么卖出，不能都成
    total = await stones(world, S) + await stones(world, B)
    assert total == 200_000 - (int(1000 * FEE_RATE) if b["ok"] else 0)


# --- 过期 / 查询 --------------------------------------------------------------

async def test_过期清理只处理到期的在售商品(world):
    a = (await list_item(S, HERB, 1, 100))["listing_id"]
    b = (await list_item(S, HERB, 1, 100))["listing_id"]
    await set_listing(world, a, expires_at=time.time() - 1)
    await expire_old_listings()
    assert await status(world, a) == "expired" and await status(world, b) == "active"


async def test_查询_按类型筛选_我的摊位含全部状态(world):
    await give_eq(world)
    await list_item(S, HERB, 1, 100)
    await list_equipment(S, "eq000001", 100)
    assert len(await get_active_listings()) == 2
    assert [x["item_type"] for x in await get_active_listings("equipment")] == ["equipment"]
    assert len(await get_my_listings(S)) == 2 and await get_my_listings(B) == []


# --- 只在交易坊所在城市营业（B36） --------------------------------------------

async def test_不在交易坊城市_上架与购买被拒(world):
    lid = (await list_item(S, HERB, 2, 100))["listing_id"]
    await give_eq(world)
    from sqlalchemy import update
    D = world["db_async"]
    async with D.AsyncSessionLocal() as s:
        await s.execute(update(D.Player).where(D.Player.discord_id.in_([S, B])).values(current_city="昆仑秘境"))
        await s.commit()
    for r in (await list_item(S, HERB, 1, 100), await list_equipment(S, "eq000001", 100), await buy_listing(B, lid)):
        assert not r["ok"] and "交易坊" in r["reason"], r
    assert await status(world, lid) == "active" and await stones(world, B) == 100_000
    assert (await inv(world, S))[HERB] == 8 and await eq_ids(world, S) == ["eq000001"]


async def test_不在交易坊城市_也能取回自己的货(world):
    """走远了不能把货困在摊位里：下架 / 领回不受城市限制。"""
    lid = (await list_item(S, HERB, 2, 100))["listing_id"]
    from sqlalchemy import update
    D = world["db_async"]
    async with D.AsyncSessionLocal() as s:
        await s.execute(update(D.Player).where(D.Player.discord_id == S).values(current_city="昆仑秘境"))
        await s.commit()
    assert (await delist(S, lid))["ok"]


@pytest.mark.parametrize("city", MARKET_CITIES)
async def test_每个交易坊城市都能用(db, city):
    await _add(db, S, city=city)
    await db["inventory"].add_item(S, HERB, 1)
    assert (await list_item(S, HERB, 1, 10))["ok"]
