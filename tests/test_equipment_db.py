"""装备数据层（utils/equipment_db.py）：穿戴 / 卸下 / 丢弃 / 淬炼写回。

B49 —— `equip_item` 先查出同槽位已穿的、再把它卸下、再穿新的，三步之间没有保护：
  同时穿两件同槽位装备（连点、两个面板）会各自「卸下 A、穿上自己」，最后两件都是已穿；
  之后任何一次穿戴都会在 `scalar_one_or_none()` 上抛 MultipleResultsFound，这个槽位彻底卡死。
B50 —— `discard_equipment` 用 ORM `session.delete`，同一件装备被丢弃两次（连点）或被别处刚上架 / 卖掉时，
  第二次删 0 行不报错、还会回复『已丢弃』。改成带条件的原子 DELETE，删不到就如实说不存在。
"""

import asyncio


from tests.conftest import make_player
from utils.equipment_db import (discard_equipment, equip_item, get_equipment_by_id, get_equipment_list, get_equipped,
                                give_equipment, unequip_item, update_equipment_stats)

U = "1001"


def eq(equip_id, slot="武器", tier=0, tier_req=0, quality="普通", name=None, stats=None):
    return {"equip_id": equip_id, "name": name or f"装备{equip_id}", "slot": slot, "quality": quality, "tier": tier,
            "tier_req": tier_req, "stats": stats or {"physique": 1}, "flavor": "风味"}


async def _add(db, uid=U):
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        s.add(make_player(D, uid, stones=0))
        await s.commit()


async def equipped_ids(uid=U):
    return sorted(e["equip_id"] for e in await get_equipped(uid))


# --- 读取 ---------------------------------------------------------------------

async def test_列表_已装备在前_同状态高阶在前(db):
    await _add(db)
    for e in (eq("a", tier=1), eq("b", tier=5), eq("c", tier=3, slot="防具")):
        await give_equipment(U, e)
    await equip_item(U, "c", 9)
    ids = [e["equip_id"] for e in await get_equipment_list(U)]
    assert ids == ["c", "b", "a"]


async def test_列表_属性解析成字典_只看自己的(db):
    await _add(db)
    await _add(db, "1002")
    await give_equipment(U, eq("a", stats={"bone": 3, "soul": 2}))
    await give_equipment("1002", eq("b"))
    [e] = await get_equipment_list(U)
    assert e["stats"] == {"bone": 3, "soul": 2} and e["equipped"] is False
    assert await get_equipment_list("nope") == []


async def test_按id取装备_别人的取不到(db):
    await _add(db)
    await give_equipment(U, eq("a"))
    assert (await get_equipment_by_id("a", U))["name"] == "装备a"
    assert await get_equipment_by_id("a", "1002") is None and await get_equipment_by_id("zz", U) is None


# --- 穿戴 ---------------------------------------------------------------------

async def test_穿戴_成功与顶替同槽位(db):
    await _add(db)
    await give_equipment(U, eq("a"))
    await give_equipment(U, eq("b"))
    await give_equipment(U, eq("c", slot="防具"))
    assert await equip_item(U, "a", 0) == (True, "已装备 **装备a**。")
    await equip_item(U, "c", 0)
    ok, msg = await equip_item(U, "b", 0)
    assert ok and await equipped_ids() == ["b", "c"]                     # a 被顶下，防具不受影响


async def test_穿戴_拒绝(db):
    await _add(db)
    await _add(db, "1002")
    await give_equipment("1002", eq("x"))
    assert await equip_item(U, "x", 9) == (False, "装备不存在。")        # 别人的
    assert await equip_item(U, "nope", 9) == (False, "装备不存在。")
    await give_equipment(U, eq("hi", tier_req=2))
    ok, msg = await equip_item(U, "hi", 1)
    assert not ok and "结丹期" in msg and await equipped_ids() == []
    assert (await equip_item(U, "hi", 2))[0]


async def test_穿戴_重复穿同一件没问题(db):
    await _add(db)
    await give_equipment(U, eq("a"))
    await equip_item(U, "a", 0)
    assert (await equip_item(U, "a", 0))[0] and await equipped_ids() == ["a"]


async def test_B49_并发穿同槽位不同装备_只会留下一件(db):
    await _add(db)
    for n in range(6):
        await give_equipment(U, eq(f"w{n}"))
    results = await asyncio.gather(*[equip_item(U, f"w{n}", 0) for n in range(6)], return_exceptions=True)
    assert not [r for r in results if isinstance(r, BaseException)], results
    assert len(await equipped_ids()) == 1


async def test_B49_槽位坏了_已有两件已穿时再穿一次能自愈(db):
    """线上可能已经有被旧版本弄出两件已穿的玩家，穿戴不能再抛异常，且应收敛为一件。"""
    await _add(db)
    for n in "abc":
        await give_equipment(U, eq(n))
    D = db["db_async"]
    from sqlalchemy import update
    async with D.AsyncSessionLocal() as s:
        await s.execute(update(D.Equipment).where(D.Equipment.equip_id.in_(["a", "b"])).values(equipped=True))
        await s.commit()
    assert (await equip_item(U, "c", 0))[0]
    assert await equipped_ids() == ["c"]


# --- 卸下 ---------------------------------------------------------------------

async def test_卸下(db):
    await _add(db)
    await give_equipment(U, eq("a"))
    assert await unequip_item(U, "a") == (False, "该装备未装备或不存在。")
    await equip_item(U, "a", 0)
    assert await unequip_item(U, "a") == (True, "已卸下 **装备a**。") and await equipped_ids() == []
    assert (await unequip_item("1002", "a"))[0] is False and (await unequip_item(U, "nope"))[0] is False


async def test_卸下别人的装备不行(db):
    await _add(db)
    await _add(db, "1002")
    await give_equipment("1002", eq("x"))
    await equip_item("1002", "x", 0)
    assert (await unequip_item(U, "x"))[0] is False and await equipped_ids("1002") == ["x"]


# --- 丢弃 ---------------------------------------------------------------------

async def test_丢弃(db):
    await _add(db)
    await give_equipment(U, eq("a"))
    assert await discard_equipment(U, "a") == (True, "已丢弃 **装备a**。")
    assert await get_equipment_list(U) == [] and await discard_equipment(U, "a") == (False, "装备不存在。")


async def test_丢弃_已装备的要先卸下_别人的不能丢(db):
    await _add(db)
    await _add(db, "1002")
    await give_equipment(U, eq("a"))
    await equip_item(U, "a", 0)
    assert await discard_equipment(U, "a") == (False, "请先卸下装备再丢弃。")
    assert await discard_equipment("1002", "a") == (False, "装备不存在。")
    assert len(await get_equipment_list(U)) == 1


async def test_B50_重复丢弃_只有一次回复已丢弃(db):
    await _add(db)
    await give_equipment(U, eq("a"))
    results = await asyncio.gather(*[discard_equipment(U, "a") for _ in range(5)], return_exceptions=True)
    assert not [r for r in results if isinstance(r, BaseException)], results
    assert len([r for r in results if r[0]]) == 1


async def test_B50_丢弃时刚被穿上_不会删掉已装备的(db, monkeypatch):
    """检查『没穿』之后、真正删除之前被别处穿上了：条件 DELETE 带着 equipped=0，删不掉。"""
    await _add(db)
    await give_equipment(U, eq("a"))
    D = db["db_async"]
    from sqlalchemy import update
    from sqlalchemy.ext.asyncio import AsyncSession
    orig, state = AsyncSession.get, {"done": False}

    async def get_then_equip(self, entity, ident, *a, **k):
        row = await orig(self, entity, ident, *a, **k)
        if not state["done"] and entity is D.Equipment:
            state["done"] = True
            seen = row.equipped
            async with D.AsyncSessionLocal() as other:                       # 读完之后、删除之前，别处把它穿上了
                await other.execute(update(D.Equipment).values(equipped=True))
                await other.commit()
            row.equipped = seen                                              # 本次调用仍以为『没穿』
        return row
    monkeypatch.setattr(AsyncSession, "get", get_then_equip)
    ok, msg = await discard_equipment(U, "a")
    assert not ok and "未能丢弃" in msg
    monkeypatch.undo()
    assert await equipped_ids() == ["a"]


# --- 写回 ---------------------------------------------------------------------

async def test_淬炼写回(db):
    await _add(db)
    await give_equipment(U, eq("a"))
    await update_equipment_stats("a", "新名", {"soul": 4}, "新风味")
    e = await get_equipment_by_id("a", U)
    assert (e["name"], e["stats"], e["flavor"]) == ("新名", {"soul": 4}, "新风味")
    await update_equipment_stats("nope", "x", {}, "x")                        # 不存在也不报错


async def test_穿戴时装备刚被别处拿走_如实回复且不动其他装备(db, monkeypatch):
    """校验读到装备之后、写入之前它被删了（丢弃 / 上架）：不能凭空『已装备』，也不能把同槽位的另一件白白卸下。"""
    await _add(db)
    await give_equipment(U, eq("a"))
    await give_equipment(U, eq("b"))
    await equip_item(U, "a", 0)
    D = db["db_async"]
    from sqlalchemy import delete
    from sqlalchemy.ext.asyncio import AsyncSession
    orig, state = AsyncSession.get, {"done": False}

    async def get_then_delete(self, entity, ident, *a, **k):
        row = await orig(self, entity, ident, *a, **k)
        if not state["done"] and entity is D.Equipment and ident == "b":
            state["done"] = True
            async with D.AsyncSessionLocal() as other:
                await other.execute(delete(D.Equipment).where(D.Equipment.equip_id == "b"))
                await other.commit()
        return row
    monkeypatch.setattr(AsyncSession, "get", get_then_delete)
    ok, msg = await equip_item(U, "b", 0)
    monkeypatch.undo()
    assert not ok and msg == "装备不存在。" and await equipped_ids() == ["a"]
