"""机器人的生成与清除（utils/bot_world.py、cogs/admin.py 的 生成机器人 / 清除机器人）。

· 生成：数量与总量上限、编号接着排、道号不与真人重名、档位分布、境界 / 属性 / 灵石落在档位范围内、一个事务；
· 清除：机器人与名下所有东西一并清走，真人的数据（包括和机器人的好感、双修搭档字段）不受牵连；
· 静态棘轮：带玩家 ID 的表要么在 CLEANUP 里、要么在 CLEANUP_EXEMPT 里写明理由；
· 命令：只有所有者能用，清除要带「确认」，两个操作都留审计日志。
"""

import logging
import random
from types import SimpleNamespace

import pytest
from discord.ext import commands
from sqlalchemy import func, select

from cogs.admin import AdminCog
from tests.conftest import make_player
from tests.discord_fakes import FakeContext
from utils import bot_social as bs
from utils import bot_world as bw
from utils.realms import REALMS, cultivation_needed


async def count(db, model, *where):
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        return await s.scalar(select(func.count()).select_from(model).where(*where))


async def bots_of(db):
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        return list((await s.execute(select(D.Player).where(D.Player.is_bot == True))).scalars())  # noqa: E712


async def human(db, uid="1001", name="真人甲", **kw):
    D = db["db_async"]
    p = make_player(D, uid)
    p.name = name
    for k, v in kw.items():
        setattr(p, k, v)
    async with D.AsyncSessionLocal() as s:
        s.add(p)
        await s.commit()


# ---- 数据 -------------------------------------------------------------------

def test_词库合法():
    n = bw.load_names()
    assert len(n["surnames"]) >= 30 and len(n["given_single"]) >= 20
    assert len(n["given_first"]) * len(n["given_second"]) >= 200
    for k in ("surnames", "given_single", "given_first", "given_second"):
        assert len(set(n[k])) == len(n[k]), f"{k} 有重复"
        assert all(len(x) == 1 for x in n[k])


def test_档位配置合法():
    assert set(bw.TIER_WEIGHTS) == set(bw.TIER_SPECS) and sum(bw.TIER_WEIGHTS.values()) == 100
    for tier, spec in bw.TIER_SPECS.items():
        lo, hi = spec["realms"]
        assert REALMS.index(lo) <= REALMS.index(hi), tier
        assert spec["stats"][0] <= spec["stats"][1] and spec["stones"][0] <= spec["stones"][1]


def test_道号不重名且词库抽干后加序号():
    rng, names = random.Random(0), bw.load_names()
    taken = set()
    for _ in range(500):
        name = bw.unique_name(rng, names, taken)
        assert name not in taken
        taken.add(name)
    tiny = {"surnames": ["李"], "given_single": ["云"], "given_first": ["云"], "given_second": ["云"]}
    taken = {"李云", "李云云"}
    assert bw.unique_name(random.Random(0), tiny, taken) in {"李云2", "李云云2"}


def test_档位分布大致是六三五():
    rng = random.Random(7)
    n = {t: 0 for t in bw.TIER_WEIGHTS}
    for _ in range(4000):
        n[bw.roll_tier(rng)] += 1
    assert 0.55 < n["炮灰"] / 4000 < 0.65 and 0.30 < n["正常"] / 4000 < 0.40 and 0.03 < n["天骄"] / 4000 < 0.07


@pytest.mark.parametrize("tier", list(bw.TIER_SPECS))
def test_生成的属性落在档位范围内(tier):
    spec = bw.TIER_SPECS[tier]
    allowed = REALMS[REALMS.index(spec["realms"][0]):REALMS.index(spec["realms"][1]) + 1]
    for seed in range(200):
        f = bw.roll_player_fields(random.Random(seed), tier, "bot_00001", "某", 0.0)
        assert f["realm"] in allowed and f["is_bot"] is True
        assert all(spec["stats"][0] <= f[k] <= spec["stats"][1] for k in bw._STAT_COLUMNS)
        assert spec["stones"][0] <= f["spirit_stones"] <= spec["stones"][1]
        assert 0 <= f["cultivation"] < cultivation_needed(f["realm"])
        assert 10 <= f["lifespan"] <= f["lifespan_max"]
        assert f["gender"] in ("男", "女")


# ---- 生成 -------------------------------------------------------------------

async def test_生成_写入玩家与性格(db):
    res = await bw.generate_bots(20, random.Random(1))
    assert res["ok"] and len(res["created"]) == 20 and sum(res["by_tier"].values()) == 20
    bots = await bots_of(db)
    assert len(bots) == 20 and all(b.discord_id.startswith("bot_") for b in bots)
    assert await count(db, db["db_async"].BotPersonality) == 20
    for c in res["created"]:
        persona = await bs.get_personality(c["id"])
        assert persona["archetype"] == c["archetype"] and persona["tier"] == c["tier"]


async def test_生成_编号接着排_道号不与真人重名(db):
    await human(db, name="安岚")
    await bw.generate_bots(5, random.Random(1))
    res = await bw.generate_bots(5, random.Random(1))            # 同一个种子：词库撞名只能靠去重
    ids = sorted(b.discord_id for b in await bots_of(db))
    assert ids == [f"bot_{i:05d}" for i in range(1, 11)]
    names = [b.name for b in await bots_of(db)] + ["安岚"]
    assert len(set(names)) == len(names)
    assert res["created"][0]["id"] == "bot_00006"


async def test_生成_数量与总量上限(db, monkeypatch):
    for bad in (0, -1, bw.MAX_PER_BATCH + 1):
        res = await bw.generate_bots(bad)
        assert res["ok"] is False and "1~" in res["reason"]
    assert await count(db, db["db_async"].Player) == 0
    await bw.generate_bots(10)
    monkeypatch.setattr(bw, "MAX_BOTS", 12)
    res = await bw.generate_bots(5)
    assert res["ok"] is False and "最多还能生成 2" in res["reason"]
    assert len(await bots_of(db)) == 10
    assert (await bw.generate_bots(2))["ok"]


async def test_生成_同一批里道号也不重复(db, monkeypatch):
    """词库很小、必然撞名时，同一批内部靠 taken 去重 / 加序号。"""
    tiny = {"surnames": ["李"], "given_single": ["云"], "given_first": ["云"], "given_second": ["云"]}
    monkeypatch.setattr(bw, "load_names", lambda: tiny)
    await bw.generate_bots(6)
    names = [b.name for b in await bots_of(db)]
    assert len(set(names)) == 6


async def test_生成_不影响真人(db):
    await human(db)
    await bw.generate_bots(5)
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        h = await s.get(D.Player, "1001")
        assert h.is_bot is False and h.name == "真人甲"


async def test_生成_并发两批编号不撞(db):
    import asyncio
    a, b = await asyncio.gather(bw.generate_bots(10), bw.generate_bots(10))
    assert a["ok"] and b["ok"] and len(await bots_of(db)) == 20


# ---- 清除 -------------------------------------------------------------------

async def test_清除_没有机器人是空操作(db):
    await human(db)
    assert await bw.clear_bots() == {"removed": 0, "rows": {}}
    assert await count(db, db["db_async"].Player) == 1


async def test_清除_机器人名下的东西一起清_真人不受牵连(db):
    D = db["db_async"]
    await human(db)
    res = await bw.generate_bots(3, random.Random(2))
    bot_id = res["created"][0]["id"]
    inv = db["inventory"]
    await inv.add_item(bot_id, "筑基丹", 2)
    await inv.add_item("1001", "筑基丹", 1)
    await bs.adjust_favor("1001", bot_id, 30)
    async with D.AsyncSessionLocal() as s:
        s.add(D.BankAccount(discord_id=bot_id, demand_balance=100))
        (await s.get(D.Player, "1001")).dual_partner_id = bot_id
        await s.commit()
    out = await bw.clear_bots()
    assert out["removed"] == 3 and out["rows"]["players"] == 3
    assert await bots_of(db) == []
    assert await count(db, D.BotPersonality) == 0 and await count(db, D.BotRelation) == 0
    assert await count(db, D.BankAccount) == 0
    assert await inv.get_inventory(bot_id) == {} and await inv.get_inventory("1001") == {"筑基丹": 1}
    async with D.AsyncSessionLocal() as s:
        h = await s.get(D.Player, "1001")
        assert h is not None and h.dual_partner_id is None


async def test_清除_队伍里的机器人退队_真人队伍保留(db):
    from utils import party
    D = db["db_async"]
    await human(db)
    bot_id = (await bw.generate_bots(1))["created"][0]["id"]
    pid = await party.create_party("1001", "灵虚城")
    async with D.AsyncSessionLocal() as s:
        for uid in ("1001", bot_id):
            (await s.get(D.Player, uid)).party_id = pid
        await s.commit()
    await bw.clear_bots()
    assert {m["discord_id"] for m in await party.get_party_members(pid)} == {"1001"}


async def test_清除_市场挂单一起撤(db):
    D = db["db_async"]
    bot_id = (await bw.generate_bots(1))["created"][0]["id"]
    async with D.AsyncSessionLocal() as s:
        s.add(D.MarketListing(listing_id="L1", seller_id=bot_id, item_type="item", item_id="筑基丹", item_name="筑基丹",
                              price=10, listed_at=0, expires_at=1))
        await s.commit()
    await bw.clear_bots()
    assert await count(db, D.MarketListing) == 0


def test_棘轮_带玩家ID的表都登记了怎么清():
    from utils.db_async import Base
    known = {m.__tablename__ for m in bw.CLEANUP} | set(bw.CLEANUP_EXEMPT)
    needs = {t.name for t in Base.metadata.sorted_tables
             if any(c in t.columns for c in bw.PLAYER_KEY_COLUMNS)}
    assert needs <= known, f"这些表带玩家 ID，却没登记在 CLEANUP / CLEANUP_EXEMPT：{sorted(needs - known)}"
    for model, column in bw.CLEANUP.items():
        assert column in model.__table__.columns


# ---- 命令 -------------------------------------------------------------------

def make_cog():
    return AdminCog(SimpleNamespace(tree=None))


async def test_命令_生成_回报档位并留审计(db, caplog):
    cog, c = make_cog(), FakeContext(user_id=1)
    with caplog.at_level(logging.WARNING, logger="mischicat.audit"):
        await cog.spawn_bots.callback(cog, c, 12)
    assert c.said("已放入 **12** 名机器人修士") and c.said("炮灰")
    assert len(await bots_of(db)) == 12
    assert any("spawn_bots" in r.getMessage() and "count=12" in r.getMessage() for r in caplog.records)


async def test_命令_生成_默认两千个_超限提示(db):
    cog, c = make_cog(), FakeContext(user_id=1)
    assert bw.DEFAULT_COUNT == 2000 and bw.MAX_BOTS == 20000
    await cog.spawn_bots.callback(cog, c, 30)
    assert len(await bots_of(db)) == 30
    c2 = FakeContext(user_id=1)
    await cog.spawn_bots.callback(cog, c2, bw.MAX_PER_BATCH + 1)
    assert c2.said(f"1~{bw.MAX_PER_BATCH}") and len(await bots_of(db)) == 30


async def test_命令_清除_必须确认(db, caplog):
    cog = make_cog()
    await bw.generate_bots(4)
    c = FakeContext(user_id=1)
    await cog.clear_bots.callback(cog, c)
    assert c.said("确认") and len(await bots_of(db)) == 4, "没带确认不能动手"
    c2 = FakeContext(user_id=1)
    with caplog.at_level(logging.WARNING, logger="mischicat.audit"):
        await cog.clear_bots.callback(cog, c2, "确认")
    assert c2.said("已清除 **4**") and await bots_of(db) == []
    assert any("clear_bots" in r.getMessage() and "removed=4" in r.getMessage() for r in caplog.records)


async def test_命令_只有所有者(db):
    cog = make_cog()
    for cmd in (cog.spawn_bots, cog.clear_bots):
        assert cmd.checks, f"{cmd.name} 没有任何检查"
        assert "is_owner" in cmd.checks[0].__qualname__
    c = FakeContext(user_id=2)
    await cog.sync_error(c, commands.NotOwner())
    assert c.said("只有 bot 所有者能用")


async def test_命令_数量写错的提示(db):
    cog, c = make_cog(), FakeContext(user_id=1)
    await cog.sync_error(c, commands.BadArgument("x"))
    assert c.said("数量要写整数")
