"""机器人关系网（utils/bot_ties.py、data/bot_ties.json）。

用户 2026-10-12 的设计：相识 / 朋友 / 结拜（可多人）/ 同门 / 仇敌；认识的人有上限；一切结识都是概率（性格相合只提高概率，不保证）；
同城为主、跨城为辅；境界相近更容易；关系会变（反目、和解、结拜）；共同经历（组队、公共事件）能认识；真人 × 机器人也有正式关系。
"""

import copy
import json
import random

import pytest
from sqlalchemy import select

from tests.conftest import make_player
from utils import bot_ties as bt
from utils.bot_social import load_archetypes

CITY = "灵虚城"


def R(seed=0):
    return random.Random(seed)


def info(uid, arche="豪爽", city=CITY, realm=1, cap=10, loyalty=60, vengeful=50, **kw):
    return {"id": uid, "arche": arche, "city": city, "realm": realm, "cap": cap, "loyalty": loyalty, "vengeful": vengeful,
            "lawful": 50, "pride": 50, "kindness": 50, **kw}


def book_of(*infos, ties=None):
    return bt.TieBook({i["id"]: i for i in infos}, ties or {})


# ---- 数据 -------------------------------------------------------------------

def test_配置合法_覆盖所有原型():
    cfg = bt.load()
    assert bt.validate(cfg, list(load_archetypes())) == []
    pairs = {tuple(sorted(r[:2])) for r in cfg["affinity"]["pairs"]}
    names = sorted(load_archetypes())
    assert pairs == {(a, b) for i, a in enumerate(names) for b in names[i:]}, "每一对性格组合都有明确的亲和度"


@pytest.mark.parametrize("mutate,expect", [
    (lambda c: c["affinity"].update(min=0.9, default=0.5), "affinity:"),
    (lambda c: c["affinity"]["pairs"].append(["豪爽", "憨直", 0.5]), "重复"),
    (lambda c: c["affinity"]["pairs"].append(["豪爽", "没有的性格", 0.5]), "未知原型"),
    (lambda c: c["affinity"]["pairs"].append(["豪爽", "憨直", 2]), "0~1"),
    (lambda c: c["start_strength"].pop("仇敌"), "覆盖"),
    (lambda c: c["start_strength"].update(朋友=[70, 20]), "start_strength.朋友"),
    (lambda c: c["daily"].update(meet_chance=2), "meet_chance"),
    (lambda c: c["daily"].update(bond_max=1), "bond_max"),
    (lambda c: c["city"].update(other=0), "city.other"),
])
def test_校验能拦住坏配置(mutate, expect):
    cfg = copy.deepcopy(bt.load())
    mutate(cfg)
    assert any(expect in e for e in bt.validate(cfg, list(load_archetypes()))), bt.validate(cfg, list(load_archetypes()))


# ---- 概率 -------------------------------------------------------------------

def test_亲和度对称_缺的用默认_不低于下限():
    assert bt.affinity("豪爽", "憨直") == bt.affinity("憨直", "豪爽") == 0.9
    assert bt.affinity("豪爽", "阴鸷") < bt.affinity("贪财", "阴鸷")
    cfg = copy.deepcopy(bt.load())
    cfg["affinity"]["pairs"] = [["豪爽", "憨直", 0.0]]
    assert bt.affinity("豪爽", "憨直", cfg) == cfg["affinity"]["min"]
    assert bt.affinity("痴丹", "迂腐", cfg) == cfg["affinity"]["default"]


def test_结识概率_同城_境界_事由_性格都有影响_但不是必然():
    a, b = info("a"), info("b")
    same = bt.form_chance(a, b, "同城")
    assert 0 < same < 0.95
    assert bt.form_chance(a, info("b", city="落云城"), "同城") < same * 0.2
    assert bt.form_chance(a, info("b", realm=3), "同城") < same
    assert bt.form_chance(a, b, "组队") > same
    assert bt.form_chance(info("a", "阴鸷"), info("b", "豪爽"), "同城") < bt.form_chance(info("a", "豪爽"), info("b", "憨直"), "同城")
    assert bt.form_chance(info("a", "阴鸷"), info("b", "豪爽"), "同城") > 0, "合不来也有可能认识"
    assert max(bt.form_chance(a, info("b", "憨直"), c) for c in bt.load()["context"]) <= 0.95


def test_初识关系_合得来的容易一见如故_合不来又记仇的容易有梁子():
    def dist(a, b):
        rng, out = R(3), {"相识": 0, "朋友": 0, "仇敌": 0}
        for _ in range(4000):
            out[bt.roll_kind(a, b, rng)] += 1
        return out
    good, bad = dist(info("a", "豪爽"), info("b", "憨直")), dist(info("a", "豪爽", vengeful=90), info("b", "阴鸷", vengeful=90))
    assert good["朋友"] > bad["朋友"] * 2 and bad["仇敌"] > good["仇敌"] * 2 and good["相识"] > 1500


# ---- 关系簿 -----------------------------------------------------------------

def test_容量上限_满了就不再认识人_真人没有上限():
    cfg = bt.load()
    book = book_of(info("bot_1", cap=2), info("bot_2"), info("bot_3"), info("bot_4"))
    assert book.add("bot_1", "bot_2", "相识", R(), cfg) and book.add("bot_1", "bot_3", "相识", R(), cfg)
    assert not book.add("bot_1", "bot_4", "相识", R(), cfg), "bot_1 的容量是 2"
    assert not book.add("bot_2", "bot_1", "朋友", R(), cfg), "已经认识了不重复加"
    assert book.add("1001", "bot_4", "朋友", R(), cfg), "真人（不在 infos 里）没有容量限制"
    assert not book.add("bot_2", "bot_2", "相识", R(), cfg)


def test_团体结拜_两两成为兄弟_共用编号_升级已有的关系():
    cfg = bt.load()
    book = book_of(*(info(f"bot_{i}", cap=1) for i in range(1, 5)))
    book.add("bot_1", "bot_2", "朋友", R(), cfg)
    book.changed.clear()
    bond = bt.form_group(book, ["bot_1", "bot_2", "bot_3", "bot_4"], "结拜", R(1), cfg, note="结拜")
    assert len(book.ties) == 6, "四个人两两都是兄弟：C(4,2)"
    assert {r["kind"] for r in book.ties.values()} == {"结拜"} and {r["bond_id"] for r in book.ties.values()} == {bond}
    assert book.ties[("bot_1", "bot_2")]["strength"] >= cfg["start_strength"]["结拜"][0]
    assert ("bot_1", "bot_2") in book.new and not book.changed, "原来那条本来就是这次新增的，整条一起写"
    old = {("bot_1", "bot_2"): {"kind": "朋友", "strength": 90, "bond_id": "", "note": "同城"}}
    book = book_of(info("bot_1"), info("bot_2"), ties=old)
    bt.form_group(book, ["bot_1", "bot_2"], "结拜", R(1), cfg)
    assert book.changed == {("bot_1", "bot_2")} and book.ties[("bot_1", "bot_2")]["strength"] == 90 and book.ties[("bot_1", "bot_2")]["note"] == "同城"


def test_初始关系网_不超容量_多在同城_不重复_可复现():
    cfg = bt.load()
    arches = sorted(load_archetypes())
    infos = [info(f"bot_{i:03d}", arches[i % 8], CITY if i % 3 else "落云城", cap=(i % 20) + 3) for i in range(120)]

    def build(seed):
        b = book_of(*infos)
        bt.seed_book(b, [i["id"] for i in infos], R(seed), cfg)
        return b
    b1, b2 = build(5), build(5)
    assert b1.ties == b2.ties and b1.ties
    assert build(6).ties != b1.ties
    same_city = sum(1 for (x, y) in b1.ties if b1.infos[x]["city"] == b1.infos[y]["city"])
    assert same_city / len(b1.ties) > 0.7
    for uid, n in b1.count.items():
        assert n <= b1.infos[uid]["cap"] or any(r["kind"] in ("同门", "结拜") for k, r in b1.ties.items() if uid in k), "团体关系（同门 / 结拜）不受容量限制"
    assert all(a < b for a, b in b1.ties)
    assert {r["kind"] for r in b1.ties.values()} >= {"相识", "朋友"}


def test_初始关系网_有同门小团体_同城_共用编号():
    cfg = bt.load()
    infos = [info(f"bot_{i:03d}", cap=5) for i in range(200)]
    b = book_of(*infos)
    bt.seed_book(b, [i["id"] for i in infos], R(1), cfg)
    groups = {}
    for key, row in b.ties.items():
        if row["kind"] == "同门":
            groups.setdefault(row["bond_id"], set()).update(key)
    assert groups and all(2 <= len(m) <= cfg["seed"]["sect_group_size"][1] for m in groups.values())
    for members in groups.values():
        assert len({b.infos[m]["city"] for m in members}) == 1


def test_初始就有结拜兄弟_重义气_同城_共用编号():
    cfg = bt.load()
    infos = [info(f"bot_{i:03d}", cap=5, loyalty=(90 if i % 2 else 10)) for i in range(300)]
    b = book_of(*infos)
    bt.seed_book(b, [i["id"] for i in infos], R(3), cfg)
    bonds = {}
    for key, row in b.ties.items():
        if row["kind"] == "结拜":
            bonds.setdefault(row["bond_id"], set()).update(key)
    assert bonds and all(2 <= len(m) <= cfg["seed"]["sworn_size"][1] for m in bonds.values())
    for members in bonds.values():
        assert all(b.infos[m]["loyalty"] >= cfg["daily"]["sworn_loyalty"] for m in members)
        assert len({b.infos[m]["city"] for m in members}) == 1
    sworn = {m for members in bonds.values() for m in members}
    assert len(sworn) <= 300 * cfg["seed"]["sworn_share"] + 5


def test_零容量的人不认识任何人():
    b = book_of(*[info(f"bot_{i}", cap=0) for i in range(30)])
    bt.seed_book(b, list(b.infos), R(2))
    assert not [k for k, r in b.ties.items() if r["kind"] != "同门"]


# ---- 每日社交 ---------------------------------------------------------------

def cfg_with(**daily):
    cfg = copy.deepcopy(bt.load())
    cfg["daily"].update(daily)
    return cfg


def test_同城碰面认识新人():
    cfg = cfg_with(meet_chance=1.0)
    b = book_of(*[info(f"bot_{i}", "豪爽", cap=30) for i in range(40)])
    sm = bt.social_book(b, R(1), cfg)
    assert sm["met"] > 10 and b.new
    assert all(r["note"] == "同城" for r in b.new.values())


def test_交情不够不会成朋友():
    cfg = cfg_with(meet_chance=1.0, befriend_chance=1.0)
    grew = 0
    for seed in range(20):
        b = book_of(info("bot_1", "豪爽"), info("bot_2", "憨直"), ties={("bot_1", "bot_2"): {"kind": "相识", "strength": 5, "bond_id": "", "note": ""}})
        bt.social_book(b, R(seed), cfg)
        row = b.ties[("bot_1", "bot_2")]
        assert row["kind"] == "相识" and row["strength"] < 40
        grew += row["strength"] > 5
    assert grew > 5


def test_不同城的人不会在每日社交里碰面():
    cfg = cfg_with(meet_chance=1.0)
    b = book_of(*[info(f"bot_{i}", city=f"城{i}") for i in range(20)])
    bt.social_book(b, R(1), cfg)
    assert not b.ties


def test_再次碰面加深交情_够了变成朋友():
    cfg = cfg_with(meet_chance=1.0, befriend_chance=1.0)
    b = book_of(info("bot_1", "豪爽"), info("bot_2", "憨直"), ties={("bot_1", "bot_2"): {"kind": "相识", "strength": 39, "bond_id": "", "note": ""}})
    for seed in range(20):
        bt.social_book(b, R(seed), cfg)
    assert b.ties[("bot_1", "bot_2")]["kind"] == "朋友" and b.ties[("bot_1", "bot_2")]["strength"] > 39


def test_朋友会反目_仇人会和解():
    friend = {("bot_1", "bot_2"): {"kind": "朋友", "strength": 50, "bond_id": "", "note": ""}}
    b = book_of(info("bot_1", vengeful=100), info("bot_2", vengeful=100), ties=copy.deepcopy(friend))
    sm = bt.social_book(b, R(1), cfg_with(meet_chance=0, quarrel_base=1.0))
    assert sm["quarrels"] == 1 and b.ties[("bot_1", "bot_2")]["kind"] == "仇敌" and b.ties[("bot_1", "bot_2")]["note"] == "反目"
    b = book_of(info("bot_1", vengeful=0), info("bot_2", vengeful=0), ties={("bot_1", "bot_2"): {"kind": "仇敌", "strength": 50, "bond_id": "", "note": ""}})
    sm = bt.social_book(b, R(1), cfg_with(meet_chance=0, reconcile_base=1.0))
    assert sm["reconciled"] == 1 and b.ties[("bot_1", "bot_2")]["kind"] == "相识"


def test_记仇的更难和解_温和的更少反目():
    def rate(v, kind, key):
        n = 0
        for seed in range(2000):
            b = book_of(info("bot_1", vengeful=v), info("bot_2", vengeful=v),
                        ties={("bot_1", "bot_2"): {"kind": kind, "strength": 50, "bond_id": "", "note": ""}})
            n += bt.social_book(b, R(seed), cfg_with(meet_chance=0, quarrel_base=0.05, reconcile_base=0.05))[key]
        return n
    assert rate(100, "仇敌", "reconciled") == 0 or rate(100, "仇敌", "reconciled") < rate(0, "仇敌", "reconciled") / 3
    assert rate(100, "朋友", "quarrels") > rate(10, "朋友", "quarrels") * 3


def test_结拜_交情深且重义气才会_会拉上共同的朋友_有人数上限():
    def friends(*ids, strength=90):
        return {(a, b): {"kind": "朋友", "strength": strength, "bond_id": "", "note": ""} for i, a in enumerate(ids) for b in ids[i + 1:]}
    cfg = cfg_with(meet_chance=0, sworn_chance=1.0, bond_extend_chance=1.0, quarrel_base=0)
    infos = [info(f"bot_{i}", loyalty=90) for i in range(1, 8)]
    b = book_of(*infos, ties=friends(*[i["id"] for i in infos]))
    sm = bt.social_book(b, R(1), cfg)
    sworn = [k for k, r in b.ties.items() if r["kind"] == "结拜"]
    members = {m for k in sworn for m in k}
    bonds = {}
    for k in sworn:
        bonds.setdefault(b.ties[k]["bond_id"], set()).update(k)
    assert sm["sworn"] >= 1 and all(2 <= len(m) <= cfg["daily"]["bond_max"] for m in bonds.values())
    assert max(len(m) for m in bonds.values()) > 2, "共同的朋友被拉进来了"
    assert all(not (bonds_a & bonds_b) for i, bonds_a in enumerate(bonds.values()) for bonds_b in list(bonds.values())[i + 1:]), "一个人只在一个结拜里"
    # 义气不够 / 交情不够：不结拜
    low = book_of(info("bot_1", loyalty=10), info("bot_2", loyalty=90), ties=friends("bot_1", "bot_2"))
    assert not bt.social_book(low, R(1), cfg)["sworn"]
    shallow = book_of(info("bot_1", loyalty=90), info("bot_2", loyalty=90), ties=friends("bot_1", "bot_2", strength=50))
    assert not bt.social_book(shallow, R(1), cfg)["sworn"]


def test_已经在结拜里的不再结第二次拜():
    cfg = cfg_with(meet_chance=0, sworn_chance=1.0, quarrel_base=0)
    ties = {("bot_1", "bot_2"): {"kind": "结拜", "strength": 90, "bond_id": "x", "note": ""},
            ("bot_1", "bot_3"): {"kind": "朋友", "strength": 95, "bond_id": "", "note": ""},
            ("bot_2", "bot_3"): {"kind": "朋友", "strength": 95, "bond_id": "", "note": ""}}
    b = book_of(*[info(f"bot_{i}", loyalty=90) for i in (1, 2, 3)], ties=ties)
    assert not bt.social_book(b, R(1), cfg)["sworn"]


def test_有真人的关系不参与演变():
    human = {("1001", "bot_1"): {"kind": "朋友", "strength": 90, "bond_id": "", "note": ""}}
    b = book_of(info("bot_1", vengeful=100), ties=copy.deepcopy(human))
    bt.social_book(b, R(1), cfg_with(meet_chance=0, quarrel_base=1.0, sworn_chance=1.0))
    assert b.ties == human and not b.changed


# ---- 落库 -------------------------------------------------------------------

async def mk_bot(db, uid, arche="豪爽", city=CITY, realm="筑基期1层", profile=None, alive=True):
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        p = make_player(D, uid)
        p.name, p.is_bot, p.lifespan, p.current_city, p.realm, p.is_dead = f"机{uid[-3:]}", True, 80, city, realm, not alive
        s.add(p)
        prof = {"lawful": 50, "impulse": 50, "loyalty": 60, "vengeful": 50, "capacity": 30, "deviance": 0, **(profile or {})}
        s.add(D.BotPersonality(bot_id=uid, archetype=arche, tier="正常", home_city=city, profile=json.dumps(prof)))
        await s.commit()


async def mk_human(db, uid="1001", **kw):
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        p = make_player(D, uid)
        p.name, p.lifespan = f"人{uid}", 80
        for k, v in kw.items():
            setattr(p, k, v)
        s.add(p)
        await s.commit()


async def all_ties(db):
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        return {(t.a_id, t.b_id): t for t in (await s.execute(select(D.BotTie))).scalars()}


async def test_生成机器人时建初始关系网(db):
    from utils import bot_world
    res = await bot_world.generate_bots(60, R(2))
    assert res["ok"]
    ties = await all_ties(db)
    ids = {c["id"] for c in res["created"]}
    assert ties and all(a in ids and b in ids and a < b for a, b in ties)


async def test_每日社交_按日认领_只跑一次_force可重跑(db):
    for i in range(1, 25):
        await mk_bot(db, f"bot_{i:05d}")
    first = await bt.social_day("2026-10-12", R(1))
    assert first and first.get("new_ties", 0) > 0
    n = len(await all_ties(db))
    assert await bt.social_day("2026-10-12", R(2)) == {}, "同一天不重复"
    assert len(await all_ties(db)) == n
    assert await bt.social_day("2026-10-13", R(3)), "第二天可以"
    assert await bt.social_day("2026-10-13", R(4), force=True)


async def test_每日结算后接着做社交(db):
    from utils import bot_settle
    for i in range(1, 15):
        await mk_bot(db, f"bot_{i:05d}")
    res = await bot_settle.run_settlement(force=True, rng=R(1))
    assert "social" in res and res["social"].get("new_ties", 0) >= 0
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        assert (await s.get(D.BotWorldState, bt.SOCIAL_KEY)).value


async def test_共同经历_组队的机器人互相认识(db, monkeypatch):
    from utils import party
    await mk_human(db)
    await mk_bot(db, "bot_00001")
    await mk_bot(db, "bot_00002")
    monkeypatch.setattr(bt, "form_chance", lambda *a, **k: 1.0)
    from utils import bot_social as bs
    for b in ("bot_00001", "bot_00002"):
        await bs.adjust_favor("1001", b, 100)
    pid = await party.create_party("1001", CITY)
    assert await party.add_to_party(pid, "bot_00001")
    assert not await all_ties_between(db, "bot_00001", "bot_00002")
    assert await party.add_to_party(pid, "bot_00002")
    assert await all_ties_between(db, "bot_00001", "bot_00002"), "同队的两个机器人认识了"
    assert (await all_ties_between(db, "bot_00001", "bot_00002")).note == "组队"


async def test_共同经历_邀请入队也算(db, monkeypatch):
    from utils import bot_social as bs
    from utils import party
    await mk_human(db)
    for b in ("bot_00001", "bot_00002"):
        await mk_bot(db, b)
        await bs.adjust_favor("1001", b, 100)
    monkeypatch.setattr(bt, "form_chance", lambda *a, **k: 1.0)
    assert (await party.accept_invite("1001", "bot_00001"))["ok"]
    assert not await all_ties_between(db, "bot_00001", "bot_00002")
    assert (await party.accept_invite("1001", "bot_00002"))["ok"]
    assert (await all_ties_between(db, "bot_00001", "bot_00002")).note == "组队"


async def all_ties_between(db, a, b):
    return (await all_ties(db)).get(bt.pair(a, b))


async def test_共同经历_公共事件里碰面的机器人互相认识(db, monkeypatch):
    from utils import bot_events
    for i in range(1, 7):
        await mk_bot(db, f"bot_{i:05d}")
    seen = []

    async def spy(ids, context, rng=None, max_pairs=8):
        seen.append((sorted(ids), context, max_pairs))
        return 0
    monkeypatch.setattr(bt, "meet_group", spy)
    monkeypatch.setattr(bot_events.be, "load_config", (lambda real=bot_events.be.load_config: (lambda: {**real(), "public_events": {**real()["public_events"], "join_chance": 1.0}}))())
    out = await bot_events.join_spirit_rain("evt1", CITY, False, R(1))
    assert out["joined"] > 0 and seen and seen[0][1] == "公共事件" and len(seen[0][0]) == out["joined"]


async def test_meet_group_概率认识_已认识的加深_真人不算(db, monkeypatch):
    await mk_human(db)
    for i in range(1, 4):
        await mk_bot(db, f"bot_{i:05d}")
    monkeypatch.setattr(bt, "form_chance", lambda *a, **k: 1.0)
    assert await bt.meet_group(["bot_00001", "bot_00002", "bot_00003", "1001"], "公共事件", R(1)) == 3
    ties = await all_ties(db)
    assert len(ties) == 3 and not any("1001" in k for k in ties)
    before = ties[("bot_00001", "bot_00002")].strength
    assert await bt.meet_group(["bot_00001", "bot_00002"], "组队", R(2)) == 0
    assert (await all_ties(db))[("bot_00001", "bot_00002")].strength > before
    assert await bt.meet_group(["bot_00001"], "组队") == 0


async def test_meet_group_出错只记警告(db, monkeypatch, caplog):
    def boom(*a, **k):
        raise RuntimeError("库坏了")
    monkeypatch.setattr(bt, "AsyncSessionLocal", boom)
    assert await bt.meet_group(["bot_00001", "bot_00002"], "组队") == 0
    assert "共同经历建立关系失败" in caplog.text


# ---- 查询 / 清理 ------------------------------------------------------------

async def seed_ties(db, rows):
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        for a, b, kind, strength in rows:
            x, y = bt.pair(a, b)
            s.add(D.BotTie(a_id=x, b_id=y, kind=kind, strength=strength, bond_id="g" if kind in ("结拜", "同门") else ""))
        await s.commit()


async def test_查询_两头都能查到_按交情排序_可按种类筛(db):
    for i in range(1, 6):
        await mk_bot(db, f"bot_{i:05d}")
    await seed_ties(db, [("bot_00001", "bot_00002", "朋友", 50), ("bot_00003", "bot_00001", "结拜", 90),
                         ("bot_00001", "bot_00004", "仇敌", 60), ("bot_00001", "bot_00005", "相识", 10)])
    got = await bt.ties_of("bot_00001")
    assert [(t["other"], t["kind"]) for t in got] == [("bot_00003", "结拜"), ("bot_00004", "仇敌"), ("bot_00002", "朋友"), ("bot_00005", "相识")]
    assert [t["other"] for t in await bt.ties_of("bot_00003")] == ["bot_00001"]
    assert [t["kind"] for t in await bt.ties_of("bot_00001", ("朋友", "结拜"))] == ["结拜", "朋友"]
    assert [t["other"] for t in await bt.mourners("bot_00001")] == ["bot_00003", "bot_00002"], "替死者出头的只有 朋友 / 结拜 / 同门"


async def test_资料页一行关系(db):
    for i in range(1, 7):
        await mk_bot(db, f"bot_{i:05d}")
    assert await bt.describe("bot_00001") == ""
    await seed_ties(db, [("bot_00001", "bot_00002", "结拜", 90), ("bot_00001", "bot_00003", "同门", 60), ("bot_00001", "bot_00004", "朋友", 50),
                         ("bot_00001", "bot_00005", "仇敌", 60), ("bot_00001", "bot_00006", "相识", 10)])
    line = await bt.describe("bot_00001")
    assert line.startswith("关系：") and "结拜兄弟：机002" in line and "同门 1 人" in line and "朋友 1 人" in line
    assert "仇家 1 人" in line and "相识 1 人" in line


async def test_清理机器人_两头的关系都删_包括真人的(db):
    from utils import bot_world
    await mk_human(db)
    for i in range(1, 4):
        await mk_bot(db, f"bot_{i:05d}")
    await seed_ties(db, [("bot_00001", "bot_00002", "朋友", 50), ("bot_00002", "bot_00003", "朋友", 50), ("1001", "bot_00001", "朋友", 50),
                         ("1001", "bot_00003", "朋友", 50)])
    res = await bot_world.remove_bots(["bot_00001"])
    assert res["rows"]["bot_ties"] == 2
    assert set(await all_ties(db)) == {("bot_00002", "bot_00003"), ("1001", "bot_00003")}


async def test_转世后真人的关系清掉_别人的不动(db):
    from utils.character_create_logic import commit_character
    await mk_human(db, is_dead=True)
    await mk_bot(db, "bot_00001")
    await mk_bot(db, "bot_00002")
    await seed_ties(db, [("1001", "bot_00001", "结拜", 90), ("bot_00001", "bot_00002", "朋友", 50)])
    assert await commit_character("1001", "新名字", "男", {})
    assert set(await all_ties(db)) == {("bot_00001", "bot_00002")}


# ---- 真人 × 机器人 ----------------------------------------------------------

async def test_好感到线自动升级关系_相识_朋友_仇敌(db):
    await mk_human(db)
    await mk_bot(db, "bot_00001")
    key = ("1001", "bot_00001")
    await bt.sync_player_tie("1001", "bot_00001", 10)
    assert (await all_ties(db))[key].kind == "相识"
    await bt.sync_player_tie("1001", "bot_00001", 49)
    assert (await all_ties(db))[key].kind == "相识"
    await bt.sync_player_tie("1001", "bot_00001", 50)
    assert (await all_ties(db))[key].kind == "朋友"
    await bt.sync_player_tie("1001", "bot_00001", 20)
    assert (await all_ties(db))[key].kind == "朋友", "好感回落不会立刻绝交"
    await bt.sync_player_tie("1001", "bot_00001", -30)
    assert (await all_ties(db))[key].kind == "仇敌"
    await bt.sync_player_tie("1001", "bot_00001", -5)
    assert (await all_ties(db))[key].kind == "相识", "仇恨淡去（好感回到 -10 以上）"
    await bt.sync_player_tie("1001", "bot_00001", 60)
    assert (await all_ties(db))[key].kind == "朋友"


async def test_好感变化时自动同步(db):
    from utils import bot_social as bs
    await mk_human(db)
    await mk_bot(db, "bot_00001")
    await bs.adjust_favor("1001", "bot_00001", 55)
    assert (await all_ties_between(db, "1001", "bot_00001")).kind == "朋友"
    await bs.adjust_favor("1001", "bot_00001", -100)
    assert (await all_ties_between(db, "1001", "bot_00001")).kind == "仇敌"


async def test_结拜_条件_拒绝冷却_成功(db):
    await mk_human(db)
    await mk_bot(db, "bot_00001", profile={"loyalty": 100})
    now = 1_000_000.0
    res = await bt.propose_bond("1001", "bot_00001", 90, R(1), now)
    assert not res["ok"] and "交情还不到" in res["reason"]                          # 还不是朋友
    await seed_ties(db, [("1001", "bot_00001", "朋友", 70)])
    assert "交情还不到" in (await bt.propose_bond("1001", "bot_00001", 79, R(1), now))["reason"]

    class Refuse(random.Random):
        def random(self):
            return 0.99
    res = await bt.propose_bond("1001", "bot_00001", 90, Refuse(), now)
    assert not res["ok"] and "婉拒" in res["reason"]
    assert "刚拒绝过" in (await bt.propose_bond("1001", "bot_00001", 90, R(1), now + 3600))["reason"]

    class Accept(random.Random):
        def random(self):
            return 0.0
    res = await bt.propose_bond("1001", "bot_00001", 90, Accept(), now + 25 * 3600)
    assert res["ok"] and "结拜" in res["reason"]
    tie = await all_ties_between(db, "1001", "bot_00001")
    assert tie.kind == "结拜" and tie.bond_id and tie.strength >= 80
    assert "早已结为" in (await bt.propose_bond("1001", "bot_00001", 90, R(1), now + 10**6))["reason"]


async def test_结拜_义气低的更容易拒绝(db):
    await mk_human(db)
    await mk_bot(db, "bot_00001", profile={"loyalty": 0})
    await seed_ties(db, [("1001", "bot_00001", "朋友", 70)])

    class Roll(random.Random):
        def random(self):
            return 0.45                                    # 义气 0 → 成功率 40%；义气 100 → 90%
    assert not (await bt.propose_bond("1001", "bot_00001", 90, Roll(), 1.0))["ok"]
    await mk_bot(db, "bot_00002", profile={"loyalty": 100})
    await seed_ties(db, [("1001", "bot_00002", "朋友", 70)])
    assert (await bt.propose_bond("1001", "bot_00002", 90, Roll(), 1.0))["ok"]


async def test_结拜_对方已死_拒绝(db):
    await mk_human(db)
    await mk_bot(db, "bot_00001", alive=False)
    assert "不在人世" in (await bt.propose_bond("1001", "bot_00001", 90, R(1)))["reason"]


async def test_结拜之后背义_好感跌到_10就反目(db):
    await mk_human(db)
    await mk_bot(db, "bot_00001")
    await seed_ties(db, [("1001", "bot_00001", "结拜", 90)])
    await bt.sync_player_tie("1001", "bot_00001", 10)
    assert (await all_ties_between(db, "1001", "bot_00001")).kind == "结拜"
    await bt.sync_player_tie("1001", "bot_00001", -9)
    assert (await all_ties_between(db, "1001", "bot_00001")).kind == "结拜", "-9 还不算背义"
    await bt.sync_player_tie("1001", "bot_00001", -10)
    assert (await all_ties_between(db, "1001", "bot_00001")).kind == "仇敌"


# ---- 资料页接入 -------------------------------------------------------------

async def test_机器人资料页显示关系(db):
    from utils.views import bot_actions
    await mk_human(db)
    await mk_bot(db, "bot_00001")
    await mk_bot(db, "bot_00002")
    await seed_ties(db, [("bot_00001", "bot_00002", "结拜", 90)])
    lines = await bot_actions.profile_lines("1001", "bot_00001")
    assert any(l.startswith("关系：") and "结拜兄弟" in l for l in lines)


async def test_结拜按钮_走结拜流程_失败只告诉自己(db, monkeypatch):
    from types import SimpleNamespace

    from tests.discord_fakes import FakeInteraction
    from utils import bot_social as bs
    from utils.views import bot_actions
    await mk_human(db)
    await mk_bot(db, "bot_00001", profile={"loyalty": 100})
    button = bot_actions.BotBondButton({"discord_id": "bot_00001", "name": "机001"})
    i = FakeInteraction(user_id=1001)
    await button.callback(i)
    assert i.response.said("交情还不到") and i.response.last.ephemeral
    await seed_ties(db, [("1001", "bot_00001", "朋友", 70)])
    await bs.adjust_favor("1001", "bot_00001", 90)


    class Accept(random.Random):
        def random(self):
            return 0.0
    monkeypatch.setattr(bt, "random", SimpleNamespace(Random=Accept))
    i = FakeInteraction(user_id=1001)
    await button.callback(i)
    assert i.response.said("焚香结拜") and not i.response.last.ephemeral
    assert (await all_ties_between(db, "1001", "bot_00001")).kind == "结拜"


def test_机器人面板上有结拜按钮():
    import discord
    from utils.views import bot_actions
    view = discord.ui.View()
    bot_actions.add_bot_buttons(view, {"discord_id": "bot_00001", "name": "x"})
    assert [c.label for c in view.children] == ["💬 搭话", "🎁 送礼", "🤝 结拜", "🕊️ 化解", "🙏 求助", "💰 还钱"]
    view = discord.ui.View()
    bot_actions.add_bot_buttons(view, {"discord_id": "1001", "name": "x"})
    assert not view.children
