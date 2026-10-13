"""劫杀机器人（utils/bot_combat.py、utils/views/combat.py、机器人去秘地历练）。

用户 2026-10-10 的决定：机器人每天按概率去秘地历练（只有秘地能动手）；打劫拿随身 15%（≤150）、每人每天 3 次；
击杀拿随身 30%（≤300）、钱庄随人消失、每人每天 5 次；声望 -1/-2/-5（天骄 -10），被劫的机器人记仇；
真人打输了被擒获时机器人按性格处置（放走 / 劫 15% / 杀），杀真人的总开关默认关。
"""

import asyncio
import logging
import random
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from tests.conftest import make_player
from tests.discord_fakes import FakeInteraction
from utils import bot_combat as bc
from utils import bot_economy as be
from utils import bot_settle as bsl
from utils import bot_social
from utils import combat as combat_mod
from utils.views.combat import PlayerActionView, VictoryActionView

H, B = "1001", "bot_00001"
WILD, CITY = "万妖岭", "灵虚城"
TODAY = "2026-10-10"
_REAL_TODAY = bc.today              # 导入时拿到真正的函数（fixture 会把它换成固定日期）


@pytest.fixture(autouse=True)
def fixed_day(monkeypatch):
    monkeypatch.setattr(bc, "today", lambda: TODAY)
    monkeypatch.setattr(bsl, "today", lambda: TODAY)


@pytest.fixture
def cfg(monkeypatch):
    """可改的配置；用 set(combat={...}) 整块替换某一项（只覆盖给出的键）。"""
    import json
    holder = be.load_config()

    def set_(**kw):
        for k, v in kw.items():
            if isinstance(v, dict) and isinstance(holder.get(k), dict):
                holder[k].update(v)
            else:
                holder[k] = v

    monkeypatch.setattr(be, "load_config", lambda: json.loads(json.dumps(holder)))
    set_.cfg = holder
    return set_


async def mk_human(db, uid=H, city=WILD, **kw):
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        p = make_player(D, uid, stones=kw.pop("stones", 1000))
        p.name, p.current_city, p.lifespan, p.lifespan_max = f"真人{uid}", city, 80, 100
        p.reputation = kw.pop("reputation", 10)
        for k, v in kw.items():
            setattr(p, k, v)
        s.add(p)
        await s.commit()


async def mk_bot(db, bot_id=B, city=WILD, stones=1000, bank=500, tier="正常", archetype="豪爽", **kw):
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        p = make_player(D, bot_id, stones=stones)
        p.name, p.is_bot, p.current_city, p.lifespan, p.lifespan_max = f"道友{bot_id}", True, city, 80, 100
        p.cultivation = kw.pop("cultivation", 50)
        for k, v in kw.items():
            setattr(p, k, v)
        s.add(p)
        s.add(D.BotPersonality(bot_id=bot_id, archetype=archetype, tier=tier, home_city=CITY))
        if bank:
            s.add(D.BankAccount(discord_id=bot_id, demand_balance=bank))
        await s.commit()


async def get(db, uid):
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        return await s.get(D.Player, uid)


async def raids(db, uid=H):
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        r = await s.get(D.BotRaid, (uid, TODAY))
        return (r.robs, r.kills) if r else (0, 0)


# ---- 打劫 -------------------------------------------------------------------

async def test_打劫_拿随身的百分之十五_声望减一_记仇(db):
    await mk_human(db, stones=100)
    await mk_bot(db, stones=1000)
    res = await bc.rob_bot(H, B)
    assert res["ok"] and res["amount"] == 150 and res["favor"] == -40
    assert (await get(db, H)).spirit_stones == 250 and (await get(db, B)).spirit_stones == 850
    assert (await get(db, H)).reputation == 9
    assert bot_social.favor_tier(await bot_social.get_favor(H, B)) == "仇视"
    assert await raids(db) == (1, 0)


@pytest.mark.parametrize("stones,expect", [(400, 60), (1000, 150), (5000, 150), (6, 0)])
async def test_打劫_比例与单次上限(db, stones, expect):
    await mk_human(db)
    await mk_bot(db, stones=stones)
    res = await bc.rob_bot(H, B)
    assert res["ok"] is (expect > 0) and res.get("amount", 0) == expect


async def test_打劫_落空不占次数_不扣声望_不改好感_但记一笔轻仇(db):
    from utils import bot_grudges
    await mk_human(db)
    await mk_bot(db, stones=0)
    res = await bc.rob_bot(H, B)
    assert res["ok"] is False and "没什么油水" in res["reason"]
    assert await raids(db) == (0, 0) and (await get(db, H)).reputation == 10
    assert await bot_social.get_favor(H, B) == 0
    (g,) = await bot_grudges.grudges_of(B)
    assert g["kind"] == "rob_fail" and g["target"] == H and "曾想打劫你" in g["reason"] and g["severity"] < 20


async def test_打劫_每人每天三次_第二天重新算(db, monkeypatch):
    await mk_human(db)
    await mk_bot(db, stones=100_000)
    assert [(await bc.rob_bot(H, B))["ok"] for _ in range(3)] == [True] * 3
    res = await bc.rob_bot(H, B)
    assert res["ok"] is False and "3 次" in res["reason"]
    assert await raids(db) == (3, 0)
    monkeypatch.setattr(bc, "today", lambda: "2026-10-11")
    assert (await bc.rob_bot(H, B))["ok"]


async def test_打劫_次数按人算_别人不受影响(db):
    await mk_human(db, H)
    await mk_human(db, "1002")
    await mk_bot(db, stones=100_000)
    for _ in range(3):
        await bc.rob_bot(H, B)
    assert (await bc.rob_bot("1002", B))["ok"]


async def test_打劫_并发只有上限那么多次(db, cfg):
    cfg(combat={"rob": {"share": 0.15, "cap": 150, "per_human_per_day": 2}})
    await mk_human(db)
    await mk_bot(db, stones=100_000)
    results = await asyncio.gather(*[bc.rob_bot(H, B) for _ in range(6)])
    assert sum(r["ok"] for r in results) == 2 and await raids(db) == (2, 0)
    assert (await get(db, H)).spirit_stones == 1000 + 300


@pytest.mark.parametrize("case", ["far", "bot_dead", "me_dead", "target_human"])
async def test_打劫_条件不满足什么都不改(db, case):
    await mk_human(db, is_dead=(case == "me_dead"))
    await mk_bot(db, city=CITY if case == "far" else WILD, is_dead=(case == "bot_dead"))
    target = B
    if case == "target_human":
        await mk_human(db, "1002")
        target = "1002"
    res = await bc.rob_bot(H, target)
    assert res["ok"] is False and res["reason"]
    assert await raids(db) == (0, 0) and (await get(db, H)).spirit_stones == 1000


async def test_声望扣到零为止(db):
    await mk_human(db, reputation=0)
    await mk_bot(db)
    await bc.rob_bot(H, B)
    assert (await get(db, H)).reputation == 0


# ---- 废修为 -----------------------------------------------------------------

async def test_废修为_归零_声望减二_好感减六十_与打劫共用次数(db):
    await mk_human(db)
    await mk_bot(db, cultivation=500)
    res = await bc.cripple_bot(H, B)
    assert res["ok"] and res["favor"] == -60
    assert (await get(db, B)).cultivation == 0 and (await get(db, H)).reputation == 8
    assert await raids(db) == (1, 0)
    await bc.rob_bot(H, B)
    await bc.cripple_bot(H, B)
    assert (await bc.cripple_bot(H, B))["ok"] is False, "打劫和废修为合起来每天 3 次"


# ---- 击杀 -------------------------------------------------------------------

async def test_击杀_拿随身三成_钱庄随人消失_机器人被清走(db):
    await mk_human(db, stones=0)
    await mk_bot(db, stones=1000, bank=800)
    await db["inventory"].add_item(B, "筑基丹", 1)
    res = await bc.kill_bot(H, B)
    assert res["ok"] and res["amount"] == 300                              # 30% = 300，刚好到上限
    assert (await get(db, H)).spirit_stones == 300 and (await get(db, H)).reputation == 5
    assert await get(db, B) is None
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        assert await s.get(D.BankAccount, B) is None and await s.get(D.BotPersonality, B) is None
    assert await db["inventory"].get_inventory(B) == {}
    assert await raids(db) == (0, 1)


@pytest.mark.parametrize("stones,expect", [(500, 150), (1000, 300), (9000, 300), (0, 0)])
async def test_击杀_比例与上限_身上没钱也能杀(db, stones, expect):
    await mk_human(db, stones=0)
    await mk_bot(db, stones=stones)
    res = await bc.kill_bot(H, B)
    assert res["ok"] and res["amount"] == expect and (await get(db, H)).spirit_stones == expect


async def test_击杀_天骄声望扣十(db):
    await mk_human(db, reputation=30)
    await mk_bot(db, tier="天骄")
    await bc.kill_bot(H, B)
    assert (await get(db, H)).reputation == 20


async def test_击杀_每人每天五次_落空不占次数(db, cfg):
    cfg(combat={"kill": {"share": 0.30, "cap": 300, "per_human_per_day": 5, "global_per_day": 100}})
    await mk_human(db)
    for i in range(1, 8):
        await mk_bot(db, f"bot_{i:05d}", stones=0, bank=0)
    ok = [(await bc.kill_bot(H, f"bot_{i:05d}"))["ok"] for i in range(1, 8)]
    assert ok == [True] * 5 + [False] * 2
    assert await raids(db) == (0, 5)
    res = await bc.kill_bot(H, "bot_00006")
    assert "5 名" in res["reason"]


async def test_击杀_已经死了的落空_不占次数(db):
    await mk_human(db)
    await mk_bot(db, is_dead=True)
    assert (await bc.kill_bot(H, B))["ok"] is False and await raids(db) == (0, 0)


async def test_击杀_名下玩家不被连带(db):
    await mk_human(db, "1002")
    await mk_human(db)
    await mk_bot(db)
    await bc.kill_bot(H, B)
    assert (await get(db, "1002")) is not None


# ---- 打输了被擒获 -----------------------------------------------------------

@pytest.fixture
def reaction(cfg):
    def set_(archetype, **weights):
        cfg.cfg["combat"]["reaction"][archetype] = weights
    return set_


async def test_擒获_憨直放走_什么都不丢(db, reaction):
    await mk_human(db, stones=1000)
    await mk_bot(db, archetype="憨直")
    res = await bc.handle_captive(B, H, random.Random(0))
    assert res == {"outcome": "release", "amount": 0, "killed": False}
    assert (await get(db, H)).spirit_stones == 1000


async def test_擒获_劫随身百分之十五_给机器人(db, reaction):
    reaction("贪财", rob=100)
    await mk_human(db, stones=2000)
    await mk_bot(db, archetype="贪财", stones=0)
    res = await bc.handle_captive(B, H, random.Random(0))
    assert res["outcome"] == "rob" and res["amount"] == 150                  # 15% = 300，单次上限 150
    assert (await get(db, H)).spirit_stones == 1850 and (await get(db, B)).spirit_stones == 150


async def test_擒获_身上没钱可劫就放走(db, reaction):
    reaction("贪财", rob=100)
    await mk_human(db, stones=0)
    await mk_bot(db, archetype="贪财")
    assert (await bc.handle_captive(B, H, random.Random(0)))["outcome"] == "release"


async def test_擒获_默认的正常模式机器人不杀人(db, reaction):
    """现网升级默认『正常』模式：机器人不杀玩家（配置里的 can_kill_humans 只是硬上限，默认放开）。"""
    assert be.load_config()["combat"]["can_kill_humans"] is True
    reaction("阴鸷", kill=100)
    await mk_human(db, stones=1000, realm="筑基期5层")
    await mk_bot(db, archetype="阴鸷")
    res = await bc.handle_captive(B, H, random.Random(0))
    assert res["outcome"] == "rob" and res["killed"] is False, "模式不允许：杀的权重并入劫财"
    assert not (await get(db, H)).is_dead


@pytest.mark.parametrize("mode,kills", [("幸福", False), ("正常", False), ("真实", True)])
async def test_擒获_只有真实模式才杀(db, reaction, mode, kills):
    from utils import world_settings
    await world_settings.set_values(mode=mode)
    reaction("阴鸷", kill=100)
    await mk_human(db, stones=1000, realm="筑基期5层")
    await mk_bot(db, archetype="阴鸷")
    assert (await bc.handle_captive(B, H, random.Random(0)))["killed"] is kills


async def test_擒获_配置里关掉can_kill_humans_真实模式也不杀(db, reaction, cfg):
    from utils import world_settings
    await world_settings.set_values(mode="真实")
    cfg(combat={"can_kill_humans": False})
    reaction("阴鸷", kill=100)
    await mk_human(db, stones=1000, realm="筑基期5层")
    await mk_bot(db, archetype="阴鸷")
    assert (await bc.handle_captive(B, H, random.Random(0)))["killed"] is False


async def test_擒获_真实模式_高境界的真人会被杀(db, reaction, caplog):
    from utils import world_settings
    await world_settings.set_values(mode="真实")
    reaction("阴鸷", kill=100)
    await mk_human(db, stones=1000, realm="筑基期5层")
    await mk_bot(db, archetype="阴鸷", stones=0)
    with caplog.at_level(logging.WARNING):
        res = await bc.handle_captive(B, H, random.Random(0))
    h = await get(db, H)
    assert res["outcome"] == "kill" and res["killed"] and h.is_dead and h.lifespan == 0
    assert res["amount"] == 150 and h.spirit_stones == 850, "杀之前先搜走一份"
    assert "击杀了真人" in caplog.text


async def test_擒获_新手受保护_永远不杀(db, reaction):
    from utils import world_settings
    await world_settings.set_values(mode="真实")
    reaction("阴鸷", kill=100)
    await mk_human(db, stones=1000, realm="炼气期9层")                        # 低于 kill_protect_below（筑基期1层）
    await mk_bot(db, archetype="阴鸷")
    for seed in range(20):
        res = await bc.handle_captive(B, H, random.Random(seed))
        assert res["outcome"] != "kill" and not res["killed"]
    assert not (await get(db, H)).is_dead


async def test_擒获_不在同一个地方就放走(db, reaction):
    from utils import world_settings
    await world_settings.set_values(mode="真实")
    reaction("阴鸷", kill=100)
    await mk_human(db, realm="筑基期5层")
    await mk_bot(db, archetype="阴鸷", city=CITY)
    assert (await bc.handle_captive(B, H, random.Random(0)))["outcome"] == "release"


def test_处置权重_杀并入劫财():
    cfg = be.load_config()
    counts = {"release": 0, "rob": 0, "kill": 0}
    rng = random.Random(3)
    for _ in range(3000):
        counts[be.captive_outcome("阴鸷", cfg, can_kill=False, rng=rng)] += 1
    assert counts["kill"] == 0 and 0.7 < counts["rob"] / 3000 < 0.9              # 50 + 30 = 80%
    counts = {"release": 0, "rob": 0, "kill": 0}
    for _ in range(3000):
        counts[be.captive_outcome("阴鸷", cfg, can_kill=True, rng=rng)] += 1
    assert 0.2 < counts["kill"] / 3000 < 0.4
    assert {be.captive_outcome("憨直", cfg, can_kill=True, rng=rng) for _ in range(100)} == {"release"}


# ---- 战力加成 ---------------------------------------------------------------

async def test_战力加成_机器人按档位_真人没有(db):
    await mk_human(db)
    await mk_bot(db, "bot_00001", tier="炮灰")
    await mk_bot(db, "bot_00002", tier="正常")
    await mk_bot(db, "bot_00003", tier="天骄")
    pm = {u: await bc.power_multiplier({"discord_id": u, "is_bot": u.startswith("bot_")}) for u in (H, "bot_00001", "bot_00002", "bot_00003")}
    assert pm == {H: 1.0, "bot_00001": 1.0, "bot_00002": 1.2, "bot_00003": 1.5}


async def test_roll_combat_把机器人加成算进去(db, monkeypatch):
    await mk_bot(db, tier="正常")

    async def flat(player, equipped=None):
        return 100.0
    monkeypatch.setattr(combat_mod, "calc_power", flat)
    monkeypatch.setattr(random, "uniform", lambda a, b: 1.0)
    human = {"discord_id": H, "is_bot": False}
    bot = {"discord_id": B, "is_bot": True}
    won, atk, dfn = await combat_mod.roll_combat(human, bot)
    assert (won, atk, dfn) == (False, 100.0, 120.0)
    won, atk, dfn = await combat_mod.roll_combat(bot, human)
    assert (won, atk, dfn) == (True, 120.0, 100.0)
    assert (await combat_mod.roll_combat(human, human))[0] is False


# ---- 面板：攻击与胜负处置 ---------------------------------------------------

def inter(uid=H):
    i = FakeInteraction(uid)
    i.client = SimpleNamespace(cogs={}, fetch_user=None)
    return i


async def view_for(db):
    from utils.player import get_player
    return PlayerActionView(inter().user, await get_player(H), await get_player(B), True)


def fix_fight(monkeypatch, won, escaped=False):
    async def rc(atk, dfn):
        return won, 100.0, 50.0

    async def re(who):
        return escaped, 30.0
    monkeypatch.setattr(combat_mod, "roll_combat", rc)
    monkeypatch.setattr(combat_mod, "roll_escape", re)


async def test_攻击机器人_赢了出现处置面板(db, monkeypatch):
    await mk_human(db)
    await mk_bot(db)
    fix_fight(monkeypatch, True)
    i = inter()
    await (await view_for(db))._attack_callback(i)
    assert isinstance(i.last.view, VictoryActionView) and "胜" in i.last.embed.description


async def test_攻击机器人_输了没逃掉_被机器人处置(db, monkeypatch, reaction=None, cfg=None):
    await mk_human(db, stones=1000)
    await mk_bot(db, archetype="贪财", stones=0)
    fix_fight(monkeypatch, False, escaped=False)
    cfgd = be.load_config()
    cfgd["combat"]["reaction"]["贪财"] = {"rob": 100}
    monkeypatch.setattr(be, "load_config", lambda: __import__("copy").deepcopy(cfgd))
    i = inter()
    await (await view_for(db))._attack_callback(i)
    text = i.last.embed.description
    assert "擒获" in text and "被搜走了 **150 灵石**" in text and f"道友{B}" in text and "「" in text
    assert (await get(db, H)).spirit_stones == 850


async def test_攻击机器人_输了但逃脱_不被处置(db, monkeypatch):
    await mk_human(db, stones=1000)
    await mk_bot(db, archetype="贪财")
    fix_fight(monkeypatch, False, escaped=True)
    i = inter()
    await (await view_for(db))._attack_callback(i)
    assert "趁乱逃脱" in i.last.embed.description and "搜走" not in i.last.embed.description
    assert (await get(db, H)).spirit_stones == 1000


async def test_攻击机器人_输了被杀_战报写明(db, monkeypatch):
    from utils import world_settings
    await world_settings.set_values(mode="真实")
    await mk_human(db, stones=1000, realm="筑基期5层")
    await mk_bot(db, archetype="阴鸷", stones=0)
    fix_fight(monkeypatch, False, escaped=False)
    cfgd = be.load_config()
    cfgd["combat"]["can_kill_humans"] = True
    cfgd["combat"]["reaction"]["阴鸷"] = {"kill": 100}
    monkeypatch.setattr(be, "load_config", lambda: __import__("copy").deepcopy(cfgd))
    i = inter()
    await (await view_for(db))._attack_callback(i)
    assert "一击毙命" in i.last.embed.description and (await get(db, H)).is_dead


async def victory(db):
    from utils.player import get_player
    return VictoryActionView(inter().user, await get_player(H), await get_player(B))


def click(view, label):
    return next(c for c in view.children if c.label == label)


async def test_处置面板_打劫机器人(db):
    await mk_human(db)
    await mk_bot(db, stones=1000)
    v = await victory(db)
    i = inter()
    await click(v, "💰 打劫灵石").callback(i)
    msg = i.last.content
    assert "搜刮了 **150 灵石**" in msg and "「" in msg and "声望 -1" in msg and "怀恨在心" in msg
    j = inter()
    await click(v, "☠️ 击杀").callback(j)
    assert "已经做出了选择" in j.last, "成功之后这次选择就用掉了"
    assert (await get(db, B)) is not None


async def test_处置面板_废修为(db):
    await mk_human(db)
    await mk_bot(db, cultivation=500)
    i = inter()
    await click(await victory(db), "💀 废去修为").callback(i)
    assert "修为归零" in i.last.content and "声望 -2" in i.last.content and (await get(db, B)).cultivation == 0


async def test_处置面板_击杀(db):
    await mk_human(db, stones=0)
    await mk_bot(db, stones=1000)
    i = inter()
    await click(await victory(db), "☠️ 击杀").callback(i)
    msg = i.last.content
    assert "取了" in msg and "夺得 **300 灵石**" in msg and "声望 -5" in msg and "「" in msg
    assert await get(db, B) is None


async def test_处置面板_击杀天骄显示声望减十(db):
    await mk_human(db, reputation=40)
    await mk_bot(db, tier="天骄")
    i = inter()
    await click(await victory(db), "☠️ 击杀").callback(i)
    assert "声望 -10" in i.last.content


async def test_处置面板_落空时放回_可以改选(db):
    await mk_human(db)
    await mk_bot(db, stones=0)
    v = await victory(db)
    i = inter()
    await click(v, "💰 打劫灵石").callback(i)
    assert "没什么油水" in i.last and i.last.ephemeral
    j = inter()
    await click(v, "☠️ 击杀").callback(j)
    assert "取了" in j.last.content


async def test_处置面板_机器人已经离开(db):
    await mk_human(db)
    await mk_bot(db, city=CITY)
    i = inter()
    await click(await victory(db), "💰 打劫灵石").callback(i)
    assert "已经离开此地" in i.last


# ---- 机器人去秘地历练 -------------------------------------------------------

def test_秘地历练_只去境界够得着的(cfg=None):
    c = be.load_config()
    c["wild"]["trip_chance"] = 1.0
    rng = random.Random(1)
    low = {be.pick_wild_trip("炼气期1层", c, rng) for _ in range(300)}
    assert low and low <= {"漠北荒漠", "百草谷", "火云洞", "万妖岭", "灵木林", "碧波潭"}
    high = {be.pick_wild_trip("元婴期初期", c, rng) for _ in range(500)}
    assert "虚空裂缝" in high and "昆仑秘境" in high and len(high) > len(low)
    c["wild"]["trip_chance"] = 0.0
    assert be.pick_wild_trip("元婴期初期", c, rng) is None
    c["wild"]["trip_chance"] = 0.15
    hits = sum(be.pick_wild_trip("炼气期1层", c, random.Random(i)) is not None for i in range(2000))
    assert 0.11 < hits / 2000 < 0.19


async def test_每日结算_去秘地历练_第二天回城(db, cfg, monkeypatch):
    cfg(wild={"trip_chance": 1.0}, speed={"正常": 0.0}, materials={"jobs_per_day": 0})
    await mk_bot(db, city=CITY, stones=0, bank=0)
    out = await bsl.run_settlement(rng=random.Random(0))
    p = await get(db, B)
    assert out["wild_trips"] == 1 and p.current_city in be.WILD_NAMES
    monkeypatch.setattr(bsl, "today", lambda: "2026-10-11")
    cfg(wild={"trip_chance": 1.0})
    out = await bsl.run_settlement(rng=random.Random(0))
    assert out["wild_trips"] == 0 and (await get(db, B)).current_city == CITY, "在外面的第二天先回家，不会连着再出门"


async def test_每日结算_闭关中的机器人不出门(db, cfg):
    import time
    cfg(wild={"trip_chance": 1.0}, speed={"正常": 0.0}, materials={"jobs_per_day": 0})
    await mk_bot(db, city=CITY, cultivating_until=time.time() + 3600)
    assert (await bsl.run_settlement(rng=random.Random(0)))["wild_trips"] == 0
    assert (await get(db, B)).current_city == CITY


async def test_每日结算_老机器人补上常驻城市(db, cfg):
    cfg(wild={"trip_chance": 0.0}, speed={"正常": 0.0}, materials={"jobs_per_day": 0})
    await mk_bot(db, city="落云城")
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        (await s.get(D.BotPersonality, B)).home_city = ""
        await s.commit()
    await bsl.run_settlement(rng=random.Random(0))
    async with D.AsyncSessionLocal() as s:
        assert (await s.get(D.BotPersonality, B)).home_city == "落云城"


async def test_生成机器人_记下常驻城市(db):
    from utils import bot_world
    await bot_world.generate_bots(5, random.Random(2))
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        for pers in (await s.execute(select(D.BotPersonality))).scalars():
            assert pers.home_city == (await s.get(D.Player, pers.bot_id)).current_city != ""


async def test_每日结算_补清被击杀却没清干净的机器人(db, cfg):
    cfg(wild={"trip_chance": 0.0}, speed={"正常": 0.0}, materials={"jobs_per_day": 0})
    await mk_bot(db, "bot_00001", is_dead=True)             # 被击杀：标了坐化，但清理没做完
    await mk_bot(db, "bot_00002")
    out = await bsl.run_settlement(rng=random.Random(0))
    assert out["cleaned"] == 1 and await get(db, "bot_00001") is None and await get(db, "bot_00002") is not None


async def test_每日结算_清理过期的打劫记录(db, cfg):
    cfg(wild={"trip_chance": 0.0})
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        for day in ("2026-10-01", "2026-10-06", "2026-10-07", "2026-10-10"):
            s.add(D.BotRaid(player_id=H, day=day, robs=1, kills=0))
        await s.commit()
    await bsl.run_settlement(rng=random.Random(0))
    async with D.AsyncSessionLocal() as s:
        days = sorted(r.day for r in (await s.execute(select(D.BotRaid))).scalars())
    assert days == ["2026-10-07", "2026-10-10"], "只留最近 3 天"


async def test_秘地里能聊天送礼_也能被攻击(db):
    """机器人在秘地时和真人同处一地：搭话 / 送礼照常，攻击按钮可用。"""
    await mk_human(db)
    await mk_bot(db)
    v = await view_for(db)
    labels = [c.label for c in v.children]
    assert {"💬 搭话", "🎁 送礼", "⚔️ 发起攻击"} <= set(labels)
    assert not click(v, "⚔️ 发起攻击").disabled
    res = await bot_social.chat(H, B)
    assert res["ok"]


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

    assert alembic("upgrade", "9c4f7a1e5b83").returncode == 0
    conn = sqlite3.connect(path)
    conn.execute("DROP TABLE bot_raids")
    conn.execute("ALTER TABLE bot_personality DROP COLUMN home_city")
    conn.execute("INSERT INTO bot_personality (bot_id, archetype) VALUES ('bot_00001', '豪爽')")
    conn.commit()
    conn.close()
    assert alembic("upgrade", "head").returncode == 0
    conn = sqlite3.connect(path)
    assert conn.execute("SELECT home_city FROM bot_personality").fetchone() == ("",)
    assert {r[1] for r in conn.execute("PRAGMA table_info(bot_raids)")} == {"player_id", "day", "robs", "kills"}
    conn.close()
    assert alembic("upgrade", "head").returncode == 0


async def test_击杀遗言_用它生前的性格和交情(db, monkeypatch):
    """机器人被清走之后就查不到性格了，所以遗言要在击杀之前取。"""
    seen = []
    real = bot_social.get_line

    def spy(archetype, scene, tier, rng=None, **fmt):
        seen.append((archetype, scene, tier))
        return real(archetype, scene, tier, rng, **fmt)
    monkeypatch.setattr(bot_social, "get_line", spy)
    await mk_human(db)
    await mk_bot(db, archetype="豪爽")
    await bot_social.adjust_favor(H, B, 25)
    await click(await victory(db), "☠️ 击杀").callback(inter())
    assert seen == [("豪爽", "bot_killed", "熟识")]


def test_today是年月日():
    import re
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", _REAL_TODAY())


async def test_废修为_条件不满足也不改(db):
    await mk_human(db)
    await mk_bot(db, city=CITY, cultivation=500)
    res = await bc.cripple_bot(H, B)
    assert res["ok"] is False and (await get(db, B)).cultivation == 500 and await raids(db) == (0, 0)


async def test_击杀_更新时机器人已经死了_回滚不占次数(db, monkeypatch):
    """_check_pair 之后、更新之前机器人被别处弄死了：回滚，不给钱、不扣声望、不占次数。"""
    await mk_human(db, stones=0)
    await mk_bot(db, is_dead=True, stones=1000)

    async def fake_pair(session, human_id, bot_id):
        return await session.get(bc.Player, human_id), await session.get(bc.Player, bot_id)
    monkeypatch.setattr(bc, "_check_pair", fake_pair)
    res = await bc.kill_bot(H, B)
    assert res["ok"] is False and "已经坐化" in res["reason"]
    assert (await get(db, H)).spirit_stones == 0 and (await get(db, H)).reputation == 10 and await raids(db) == (0, 0)


async def test_击杀_全服每天上限_被拒不占个人次数(db, cfg):
    cfg(combat={"kill": {"share": 0.30, "cap": 300, "per_human_per_day": 5, "global_per_day": 3}})
    await mk_human(db, H)
    await mk_human(db, "1002")
    for i in range(1, 7):
        await mk_bot(db, f"bot_{i:05d}", stones=0, bank=0)
    assert (await bc.kill_bot(H, "bot_00001"))["ok"] and (await bc.kill_bot("1002", "bot_00002"))["ok"]
    assert (await bc.kill_bot(H, "bot_00003"))["ok"]
    res = await bc.kill_bot("1002", "bot_00004")
    assert res["ok"] is False and "全服已有 3 名" in res["reason"]
    assert await raids(db, "1002") == (0, 1), "被全服上限拒掉的这次，个人次数原样"
    assert await get(db, "bot_00004") is not None
    assert (await raids(db, bc.ALL)) == (0, 3)


async def test_击杀_全服上限第二天重新算(db, cfg, monkeypatch):
    cfg(combat={"kill": {"share": 0.30, "cap": 300, "per_human_per_day": 5, "global_per_day": 1}})
    await mk_human(db)
    for i in range(1, 4):
        await mk_bot(db, f"bot_{i:05d}", stones=0, bank=0)
    assert (await bc.kill_bot(H, "bot_00001"))["ok"] and not (await bc.kill_bot(H, "bot_00002"))["ok"]
    monkeypatch.setattr(bc, "today", lambda: "2026-10-11")
    assert (await bc.kill_bot(H, "bot_00002"))["ok"]


def test_全服击杀上限不超过补员能力():
    """全服每日击杀上限 + 自然老死（≈1.2%/天，模拟值）不能超过补员上限，否则世界会被杀空
    （模拟：补员 10/天、击杀上限 10 时，500 个的世界稳定在 ≈200 个；上限 4 时稳定在 ≈499 个）。"""
    c = be.load_config()
    assert c["combat"]["kill"]["global_per_day"] + int(500 * 0.012) <= be.refill_cap(500, c)
