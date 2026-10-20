"""机器人之间的恩怨（utils/bot_feuds.py、data/bot_feuds.json）：仇敌 / 复仇动手，输的丢钱丢修为丢命，朋友接着记仇，有看头的进传闻。"""

import copy
import json
import random

import pytest
from sqlalchemy import select

from tests.conftest import make_player
from utils import bot_feuds as bf
from utils import bot_ties, rumors

CITY = "灵虚城"
NOW = 1_800_000_000.0
A, B, C = "bot_00001", "bot_00002", "bot_00003"


class U(random.Random):
    """uniform 依次吐出给定的值（比胜负时攻击方先、防守方后）。"""

    def __init__(self, *values):
        super().__init__(0)
        self.values = list(values)

    def uniform(self, a, b):
        return self.values.pop(0)


class Z(random.Random):
    def __init__(self, value=0.0):
        super().__init__(0)
        self.value = value

    def random(self):
        return self.value

    def uniform(self, a, b):
        return a + (b - a) * self.value


# ---- 配置与纯函数 -----------------------------------------------------------

def test_配置合法():
    from utils import bot_traits
    assert bf.validate(bf.load(), bot_traits.ARCHETYPES if hasattr(bot_traits, "ARCHETYPES") else None) == []


@pytest.mark.parametrize("mutate,expect", [
    (lambda c: c.update(tie_chance=2), "tie_chance"),
    (lambda c: c["outcomes"]["default"].pop("击杀"), "outcomes.default"),
    (lambda c: c["outcomes"]["by_archetype"]["豪爽"].update(口角=-1), "豪爽"),
    (lambda c: c["rumor"].update(击杀=2), "rumor"),
    (lambda c: c["power"].update(realm_step=0), "power"),
    (lambda c: c["social_rumors"].update(max_per_day=-1), "social_rumors"),
    (lambda c: c["rob"].update(share=2), "rob"),
])
def test_校验能拦住坏配置(mutate, expect):
    cfg = copy.deepcopy(bf.load())
    mutate(cfg)
    assert any(expect in e for e in bf.validate(cfg)), bf.validate(cfg)


def test_八种性格都有结果表():
    from utils import bot_grudges
    assert bf.validate(bf.load(), list(bot_grudges.load()["windows"])) == []


def info(realm=1, vengeful=50, city=CITY, arche="豪爽", uid=A):
    return {"id": uid, "realm": realm, "vengeful": vengeful, "city": city, "arche": arche}


def test_动手概率_仇敌看记仇度之和_仇恨账看轻重():
    assert bf.clash_chance("tie", info(vengeful=100), info(vengeful=100), True) == pytest.approx(0.03 * 2)
    assert bf.clash_chance("tie", info(vengeful=0), info(vengeful=0), True) == 0
    lo = bf.clash_chance("grudge", info(), info(), True, 10)
    hi = bf.clash_chance("grudge", info(), info(), True, 90)
    assert hi > lo > 0
    assert bf.clash_chance("grudge", info(), info(), False, 50) == pytest.approx(bf.clash_chance("grudge", info(), info(), True, 50) * 0.25)


def test_谨慎的等境界够了才动手():
    assert bf.ready("直接", 0, 5) and bf.ready("等待时机", 3, 4) and bf.ready("隐忍", 3, 3) and not bf.ready("隐忍", 3, 4)
    assert not bf.ready("等待时机", 0, 5)


def test_比胜负_境界高的赢_差距小才有变数():
    hi, lo = info(realm=3, uid=A), info(realm=1, uid=B)
    assert bf.fight(hi, lo, Z(0.0)) == (A, B) and bf.fight(lo, hi, Z(1.0)) == (A, B)
    near, far = info(realm=2, uid=B), info(realm=1, uid=A)
    assert bf.fight(far, near, U(1.5, 0.0)) == (A, B), "只差一个大境界，运气好的能翻盘"
    assert bf.fight(far, near, U(0.0, 1.5)) == (B, A)


def test_挑结果_性格不同_杀心不同():
    pick = lambda arche, **kw: bf.pick_outcome(arche, kw.get("kind", 50), kw.get("sev", 0), kw.get("gk"), Z(kw.get("r", 0.0)), kills_left=kw.get("kills", 1))  # noqa: E731
    assert pick("话痨", r=0.0) == "口角"
    assert pick("贪财", r=0.99) == "击杀" or True
    assert pick("阴鸷", r=0.999) == "击杀"
    assert pick("阴鸷", r=0.999, kills=0) != "击杀"
    assert pick("阴鸷", r=0.999, kind=100) == "击杀", "善良只是降低杀心，不是没有"


def test_挑结果_杀人大仇加重杀心_配置可整体关掉(monkeypatch):
    cfg = copy.deepcopy(bf.load())
    w = lambda **kw: bf.pick_outcome("豪爽", 50, kw.get("sev", 0), kw.get("gk"), Z(0.85), cfg, 1)  # noqa: E731
    assert w() != "击杀" and w(sev=100, gk="kill") == "击杀"
    cfg["kill_enabled"] = False
    assert w(sev=100, gk="kill") != "击杀"


def test_挑结果_权重全零退回口角():
    cfg = copy.deepcopy(bf.load())
    cfg["outcomes"]["by_archetype"]["豪爽"] = {"口角": 0, "劫财": 0, "废修为": 0, "击杀": 5}
    cfg["kill_enabled"] = False
    assert bf.pick_outcome("豪爽", 50, 0, None, Z(0.5), cfg, 1) == "口角"


# ---- 夹具 -------------------------------------------------------------------

async def mk_bot(db, uid, city=CITY, realm="炼气期1层", stones=1000, arche="豪爽", vengeful=100, kindness=50, tier="正常"):
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        p = make_player(D, uid)
        p.name, p.is_bot, p.lifespan, p.current_city, p.realm, p.spirit_stones, p.cultivation = f"机{uid[-3:]}", True, 80, city, realm, stones, 500
        s.add(p)
        prof = {"lawful": 50, "impulse": 50, "loyalty": 70, "vengeful": vengeful, "capacity": 30, "deviance": 0}
        s.add(D.BotPersonality(bot_id=uid, archetype=arche, tier=tier, home_city=city, kindness=kindness, profile=json.dumps(prof)))
        await s.commit()


async def mk_tie(db, a, b, kind="仇敌", strength=60):
    D = db["db_async"]
    x, y = bot_ties.pair(a, b)
    async with D.AsyncSessionLocal() as s:
        s.add(D.BotTie(a_id=x, b_id=y, kind=kind, strength=strength))
        await s.commit()


async def mk_grudge(db, holder, target, victim=None, kind="kill", severity=60, style="直接"):
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        s.add(D.BotGrudge(holder_id=holder, target_id=target, victim_id=victim or holder, kind=kind, reason="x", severity=severity,
                          state="active", style=style, known_at=NOW - 10, created_at=NOW - 10, window_until=NOW + 10**9))
        await s.commit()


async def player(db, uid):
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        p = await s.get(D.Player, uid)
        return None if p is None else (p.spirit_stones, p.cultivation, p.is_dead)


@pytest.fixture
def cfg(monkeypatch):
    c = copy.deepcopy(bf.load())
    monkeypatch.setattr(bf, "load", lambda: c)
    return c


def only(cfg, outcome):
    for t in [cfg["outcomes"]["default"], *cfg["outcomes"]["by_archetype"].values()]:
        for k in t:
            t[k] = 100 if k == outcome else 0


# ---- 一场冲突 ---------------------------------------------------------------

async def test_劫财_转走一部分灵石(db, cfg):
    await mk_bot(db, A, stones=100)
    await mk_bot(db, B, stones=1000)
    res = await bf._clash(A, B, "劫财", cfg)
    assert res["outcome"] == "劫财" and res["amount"] == 150
    assert (await player(db, A))[0] == 250 and (await player(db, B))[0] == 850


async def test_劫财_对方没钱退成口角(db, cfg):
    await mk_bot(db, A)
    await mk_bot(db, B, stones=0)
    res = await bf._clash(A, B, "劫财", cfg)
    assert (res["outcome"], res["amount"]) == ("口角", 0)


async def test_废修为(db, cfg):
    await mk_bot(db, A)
    await mk_bot(db, B)
    assert (await bf._clash(A, B, "废修为", cfg))["outcome"] == "废修为"
    assert (await player(db, B))[1] == 0 and (await player(db, A))[1] == 500


async def test_击杀_拿钱_并且死亡(db, cfg):
    await mk_bot(db, A, stones=0)
    await mk_bot(db, B, stones=1000)
    res = await bf._clash(A, B, "击杀", cfg)
    assert res["outcome"] == "击杀" and res["amount"] == 300
    assert (await player(db, B))[2] is True and (await player(db, A))[0] == 300


async def test_任何一方已死或是真人_不动手(db, cfg):
    D = db["db_async"]
    await mk_bot(db, A)
    await mk_bot(db, B)
    async with D.AsyncSessionLocal() as s:
        h = make_player(D, "1001")
        h.name = "真人"
        s.add(h)
        await s.commit()
    assert await bf._clash(A, "1001", "击杀", cfg) is None, "真人不在这里被杀"
    assert await bf._clash("1001", A, "击杀", cfg) is None
    assert await bf._clash(A, "bot_99999", "击杀", cfg) is None
    assert await bf._clash(A, B, "击杀", cfg) is not None
    assert await bf._clash(A, B, "击杀", cfg) is None, "已经死了不能再杀"


# ---- 每日 -------------------------------------------------------------------

async def run_day(cfg, rng=None, day="2026-10-20", **kw):
    cfg.update(tie_chance=1.0, grudge_chance=1.0)
    return await bf.feud_day(day, rng or Z(0.0), now=NOW, **kw)


async def test_仇敌关系每天动手_境界高的赢(db, cfg):
    only(cfg, "劫财")
    await mk_bot(db, A, realm="筑基期1层", stones=0)
    await mk_bot(db, B, realm="炼气期1层", stones=1000)
    await mk_tie(db, A, B)
    sm = await run_day(cfg, Z(0.0))
    assert sm["clashes"] == 1 and sm["劫财"] == 1
    assert (await player(db, A))[0] == 150 and (await player(db, B))[0] == 850


async def test_每日只认领一次_force可重跑(db, cfg):
    only(cfg, "废修为")
    await mk_bot(db, A, realm="筑基期1层")
    await mk_bot(db, B)
    await mk_tie(db, A, B)
    assert (await run_day(cfg))["clashes"] == 1
    assert await run_day(cfg) == {}
    assert (await run_day(cfg, force=True))["candidates"] == 2, "败者也记下了对胜者的仇"


async def test_朋友不打架(db, cfg):
    await mk_bot(db, A, realm="筑基期1层")
    await mk_bot(db, B)
    await mk_tie(db, A, B, kind="朋友")
    sm = await run_day(cfg)
    assert sm["candidates"] == 0 and sm["clashes"] == 0


async def test_复仇_持仇的人找目标_谨慎的境界不够就忍(db, cfg):
    only(cfg, "废修为")
    await mk_bot(db, A, realm="炼气期1层")
    await mk_bot(db, B, realm="元婴期初期")
    await mk_grudge(db, A, B, style="等待时机")
    sm = await run_day(cfg)
    assert sm["candidates"] == 1 and sm["clashes"] == 0
    await mk_bot(db, C, realm="炼气期1层")
    await mk_grudge(db, C, B, style="直接")
    assert (await run_day(cfg, force=True))["clashes"] == 1


async def test_击杀_有每日上限_败者朋友记仇_败者被清走(db, cfg):
    only(cfg, "击杀")
    cfg["kills_per_day"] = 1
    for uid, realm in ((A, "筑基期1层"), (B, "炼气期1层"), (C, "炼气期1层"), ("bot_00004", "炼气期1层"), ("bot_00005", "炼气期1层")):
        await mk_bot(db, uid, realm=realm, kindness=0)
    await mk_tie(db, A, B)
    await mk_tie(db, A, C)
    await mk_tie(db, B, "bot_00004", kind="朋友")                  # B 的朋友
    sm = await run_day(cfg, Z(0.0))
    assert sm["击杀"] == 1 and sm["clashes"] == 2 and sm["口角"] == 1, "第二场没有杀额度，只好口角"
    dead = [u for u in (B, C) if await player(db, u) is None]
    assert len(dead) == 1, "死掉的机器人被清走"
    if dead == [B]:
        D = db["db_async"]
        async with D.AsyncSessionLocal() as s:
            rows = list((await s.execute(select(D.BotGrudge).where(D.BotGrudge.holder_id == "bot_00004"))).scalars())
        assert [r.target_id for r in rows] == [A], "死者的朋友记下了凶手"


async def test_每天全服场次有上限(db, cfg):
    only(cfg, "废修为")
    cfg["max_clashes_per_day"] = 1
    for uid in (A, B, C):
        await mk_bot(db, uid, realm="炼气期1层")
    await mk_tie(db, A, B)
    await mk_tie(db, A, C)
    assert (await run_day(cfg))["clashes"] == 1


async def test_不同城折扣(db, cfg):
    only(cfg, "废修为")
    await mk_bot(db, A, city="灵虚城", realm="筑基期1层")
    await mk_bot(db, B, city="落云城")
    await mk_tie(db, A, B)
    cfg.update(tie_chance=1.0, cross_city_mult=0.0)
    assert (await bf.feud_day("d1", Z(0.5), now=NOW))["clashes"] == 0
    cfg["cross_city_mult"] = 1.0
    assert (await bf.feud_day("d2", Z(0.0), now=NOW))["clashes"] == 1


async def test_出错只记警告(db, cfg, monkeypatch, caplog):
    def boom(*a, **k):
        raise RuntimeError("库坏了")
    monkeypatch.setattr(bf, "AsyncSessionLocal", boom)
    sm = await bf.feud_day("d", Z(0.0), now=NOW)
    assert sm["clashes"] == 0 and "机器人每日恩怨失败" in caplog.text


# ---- 传闻 -------------------------------------------------------------------

async def rumor_kinds(db):
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        return sorted(r.kind for r in (await s.execute(select(D.Rumor))).scalars())


@pytest.mark.parametrize("outcome,kind", [("劫财", "bot_feud_rob"), ("废修为", "bot_feud_cripple"), ("击杀", "bot_feud_kill")])
async def test_有看头的结果进传闻(db, cfg, outcome, kind):
    only(cfg, outcome)
    cfg["rumor"][outcome] = 1.0
    await mk_bot(db, A, realm="筑基期1层", stones=0)
    await mk_bot(db, B, stones=1000)
    await mk_tie(db, A, B)
    await run_day(cfg)
    assert await rumor_kinds(db) == [kind]


async def test_口角不进传闻_概率为零也不进(db, cfg):
    only(cfg, "口角")
    await mk_bot(db, A, realm="筑基期1层")
    await mk_bot(db, B)
    await mk_tie(db, A, B)
    await run_day(cfg)
    assert await rumor_kinds(db) == []
    only(cfg, "废修为")
    cfg["rumor"]["废修为"] = 0.0
    await run_day(cfg, Z(0.0), force=True)
    assert await rumor_kinds(db) == []


async def test_关系演变的反目和结拜进传闻_有上限(db, cfg):
    await mk_bot(db, A)
    await mk_bot(db, B)
    await mk_bot(db, C)
    infos = {u: {} for u in (A, B, C)}
    cfg["social_rumors"] = {"max_per_day": 2, "quarrel_chance": 1.0, "sworn_chance": 1.0}
    n = await bf.social_gossip([("quarrel", A, B), ("sworn", [B, C]), ("quarrel", A, C)], infos, Z(0.0))
    assert n == 2 and await rumor_kinds(db) == ["bot_quarrel", "bot_sworn"]


async def test_传闻_概率为零_或成员不在时不记(db, cfg):
    await mk_bot(db, A)
    await mk_bot(db, B)
    cfg["social_rumors"] = {"max_per_day": 5, "quarrel_chance": 0.0, "sworn_chance": 0.0}
    assert await bf.social_gossip([("quarrel", A, B)], {A: {}, B: {}}, Z(0.5)) == 0
    cfg["social_rumors"] = {"max_per_day": 5, "quarrel_chance": 1.0, "sworn_chance": 1.0}
    assert await bf.social_gossip([("quarrel", A, B)], {A: {}}, Z(0.0)) == 0, "有人已不在世界里"
    assert await bf.social_gossip([("quarrel", A, "bot_99999")], {A: {}, "bot_99999": {}}, Z(0.0)) == 0, "库里查不到"
    assert await bf.social_gossip([("sworn", [A])], {A: {}}, Z(0.0)) == 0, "一个人结不了拜"


async def test_社交日把反目和结拜交给传闻(db, monkeypatch):
    await mk_bot(db, A)
    await mk_bot(db, B)
    got = {}

    async def fake(events, infos, rng):
        got["events"] = events
        return 7

    monkeypatch.setattr(bf, "social_gossip", fake)
    monkeypatch.setattr(bot_ties, "social_book", lambda book, rng, cfg=None: book.events.append(("quarrel", A, B)) or {})
    sm = await bot_ties.social_day("d", random.Random(1))
    assert got["events"] == [("quarrel", A, B)] and sm["gossip"] == 7


def test_社交簿记录反目与结拜():
    rng = random.Random(3)
    cfg = copy.deepcopy(bot_ties.load())
    cfg["daily"].update(quarrel_base=1.0, sworn_strength=0, sworn_loyalty=0, sworn_chance=1.0, meet_chance=0.0)
    infos = {u: {"id": u, "arche": "豪爽", "city": CITY, "realm": 1, "cap": 30, "loyalty": 90, "vengeful": 100, "lawful": 50, "pride": 50, "kindness": 50}
             for u in (A, B)}
    book = bot_ties.TieBook(infos, {bot_ties.pair(A, B): {"kind": "朋友", "strength": 90, "bond_id": "", "note": ""}})
    bot_ties.social_book(book, rng, cfg)
    assert [e[0] for e in book.events] == ["quarrel"]
    cfg["daily"]["quarrel_base"] = 0.0
    book = bot_ties.TieBook(infos, {bot_ties.pair(A, B): {"kind": "朋友", "strength": 90, "bond_id": "", "note": ""}})
    bot_ties.social_book(book, rng, cfg)
    assert [e[0] for e in book.events] == ["sworn"] and sorted(book.events[0][1]) == [A, B]


# ---- 补：变异测试暴露的缺口 -------------------------------------------------

def test_仇恨账动手概率看持仇人自己的记仇度():
    assert bf.clash_chance("grudge", info(vengeful=100), info(vengeful=0), True, 50) > bf.clash_chance("grudge", info(vengeful=0), info(vengeful=100), True, 50)


def test_境界和运气都一样_先动手的赢():
    assert bf.fight(info(uid=A), info(uid=B), Z(0.3)) == (A, B)


def test_杀人大仇加重杀心的幅度由配置定():
    cfg = copy.deepcopy(bf.load())
    cfg["grudge_kill_bonus"] = 0
    assert bf.pick_outcome("豪爽", 50, 100, "kill", Z(0.85), cfg, 1) != "击杀"
    cfg["grudge_kill_bonus"] = 1
    assert bf.pick_outcome("豪爽", 50, 100, "kill", Z(0.85), cfg, 1) == "击杀"


async def test_仇敌关系里谁先动手是随机的(db, cfg):
    only(cfg, "废修为")
    await mk_bot(db, A)
    await mk_bot(db, B)
    await mk_tie(db, A, B)
    await run_day(cfg, Z(0.0))                      # random() < 0.5 → 换边，后一个（B）先动手；境界相同先动手的赢
    assert (await player(db, A))[1] == 0 and (await player(db, B))[1] == 500
    await bf.feud_day("d2", Z(0.9), now=NOW)        # 不换边：A 先动手
    assert (await player(db, B))[1] == 0


async def test_复仇时_只有持仇的人赢了才带着仇恨的轻重(db, cfg, monkeypatch):
    await mk_bot(db, A, realm="炼气期1层")
    await mk_bot(db, B, realm="元婴期初期")
    await mk_grudge(db, A, B, kind="kill", severity=77)
    seen = []
    real = bf.pick_outcome
    monkeypatch.setattr(bf, "pick_outcome", lambda *a, **k: seen.append(a[2:4]) or real(*a, **k))
    cfg.update(tie_chance=1.0, grudge_chance=1.0)
    await bf.feud_day("d", Z(0.0), now=NOW)
    assert seen == [(0, None)], "B 反杀了 A，B 身上没有这笔仇"


async def test_还没得知的仇不动手(db, cfg):
    D = db["db_async"]
    await mk_bot(db, A, realm="筑基期1层")
    await mk_bot(db, B)
    await mk_grudge(db, A, B)
    async with D.AsyncSessionLocal() as s:
        g = (await s.execute(select(D.BotGrudge))).scalar_one()
        g.known_at = NOW + 1000
        await s.commit()
    assert (await run_day(cfg))["candidates"] == 0


async def test_结拜传闻用结拜的概率(db, cfg):
    await mk_bot(db, A)
    await mk_bot(db, B)
    cfg["social_rumors"] = {"max_per_day": 5, "quarrel_chance": 0.0, "sworn_chance": 1.0}
    assert await bf.social_gossip([("sworn", [A, B])], {A: {}, B: {}}, Z(0.5)) == 1
