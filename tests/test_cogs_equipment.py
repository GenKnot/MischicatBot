"""服用丹药命令测试。

原先是先写 buff、最后才 inv.quantity -= 1，连点两次都生效却只扣一颗。
改成先原子扣药，扣不到就连 buff 一起回滚。
"""

import asyncio
import json

import pytest

from tests.conftest import make_player
from tests.discord_fakes import FakeContext
from cogs.equipment import EquipmentCog

PILL = "聚灵丹"          # effect: cultivation_speed_bonus


@pytest.fixture
def cog():
    return EquipmentCog(bot=None)


@pytest.fixture
async def user(db):
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        s.add(make_player(D, "1", stones=0))
        s.add(D.Inventory(discord_id="1", item_id=PILL, quantity=1))
        await s.commit()
    return FakeContext(user_id=1)


async def _qty(db, item=PILL, uid="1"):
    return (await db["inventory"].get_inventory(uid)).get(item, 0)


async def _buffs(db, uid="1"):
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        return json.loads((await s.get(D.Player, uid)).active_buffs or "{}")


async def test_服用丹药扣掉一颗并生效(db, cog, user):
    await cog.use_item.callback(cog, user, item_name=PILL)

    assert await _qty(db) == 0
    assert await _buffs(db), "buff 应当写入 active_buffs"


async def test_背包没有时提示且不生效(db, cog):
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        s.add(make_player(D, "2", stones=0))
        await s.commit()
    ctx = FakeContext(user_id=2)

    await cog.use_item.callback(cog, ctx, item_name=PILL)

    assert ctx.said("背包中没有")
    assert await _buffs(db, "2") == {}


async def test_未知道具被拒(db, cog, user):
    await cog.use_item.callback(cog, user, item_name="根本不存在的丹")
    assert user.said("未知道具")


async def test_不传道具名时提示用法(db, cog, user):
    await cog.use_item.callback(cog, user, item_name=None)
    assert user.said("用法")


async def test_未创建角色时提示(db, cog):
    ctx = FakeContext(user_id=999)
    await cog.use_item.callback(cog, ctx, item_name=PILL)
    assert ctx.said("尚未踏入修仙之路")


async def test_已坐化不能服药(db, cog):
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        p = make_player(D, "3", stones=0)
        p.is_dead = True
        s.add(p)
        s.add(D.Inventory(discord_id="3", item_id=PILL, quantity=1))
        await s.commit()
    ctx = FakeContext(user_id=3)

    await cog.use_item.callback(cog, ctx, item_name=PILL)

    assert ctx.said("尚未踏入修仙之路")
    assert await _qty(db, uid="3") == 1, "被拒时不能扣药"


async def test_扣药失败时_buff_不生效(db, cog, user, monkeypatch):
    """回归重点：原先先写 buff、最后才扣药，扣不到时 buff 已经落库了。

    为什么不用 `asyncio.gather` 去撞并发：那样并不可靠 —— 两个调用往往实际
    串行，第二个会在读取时就发现背包空了，于是即便改回旧写法测试照样通过
    （曾经如此）。这里改为**让扣药这一步失败**，直接检验"扣不到就整体回滚"
    这条性质；旧写法根本不调用 `consume_item`，因此必然会被这个用例抓住。
    """
    async def _always_fail(session, uid, item_id, quantity=1):
        return False
    monkeypatch.setattr("cogs.equipment.consume_item", _always_fail)

    await cog.use_item.callback(cog, user, item_name=PILL)

    assert user.said("背包中没有")
    assert await _buffs(db) == {}, "扣药失败时 buff 必须一并回滚"
    assert await _qty(db) == 1, "丹药应当原样保留"


async def test_并发服用最终只扣掉一颗(db, cog, user):
    """端到端补充：不论调度如何，账面上不会出现负数或多扣。"""
    contexts = [FakeContext(user_id=1) for _ in range(6)]

    await asyncio.gather(*[
        cog.use_item.callback(cog, c, item_name=PILL) for c in contexts
    ])

    assert await _qty(db) == 0
