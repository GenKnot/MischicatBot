"""机器人每日结算（utils/bot_settle.py、cogs/botworld.py、cogs/admin.py 的 结算机器人）。

重点：
· 每个机器人每天只结一次（认领与结算同一个事务），崩了能续，一个出错不影响别人；
· 收入按全服上限缩放并按性格分成随身 / 钱庄；修炼耗寿元；开销消失；材料有上限、每种最多留 keep_per_item 件；
· 死亡（寿元耗尽 / 突破致死）连同名下的东西一起清走；补员每天一次、不超过 refill_rate、不改目标；
· 突破直接走游戏里的突破逻辑；三道大关先扣丹药钱（随身 → 钱庄），付不起就等，没走到消耗丹药就退款；
· 天花板：不超过最高真人所在大境；
· 真人不被碰。
"""

import asyncio
import logging
import random
import time
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from cogs.admin import AdminCog
from cogs.botworld import BotWorldCog
from tests.conftest import make_player
from tests.discord_fakes import FakeContext
from utils import bot_economy as be
from utils import bot_settle as bsl
from utils import bot_world
from utils.realms import cultivation_needed

TODAY = "2026-10-10"
_REAL_TODAY = bsl.today              # 导入时拿到真正的函数（fixture 之后会把它换成固定日期）


@pytest.fixture(autouse=True)
def fixed_day(monkeypatch):
    monkeypatch.setattr(bsl, "today", lambda: TODAY)


@pytest.fixture
def cfg(monkeypatch):
    """确定性的配置：收入无噪声，速度 1.0 时每天正好 12 个游戏年；用 set(...) 改局部。"""
    c = be.load_config()
    c["income_noise"] = [1.0, 1.0]
    c["wild"]["trip_chance"] = 0                          # 默认不去秘地；要测的用例自己设
    c["daily_cap_per_bot"] = 10**6                        # 默认不触发上限；要测上限的用例自己设
    holder = {"cfg": c}

    def set_(**kw):
        for k, v in kw.items():
            if isinstance(v, dict) and isinstance(holder["cfg"].get(k), dict):
                holder["cfg"][k].update(v)
            else:
                holder["cfg"][k] = v
    monkeypatch.setattr(be, "load_config", lambda: __import__("json").loads(__import__("json").dumps(holder["cfg"])))
    set_.cfg = holder["cfg"]
    return set_


async def mk(db, bot_id="bot_00001", tier="正常", archetype="豪爽", realm="炼气期3层", cultivation=0, lifespan=80,
             stones=0, bank=0, settled_day="", **kw):
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        p = make_player(D, bot_id, stones=stones)
        p.name, p.is_bot, p.realm, p.cultivation = f"道友{bot_id}", True, realm, cultivation
        p.lifespan, p.lifespan_max, p.current_city = lifespan, max(lifespan, 100), "灵虚城"
        p.spirit_root_type, p.comprehension = "单灵根", 5
        for k, v in kw.items():
            setattr(p, k, v)
        s.add(p)
        s.add(D.BotPersonality(bot_id=bot_id, archetype=archetype, tier=tier, settled_day=settled_day))
        if bank:
            s.add(D.BankAccount(discord_id=bot_id, demand_balance=bank))
        await s.commit()


async def human(db, uid="1001", realm="炼气期1层", **kw):
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        p = make_player(D, uid, stones=500)
        p.name, p.realm = f"真人{uid}", realm
        for k, v in kw.items():
            setattr(p, k, v)
        s.add(p)
        await s.commit()


async def snap(db, bot_id="bot_00001"):
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        p = await s.get(D.Player, bot_id)
        if p is None:
            return None
        acct = await s.get(D.BankAccount, bot_id)
        pers = await s.get(D.BotPersonality, bot_id)
        return SimpleNamespace(stones=p.spirit_stones, bank=acct.demand_balance if acct else 0, realm=p.realm,
                               cultivation=p.cultivation, lifespan=p.lifespan, dead=p.is_dead,
                               day=pers.settled_day if pers else None,
                               inv=await db["inventory"].get_inventory(bot_id))


async def run(**kw):
    kw.setdefault("rng", random.Random(0))
    return await bsl.run_settlement(**kw)


# ---- 收入 / 修炼 / 开销 -----------------------------------------------------

async def test_收入_按性格分成随身与钱庄_扣掉开销(db, cfg):
    cfg(speed={"正常": 0.0}, materials={"jobs_per_day": 0})                 # 只看钱
    await mk(db, archetype="豪爽")                                             # 随身 70%，开销 15%
    out = await run()
    s = await snap(db)
    assert out["settled"] == 1 and out["income"] == 200
    assert s.bank + s.stones + out["upkeep"] == 200, "钱不能凭空多或少"
    assert abs(s.bank - 60) <= 1, "豪爽随身 70%，钱庄 30%"
    assert out["upkeep"] == int((200 - s.bank) * 0.15), "开销是随身的 15%"
    assert s.day == TODAY


async def test_收入_全服上限按期望缩放(db, cfg):
    cfg(speed={"正常": 0.0}, daily_cap_per_bot=100, materials={"jobs_per_day": 0})   # 期望 200 → 缩到一半
    await mk(db, "bot_00001")
    await mk(db, "bot_00002")
    out = await run()
    assert out["income"] == 200                                              # 2 个 × 100
    a, b = await snap(db, "bot_00001"), await snap(db, "bot_00002")
    assert a.bank + a.stones + b.bank + b.stones + out["upkeep"] == 200


async def test_修炼_涨修为耗寿元(db, cfg, monkeypatch):
    monkeypatch.setattr(bsl, "_breakthrough", _noop_bt)
    cfg(speed={"正常": 0.5}, materials={"jobs_per_day": 0})                   # 活跃 6 年
    await mk(db, cultivation=0, lifespan=80, realm="炼气期3层")
    await run()
    s = await snap(db)
    gain = be.cultivation_gain(6, {"comprehension": 5, "spirit_root_type": "单灵根"})
    assert s.lifespan == 80 - 6
    assert s.cultivation == gain == 120                                       # 6 年 × 10 × 单灵根 2.0


async def test_修为封顶两倍_等着突破的人不会无限涨(db, cfg, monkeypatch):
    cfg(speed={"正常": 1.0}, materials={"jobs_per_day": 0})
    await mk(db, realm="炼气期3层", cultivation=190)
    D = db["db_async"]
    monkeypatch.setattr(bsl, "_breakthrough", _noop_bt)
    await run()
    assert (await snap(db)).cultivation == 2 * cultivation_needed("炼气期3层")


async def _noop_bt(*a, **k):
    return False


async def test_开销_花掉随身的一部分_消失(db, cfg):
    cfg(speed={"正常": 0.0}, income={"正常": 0}, materials={"jobs_per_day": 0})
    await mk(db, archetype="豪爽", stones=1000, bank=500)
    out = await run()
    s = await snap(db)
    assert s.stones == 850 and s.bank == 500 and out["upkeep"] == 150


async def test_材料_有每日价值上限(db, cfg, monkeypatch):
    cfg(speed={"正常": 0.0}, income={"正常": 0}, materials={"daily_cap_value_per_bot": 12})
    monkeypatch.setattr(be, "material_roll", lambda realm, c, rng=None: ["铜矿石"] * 5)         # 每个 5 灵石
    await mk(db)
    out = await run()
    s = await snap(db)
    assert s.inv == {"铜矿石": 2} and out["materials_value"] == 10, "预算 12，只够两件（每件 5）"


async def test_材料_每种最多留_keep_per_item(db, cfg, monkeypatch):
    cfg(speed={"正常": 0.0}, income={"正常": 0}, materials={"keep_per_item": 20, "daily_cap_value_per_bot": 1000})
    monkeypatch.setattr(be, "material_roll", lambda realm, c, rng=None: ["铜矿石"] * 3)
    await mk(db)
    await db["inventory"].add_item("bot_00001", "铜矿石", 30)
    await db["inventory"].add_item("bot_00001", "灵芝草", 5)
    await run()
    assert (await snap(db)).inv == {"铜矿石": 20, "灵芝草": 5}


async def test_材料_玩家送的礼物也受_keep_限制但不影响少量(db, cfg, monkeypatch):
    cfg(speed={"正常": 0.0}, income={"正常": 0}, materials={"jobs_per_day": 0})
    await mk(db)
    await db["inventory"].add_item("bot_00001", "筑基丹", 3)
    await run()
    assert (await snap(db)).inv == {"筑基丹": 3}


# ---- 每天一次 / 崩了能续 / 隔离 ----------------------------------------------

async def test_一天只结一次(db, cfg):
    cfg(speed={"正常": 0.0}, materials={"jobs_per_day": 0})
    await mk(db)
    first = await run()
    before = await snap(db)
    second = await run()
    after = await snap(db)
    assert first["settled"] == 1 and second["bots"] == 0 and second["settled"] == 0
    assert (before.stones, before.bank, before.cultivation) == (after.stones, after.bank, after.cultivation)


async def test_强制可以重结(db, cfg):
    cfg(speed={"正常": 0.0}, materials={"jobs_per_day": 0})
    await mk(db)
    await run()
    out = await run(force=True)
    assert out["settled"] == 1 and out["income"] == 200


async def test_第二天会再结(db, cfg, monkeypatch):
    cfg(speed={"正常": 0.0}, materials={"jobs_per_day": 0})
    await mk(db)
    await run()
    monkeypatch.setattr(bsl, "today", lambda: "2026-10-11")
    assert (await run())["settled"] == 1


async def test_并发两轮只有一个认领到(db, cfg):
    import asyncio
    cfg(speed={"正常": 0.0}, materials={"jobs_per_day": 0})
    await mk(db)
    a, b = await asyncio.gather(run(), run())
    assert a["settled"] + b["settled"] == 1 and a["income"] + b["income"] == 200
    s = await snap(db)
    assert s.stones + s.bank + a["upkeep"] + b["upkeep"] == 200


async def test_一个出错不影响别的_且出错的下一轮能重来(db, cfg, monkeypatch, caplog):
    cfg(speed={"正常": 0.0}, materials={"jobs_per_day": 0})
    await mk(db, "bot_00001")
    await mk(db, "bot_00002")
    await mk(db, "bot_00003")
    real = be.daily_income

    def flaky(tier, c, rng=random):
        if flaky.fail:
            flaky.fail = False
            raise RuntimeError("数据坏了")
        return real(tier, c, rng)
    flaky.fail = False
    monkeypatch.setattr(be, "daily_income", flaky)
    flaky.fail = True                                       # 排在最前的 bot_00001 出错
    with caplog.at_level(logging.ERROR):
        out = await run()
    assert out["errors"] == 1 and out["settled"] == 2 and "bot_00001" in caplog.text
    broken = await snap(db, "bot_00001")
    assert broken.day == "" and broken.stones == 0 and broken.bank == 0, "出错整体回滚，认领也撤销了"
    assert (await snap(db, "bot_00002")).day == TODAY
    again = await run()
    assert again["settled"] == 1 and (await snap(db, "bot_00001")).day == TODAY


async def test_材料掷骰中途出错也整体回滚(db, cfg, monkeypatch):
    cfg(speed={"正常": 0.0})
    await mk(db)

    def boom(*a, **k):
        raise RuntimeError("x")
    monkeypatch.setattr(be, "material_roll", boom)
    out = await run()
    s = await snap(db)
    assert out["errors"] == 1 and s.day == "" and s.stones == 0 and s.bank == 0 and s.lifespan == 80


async def test_没有性格行的机器人_和真人_都不碰(db, cfg):
    cfg(speed={"正常": 0.0}, materials={"jobs_per_day": 0})
    await human(db, "1001")
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        p = make_player(D, "bot_00009")
        p.name, p.is_bot = "无性格", True
        s.add(p)
        await s.commit()
    out = await run()
    assert out["bots"] == 0
    assert (await snap(db, "1001")).stones == 500 and (await snap(db, "bot_00009")).stones == 10_000


async def test_已坐化的机器人不结算(db, cfg):
    cfg(speed={"正常": 0.0})
    await mk(db, is_dead=True)
    assert (await run())["bots"] == 0


# ---- 死亡 / 补员 ------------------------------------------------------------

async def test_寿元耗尽_连同名下的东西一起清走(db, cfg):
    cfg(speed={"正常": 1.0}, materials={"jobs_per_day": 0})
    await mk(db, lifespan=5, stones=100, bank=100)
    await db["inventory"].add_item("bot_00001", "筑基丹", 1)
    out = await run()
    assert out["deaths"] == 1 and await snap(db) is None
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        assert (await s.get(D.BotPersonality, "bot_00001")) is None and (await s.get(D.BankAccount, "bot_00001")) is None
    assert await db["inventory"].get_inventory("bot_00001") == {}


async def test_补员_补到目标_每天最多_refill_rate(db, cfg):
    cfg(speed={"正常": 0.0}, materials={"jobs_per_day": 0}, refill_rate=0.1, refill_min_per_day=1)
    for i in range(1, 6):
        await mk(db, f"bot_{i:05d}")
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        await bot_world.set_state(s, "target", "50")
        await s.commit()
    out = await run()
    assert out["refilled"] == 5                                              # 50 × 10% = 5，缺 45 只补 5
    again = await run()
    assert again["refilled"] == 0, "同一天不补第二次（refill_day）"
    async with D.AsyncSessionLocal() as s:
        assert await bot_world.get_state(s, "target") == "50", "补员不改目标"


async def test_补员_每天至少补_refill_min_per_day(db, cfg):
    cfg(speed={"正常": 0.0}, materials={"jobs_per_day": 0}, refill_rate=0.001, refill_min_per_day=3)
    await mk(db)
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        await bot_world.set_state(s, "target", "10")
        await s.commit()
    assert (await run())["refilled"] == 3


async def test_补员_目标够了或没设就不补(db, cfg):
    cfg(speed={"正常": 0.0}, materials={"jobs_per_day": 0})
    await mk(db)
    assert (await run())["refilled"] == 0                                    # 没有目标
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        await bot_world.set_state(s, "target", "1")
        await s.commit()
    assert (await run(force=True))["refilled"] == 0                          # 已经够了


async def test_补员_第二天可以再补(db, cfg, monkeypatch):
    cfg(speed={"正常": 0.0}, materials={"jobs_per_day": 0}, refill_rate=0.1, refill_min_per_day=1)
    await mk(db)
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        await bot_world.set_state(s, "target", "30")
        await s.commit()
    first = await run()
    monkeypatch.setattr(bsl, "today", lambda: "2026-10-11")
    second = await run()
    assert first["refilled"] == 3 and second["refilled"] == 3


async def test_生成命令记下目标人数_清除归零(db, cfg):
    D = db["db_async"]
    await bot_world.generate_bots(7, random.Random(1))
    async with D.AsyncSessionLocal() as s:
        assert await bot_world.get_state(s, "target") == "7"
    await bot_world.generate_bots(3, random.Random(2))
    async with D.AsyncSessionLocal() as s:
        assert await bot_world.get_state(s, "target") == "10"
    await bot_world.clear_bots()
    async with D.AsyncSessionLocal() as s:
        assert await bot_world.get_state(s, "target") == ""
    cfg(speed={"正常": 0.0})
    assert (await run())["refilled"] == 0, "清除之后不会自己长出新的机器人"


async def test_死后补员_世界人数稳定(db, cfg):
    cfg(speed={"正常": 1.0, "炮灰": 1.0, "天骄": 1.0}, materials={"jobs_per_day": 0}, refill_rate=1.0)
    await bot_world.generate_bots(10, random.Random(3))
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        for p in (await s.execute(select(D.Player))).scalars():
            p.lifespan = 3                                                    # 全体今天寿尽
        await s.commit()
    out = await run()
    assert out["deaths"] == 10 and out["refilled"] == 10
    async with D.AsyncSessionLocal() as s:
        assert len(list((await s.execute(select(D.Player).where(D.Player.is_bot == True))).scalars())) == 10  # noqa: E712


# ---- 突破（直接走游戏里的突破逻辑）------------------------------------------

@pytest.fixture
def roll(monkeypatch):
    """让突破掷骰可控：roll(0.0) = 必成功，roll(0.999) = 必失败。"""
    def set_(value, outcome="light"):
        monkeypatch.setattr(random, "random", lambda: value)
        monkeypatch.setattr(random, "choices", lambda pop, weights=None, k=1: [outcome])
    return set_


async def test_突破_修为够了就晋级(db, cfg, roll):
    cfg(speed={"正常": 0.0}, income={"正常": 0}, materials={"jobs_per_day": 0})
    await human(db, "1001", realm="筑基期5层")
    await mk(db, realm="炼气期3层", cultivation=150)
    roll(0.0)
    out = await run()
    s = await snap(db)
    assert out["breakthroughs"] == 1 and s.realm == "炼气期4层" and s.cultivation == 50


async def test_突破_失败按游戏规则扣修为(db, cfg, roll):
    cfg(speed={"正常": 0.0}, income={"正常": 0}, materials={"jobs_per_day": 0})
    await human(db, "1001", realm="筑基期5层")
    await mk(db, realm="炼气期3层", cultivation=150)
    roll(0.999, "light")
    out = await run()
    s = await snap(db)
    assert out["bt_failures"] == 1 and s.realm == "炼气期3层" and s.cultivation == 75


async def test_突破_修为不够不尝试(db, cfg, roll):
    cfg(speed={"正常": 0.0}, income={"正常": 0}, materials={"jobs_per_day": 0})
    await mk(db, realm="炼气期3层", cultivation=99)
    roll(0.0)
    out = await run()
    assert out["breakthroughs"] == 0 and (await snap(db)).realm == "炼气期3层"


async def test_突破失败致死_清走(db, cfg, roll):
    cfg(speed={"正常": 0.0}, income={"正常": 0}, materials={"jobs_per_day": 0})
    await human(db, "1001", realm="筑基期5层")
    await mk(db, realm="炼气期3层", cultivation=150, lifespan=1)
    roll(0.999, "deviate")                                                    # 走火入魔：寿元大损
    out = await run()
    assert out["bt_failures"] == 1 and out["deaths"] == 1 and await snap(db) is None


async def test_突破_正在闭关不打扰(db, cfg, roll):
    cfg(speed={"正常": 0.0}, income={"正常": 0}, materials={"jobs_per_day": 0})
    await human(db, "1001", realm="筑基期5层")
    await mk(db, realm="炼气期3层", cultivation=150, cultivating_until=time.time() + 3600)
    roll(0.0)
    assert (await run())["breakthroughs"] == 0


# ---- 天花板 -----------------------------------------------------------------

async def test_天花板_没有真人时不超过炼气期(db, cfg, roll):
    cfg(speed={"正常": 0.0}, income={"正常": 0}, materials={"jobs_per_day": 0})
    await mk(db, realm="炼气期10层", cultivation=200, stones=5000)
    roll(0.0)
    out = await run()
    assert out["capped"] == 1 and out["breakthroughs"] == 0 and out["pills"] == 0
    assert (await snap(db)).realm == "炼气期10层", "到天花板了，也没有白白买丹"


async def test_天花板_真人到了筑基机器人才能过大关(db, cfg, roll):
    cfg(speed={"正常": 0.0}, income={"正常": 0}, materials={"jobs_per_day": 0})
    await human(db, "1001", realm="筑基期2层")
    await mk(db, realm="炼气期10层", cultivation=200, stones=5000)
    roll(0.0)
    out = await run()
    assert out["breakthroughs"] == 1 and (await snap(db)).realm == "筑基期1层"


async def test_天花板_最高真人所在大境的末层是上限(db, cfg, roll):
    cfg(speed={"正常": 0.0}, income={"正常": 0}, materials={"jobs_per_day": 0})
    await human(db, "1001", realm="筑基期2层")
    await mk(db, realm="筑基期10层", cultivation=400, stones=9000)            # 要吃凝丹丹进结丹期
    roll(0.0)
    out = await run()
    assert out["capped"] == 1 and (await snap(db)).realm == "筑基期10层"


async def test_天花板_坐化的真人不算_机器人不算(db, cfg, roll):
    cfg(speed={"正常": 0.0}, income={"正常": 0}, materials={"jobs_per_day": 0})
    await human(db, "1001", realm="元婴期初期", is_dead=True)
    await mk(db, "bot_00002", realm="结丹期初期")
    await mk(db, realm="炼气期10层", cultivation=200, stones=5000)
    async with db["db_async"].AsyncSessionLocal() as s:
        assert await bot_world.current_ceiling_index(s) == 9


async def test_天花板_覆盖配置(db, cfg, roll):
    cfg(speed={"正常": 0.0}, income={"正常": 0}, materials={"jobs_per_day": 0}, ceiling={"override": "筑基期"})
    await human(db, "1001", realm="太乙中期")                                  # 现网那个调试账号
    await mk(db, realm="炼气期10层", cultivation=200, stones=5000)
    roll(0.0)
    assert (await run())["breakthroughs"] == 1


async def test_出生按天花板收住(db, cfg):
    await bot_world.generate_bots(60, random.Random(5))
    D = db["db_async"]
    from utils.realms import get_realm_index
    async with D.AsyncSessionLocal() as s:
        realms = [p.realm for p in (await s.execute(select(D.Player))).scalars()]
    assert max(get_realm_index(r) for r in realms) <= 9
    await human(db, "1001", realm="元婴期初期")
    await bot_world.generate_bots(150, random.Random(6))
    async with D.AsyncSessionLocal() as s:
        realms = [p.realm for p in (await s.execute(select(D.Player).where(D.Player.is_bot == True))).scalars()]  # noqa: E712
    assert max(get_realm_index(r) for r in realms) > 9, "真人到了元婴，机器人才可能出生在筑基 / 结丹"


# ---- 三道大关：买丹 ---------------------------------------------------------

def gate_setup(cfg):
    cfg(speed={"正常": 0.0}, income={"正常": 0}, materials={"jobs_per_day": 0}, ceiling={"override": "元婴期"})


async def test_大关_先扣随身再扣钱庄_吃丹突破(db, cfg, roll):
    gate_setup(cfg)
    await mk(db, realm="炼气期10层", cultivation=200, stones=300, bank=900, archetype="高冷")
    roll(0.0)
    out = await run()
    s = await snap(db)
    assert out["breakthroughs"] == 1 and out["pills"] == 1000 and s.realm == "筑基期1层"
    upkeep = out["upkeep"]
    assert upkeep == 21, "先花掉随身的 7%（高冷），随身剩 279"
    assert s.stones == 0 and s.bank == 179, "随身 279 全付，钱庄付 721；付完随身为 0"
    assert "筑基丹" not in s.inv, "丹药被用掉了"


async def test_大关_失败也吃掉了丹(db, cfg, roll):
    gate_setup(cfg)
    await mk(db, realm="炼气期10层", cultivation=200, stones=0, bank=1200)
    roll(0.999, "light")
    out = await run()
    s = await snap(db)
    assert out["bt_failures"] == 1 and out["pills"] == 1000 and s.bank == 200 and s.realm == "炼气期10层"
    assert "筑基丹" not in s.inv


async def test_大关_买不起就等_什么都不扣(db, cfg, roll):
    gate_setup(cfg)
    await mk(db, realm="炼气期10层", cultivation=200, stones=400, bank=500, archetype="高冷")
    roll(0.0)
    out = await run()
    s = await snap(db)
    assert out["gate_wait"] == 1 and out["pills"] == 0 and s.realm == "炼气期10层" and s.bank == 500
    assert s.stones == 400 - int(400 * 0.07)


async def test_大关_没走到吃丹就退款(db, cfg, monkeypatch):
    """游戏里的突破逻辑拒绝了（状态变了）：丹药收回、钱原样退（随身退随身、钱庄退钱庄）。"""
    gate_setup(cfg)
    await mk(db, realm="炼气期10层", cultivation=200, stones=300, bank=900, archetype="高冷")

    async def refuse(bot_id, use_pill):
        return {"success": False, "message": "状态已变化"}
    monkeypatch.setitem(bsl.PILL_HANDLERS, "筑基丹", refuse)
    out = await run()
    s = await snap(db)
    assert out["pills"] == 0 and out["breakthroughs"] == 0
    assert s.bank == 900 and s.stones == 300 - int(300 * 0.07) and "筑基丹" not in s.inv


async def test_大关_凝丹与化婴价格不同(db, cfg, roll):
    gate_setup(cfg)
    await mk(db, "bot_00001", realm="筑基期10层", cultivation=300, bank=3000)
    await mk(db, "bot_00002", realm="结丹期后期", cultivation=800, bank=8000)
    roll(0.0)
    out = await run()
    assert out["pills"] == 3000 + 8000 and out["breakthroughs"] == 2
    assert (await snap(db, "bot_00001")).realm == "结丹期初期" and (await snap(db, "bot_00002")).realm == "元婴期初期"


# ---- 真人不受影响 -----------------------------------------------------------

async def test_真人原样(db, cfg, roll):
    cfg(speed={"正常": 1.0}, materials={"jobs_per_day": 3})
    await human(db, "1001", realm="筑基期1层", cultivation=50, lifespan=60)
    await db["inventory"].add_item("1001", "铜矿石", 50)
    await mk(db)
    roll(0.0)
    await run()
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        h = await s.get(D.Player, "1001")
        assert (h.spirit_stones, h.cultivation, h.lifespan, h.realm) == (500, 50, 60, "筑基期1层")
        assert await s.get(D.BotPersonality, "1001") is None
    assert await db["inventory"].get_inventory("1001") == {"铜矿石": 50}


async def test_remove_bots_绝不删真人(db):
    await human(db, "1001")
    await mk(db)
    out = await bot_world.remove_bots(["1001", "bot_00001"])
    assert out["removed"] == 1 and (await snap(db, "1001")) is not None and await snap(db) is None
    assert (await bot_world.remove_bots(["1001"]))["removed"] == 0
    assert (await bot_world.remove_bots([]))["removed"] == 0


# ---- 后台任务与管理员命令 ---------------------------------------------------

async def test_后台任务调用结算(db, monkeypatch):
    calls = []

    async def fake(**kw):
        calls.append(kw)
        return {}
    monkeypatch.setattr(bsl, "run_settlement", fake)
    cog = BotWorldCog(bot=SimpleNamespace())
    await cog._daily_settlement.coro(cog)
    assert calls == [{}]


async def test_后台任务出错不让循环停(db, monkeypatch, caplog):
    async def boom(**kw):
        raise RuntimeError("库挂了")
    monkeypatch.setattr(bsl, "run_settlement", boom)
    cog = BotWorldCog(bot=SimpleNamespace())
    with caplog.at_level(logging.ERROR):
        await cog._daily_settlement.coro(cog)
    assert "机器人每日结算 本轮出错" in caplog.text


async def test_后台任务随_cog_启停(db):
    class Bot:
        async def wait_until_ready(self):
            await asyncio.sleep(3600)                       # 一直等着，不让任务真的跑
    cog = BotWorldCog(bot=Bot())
    await cog.cog_load()
    assert cog._daily_settlement.is_running()
    await cog.cog_unload()
    await asyncio.sleep(0.05)
    assert not cog._daily_settlement.is_running()


async def test_setup注册(db):
    from cogs import botworld
    added = []

    class Bot:
        async def add_cog(self, c):
            added.append(c)
    await botworld.setup(Bot())
    assert isinstance(added[0], BotWorldCog)


def _bot_py_loads_botworld():
    return 'load_extension("cogs.botworld")' in open("bot.py", encoding="utf-8").read()


def test_bot启动时加载这个_cog():
    assert _bot_py_loads_botworld()


async def test_命令_结算机器人(db, cfg, caplog):
    cfg(speed={"正常": 0.0}, materials={"jobs_per_day": 0})
    await mk(db)
    cog, c = AdminCog(SimpleNamespace(tree=None)), FakeContext(user_id=1)
    with caplog.at_level(logging.WARNING, logger="mischicat.audit"):
        await cog.settle_bots.callback(cog, c)
    assert c.said("已结算 **1** 名机器人") and any("settle_bots" in r.getMessage() for r in caplog.records)
    c2 = FakeContext(user_id=1)
    await cog.settle_bots.callback(cog, c2)
    assert c2.said("已经全部结算过了")
    c3 = FakeContext(user_id=1)
    await cog.settle_bots.callback(cog, c3, "强制")
    assert c3.said("已结算 **1** 名机器人")


async def test_命令_只有所有者(db):
    cog = AdminCog(SimpleNamespace(tree=None))
    assert cog.settle_bots.checks and "is_owner" in cog.settle_bots.checks[0].__qualname__


# ---- 迁移 -------------------------------------------------------------------

def test_迁移补上新表新列(tmp_path):
    import os
    import sqlite3
    import subprocess
    import sys
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    path = tmp_path / "old.db"
    env = dict(os.environ, DB_PATH=str(path))

    def alembic(*a):
        return subprocess.run([sys.executable, "-m", "alembic", "-c", os.path.join(root, "alembic.ini"), *a],
                              cwd=root, env=env, capture_output=True, text=True)

    assert alembic("upgrade", "7b1c4e9d2a60").returncode == 0
    conn = sqlite3.connect(path)
    conn.execute("DROP TABLE bot_world_state")                              # 基线按当前 ORM 建表，这里模拟真正的老库
    conn.execute("ALTER TABLE bot_personality DROP COLUMN settled_day")
    conn.execute("INSERT INTO bot_personality (bot_id, archetype) VALUES ('bot_00001', '豪爽')")
    conn.commit()
    conn.close()
    assert alembic("upgrade", "head").returncode == 0
    conn = sqlite3.connect(path)
    assert conn.execute("SELECT settled_day FROM bot_personality").fetchone() == ("",), "老行默认 ''，下次结算会被当作没结过"
    conn.execute("INSERT INTO bot_world_state (key, value) VALUES ('target', '5')")
    conn.close()
    assert alembic("upgrade", "head").returncode == 0                       # 幂等


# ---- 跨天的账目守恒 ---------------------------------------------------------

async def test_连续十天_机器人手里的钱_等于收入减去开销和买丹(db, cfg, monkeypatch, roll):
    """没有人死亡的情形下，整个机器人世界的灵石（随身 + 钱庄）只会因为三件事变化：发的收入、日常开销、买丹。"""
    cfg(speed={"炮灰": 0.3, "正常": 0.3, "天骄": 0.3}, materials={"jobs_per_day": 0}, ceiling={"override": "筑基期"})
    await human(db, "1001", realm="筑基期5层")
    await bot_world.generate_bots(40, random.Random(11))
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:                                    # 保证 10 天内没有人老死
        for p in (await s.execute(select(D.Player).where(D.Player.is_bot == True))).scalars():  # noqa: E712
            p.lifespan = p.lifespan_max = 5000
        await s.commit()

    async def total():
        async with D.AsyncSessionLocal() as s:
            stones = sum(p.spirit_stones for p in (await s.execute(select(D.Player).where(D.Player.is_bot == True))).scalars())  # noqa: E712
            bank = sum(a.demand_balance for a in (await s.execute(select(D.BankAccount))).scalars())
        return stones + bank
    start, income, upkeep, pills = await total(), 0, 0, 0
    rng = random.Random(5)
    for d in range(10):
        monkeypatch.setattr(bsl, "today", lambda d=d: f"2026-11-{d + 1:02d}")
        out = await bsl.run_settlement(rng=rng)
        income, upkeep, pills = income + out["income"], upkeep + out["upkeep"], pills + out["pills"]
        assert out["errors"] == 0 and out["deaths"] == 0
    assert income > 0 and upkeep > 0
    assert await total() == start + income - upkeep - pills


# ---- 边角 -------------------------------------------------------------------

def test_today是年月日():
    import re
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", _REAL_TODAY())


async def test_认领时玩家已经死了_回滚不改(db, cfg):
    """查出来之后、认领之前机器人被别处弄死了（比如被击杀）：不发钱，认领也撤销。"""
    cfg(speed={"正常": 0.0}, materials={"jobs_per_day": 0})
    await mk(db, is_dead=True)
    out = await bsl._settle_economy("bot_00001", "正常", "豪爽", TODAY, False, be.load_config(), 1.0,
                                    random.Random(0), {"left": 100}, __import__("collections").Counter())
    s = await snap(db)
    assert out is None and s.day == "" and s.stones == 0 and s.bank == 0


async def test_补员失败只记日志(db, cfg, monkeypatch, caplog):
    cfg(speed={"正常": 0.0}, materials={"jobs_per_day": 0})
    await mk(db)
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        await bot_world.set_state(s, "target", "50")
        await s.commit()
    monkeypatch.setattr(bot_world, "MAX_BOTS", 1)                           # 已经满了：生成会被拒绝
    with caplog.at_level(logging.WARNING):
        out = await run()
    assert out["refilled"] == 0 and "补员失败" in caplog.text


async def test_补员出异常不影响本轮_也不崩(db, cfg, monkeypatch, caplog):
    cfg(speed={"正常": 0.0}, materials={"jobs_per_day": 0})
    await mk(db)
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        await bot_world.set_state(s, "target", "50")
        await s.commit()

    async def boom(*a, **k):
        raise RuntimeError("库挂了")
    monkeypatch.setattr(bot_world, "generate_bots", boom)
    with caplog.at_level(logging.ERROR):
        out = await run()
    assert out["errors"] == 1 and out["settled"] == 1 and "机器人补员失败" in caplog.text


async def test_付丹钱_随身不够钱庄也不够_什么都不扣(db):
    await mk(db, stones=100, bank=200)
    async with db["db_async"].AsyncSessionLocal() as session:
        assert await bsl._pay_from_wealth(session, "bot_00001", 500) is None
    s = await snap(db)
    assert (s.stones, s.bank) == (100, 200)


async def test_付丹钱_钱庄并发被取走_回滚返回None(db):
    """读到钱庄够、扣的时候已经被别人取走（条件 UPDATE 不命中）：整体回滚，不留半扣状态。"""
    class FakeSession:
        def __init__(self):
            self.rolled, self.values = False, iter([100, 1000])

        async def scalar(self, stmt):
            return next(self.values)

        async def execute(self, stmt):
            return SimpleNamespace(rowcount=0)

        async def rollback(self):
            self.rolled = True
    fake = FakeSession()
    import utils.bot_settle as mod

    async def ok(session, bot_id, amount):
        return True
    orig = mod.spend_stones
    mod.spend_stones = ok
    try:
        assert await mod._pay_from_wealth(fake, "bot_00001", 500) is None
    finally:
        mod.spend_stones = orig
    assert fake.rolled


async def test_付丹钱_随身扣不动_返回None(db, monkeypatch):
    await mk(db, stones=1000)

    async def no(session, bot_id, amount):
        return False
    monkeypatch.setattr(bsl, "spend_stones", no)
    async with db["db_async"].AsyncSessionLocal() as session:
        assert await bsl._pay_from_wealth(session, "bot_00001", 500) is None


async def test_before_loop等待就绪(db):
    waited = []

    class Bot:
        async def wait_until_ready(self):
            waited.append(1)
    await BotWorldCog(bot=Bot())._before_settlement()
    assert waited == [1]


async def test_同一个机器人认领第二次被跳过(db, cfg):
    """认领是条件 UPDATE：同一天第二次（别的循环抢先、或手动结算撞上）拿不到，计入 skipped，不发钱。"""
    from collections import Counter
    cfg(speed={"正常": 0.0}, materials={"jobs_per_day": 0})
    await mk(db)
    sm = Counter()
    args = ("bot_00001", "正常", "豪爽", TODAY, False, be.load_config(), 1.0, 9, random.Random(0), {"left": 100}, sm)
    await bsl._settle_bot(*args)
    await bsl._settle_bot(*args)
    assert sm["settled"] == 1 and sm["skipped"] == 1 and sm["income"] == 200


async def test_装备只留最好的几件(db, cfg):
    """守城 / 拍卖会给机器人发装备，机器人不穿：每天只留品阶最高的 keep_equipment 件。"""
    cfg(speed={"正常": 0.0}, income={"正常": 0}, materials={"jobs_per_day": 0, "keep_equipment": 3})
    await mk(db)
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        for i in range(6):
            s.add(D.Equipment(equip_id=f"E{i}", discord_id="bot_00001", name=f"装备{i}", slot="武器", quality="普通",
                              tier=i, tier_req=0, stats="{}", flavor="", equipped=False))
        s.add(D.Equipment(equip_id="H1", discord_id="1001", name="真人的装备", slot="武器", quality="普通", tier=0,
                          tier_req=0, stats="{}", flavor="", equipped=False))
        await s.commit()
    await run()
    async with D.AsyncSessionLocal() as s:
        mine = sorted(e.equip_id for e in (await s.execute(select(D.Equipment).where(D.Equipment.discord_id == "bot_00001"))).scalars())
        humans = (await s.execute(select(D.Equipment).where(D.Equipment.discord_id == "1001"))).scalars().all()
    assert mine == ["E3", "E4", "E5"] and len(humans) == 1
