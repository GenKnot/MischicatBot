"""仇恨账本（utils/bot_grudges.py、data/bot_grudges.json）。

用户 2026-10-12 的设计：冒犯（打劫、打劫失败、废修为、击杀）让受害者和关系网里的朋友 / 结拜 / 同门按概率记仇；
仇恨有具体原因；蹲守窗口按性格，到期不等于放下（按性格续期，否则潜伏，新事件重新激活）；少数人特别执着；
受害者没名气朋友要过一阵才知道；玩家能化解；杀仇敌不等于仇恨结束；转世后机器人不认识新的他，玩家保留前世仇人。
"""

import copy
import json
import random

import pytest
from sqlalchemy import select

from tests.conftest import make_player
from utils import bot_combat as bc
from utils import bot_grudges as bg
from utils import bot_ties
from utils.bot_social import load_archetypes
from utils.character import years_to_seconds

H, CITY, OTHER = "1001", "灵虚城", "落云城"
YEAR = years_to_seconds(1)
NOW = 1_800_000_000.0


class Seq(random.Random):
    """random() 依次返回给定的值（用完后一直返回最后一个）。"""
    def __init__(self, *values):
        super().__init__(0)
        self.values, self.i = list(values), 0

    def random(self):
        v = self.values[min(self.i, len(self.values) - 1)]
        self.i += 1
        return v


class Z(random.Random):
    """random() 永远返回固定值：0.0 = 所有『概率』都过，0.99 = 都不过。"""
    def __init__(self, value=0.0, seed=0):
        super().__init__(seed)
        self.value = value

    def random(self):
        return self.value


def R(seed=0):
    return random.Random(seed)


# ---- 数据与纯函数 -----------------------------------------------------------

def test_配置合法():
    assert bg.validate(bg.load(), list(load_archetypes())) == []


@pytest.mark.parametrize("mutate,expect", [
    (lambda c: c["kinds"]["kill"].update(severity=0), "kinds.kill.severity"),
    (lambda c: c["kinds"]["rob"].update(third="{actor}劫了人"), "kinds.rob.third"),
    (lambda c: c["relation"].update(朋友=2), "relation.朋友"),
    (lambda c: c["relation"].pop("self"), "self"),
    (lambda c: c["relation_names"].pop("朋友"), "relation_names"),
    (lambda c: c["windows"].pop("豪爽"), "windows 缺原型"),
    (lambda c: c["windows"].update(豪爽=0), "windows.豪爽"),
    (lambda c: c["renew"].update(豪爽=1.5), "renew.豪爽"),
    (lambda c: c["renew"].update(max_renewals=-1), "max_renewals"),
    (lambda c: c["stubborn"].update(mult=0.5), "stubborn"),
    (lambda c: c["ready"].pop("隐忍"), "ready"),
    (lambda c: c.update(third_party_scale=0), "third_party_scale"),
    (lambda c: c["appease"].update(stones_per_point=0), "appease"),
])
def test_校验能拦住坏配置(mutate, expect):
    cfg = copy.deepcopy(bg.load())
    mutate(cfg)
    errors = bg.validate(cfg, list(load_archetypes()))
    assert any(expect in e for e in errors), errors


def test_窗口年数_性格_结拜加成_执着加成():
    cfg = bg.load()
    assert bg.window_years("阴鸷", "self", False) == 30 and bg.window_years("话痨", "朋友", False) == 1
    assert bg.window_years("豪爽", "结拜", False) == 10 * cfg["sworn_window_mult"]
    assert bg.window_years("豪爽", "self", True) == 10 * cfg["stubborn"]["mult"]
    assert bg.window_years("豪爽", "结拜", True) == 10 * cfg["sworn_window_mult"] * cfg["stubborn"]["mult"]


def test_谨慎的人要等自己够强():
    assert bg.is_ready("直接", "炼气期1层", "元婴期初期")
    assert not bg.is_ready("隐忍", "炼气期1层", "筑基期1层")
    assert bg.is_ready("隐忍", "筑基期1层", "筑基期5层")
    assert bg.is_ready("隐忍", "元婴期初期", "炼气期1层")
    assert bg.is_ready("等待时机", "炼气期1层", "筑基期1层") and not bg.is_ready("等待时机", "炼气期1层", "结丹期初期")


def test_更重的冒犯盖过轻的():
    assert bg.stronger("rob", "kill") == "kill" and bg.stronger("kill", "rob") == "kill" and bg.stronger("rob_fail", "rob") == "rob"


# ---- 夹具 -------------------------------------------------------------------

async def mk_bot(db, uid, arche="豪爽", city=CITY, realm="筑基期1层", profile=None, kindness=50, alive=True, fame=300, stones=1000):
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        p = make_player(D, uid, stones=stones)
        p.name, p.is_bot, p.lifespan, p.current_city, p.realm, p.is_dead, p.fame = f"机{uid[-3:]}", True, 80, city, realm, not alive, fame
        s.add(p)
        prof = {"lawful": 50, "impulse": 50, "loyalty": 60, "vengeful": 50, "capacity": 30, "deviance": 0, **(profile or {})}
        s.add(D.BotPersonality(bot_id=uid, archetype=arche, tier="正常", home_city=city, kindness=kindness, profile=json.dumps(prof)))
        await s.commit()


async def mk_human(db, uid=H, city=CITY, **kw):
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        p = make_player(D, uid, stones=kw.pop("stones", 1000))
        p.fame = kw.pop("fame", 300)                       # 默认有名气：出事全服都知道（没名气的另有测试）
        p.name, p.lifespan, p.current_city = f"人{uid}", 80, city
        for k, v in kw.items():
            setattr(p, k, v)
        s.add(p)
        await s.commit()


async def tie(db, a, b, kind="朋友", strength=70):
    D = db["db_async"]
    x, y = bot_ties.pair(a, b)
    async with D.AsyncSessionLocal() as s:
        s.add(D.BotTie(a_id=x, b_id=y, kind=kind, strength=strength))
        await s.commit()


async def rows(db, **where):
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        q = select(D.BotGrudge)
        for k, v in where.items():
            q = q.where(getattr(D.BotGrudge, k) == v)
        return list((await s.execute(q)).scalars())


# ---- 受害者本人 -------------------------------------------------------------

async def test_打劫_受害机器人记仇_写明原因_蹲守窗口按性格(db):
    await mk_human(db)
    await mk_bot(db, "bot_00001", "阴鸷", profile={"vengeful": 100, "impulse": 10})
    out = await bg.on_offense(H, "bot_00001", "rob", rng=R(1), now=NOW)
    assert len(out) == 1
    (g,) = await rows(db)
    assert (g.holder_id, g.target_id, g.victim_id, g.kind, g.state) == ("bot_00001", H, "bot_00001", "rob", "active")
    assert g.reason == f"人{H}劫走了你的灵石" and g.known_at == NOW
    assert g.window_until == pytest.approx(NOW + 30 * YEAR) and g.style in bg.STYLES and g.renewals == 0
    assert g.severity == round(20 * (0.5 + 1.0))                      # 记仇满格 → 1.5 倍


async def test_记仇的更重_温和的更轻(db):
    await mk_human(db)
    await mk_bot(db, "bot_00001", profile={"vengeful": 100})
    await mk_bot(db, "bot_00002", profile={"vengeful": 0})
    await bg.on_offense(H, "bot_00001", "cripple", rng=R(1), now=NOW)
    await bg.on_offense(H, "bot_00002", "cripple", rng=R(1), now=NOW)
    hi, lo = (await rows(db, holder_id="bot_00001"))[0], (await rows(db, holder_id="bot_00002"))[0]
    assert hi.severity == 68 and lo.severity == 22 and hi.reason.endswith("废了你的修为")


async def test_冒犯轻重_打劫失败比打劫轻比废修为轻比击杀轻(db):
    await mk_human(db)
    sev = {}
    for i, kind in enumerate(("rob_fail", "rob", "cripple")):
        await mk_bot(db, f"bot_0000{i + 1}")
        await bg.on_offense(H, f"bot_0000{i + 1}", kind, rng=R(1), now=NOW)
        sev[kind] = (await rows(db, holder_id=f"bot_0000{i + 1}"))[0].severity
    assert sev["rob_fail"] < sev["rob"] < sev["cripple"]
    cfg = bg.load()["kinds"]
    assert cfg["rob_fail"]["severity"] < cfg["rob"]["severity"] < cfg["cripple"]["severity"] < cfg["kill"]["severity"]


async def test_击杀_受害者已死_没有本人那一笔(db):
    await mk_human(db)
    await mk_bot(db, "bot_00001")
    assert await bg.on_offense(H, "bot_00001", "kill", rng=R(1), now=NOW) == []
    assert await rows(db) == []


async def test_对自己动手_或_人不存在_什么都不记(db):
    await mk_human(db)
    assert await bg.on_offense(H, H, "rob") == []
    assert await bg.on_offense(H, "bot_99999", "rob") == []
    assert await bg.on_offense("bot_99998", H, "rob") == []
    assert await rows(db) == []


# ---- 关系网上的人 -----------------------------------------------------------

async def circle(db, kinds=("结拜", "同门", "朋友", "相识")):
    await mk_human(db)
    await mk_bot(db, "bot_00001")                                # 受害者
    for i, kind in enumerate(kinds, start=2):
        await mk_bot(db, f"bot_{i:05d}")
        await tie(db, "bot_00001", f"bot_{i:05d}", kind)


async def test_朋友出头_原因里写着和受害者的关系(db):
    await circle(db)
    out = await bg.on_offense(H, "bot_00001", "cripple", rng=Z(0.0), now=NOW)
    by_holder = {o["holder"]: o for o in out}
    assert set(by_holder) == {"bot_00001", "bot_00002", "bot_00003", "bot_00004", "bot_00005"}
    assert by_holder["bot_00002"]["reason"] == f"人{H}废了你的结拜兄弟机001的修为"
    assert by_holder["bot_00003"]["reason"].startswith(f"人{H}废了你的同门")
    assert "你的朋友" in by_holder["bot_00004"]["reason"] and "你的熟人" in by_holder["bot_00005"]["reason"]
    sev = {h: o["severity"] for h, o in by_holder.items()}
    assert sev["bot_00002"] > sev["bot_00003"] > sev["bot_00004"] > sev["bot_00005"], "关系越近分量越重：结拜 > 同门 > 朋友 > 熟人"


async def test_不是人人出头_概率不过就不记(db):
    await circle(db)
    out = await bg.on_offense(H, "bot_00001", "cripple", rng=Z(0.99), now=NOW)
    assert [o["holder"] for o in out] == ["bot_00001"], "本人一定记仇，朋友们这次没出头"


async def test_交情浅_事情轻_出头的就少(db):
    await mk_human(db)
    await mk_bot(db, "bot_00001")
    for i in range(2, 42):
        await mk_bot(db, f"bot_{i:05d}")
        await tie(db, "bot_00001", f"bot_{i:05d}", "朋友", 70)
    heavy = {o["holder"] for o in await bg.on_offense(H, "bot_00001", "kill", rng=R(1), now=NOW)}
    await mk_bot(db, "bot_00099")
    light = {o["holder"] for o in await bg.on_offense("bot_00099", "bot_00001", "rob_fail", rng=R(1), now=NOW)}
    assert len(heavy) > len(light)


async def test_仇敌_已死的_以及动手的人自己_不会替他出头(db):
    await mk_human(db)
    await mk_bot(db, "bot_00001")
    await mk_bot(db, "bot_00002")
    await mk_bot(db, "bot_00003", alive=False)
    await mk_bot(db, "bot_00004")
    await tie(db, "bot_00001", "bot_00002", "仇敌")
    await tie(db, "bot_00001", "bot_00003", "朋友")
    await tie(db, "bot_00001", H, "朋友")                         # 动手的是真人，他和受害者是朋友也不会恨自己
    await tie(db, "bot_00001", "bot_00004", "朋友")
    out = await bg.on_offense(H, "bot_00001", "cripple", rng=Z(0.0), now=NOW)
    assert {o["holder"] for o in out} == {"bot_00001", "bot_00004"}


async def test_交情深的朋友比泛泛之交更愿意出头_也更重(db):
    await mk_human(db)
    await mk_bot(db, "bot_00001")
    await mk_bot(db, "bot_00002")
    await mk_bot(db, "bot_00003")
    await tie(db, "bot_00001", "bot_00002", "朋友", 100)
    await tie(db, "bot_00001", "bot_00003", "朋友", 0)
    out = {o["holder"]: o["severity"] for o in await bg.on_offense(H, "bot_00001", "cripple", rng=Z(0.0), now=NOW)}
    assert out["bot_00002"] > out["bot_00003"] * 2


async def test_义气重的人更愿意出头(db):
    await mk_human(db)
    await mk_bot(db, "bot_00001")
    await mk_bot(db, "bot_00002", profile={"loyalty": 100})
    await mk_bot(db, "bot_00003", profile={"loyalty": 0})
    await tie(db, "bot_00001", "bot_00002", "朋友", 100)
    await tie(db, "bot_00001", "bot_00003", "朋友", 100)
    out = {o["holder"]: o["severity"] for o in await bg.on_offense(H, "bot_00001", "cripple", rng=Z(0.0), now=NOW)}
    assert out["bot_00002"] > out["bot_00003"]


async def test_击杀_连环复仇_杀了小的来了小的的朋友(db):
    """杀了 A，A 的朋友 B 来；杀了 B，B 的朋友 C 来 —— 复仇者都是关系网里真实存在的人。"""
    await mk_human(db)
    for i in (1, 2, 3):
        await mk_bot(db, f"bot_{i:05d}", fame=300)
    await tie(db, "bot_00001", "bot_00002", "结拜", 90)
    await tie(db, "bot_00002", "bot_00003", "朋友", 90)
    first = await bg.on_offense(H, "bot_00001", "kill", rng=Z(0.0), now=NOW)
    assert [o["holder"] for o in first] == ["bot_00002"]
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        (await s.get(D.Player, "bot_00001")).is_dead = True
        await s.commit()
    second = await bg.on_offense(H, "bot_00002", "kill", rng=Z(0.0), now=NOW)
    assert [o["holder"] for o in second] == ["bot_00003"], "bot_00001 已经死了；轮到 bot_00002 的朋友 bot_00003"
    assert {g.target_id for g in await rows(db)} == {H}


# ---- 名望：朋友多久得知 -----------------------------------------------------

async def test_有名的人出事_全服都立刻知道(db):
    await mk_human(db)
    await mk_bot(db, "bot_00001", fame=300)
    await mk_bot(db, "bot_00002", city=OTHER)
    await tie(db, "bot_00001", "bot_00002")
    out = await bg.on_offense(H, "bot_00001", "kill", rng=Z(0.0), now=NOW)
    assert out[0]["known_at"] == NOW


async def test_小有名气_同城立刻知道_外城的要过一年(db):
    await mk_human(db)
    await mk_bot(db, "bot_00001", fame=60)
    await mk_bot(db, "bot_00002", city=CITY)
    await mk_bot(db, "bot_00003", city=OTHER)
    await tie(db, "bot_00001", "bot_00002")
    await tie(db, "bot_00001", "bot_00003")
    out = {o["holder"]: o for o in await bg.on_offense(H, "bot_00001", "kill", rng=Z(0.0), now=NOW)}
    assert out["bot_00002"]["known_at"] == NOW
    assert out["bot_00003"]["known_at"] == pytest.approx(NOW + bg.load()["reach_delay_years"]["city_other"] * YEAR)
    (g,) = await rows(db, holder_id="bot_00003")
    assert g.window_until == pytest.approx(g.known_at + bg.window_years("豪爽", "朋友", g.stubborn) * YEAR), "窗口从得知那天算起"


async def test_无名小卒出事_机器人朋友不会立刻知道_开一份调查而不是直接记仇(db):
    await mk_human(db)
    await mk_bot(db, "bot_00001", fame=0)
    await mk_bot(db, "bot_00002")
    await tie(db, "bot_00001", "bot_00002")
    assert await bg.on_offense(H, "bot_00001", "kill", rng=Z(0.0), now=NOW) == [], "现在还不知道，没有仇"
    assert await rows(db) == []
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        (m,) = (await s.execute(select(D.BotMissing))).scalars().all()
    assert (m.seeker_id, m.missing_id, m.culprit_id, m.state, m.progress) == ("bot_00002", "bot_00001", H, "active", 0)
    assert m.missing_name == "机001" and m.culprit_name == f"人{H}" and m.reason == f"人{H}杀害了你的朋友机001" and m.kind == "kill"


async def test_无名小卒出事_真人朋友还是按旧办法_过一阵知道或根本没听说(db):
    await mk_human(db, "1002")
    await mk_human(db)
    await mk_bot(db, "bot_00001", fame=0)
    await tie(db, "1002", "bot_00001")
    lo, hi = bg.load()["reach_delay_years"]["none"]
    got = await bg.on_offense(H, "bot_00001", "kill", rng=Z(0.0), now=NOW)
    assert len(got) == 1 and got[0]["holder"] == "1002" and NOW + lo * YEAR <= got[0]["known_at"] <= NOW + hi * YEAR + 1
    await mk_bot(db, "bot_00003", fame=0)
    await tie(db, "1002", "bot_00003")
    assert await bg.on_offense(H, "bot_00003", "kill", rng=Seq(0.0, 0.99), now=NOW) == [], "真人朋友没听说就没有仇"


# ---- 累积 / 重新激活 --------------------------------------------------------

async def test_再次冒犯_仇恨累加_事件数加一_更重的原因盖过轻的_上限100(db):
    await mk_human(db)
    await mk_bot(db, "bot_00001")
    await bg.on_offense(H, "bot_00001", "rob", rng=R(1), now=NOW)
    s1 = (await rows(db))[0].severity
    await bg.on_offense(H, "bot_00001", "cripple", rng=R(1), now=NOW + 100)
    (g,) = await rows(db)
    assert g.events == 2 and g.severity > s1 and g.kind == "cripple" and "废了你的修为" in g.reason
    await bg.on_offense(H, "bot_00001", "rob", rng=R(1), now=NOW + 200)
    assert (await rows(db))[0].kind == "cripple", "轻的不会盖掉重的"
    for _ in range(5):
        await bg.on_offense(H, "bot_00001", "cripple", rng=R(1), now=NOW + 300)
    assert (await rows(db))[0].severity == 100


async def test_潜伏的仇恨被新事件重新激活_窗口重新计(db):
    await mk_human(db)
    await mk_bot(db, "bot_00001", "阴鸷")
    await bg.on_offense(H, "bot_00001", "rob", rng=R(1), now=NOW)
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        g = (await s.execute(select(D.BotGrudge))).scalars().one()
        g.state, g.window_until = "dormant", NOW + 1
        await s.commit()
    await bg.on_offense(H, "bot_00001", "rob_fail", rng=R(1), now=NOW + 10 * YEAR)
    (g,) = await rows(db)
    assert g.state == "active" and g.window_until == pytest.approx(NOW + 10 * YEAR + 30 * YEAR)


async def test_新仇勾起旧恨_同一个人对同一个对象的其它账也激活(db):
    await mk_human(db)
    await mk_bot(db, "bot_00001")
    await mk_bot(db, "bot_00002")
    await tie(db, "bot_00001", "bot_00002", "结拜", 100)
    await bg.on_offense(H, "bot_00002", "rob", rng=Z(0.0), now=NOW)          # bot_00001 为 bot_00002 出头
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        for g in (await s.execute(select(D.BotGrudge).where(D.BotGrudge.holder_id == "bot_00001"))).scalars():
            g.state = "dormant"
        await s.commit()
    await bg.on_offense(H, "bot_00001", "rob", rng=Z(0.0), now=NOW + 5)      # 现在是对它本人下手
    assert {g.state for g in await rows(db, holder_id="bot_00001")} == {"active"}
    assert len(await rows(db, holder_id="bot_00001")) == 2


async def test_执着的人窗口特别长(db):
    await mk_human(db)
    await mk_bot(db, "bot_00001", "豪爽", profile={"loyalty": 100})
    await bg.on_offense(H, "bot_00001", "rob", rng=Z(0.0), now=NOW)          # random() 恒为 0 → 一定执着
    (g,) = await rows(db)
    assert g.stubborn and g.window_until == pytest.approx(NOW + 10 * bg.load()["stubborn"]["mult"] * YEAR)
    await mk_bot(db, "bot_00002", "豪爽", profile={"loyalty": 10})
    await bg.on_offense(H, "bot_00002", "rob", rng=Z(0.0), now=NOW)
    assert not (await rows(db, holder_id="bot_00002"))[0].stubborn, "义气不够的人谈不上执着"


async def test_执着的人只占少数(db):
    await mk_human(db)
    n = 0
    for i in range(1, 201):
        await mk_bot(db, f"bot_{i:05d}", profile={"loyalty": 100})
        await bg.on_offense(H, f"bot_{i:05d}", "rob_fail", rng=R(i), now=NOW)
    n = len([g for g in await rows(db) if g.stubborn])
    assert 3 <= n <= 20, n


# ---- 每日处理 ---------------------------------------------------------------

async def expired_grudge(db, arche="豪爽", severity=30):
    await mk_human(db)
    await mk_bot(db, "bot_00001", arche)
    await bg.on_offense(H, "bot_00001", "rob", rng=R(1), now=NOW)
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        g = (await s.execute(select(D.BotGrudge))).scalars().one()
        g.window_until, g.severity = NOW + 5, severity
        await s.commit()


async def test_窗口到期_按性格概率续期_续了窗口重新计(db):
    await expired_grudge(db, "阴鸷")
    sm = await bg.grudge_day("d1", Z(0.0), now=NOW + YEAR)
    (g,) = await rows(db)
    assert sm["renewed"] == 1 and g.state == "active" and g.renewals == 1
    assert g.window_until == pytest.approx(NOW + YEAR + 30 * YEAR)


async def test_窗口到期_不续就潜伏_仇恨还在(db):
    await expired_grudge(db)
    sm = await bg.grudge_day("d1", Z(0.99), now=NOW + YEAR)
    (g,) = await rows(db)
    assert sm["dormant"] == 1 and g.state == "dormant" and g.severity > 0


@pytest.mark.parametrize("arche", ["阴鸷", "话痨"])
async def test_续期概率按性格_仇越重越愿意续(db, arche):
    cfg = bg.load()
    await expired_grudge(db, arche, severity=100)
    D = db["db_async"]
    res = []
    for seed in range(300):
        async with D.AsyncSessionLocal() as s:
            g = (await s.execute(select(D.BotGrudge))).scalars().one()
            g.state, g.window_until, g.renewals, g.severity = "active", NOW + 5, 0, 100
            await s.commit()
        await bg.grudge_day(f"d{seed}", R(seed), now=NOW + YEAR)
        res.append((await rows(db))[0].state == "active")
    expect = min(0.95, cfg["renew"][arche] + cfg["renew"]["severity_bonus_per_100"])        # 仇恨 100 → 加成拉满
    assert abs(sum(res) / 300 - expect) < 0.07, (arche, sum(res) / 300, expect)


async def test_续期有上限时用完就潜伏(db, monkeypatch):
    cfg = copy.deepcopy(bg.load())
    cfg["renew"]["max_renewals"] = 1
    monkeypatch.setattr(bg, "load", lambda: cfg)
    await expired_grudge(db, "阴鸷")
    await bg.grudge_day("d1", Z(0.0), now=NOW + YEAR)
    assert (await rows(db))[0].renewals == 1
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        g = (await s.execute(select(D.BotGrudge))).scalars().one()
        g.window_until = NOW + 5
        await s.commit()
    await bg.grudge_day("d2", Z(0.0), now=NOW + 100 * YEAR)
    assert (await rows(db))[0].state == "dormant"


async def test_还没得知的不处理_窗口没到期的不处理(db):
    await mk_human(db)
    await mk_bot(db, "bot_00001", fame=60)
    await mk_bot(db, "bot_00002", city="落云城")
    await tie(db, "bot_00001", "bot_00002")
    await bg.on_offense(H, "bot_00001", "kill", rng=Z(0.0), now=NOW)             # 小有名气：外城的朋友 1 游戏年后才知道
    (g,) = await rows(db)
    assert g.known_at > NOW
    sm = await bg.grudge_day("d1", Z(0.99), now=NOW + 1)
    assert sm["dormant"] == 0 and (await rows(db))[0].state == "active"


async def test_每日处理按日认领_force可重跑(db):
    await expired_grudge(db)
    assert await bg.grudge_day("d1", Z(0.99), now=NOW + YEAR)
    assert await bg.grudge_day("d1", Z(0.99), now=NOW + YEAR) == {}
    assert await bg.grudge_day("d2", Z(0.99), now=NOW + YEAR)
    assert await bg.grudge_day("d2", Z(0.99), force=True, now=NOW + YEAR)


async def test_潜伏的仇恨缓慢淡去_淡没了就清掉(db, monkeypatch):
    await expired_grudge(db, severity=2)
    await bg.grudge_day("d1", Z(0.99), now=NOW + YEAR)                       # 转潜伏
    cfg = copy.deepcopy(bg.load())
    cfg["decay"]["dormant_per_day"] = 1
    monkeypatch.setattr(bg, "load", lambda: cfg)
    await bg.grudge_day("d2", R(1), now=NOW + YEAR)
    assert (await rows(db))[0].severity == 1
    sm = await bg.grudge_day("d3", R(1), now=NOW + YEAR)
    assert sm["faded"] == 1 and await rows(db) == []


async def test_潜伏淡去的速度可以是小数(db):
    await expired_grudge(db, severity=100)
    await bg.grudge_day("d0", Z(0.99), now=NOW + YEAR)
    for day in range(1, 101):
        await bg.grudge_day(f"d{day}", R(day), now=NOW + YEAR)
    sev = (await rows(db))[0].severity
    assert abs(sev - (100 - 100 * bg.load()["decay"]["dormant_per_day"])) < 15, sev


async def test_机器人没了_它名下的账清走(db):
    await expired_grudge(db)
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        (await s.get(D.Player, "bot_00001")).is_dead = True
        await s.commit()
    sm = await bg.grudge_day("d1", R(1), now=NOW + YEAR)
    assert sm["orphans"] == 1 and await rows(db) == []


async def test_清理机器人_恨它的_它恨的都删(db):
    from utils import bot_world
    await mk_human(db)
    await mk_bot(db, "bot_00001")
    await mk_bot(db, "bot_00002")
    await bg.on_offense(H, "bot_00001", "rob", rng=R(1), now=NOW)
    await bg.on_offense("bot_00001", "bot_00002", "rob", rng=R(1), now=NOW)       # bot_00002 恨 bot_00001
    assert {(g.holder_id, g.target_id) for g in await rows(db)} == {("bot_00001", H), ("bot_00002", "bot_00001")}
    res = await bot_world.remove_bots(["bot_00001"])
    assert res["rows"]["bot_grudges"] == 2 and await rows(db) == []


# ---- 谁现在可以来蹲 ---------------------------------------------------------

async def test_候选_窗口开着_已得知_活着_带上敢不敢(db):
    await mk_human(db, realm="结丹期初期")
    await mk_bot(db, "bot_00001", realm="筑基期1层", profile={"impulse": 5})                    # 谨慎：打不过就等
    await mk_bot(db, "bot_00002", realm="炼气期1层", profile={"impulse": 95})                   # 冲动：直接上
    await mk_bot(db, "bot_00003")                                                              # 窗口已过
    await mk_bot(db, "bot_00004", alive=False)
    for b in ("bot_00001", "bot_00002", "bot_00003", "bot_00004"):
        await bg.on_offense(H, b, "rob", rng=Z(0.0), now=NOW)
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        for g in (await s.execute(select(D.BotGrudge))).scalars():
            g.style = {"bot_00001": "隐忍", "bot_00002": "直接"}.get(g.holder_id, "等待时机")
            if g.holder_id == "bot_00003":
                g.window_until = NOW + 1
            if g.holder_id == "bot_00004":
                g.state = "active"
        await s.commit()
    got = {c["holder"]: c for c in await bg.candidates_against(H, NOW + 100)}
    assert set(got) == {"bot_00001", "bot_00002"}
    assert got["bot_00001"]["ready"] is False and got["bot_00002"]["ready"] is True


async def test_候选_潜伏的不来_死掉的真人没有候选(db):
    await mk_human(db)
    await mk_bot(db, "bot_00001")
    await bg.on_offense(H, "bot_00001", "rob", rng=Z(0.0), now=NOW)
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        (await s.execute(select(D.BotGrudge))).scalars().one().state = "dormant"
        await s.commit()
    assert await bg.candidates_against(H, NOW + 1) == []
    async with D.AsyncSessionLocal() as s:
        (await s.execute(select(D.BotGrudge))).scalars().one().state = "active"
        (await s.get(D.Player, H)).is_dead = True
        await s.commit()
    assert await bg.candidates_against(H, NOW + 1) == []


# ---- 化解 -------------------------------------------------------------------

async def with_grudge(db, severity=40, **bot_kw):
    await mk_human(db, stones=3000)
    await mk_bot(db, "bot_00001", **bot_kw)
    await bg.on_offense(H, "bot_00001", "rob", rng=R(1), now=NOW)
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        (await s.execute(select(D.BotGrudge))).scalars().one().severity = severity
        await s.commit()


async def stones(db):
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        return (await s.get(D.Player, H)).spirit_stones


async def test_赔礼_按灵石折算_不够全消_够了一笔勾销(db):
    await with_grudge(db, 40)
    res = await bg.appease(H, "bot_00001", "stones", 100)
    assert res["ok"] and res["left"] == 30 and await stones(db) == 2900
    res = await bg.appease(H, "bot_00001", "stones", 500)
    assert res["ok"] and res["left"] == 0 and "一笔勾销" in res["reason"] and await rows(db) == []
    assert await stones(db) == 2400, "多赔的也照扣（没有退款）"


async def test_赔礼_灵石不够_数目不对_没有仇_都不扣钱(db):
    await with_grudge(db, 40)
    assert not (await bg.appease(H, "bot_00001", "stones", 0))["ok"]
    assert not (await bg.appease(H, "bot_00001", "stones", -5))["ok"]
    await mk_human(db, "1002", stones=3)
    assert "没有记恨" in (await bg.appease("1002", "bot_00001", "stones", 100))["reason"]
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        (await s.get(D.Player, H)).spirit_stones = 50
        await s.commit()
    res = await bg.appease(H, "bot_00001", "stones", 100)
    assert not res["ok"] and "不够" in res["reason"] and await stones(db) == 50
    assert not (await bg.appease(H, "bot_99999", "stones", 10))["ok"]
    assert not (await bg.appease(H, "bot_00001", "唱歌", 10))["ok"]


async def test_赔礼有上限(db):
    await with_grudge(db, 100)
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        (await s.get(D.Player, H)).spirit_stones = 10_000
        await s.commit()
    await bg.appease(H, "bot_00001", "stones", 10**6)
    assert await stones(db) == 10_000 - bg.load()["appease"]["max_stones"]


async def test_道歉_成功减仇_失败反而更恼_有冷却(db):
    await with_grudge(db, 50, kindness=80, profile={"vengeful": 0})
    now = 1_000_000.0
    res = await bg.appease(H, "bot_00001", "apology", rng=Z(0.99), now=now)
    assert not res["ok"] and "晚了" in res["reason"] and res["left"] == 55
    res = await bg.appease(H, "bot_00001", "apology", rng=Z(0.0), now=now + 60)
    assert not res["ok"] and "刚听过" in res["reason"]
    res = await bg.appease(H, "bot_00001", "apology", rng=Z(0.0), now=now + 13 * 3600)
    assert res["ok"] and res["left"] == 25


async def test_道歉_善良不记仇的更容易接受(db):
    D = db["db_async"]

    async def rate(kind, vengeful):
        n = 0
        for seed in range(400):
            async with D.AsyncSessionLocal() as s:
                for t in (await s.execute(select(D.BotGrudge))).scalars():
                    t.severity, t.last_apology = 50, 0
                await s.commit()
            n += (await bg.appease(H, "bot_00001", "apology", rng=R(seed), now=10**7))["ok"]
        return n / 400
    await with_grudge(db, 50, kindness=100, profile={"vengeful": 0})
    good = await rate(100, 0)
    async with D.AsyncSessionLocal() as s:
        p = await s.get(D.BotPersonality, "bot_00001")
        p.kindness, p.profile = 0, json.dumps({"vengeful": 100})
        await s.commit()
    bad = await rate(0, 100)
    cfg = bg.load()["appease"]["apology"]
    assert good > bad + 0.3 and abs(bad - cfg["base"]) < 0.08


async def test_送礼消气_好感加多少_仇恨减一倍半(db):
    await with_grudge(db, 40)
    assert await bg.on_gift(H, "bot_00001", 10) == 15
    assert (await rows(db))[0].severity == 25
    assert await bg.on_gift(H, "bot_00001", 0) == 0 and await bg.on_gift(H, "bot_00001", -5) == 0
    assert await bg.on_gift(H, "bot_00002", 10) == 0, "它没有恨你就什么都不做"
    await bg.on_gift(H, "bot_00001", 100)
    assert await rows(db) == []


async def test_真的送礼也会消气(db):
    from utils import bot_social as bs
    await with_grudge(db, 40)
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        p = await s.get(D.BotPersonality, "bot_00001")
        p.likes, p.dislikes = json.dumps({"categories": [], "items": ["筑基丹"]}), "{}"
        await s.commit()
    await db["inventory"].add_item(H, "筑基丹", 1)
    res = await bs.give_gift(H, "bot_00001", "筑基丹")
    assert res["ok"] and res["delta"] > 0
    assert (await rows(db))[0].severity == 40 - int(res["delta"] * bg.load()["appease"]["gift_factor"])


# ---- 机器人杀人 / 玩家被杀 --------------------------------------------------

async def test_机器人杀了真人_记进前世仇人_真人的朋友记仇(db):
    await mk_human(db, created_at=555.0)
    await mk_bot(db, "bot_00001", "阴鸷")                   # 凶手
    await mk_bot(db, "bot_00002")                          # 真人的朋友（真人 × 机器人的关系）
    await tie(db, H, "bot_00002", "结拜", 100)
    out = await bg.on_offense("bot_00001", H, "kill", rng=Z(0.0), now=NOW)
    assert [o["holder"] for o in out] == ["bot_00002"] and out[0]["target"] == "bot_00001"
    assert out[0]["reason"] == "机001杀害了你的结拜兄弟人1001"
    (e,) = await bg.previous_enemies(H)
    assert (e["enemy"], e["name"], e["life"], e["reason"]) == ("bot_00001", "机001", 555, "机001杀害了你")
    assert await bg.grudges_of(H) == [], "死人不在『现世』账上"


async def test_机器人劫了真人_真人的仇人列表里有它(db):
    await mk_human(db)
    await mk_bot(db, "bot_00001")
    await bg.on_offense("bot_00001", H, "rob", rng=R(1), now=NOW)
    (g,) = await bg.grudges_of(H)
    assert g["target"] == "bot_00001" and g["reason"] == "机001劫走了你的灵石" and g["style"] == "" and g["window_until"] == 0
    assert "机001" in await bg.format_list(H)


async def test_捕获处置杀人_走账本(db):
    from utils import world_settings
    await world_settings.set_values(mode="真实")
    await mk_human(db, realm="筑基期5层", created_at=777.0)
    await mk_bot(db, "bot_00001", "阴鸷", city=CITY)
    cfg = bc.be.load_config()
    cfg["combat"]["reaction"]["阴鸷"] = {"kill": 100}
    orig = bc.be.load_config
    bc.be.load_config = lambda: copy.deepcopy(cfg)
    try:
        res = await bc.handle_captive("bot_00001", H, R(0))
    finally:
        bc.be.load_config = orig
    assert res["killed"]
    (e,) = await bg.previous_enemies(H)
    assert e["enemy"] == "bot_00001" and e["life"] == 777


async def test_击杀机器人_它的朋友记仇_清理之前读到关系网(db, monkeypatch):
    real = bg.on_offense
    monkeypatch.setattr(bg, "on_offense", lambda a, v, k, **kw: real(a, v, k, rng=R(0), **kw))      # 第三方出头有概率（上限 95%），固定骰子
    await mk_human(db, city="万妖岭")
    await mk_bot(db, "bot_00001", city="万妖岭", fame=300)
    await mk_bot(db, "bot_00002", "豪爽", profile={"loyalty": 100})
    await tie(db, "bot_00001", "bot_00002", "结拜", 100)
    res = await bc.kill_bot(H, "bot_00001")
    assert res["ok"]
    got = await rows(db, holder_id="bot_00002")
    assert len(got) == 1 and got[0].target_id == H and got[0].kind == "kill" and "杀害了你的结拜兄弟" in got[0].reason
    assert await rows(db, holder_id="bot_00001") == []


async def test_废修为_受害者记仇(db):
    await mk_human(db, city="万妖岭")
    await mk_bot(db, "bot_00001", city="万妖岭")
    assert (await bc.cripple_bot(H, "bot_00001"))["ok"]
    (g,) = await rows(db, holder_id="bot_00001")
    assert g.kind == "cripple" and g.target_id == H


async def test_打劫_受害者记仇_它的朋友也会(db):
    await mk_human(db, city="万妖岭")
    await mk_bot(db, "bot_00001", city="万妖岭")
    await mk_bot(db, "bot_00002", profile={"loyalty": 100})
    await tie(db, "bot_00001", "bot_00002", "结拜", 100)
    assert (await bc.rob_bot(H, "bot_00001"))["ok"]
    assert (await rows(db, holder_id="bot_00001"))[0].kind == "rob"
    for _ in range(30):                              # 朋友是否出头看概率；多劫几次总会
        if await rows(db, holder_id="bot_00002"):
            break
        await bg.on_offense(H, "bot_00001", "rob", rng=Z(0.0), now=NOW)
    assert (await rows(db, holder_id="bot_00002"))[0].reason.endswith("劫了你的结拜兄弟机001")


async def test_机器人劫了真人_走账本(db):
    await mk_human(db, realm="筑基期5层", stones=1000)
    await mk_bot(db, "bot_00001", "贪财", city=CITY)
    cfg = bc.be.load_config()
    cfg["combat"]["reaction"]["贪财"] = {"rob": 100}
    orig = bc.be.load_config
    bc.be.load_config = lambda: copy.deepcopy(cfg)
    try:
        res = await bc.handle_captive("bot_00001", H, R(0))
    finally:
        bc.be.load_config = orig
    assert res["outcome"] == "rob"
    (g,) = await bg.grudges_of(H)
    assert g["target"] == "bot_00001" and g["kind"] == "rob"


# ---- 转世 -------------------------------------------------------------------

async def test_转世_机器人不再恨新的他_他的现世仇人存进前世(db):
    from utils.character_create_logic import commit_character
    await mk_human(db, created_at=1234.0)
    await mk_bot(db, "bot_00001")
    await mk_bot(db, "bot_00002")
    await bg.on_offense(H, "bot_00001", "rob", rng=R(1), now=NOW)                  # 机器人恨他
    await bg.on_offense("bot_00002", H, "rob", rng=R(1), now=NOW)                  # 他恨机器人
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        (await s.get(D.Player, H)).is_dead = True
        await s.commit()
    assert await commit_character(H, "新名字", "男", {})
    assert await rows(db, target_id=H) == [] and await rows(db, holder_id=H) == []
    (e,) = await bg.previous_enemies(H)
    assert e["enemy"] == "bot_00002" and e["life"] == 1234 and e["name"] == "机002" and "劫走" in e["reason"]
    assert await bg.grudges_of(H) == []
    text = await bg.format_list(H)
    assert "前世的仇" in text and "机002" in text


async def test_转世_朋友们为死者的仇还在(db):
    from utils.character_create_logic import commit_character
    await mk_human(db, is_dead=True)
    await mk_bot(db, "bot_00001")
    await mk_bot(db, "bot_00002")
    await tie(db, H, "bot_00002", "结拜", 100)
    await bg.on_offense("bot_00001", H, "kill", rng=Z(0.0), now=NOW)
    await commit_character(H, "新名字", "男", {})
    got = await rows(db, holder_id="bot_00002")
    assert len(got) == 1 and got[0].target_id == "bot_00001"


# ---- 界面 -------------------------------------------------------------------

async def test_仇人命令(db):
    from cogs.botworld import BotWorldCog
    from tests.discord_fakes import FakeContext
    await mk_human(db)
    await mk_bot(db, "bot_00001")
    cog = BotWorldCog(object())
    c = FakeContext(user_id=1001)
    await cog.enemies.callback(cog, c)
    assert c.said("还没有仇人")
    await bg.on_offense("bot_00001", H, "rob", rng=R(1), now=NOW)
    c = FakeContext(user_id=1001)
    await cog.enemies.callback(cog, c)
    assert c.said("你的仇人") and c.said("机001")


async def test_化解按钮_没仇告诉你没仇_有仇出赔礼面板(db):
    from tests.discord_fakes import FakeInteraction
    from utils.views import bot_actions
    await with_grudge(db, 40)
    target = {"discord_id": "bot_00001", "name": "机001"}
    i = FakeInteraction(user_id=int(H))
    await bot_actions.BotAppeaseButton(target).callback(i)
    assert i.response.last.view is not None and i.response.last.ephemeral
    labels = [c.label for c in i.response.last.view.children]
    assert labels == ["赔礼 100 灵石", "赔礼 500 灵石", "赔礼 2000 灵石", "诚心道歉"]
    j = FakeInteraction(user_id=int(H))
    await i.response.last.view.children[0].callback(j)
    assert j.response.said("赔礼") and (await rows(db))[0].severity == 30
    k = FakeInteraction(user_id=9999)
    await bot_actions.BotAppeaseButton(target).callback(k)
    assert k.response.said("并没有记恨你") and k.response.last.view is None


async def test_每日结算接上仇恨处理(db):
    from utils import bot_settle
    await expired_grudge(db)
    res = await bot_settle.run_settlement(force=True, rng=R(1))
    assert set(res["grudges"]) == {"renewed", "dormant", "faded", "orphans"}
