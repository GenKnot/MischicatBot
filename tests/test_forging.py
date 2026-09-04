"""锻造系统功能测试。

改过四处：每日次数原子化、材料成组扣（原先逐个扣会留下扣了一半的背包）、
淬炼的矿石和灵石并进同一事务（原先中途失败白吞矿石）、考核缴费幂等。
"""

import pytest

from tests.conftest import make_player
from utils import forging as forging_mod
from utils.forging import (DAILY_LIMIT, EXAM_COST, EXAM_MATERIALS,
                           SLOT_MAIN_ORE_QTY, attempt_forge,
                           check_and_consume_daily, start_forging_exam)

ORE = "铜矿石"
SLOT = "饰品"                       # 用料最少：2 个主矿
ORE_QTY = SLOT_MAIN_ORE_QTY[SLOT]


@pytest.fixture
async def smith(db):
    """一个有充足材料的炼器师。"""
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        p = make_player(D, "u", stones=100_000)
        p.forging_level = 1
        s.add(p)
        s.add(D.Inventory(discord_id="u", item_id=ORE, quantity=99))
        await s.commit()
    return "u"


async def _player(db, uid="u"):
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        return await s.get(D.Player, uid)


async def _qty(db, item, uid="u"):
    return (await db["inventory"].get_inventory(uid)).get(item, 0)


# --- 每日次数 ----------------------------------------------------------------

async def test_每日次数逐次递增(db, smith):
    for expected in range(1, DAILY_LIMIT + 1):
        ok, used = await check_and_consume_daily(smith)
        assert ok and used == expected


async def test_超出每日上限后被拒(db, smith):
    for _ in range(DAILY_LIMIT):
        await check_and_consume_daily(smith)

    ok, used = await check_and_consume_daily(smith)

    assert not ok
    assert used == DAILY_LIMIT, "被拒时应回报已用次数，而不是 0"


async def test_每日次数跨日归零(db, smith):
    import time
    for _ in range(DAILY_LIMIT):
        await check_and_consume_daily(smith)

    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        p = await s.get(D.Player, smith)
        p.forging_daily_reset = time.time() - 86_400
        await s.commit()

    ok, used = await check_and_consume_daily(smith)
    assert ok and used == 1


# --- 锻造：材料扣减 ----------------------------------------------------------

async def test_开炉必定扣掉主材(db, smith):
    """成败都要扣材料 —— 失败时"材料全损"是设计，不是 bug。"""
    before = await _qty(db, ORE)
    inventory = await db["inventory"].get_inventory(smith)

    result = await attempt_forge(smith, SLOT, ORE, "普通", None, None,
                                 inventory, player_bone=10, forging_level=1)

    assert "success" in result, result           # 走到了真正开炉，而非前置校验被拒
    assert await _qty(db, ORE) == before - ORE_QTY


async def test_锻造成功产出装备(db, smith, monkeypatch):
    """把成功率拉满，确认装备真的入库。"""
    monkeypatch.setattr(forging_mod.random, "randint", lambda a, b: 1)   # 必定成功
    inventory = await db["inventory"].get_inventory(smith)

    result = await attempt_forge(smith, SLOT, ORE, "普通", None, None,
                                 inventory, player_bone=10, forging_level=1)

    assert result["success"], result
    equipment = await db["equipment_db"].get_equipment_list(smith)
    assert len(equipment) == 1
    assert equipment[0]["slot"] == SLOT


async def test_锻造失败不产出装备但扣材料(db, smith, monkeypatch):
    monkeypatch.setattr(forging_mod.random, "randint", lambda a, b: 100)  # 必定失败
    before = await _qty(db, ORE)
    inventory = await db["inventory"].get_inventory(smith)

    result = await attempt_forge(smith, SLOT, ORE, "普通", None, None,
                                 inventory, player_bone=10, forging_level=1)

    assert result["success"] is False
    assert await db["equipment_db"].get_equipment_list(smith) == []
    assert await _qty(db, ORE) == before - ORE_QTY


async def test_走火扣寿元但不会扣到_0(db, smith, monkeypatch):
    monkeypatch.setattr(forging_mod.random, "randint", lambda a, b: 100)   # 必定失败
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        p = await s.get(D.Player, smith)
        p.lifespan = 1
        await s.commit()
    inventory = await db["inventory"].get_inventory(smith)

    await attempt_forge(smith, SLOT, ORE, "普通", None, None,
                        inventory, player_bone=10, forging_level=1)

    assert (await _player(db, smith)).lifespan >= 1, "寿元不能被走火扣到 0 以下"


async def test_辅材也会被扣(db, smith):
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        s.add(D.Inventory(discord_id=smith, item_id="松木", quantity=3))
        await s.commit()
    inventory = await db["inventory"].get_inventory(smith)

    await attempt_forge(smith, SLOT, ORE, "普通", "松木", None,
                        inventory, player_bone=10, forging_level=1)

    assert await _qty(db, "松木") == 2


async def test_辅材不足时不扣主材(db, smith):
    """成组扣的关键性质：任一材料不足则整组不扣。"""
    inventory = await db["inventory"].get_inventory(smith)
    inventory["松木"] = 1                      # 谎报库存，实际背包里没有
    before = await _qty(db, ORE)

    result = await attempt_forge(smith, SLOT, ORE, "普通", "松木", None,
                                 inventory, player_bone=10, forging_level=1)

    assert result["ok"] is False
    assert await _qty(db, ORE) == before, "整组失败时主材必须原样保留"


async def test_主材不足直接被拒且不消耗次数(db, smith):
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        row = await s.get(D.Inventory, (smith, ORE))
        row.quantity = 1
        await s.commit()

    result = await attempt_forge(smith, SLOT, ORE, "普通", None, None,
                                 {ORE: 1}, player_bone=10, forging_level=1)

    assert result["ok"] is False and "主材不足" in result["reason"]


async def test_超出每日上限时不扣材料(db, smith):
    for _ in range(DAILY_LIMIT):
        await check_and_consume_daily(smith)
    before = await _qty(db, ORE)
    inventory = await db["inventory"].get_inventory(smith)

    result = await attempt_forge(smith, SLOT, ORE, "普通", None, None,
                                 inventory, player_bone=10, forging_level=1)

    assert result["ok"] is False and "上限" in result["reason"]
    assert await _qty(db, ORE) == before


# --- 考核 --------------------------------------------------------------------

async def test_考核缴费并发放材料(db):
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        s.add(make_player(D, "novice", stones=EXAM_COST))
        await s.commit()

    result = await start_forging_exam("novice")

    assert result["ok"]
    assert (await _player(db, "novice")).spirit_stones == 0
    inventory = await db["inventory"].get_inventory("novice")
    for item, qty in EXAM_MATERIALS.items():
        assert inventory.get(item) == qty


async def test_灵石不足时考核失败且不发材料(db):
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        s.add(make_player(D, "poor", stones=EXAM_COST - 1))
        await s.commit()

    result = await start_forging_exam("poor")

    assert result["ok"] is False and "灵石不足" in result["reason"]
    assert (await _player(db, "poor")).spirit_stones == EXAM_COST - 1
    assert await db["inventory"].get_inventory("poor") == {}


async def test_已是炼器师不能重复考核(db, smith):
    result = await start_forging_exam(smith)
    assert result["ok"] is False and "已经是" in result["reason"]


async def test_重复考核只收一次费(db):
    """考核费是一次性的。注意余额要给足 —— 只给刚好 500 的话，即便没有幂等
    保护也会因为"余额不够"而只成功一次，测试就会因为错误的原因通过。"""
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        s.add(make_player(D, "novice", stones=EXAM_COST * 10))
        await s.commit()

    first = await start_forging_exam("novice")
    second = await start_forging_exam("novice")

    assert first["ok"] and not second["ok"]
    assert "已缴过" in second["reason"]
    assert (await _player(db, "novice")).spirit_stones == EXAM_COST * 10 - EXAM_COST
    inventory = await db["inventory"].get_inventory("novice")
    for item, qty in EXAM_MATERIALS.items():
        assert inventory.get(item) == qty, "材料也只应发一份"


async def test_并发考核只扣一次费(db):
    """并发版本：余额充足时四次同时报名，账面仍只扣一次。"""
    import asyncio
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        s.add(make_player(D, "novice", stones=EXAM_COST * 10))
        await s.commit()

    results = await asyncio.gather(*[start_forging_exam("novice") for _ in range(4)])

    assert sum(1 for r in results if r["ok"]) == 1
    assert (await _player(db, "novice")).spirit_stones == EXAM_COST * 10 - EXAM_COST
