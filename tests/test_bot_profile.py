"""机器人行为画像（utils/bot_profile.py、data/bot_profiles.json）：性格从『怎么说』扩展到『怎么做』。

用户 2026-10-12 的要求：行为由基础性格 + 道德 / 行为倾向 + 出身 + 随机性共同决定；善良守序的人也有一定概率反常；数值可配置。
"""

import json
import random

import pytest

from tests.conftest import make_player
from utils import bot_economy as be
from utils import bot_profile as bp
from utils import bot_traits as bt
from utils.bot_social import load_archetypes


def R(seed=0):
    return random.Random(seed)


# ---- 数据 -------------------------------------------------------------------

def test_数据合法_每个原型都有画像():
    cfg = bp.load()
    assert bp.validate(cfg, list(load_archetypes()), list(bt.pool("origins"))) == []
    assert set(cfg["archetypes"]) == set(load_archetypes())


@pytest.mark.parametrize("mutate,expect", [
    (lambda c: c["archetypes"].pop("豪爽"), "差异"),
    (lambda c: c["archetypes"]["豪爽"].update(lawful=[80, 20]), "豪爽.lawful"),
    (lambda c: c["archetypes"]["豪爽"].update(capacity=[0, 51]), "豪爽.capacity"),
    (lambda c: c["archetypes"]["豪爽"].update(deviance=[0, 0.9]), "deviance"),
    (lambda c: c["origin_mods"].update(不存在的出身={"lawful": 1}), "未知出身"),
    (lambda c: c["origin_mods"]["农户"].update(capacity=5), "origin_mods.农户.capacity"),
    (lambda c: c["origin_mods"]["农户"].update(lawful=99), "幅度"),
    (lambda c: c["thresholds"].update(low=70), "thresholds"),
])
def test_校验能拦住坏数据(mutate, expect):
    cfg = json.loads(json.dumps(bp.load()))
    mutate(cfg)
    errors = bp.validate(cfg, list(load_archetypes()), list(bt.pool("origins")))
    assert any(expect in e for e in errors), errors


# ---- 抽取 -------------------------------------------------------------------

def test_抽出的画像在原型范围内_出身只做加减():
    cfg = bp.load()
    for arche, spec in cfg["archetypes"].items():
        for seed in range(80):
            p = bp.roll_profile(arche, None, R(seed))
            for axis in bp.PERCENT_AXES:
                assert spec[axis][0] <= p[axis] <= spec[axis][1], (arche, axis)
            assert 0 <= p["capacity"] <= 50 and spec["capacity"][0] <= p["capacity"] <= spec["capacity"][1]
            assert spec["deviance"][0] <= p["deviance"] <= spec["deviance"][1]


def test_出身加减并被夹在0到100之间():
    base = bp.roll_profile("迂腐", None, R(3))
    with_origin = bp.roll_profile("迂腐", "书香", R(3))              # 书香：lawful +10、impulse -10
    assert with_origin["lawful"] == min(100, base["lawful"] + 10)
    assert with_origin["impulse"] == max(0, base["impulse"] - 10)
    assert with_origin["loyalty"] == base["loyalty"]
    for seed in range(200):
        for origin in bt.pool("origins"):
            p = bp.roll_profile("迂腐", origin, R(seed))
            assert all(0 <= p[a] <= 100 for a in bp.PERCENT_AXES)


def test_同一个种子同一份画像():
    assert bp.roll_profile("阴鸷", "孤儿", R(5)) == bp.roll_profile("阴鸷", "孤儿", R(5))
    assert len({json.dumps(bp.roll_profile("豪爽", "农户", R(i))) for i in range(50)}) > 40


def test_性格塑造行为_阴鸷记仇豪爽义气迂腐守序():
    def avg(arche, axis):
        return sum(bp.roll_profile(arche, None, R(i))[axis] for i in range(200)) / 200
    assert avg("阴鸷", "vengeful") > 75 > avg("话痨", "vengeful") + 30
    assert avg("豪爽", "loyalty") > 75 > avg("贪财", "loyalty") + 30
    assert avg("迂腐", "lawful") > 80 > avg("贪财", "lawful") + 40
    assert avg("豪爽", "impulse") > 65 > avg("阴鸷", "impulse") + 30


# ---- 阵营 -------------------------------------------------------------------

@pytest.mark.parametrize("kind,lawful,label", [
    (80, 80, "守序善良"), (80, 50, "中立善良"), (80, 10, "混乱善良"),
    (50, 80, "守序中立"), (50, 50, "绝对中立"), (50, 10, "混乱中立"),
    (10, 80, "守序邪恶"), (10, 50, "中立邪恶"), (10, 10, "混乱邪恶"),
    (60, 60, "守序善良"), (59, 41, "绝对中立"), (40, 40, "混乱邪恶"),
])
def test_阵营标签(kind, lawful, label):
    assert bp.alignment(kind, lawful) == label


def test_好打抱不平_心地不坏且义气重或性子急():
    base = {"lawful": 50, "impulse": 50, "loyalty": 50, "vengeful": 50, "capacity": 5, "deviance": 0}
    assert bp.is_righteous(80, {**base, "loyalty": 90}) and bp.is_righteous(80, {**base, "impulse": 90})
    assert not bp.is_righteous(80, base), "心地好但不急不重义气，不出头"
    assert not bp.is_righteous(30, {**base, "loyalty": 90}), "义气重但心地不好，也不出头"
    assert bp.is_righteous(55, {**base, "loyalty": 60}) and not bp.is_righteous(54, {**base, "loyalty": 60})
    assert not bp.is_righteous(80, None)


def test_标签给台词用():
    p = {"lawful": 80, "impulse": 80, "loyalty": 80, "vengeful": 20, "capacity": 5, "deviance": 0}
    assert bp.tags(80, p) == ["守序善良", "冲动", "重义气", "好打抱不平"]
    q = {"lawful": 10, "impulse": 10, "loyalty": 10, "vengeful": 90, "capacity": 5, "deviance": 0}
    assert bp.tags(10, q) == ["混乱邪恶", "谨慎", "记仇"]
    assert bp.tags(50, None) == []


# ---- 偶尔反常 ---------------------------------------------------------------

def test_反常的概率就是deviance_倒过来的是善恶守序和冲动():
    p = {"lawful": 90, "impulse": 20, "loyalty": 50, "vengeful": 50, "capacity": 5, "deviance": 0.13}
    rng, flipped = R(1), 0
    for _ in range(20000):
        k, o, i, f = bp.effective(80, p, rng)
        if f:
            flipped += 1
            assert (k, o, i) == (20, 10, 80)
        else:
            assert (k, o, i) == (80, 90, 20)
    assert 0.12 < flipped / 20000 < 0.14


def test_没有画像或偏离为0_从不反常():
    assert bp.effective(70, None) == (70, 50, 50, False)
    p = {"lawful": 90, "impulse": 20, "loyalty": 50, "vengeful": 50, "capacity": 5, "deviance": 0}
    assert not any(bp.effective(70, p, R(i))[3] for i in range(500))


# ---- 复仇风格 ---------------------------------------------------------------

def test_冲动的直接上_谨慎的隐忍():
    def dist(impulse):
        p = {"lawful": 50, "impulse": impulse, "loyalty": 50, "vengeful": 50, "capacity": 5, "deviance": 0}
        rng, out = R(2), {s: 0 for s in bp.STYLES}
        for _ in range(4000):
            out[bp.revenge_style(p, rng)] += 1
        return {k: v / 4000 for k, v in out.items()}
    hot, cold, mid = dist(90), dist(10), dist(50)
    assert hot["直接"] > 0.75 and hot["隐忍"] == 0
    assert cold["隐忍"] > 0.75 and cold["直接"] == 0
    assert mid["等待时机"] > 0.4 and mid["直接"] > 0.1 and mid["隐忍"] > 0.1
    assert bp.revenge_style(None, R(1)) in bp.STYLES


# ---- 处置倾向 ---------------------------------------------------------------

def test_处置倾向_善良放_邪恶狠_混乱更容易下杀手():
    base = {"lawful": 50, "impulse": 50, "loyalty": 50, "vengeful": 50, "capacity": 5, "deviance": 0}
    assert bp.captive_shift(90, base) == {"release": 1.5, "rob": 1.0, "kill": 0.3}
    assert bp.captive_shift(10, base) == {"release": 0.6, "rob": 1.2, "kill": 1.8}
    assert bp.captive_shift(50, base) == {"release": 1.0, "rob": 1.0, "kill": 1.0}
    chaos, order = {**base, "lawful": 10}, {**base, "lawful": 90}
    assert bp.captive_shift(50, chaos)["kill"] == pytest.approx(1.2)
    assert bp.captive_shift(50, order)["kill"] == pytest.approx(0.8)
    assert bp.captive_shift(10, chaos)["kill"] == pytest.approx(1.8 * 1.2)
    assert bp.captive_shift(50, None) == {}


def test_处置倾向_偶尔反常时善恶倒过来():
    p = {"lawful": 50, "impulse": 50, "loyalty": 50, "vengeful": 50, "capacity": 5, "deviance": 1.0}
    assert bp.captive_shift(90, p) == {"release": 0.6, "rob": 1.2, "kill": 1.8}      # 善良的人这一次反常了


def test_处置权重被修正后_结果分布跟着变():
    cfg = be.load_config()

    def share(shift, name):
        rng, n = R(7), 6000
        return sum(be.captive_outcome("阴鸷", cfg, can_kill=True, rng=rng, shift=shift) == name for _ in range(n)) / n
    plain = share(None, "kill")
    assert plain == pytest.approx(0.30, abs=0.03)                              # 阴鸷原本 20/50/30
    assert share({"release": 1.5, "rob": 1.0, "kill": 0.3}, "kill") < plain / 2
    assert share({"release": 0.6, "rob": 1.2, "kill": 1.8}, "kill") > plain * 1.3
    assert be.captive_outcome("憨直", cfg, can_kill=True, rng=R(1), shift={"kill": 99}) == "release"    # 没有这一项就不凭空出现
    assert share({"kill": 0.5}, "kill") < plain


# ---- 接入 -------------------------------------------------------------------

async def test_生成的机器人都带画像_且和种子一致(db):
    from utils import bot_world
    res = await bot_world.generate_bots(25, R(4))
    assert res["ok"]
    D = db["db_async"]
    from sqlalchemy import select
    async with D.AsyncSessionLocal() as s:
        for row in (await s.execute(select(D.BotPersonality))).scalars():
            prof, traits = json.loads(row.profile), json.loads(row.traits)
            assert prof == bp.roll_profile(row.archetype, traits["origin"], random.Random(f"{row.bot_id}:profile"))


async def test_老机器人每日结算时补上画像(db):
    from utils import bot_settle
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        p = make_player(D, "bot_00001")
        p.name, p.is_bot, p.lifespan, p.current_city = "老甲", True, 80, "灵虚城"
        s.add(p)
        s.add(D.BotPersonality(bot_id="bot_00001", archetype="阴鸷", tier="正常", home_city="灵虚城"))
        await s.commit()
    await bot_settle.run_settlement(force=True, rng=R(1))
    async with D.AsyncSessionLocal() as s:
        row = await s.get(D.BotPersonality, "bot_00001")
        assert row.profile
        origin = json.loads(row.traits)["origin"]
        assert json.loads(row.profile) == bp.roll_profile("阴鸷", origin, random.Random("bot_00001:profile"))


async def test_资料页显示阵营(db):
    from utils.views import bot_actions
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        for uid, bot in (("1001", False), ("bot_00001", True)):
            p = make_player(D, uid)
            p.name, p.is_bot, p.lifespan = f"道友{uid}", bot, 80
            s.add(p)
        prof = {"lawful": 80, "impulse": 50, "loyalty": 50, "vengeful": 50, "capacity": 5, "deviance": 0.1}
        s.add(D.BotPersonality(bot_id="bot_00001", archetype="迂腐", kindness=80, profile=json.dumps(prof)))
        await s.commit()
    lines = await bot_actions.profile_lines("1001", "bot_00001")
    assert lines[0] == "性格：迂腐 · 守序善良"


async def test_擒获处置用画像_善良的几乎不杀(db):
    """同样是 阴鸷 20/50/30：善意 95 的这个，被擒获的玩家几乎不会被杀。"""
    from utils import bot_combat as bc
    from utils import world_settings
    await world_settings.set_values(mode="真实")
    D = db["db_async"]
    kills = {}
    for kind in (95, 5):
        killed = 0
        for i in range(120):
            hid, bid = f"h{kind}{i}", f"bot_{kind}{i:03d}"
            async with D.AsyncSessionLocal() as s:
                h = make_player(D, hid, stones=1000)
                h.name, h.lifespan, h.realm, h.current_city = f"人{hid}", 80, "筑基期5层", "万妖岭"
                b = make_player(D, bid, stones=0)
                b.name, b.is_bot, b.lifespan, b.current_city = f"机{bid}", True, 80, "万妖岭"
                s.add_all([h, b])
                prof = {"lawful": 50, "impulse": 50, "loyalty": 50, "vengeful": 50, "capacity": 5, "deviance": 0}
                s.add(D.BotPersonality(bot_id=bid, archetype="阴鸷", kindness=kind, profile=json.dumps(prof)))
                await s.commit()
            killed += (await bc.handle_captive(bid, hid, random.Random(i)))["killed"]
        kills[kind] = killed
    assert kills[95] < kills[5] / 3, kills
