"""置业 / 洞府命令测试。

买房原先先落产权再另开事务扣钱，扣款失败会白送一处居所。
开辟洞府的余额条件现在写在 WHERE 里，连点扣不成负数。
"""

import pytest

from tests.conftest import make_player
from tests.discord_fakes import FakeContext
from cogs.property import PropertyCog
from utils.residence import get_residences, has_residence
from utils.world import CITIES, SPECIAL_REGIONS
from utils.character import CAVE_PRICE, REPUTATION_CAVE, REPUTATION_RESIDENCE


@pytest.fixture
def cog():
    return PropertyCog(bot=None)


# 说明：被 @commands.hybrid_command 装饰后，属性拿到的是 Command 对象而不是
# 普通方法，所以测试里统一用 `cog.命令.callback(cog, ctx, ...)` 直接调底层函数。
# 这样跳过的只是 discord.py 的参数解析，业务逻辑一行不落。


@pytest.fixture
async def rich(db):
    """声望与灵石都够、且在一座普通城市里的玩家。"""
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        p = make_player(D, "1", stones=10_000_000)
        p.reputation = REPUTATION_RESIDENCE + 100
        s.add(p)
        await s.commit()
    return FakeContext(user_id=1)


async def _stones(db, uid="1"):
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        return (await s.get(D.Player, uid)).spirit_stones


# --- 买房 --------------------------------------------------------------------

async def test_买房成功扣钱并落产权(db, cog, rich):
    before = await _stones(db)

    await cog.buy_residence.callback(cog, rich)

    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        city = (await s.get(D.Player, "1")).current_city
    assert await has_residence("1", city), "产权应当落下"
    assert await _stones(db) < before, "灵石应当被扣"


async def test_灵石不足时不落产权(db, cog):
    """走的是前置余额检查这条路（并非原子扣那条），一并守住。"""
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        p = make_player(D, "2", stones=1)
        p.reputation = REPUTATION_RESIDENCE + 100
        s.add(p)
        await s.commit()
    ctx = FakeContext(user_id=2)

    await cog.buy_residence.callback(cog, ctx)

    assert ctx.said("灵石不足")
    assert await get_residences("2") == [], "扣款失败绝不能留下产权"
    assert await _stones(db, "2") == 1


async def test_声望不足不能置业(db, cog):
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        p = make_player(D, "3", stones=10_000_000)
        p.reputation = 0
        s.add(p)
        await s.commit()
    ctx = FakeContext(user_id=3)

    await cog.buy_residence.callback(cog, ctx)

    assert ctx.said("声望不足")
    assert await get_residences("3") == []


async def test_同城不能重复置业(db, cog, rich):
    await cog.buy_residence.callback(cog, rich)
    ctx2 = FakeContext(user_id=1)

    await cog.buy_residence.callback(cog, ctx2)

    assert ctx2.said("已有居所")


async def test_未创建角色时提示(db, cog):
    ctx = FakeContext(user_id=999)
    await cog.buy_residence.callback(cog, ctx)
    assert ctx.said("尚未踏入修仙之路")


async def test_已坐化不能置业(db, cog):
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        p = make_player(D, "4", stones=10_000_000)
        p.reputation = REPUTATION_RESIDENCE + 100
        p.is_dead = True
        s.add(p)
        await s.commit()
    ctx = FakeContext(user_id=4)

    await cog.buy_residence.callback(cog, ctx)

    assert ctx.said("已坐化")


# --- 洞府 --------------------------------------------------------------------

@pytest.fixture
def region_name():
    return SPECIAL_REGIONS[0]["name"]


async def test_开辟洞府扣钱并记录(db, cog, region_name):
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        p = make_player(D, "5", stones=CAVE_PRICE + 100)
        p.reputation = REPUTATION_CAVE + 100
        p.current_city = region_name
        s.add(p)
        await s.commit()
    ctx = FakeContext(user_id=5)

    await cog.open_cave.callback(cog, ctx, region_name=region_name)

    async with D.AsyncSessionLocal() as s:
        player = await s.get(D.Player, "5")
    assert player.cave == region_name
    assert player.spirit_stones == 100


async def test_灵石不足不能开辟洞府(db, cog, region_name):
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        p = make_player(D, "6", stones=CAVE_PRICE - 1)
        p.reputation = REPUTATION_CAVE + 100
        p.current_city = region_name
        s.add(p)
        await s.commit()
    ctx = FakeContext(user_id=6)

    await cog.open_cave.callback(cog, ctx, region_name=region_name)

    assert ctx.said("灵石不足")
    async with D.AsyncSessionLocal() as s:
        player = await s.get(D.Player, "6")
    assert player.cave is None
    assert player.spirit_stones == CAVE_PRICE - 1, "灵石不能被扣成负数"


async def test_并发开辟洞府只扣一次(db, cog, region_name):
    """连点开辟不能被扣两次 CAVE_PRICE。"""
    import asyncio
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        p = make_player(D, "7", stones=CAVE_PRICE)
        p.reputation = REPUTATION_CAVE + 100
        p.current_city = region_name
        s.add(p)
        await s.commit()

    await asyncio.gather(*[
        cog.open_cave.callback(cog, FakeContext(user_id=7), region_name=region_name)
        for _ in range(4)
    ])

    async with D.AsyncSessionLocal() as s:
        player = await s.get(D.Player, "7")
    assert player.spirit_stones == 0, f"只应扣一次，实际余额 {player.spirit_stones}"


async def test_声望不足不能开辟洞府(db, cog, region_name):
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        p = make_player(D, "8", stones=CAVE_PRICE * 10)
        p.reputation = 0
        p.current_city = region_name
        s.add(p)
        await s.commit()
    ctx = FakeContext(user_id=8)

    await cog.open_cave.callback(cog, ctx, region_name=region_name)

    assert ctx.said("声望不足")
    async with D.AsyncSessionLocal() as s:
        assert (await s.get(D.Player, "8")).cave is None


async def test_不存在的秘地被拒(db, cog):
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        p = make_player(D, "9", stones=CAVE_PRICE * 10)
        p.reputation = REPUTATION_CAVE + 100
        s.add(p)
        await s.commit()
    ctx = FakeContext(user_id=9)

    await cog.open_cave.callback(cog, ctx, region_name="不存在的地方")

    assert ctx.said("未找到秘地")


async def test_扣款失败时不落产权(db, cog, rich, monkeypatch):
    """回归重点：原先**先落产权、再另开事务扣钱**，扣款失败会白送一处居所。

    直接用"没钱的玩家"测不到这里 —— `buy_residence` 里有一道前置余额检查
    会先把他拦下。这里改为让扣款本身失败，检验"扣不到就不落产权"。
    旧写法在扣款之前就已经 `add_residence` 了，必然被这个用例抓住。
    """
    async def _always_fail(session, uid, amount):
        return False
    monkeypatch.setattr("cogs.property.spend_stones", _always_fail)

    await cog.buy_residence.callback(cog, rich)

    assert ctx_said(rich, "灵石不足")
    assert await get_residences("1") == [], "扣款失败绝不能留下产权"


def ctx_said(ctx, text):
    return ctx.said(text)
