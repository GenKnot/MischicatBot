"""关系记忆（utils/bot_memory.py）：机器人记得你做过的事，偶尔在对话里提一句、资料页有一行『交往』。

用户 2026-10-12 的决定：记礼物 / 聊天 / 被劫被废 / 组队双修 / 你攻击它输了；大事永久、礼物留最近 8 件、机器人没了记忆也没了；
对话偶尔点缀（约 20%~30%）+ 资料页；**纯文案，不改任何数值**；回忆台词按性格原型分别写。
"""

import random
import time

import pytest
from sqlalchemy import select

from tests.conftest import make_player
from utils import bot_combat as bc
from utils import bot_dialogue as bd
from utils import bot_memory as bm
from utils import bot_social as bs
from utils import bot_traits as bt
from utils import dual_cultivation_logic as dual
from utils import party
from utils.items import ITEMS

H, B, CITY = "1001", "bot_00001", "灵虚城"
DAY = 86400


async def mk(db, uid, bot=False, city=CITY, archetype="豪爽", traits=None, stones=1000):
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        p = make_player(D, uid, stones=stones)
        p.name, p.current_city, p.lifespan, p.lifespan_max, p.is_bot = f"甲{uid}", city, 80, 100, bot
        p.reputation = 10
        s.add(p)
        if bot:
            import json
            s.add(D.BotPersonality(bot_id=uid, archetype=archetype, tier="正常", home_city=CITY, kindness=50, greed=30,
                                   pride=40, talk=30, traits=json.dumps(traits, ensure_ascii=False) if traits else None))
        await s.commit()


async def world(db, **kw):
    await mk(db, H)
    await mk(db, B, bot=True, **kw)


async def rows(db, kind=None, bot=B):
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        q = select(D.BotMemory).where(D.BotMemory.player_id == H, D.BotMemory.bot_id == bot)
        if kind:
            q = q.where(D.BotMemory.kind == kind)
        return list((await s.execute(q)).scalars())


# ---- 记 ---------------------------------------------------------------------

async def test_同一种事累加次数_记下上一次和最近一次的时间(db):
    await world(db)
    await bm.remember(H, B, "chat", "", "灵虚城", now=1000)
    await bm.remember(H, B, "chat", "", "落云城", now=5000)
    (r,) = await rows(db, "chat")
    assert (r.count, r.first_at, r.prev_at, r.last_at, r.extra) == (2, 1000, 1000, 5000, "落云城")
    await bm.remember(H, B, "chat", "", "", now=9000)
    (r,) = await rows(db, "chat")
    assert (r.count, r.prev_at, r.last_at, r.extra) == (3, 5000, 9000, "落云城")      # extra 为空不覆盖


async def test_礼物只留最近八件_大事不会被冲掉(db):
    await world(db)
    await bm.remember(H, B, "robbed", "", "100", now=1)
    for i in range(12):
        await bm.remember(H, B, "gift", f"礼物{i}", "like", now=100 + i)
    gifts = {r.detail for r in await rows(db, "gift")}
    assert gifts == {f"礼物{i}" for i in range(4, 12)}
    assert len(await rows(db, "robbed")) == 1


async def test_同一件礼物送两次只占一格_次数累加(db):
    await world(db)
    for t in (1, 2, 3):
        await bm.remember(H, B, "gift", "筑基丹", "love", now=t)
    (r,) = await rows(db, "gift")
    assert r.count == 3


async def test_记忆是按人分开的(db):
    await world(db)
    await mk(db, "1002")
    await bm.remember(H, B, "chat")
    assert await bm.recall("1002", B) == {}


async def test_写入出错只记警告_不影响主流程(db, monkeypatch, caplog):
    await world(db)

    def boom(*a, **k):
        raise RuntimeError("库坏了")
    monkeypatch.setattr(bm, "AsyncSessionLocal", boom)
    await bm.remember(H, B, "chat")                      # 不抛
    assert "记录机器人记忆失败" in caplog.text


# ---- 钩子：各处事件会被记下来 ------------------------------------------------

async def test_钩子_送礼记下物品和反应_失败的不记(db):
    await world(db)
    await db["inventory"].add_item(H, "筑基丹", 1)
    res = await bs.give_gift(H, B, "筑基丹")
    assert res["ok"]
    (r,) = await rows(db, "gift")
    assert (r.detail, r.extra) == ("筑基丹", res["reaction"])
    bad = await bs.give_gift(H, B, "没有这个东西")
    assert not bad["ok"] and len(await rows(db, "gift")) == 1


async def test_钩子_聊天每天只记一次_并记下所在城市(db, monkeypatch):
    await world(db)
    monkeypatch.setattr(bs, "_today", lambda: "2026-10-12")
    assert (await bs.chat(H, B))["ok"]
    await bs.chat(H, B)                                  # 同一天再搭话：不算多聊
    (r,) = await rows(db, "chat")
    assert (r.count, r.extra) == (1, CITY)
    monkeypatch.setattr(bs, "_today", lambda: "2026-10-13")
    await bs.chat(H, B)
    assert (await rows(db, "chat"))[0].count == 2


async def test_钩子_打劫和废修为(db):
    await mk(db, H, city="万妖岭")
    await mk(db, B, bot=True, city="万妖岭")
    res = await bc.rob_bot(H, B)
    assert res["ok"]
    (r,) = await rows(db, "robbed")
    assert (r.count, r.extra) == (1, str(res["amount"]))
    assert (await bc.cripple_bot(H, B))["ok"]
    assert len(await rows(db, "crippled")) == 1


async def test_钩子_落空的打劫不记(db):
    await mk(db, H, city="万妖岭")
    await mk(db, B, bot=True, city="万妖岭", stones=0)
    assert not (await bc.rob_bot(H, B))["ok"]
    assert await rows(db) == []


async def test_钩子_打输被放走记一笔(db):
    await mk(db, H)
    await mk(db, B, bot=True, archetype="憨直")
    assert (await bc.handle_captive(B, H, random.Random(0)))["outcome"] == "release"
    (r,) = await rows(db, "defeated")
    assert (r.count, r.extra) == (1, "release")


async def test_钩子_真人被杀就不记了(db, monkeypatch):
    """死掉的真人不再留记忆行。"""
    import json
    from utils import bot_economy as be
    cfg = be.load_config()
    cfg["combat"]["reaction"]["阴鸷"] = {"kill": 100}
    monkeypatch.setattr(be, "load_config", lambda: json.loads(json.dumps(cfg)))
    from utils import world_settings
    await world_settings.set_values(mode="真实")
    await mk(db, H)
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        (await s.get(D.Player, H)).realm = "筑基期5层"
        await s.commit()
    await mk(db, B, bot=True, archetype="阴鸷", stones=0)
    assert (await bc.handle_captive(B, H, random.Random(0)))["killed"]
    assert await rows(db) == []


async def test_钩子_组队和双修(db):
    await world(db)
    await bs.adjust_favor(H, B, 100)
    assert (await party.accept_invite(H, B))["ok"]
    (r,) = await rows(db, "party")
    assert r.count == 1
    assert (await dual.start_dual_cultivation(H, B))["success"]
    assert len(await rows(db, "dual")) == 1


async def test_钩子_邀请被拒_什么也不记(db):
    await world(db)
    assert not (await party.accept_invite(H, B))["ok"]       # 好感不够
    assert await rows(db) == []


async def test_钩子_真人之间不记(db):
    await mk(db, H)
    await mk(db, "1002")
    assert (await party.accept_invite(H, "1002"))["ok"]
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        assert (await s.execute(select(D.BotMemory))).first() is None


async def test_钩子_通过add_to_party入队也记(db):
    await world(db)
    await bs.adjust_favor(H, B, 100)
    pid = await party.create_party(H, CITY)
    assert await party.add_to_party(pid, B)
    assert len(await rows(db, "party")) == 1


async def test_钩子_add_to_party失败不记(db):
    await world(db)
    await bs.adjust_favor(H, B, 100)
    pid = await party.create_party(H, CITY)
    assert await party.add_to_party(pid, B)
    await bm.remember(H, B, "party")                       # 已经在队里：再加一次会失败
    before = (await rows(db, "party"))[0].count
    assert not await party.add_to_party(pid, B)
    assert (await rows(db, "party"))[0].count == before


async def test_机器人没了_记忆也没了(db):
    from utils import bot_world
    await world(db)
    await bm.remember(H, B, "chat")
    await bot_world.remove_bots([B])
    assert await rows(db) == []


# ---- 挑哪句 -----------------------------------------------------------------

class M:
    """假的记忆行。"""
    def __init__(self, kind, detail="", extra="", count=1, prev_at=0, last_at=0):
        self.kind, self.detail, self.extra, self.count, self.prev_at, self.last_at = kind, detail, extra, count, prev_at, last_at


NOW = 1_000_000.0


def mem(*rows_):
    out = {}
    for r in rows_:
        out.setdefault(r.kind, []).append(r)
    return out


def names(memories, scene="greet", tier="熟识"):
    return [c[0] for c in bm.candidates(memories, scene, tier, NOW)]


def test_没有记忆没有候选():
    assert names({}) == []


def test_礼物_挑最合心意或最踩雷的_礼物场景里不提礼物():
    m = mem(M("gift", "甲", "like", last_at=3), M("gift", "乙", "love", last_at=1), M("gift", "丙", "neutral", last_at=2))
    (c,) = bm.candidates(m, "greet", "熟识", NOW)
    assert c[0] == "recall_gift" and c[1]["item"] == "乙" and c[1]["count"] == 3
    assert bm.candidates(m, "gift_like", "熟识", NOW) == []


def test_礼物_没有极端反应就取最近的一件():
    m = mem(M("gift", "旧", "like", last_at=1), M("gift", "新", "neutral", last_at=9))
    assert bm.candidates(m, "greet", "熟识", NOW)[0][1]["item"] == "新"


def test_久别重逢_隔了三天才算_带加成():
    near = mem(M("chat", count=2, prev_at=NOW - 2 * DAY, last_at=NOW))
    far = mem(M("chat", extra="落云城", count=2, prev_at=NOW - 3 * DAY - 5, last_at=NOW))
    assert "recall_absence" not in names(near)
    (c,) = bm.candidates(far, "greet", "熟识", NOW)
    assert c[0] == "recall_absence" and c[1] == {"days": 3, "city": "落云城"} and c[2] == bm.load()["recall"]["boost_p"]


def test_第一次聊天没有上一次_不算久别():
    assert names(mem(M("chat", count=1, prev_at=0, last_at=NOW))) == []


def test_聊熟了_五次起():
    assert names(mem(M("chat", count=4, prev_at=NOW - 10, last_at=NOW))) == []
    (c,) = bm.candidates(mem(M("chat", count=5, prev_at=NOW - 10, last_at=NOW)), "greet", "熟识", NOW)
    assert c[0] == "recall_chat" and c[1] == {"count": 5} and c[2] is None


def test_结仇_打劫和废修为合并计次_仇视或陌生时关键时刻():
    m = mem(M("robbed", count=2), M("crippled", count=1))
    for tier, boosted in (("仇视", True), ("陌生", True), ("熟识", False), ("至交", False)):
        (c,) = bm.candidates(m, "greet", tier, NOW)
        assert c[0] == "recall_grudge" and c[1] == {"count": 3} and (c[2] == bm.load()["recall"]["boost_p"]) is boosted


def test_一起行动_至少两次才提_次数是以前的():
    assert names(mem(M("party", count=1))) == []
    (c,) = bm.candidates(mem(M("party", count=1), M("dual", count=2)), "greet", "熟识", NOW)
    assert c[0] == "recall_together" and c[1] == {"count": 2}


def test_败给它():
    (c,) = bm.candidates(mem(M("defeated", count=4, extra="release")), "greet", "陌生", NOW)
    assert c[0] == "recall_defeat" and c[1] == {"count": 4}


class FixedRng:
    def __init__(self, roll, pick=0):
        self.roll, self.pick = roll, pick

    def choice(self, seq):
        return seq[self.pick]

    def random(self):
        return self.roll


def test_概率_按内向外向调整_普通场景():
    m = mem(M("defeated", count=2))
    for level, p in (("内向", 0.125), ("中性", 0.25), ("外向", 0.4)):
        assert bm.pick_recall(m, "greet", "熟识", level, FixedRng(p - 0.001)) is not None
        assert bm.pick_recall(m, "greet", "熟识", level, FixedRng(p + 0.001)) is None


def test_概率_关键时刻用加成概率_不看内向外向():
    m = mem(M("robbed", count=1))
    assert bm.pick_recall(m, "greet", "仇视", "内向", FixedRng(bm.load()["recall"]["boost_p"] - 0.01)) is not None
    assert bm.pick_recall(m, "greet", "仇视", "内向", FixedRng(bm.load()["recall"]["boost_p"] + 0.01)) is None


def test_只在允许的场景追加():
    m = mem(M("robbed", count=1))
    for scene in bd.SCENES:
        got = bm.pick_recall(m, scene, "仇视", "外向", FixedRng(0.0))
        assert (got is not None) == (scene in bm.RECALL_SCENES), scene


def test_场景名都是真实场景_回忆场景都有变量表():
    assert bm.RECALL_SCENES <= set(bd.SCENES)
    for name, _fmt, _b in bm.candidates(mem(M("gift", "a", "love"), M("chat", count=9, prev_at=1, last_at=NOW),
                                            M("robbed"), M("party", count=3), M("defeated")), "greet", "熟识", NOW):
        assert name in bd.RECALL_VARS


# ---- 资料页 -----------------------------------------------------------------

def test_交往一行():
    assert bm.summary({}) == ""
    m = mem(M("chat", count=7, last_at=NOW - 2 * DAY), M("gift", "a"), M("gift", "b"), M("robbed", count=2),
            M("crippled", count=1), M("party", count=1), M("dual", count=1), M("defeated", count=3))
    s = bm.summary(m, NOW)
    assert s.startswith("交往：")
    for frag in ("聊过 7 次（2 天前）", "送过 2 样礼物", "你劫过它 2 次", "你废过它的修为 1 次", "一起行动过 2 次", "你败给它 3 次"):
        assert frag in s, frag
    assert "今天" in bm.summary(mem(M("chat", count=1, last_at=NOW)), NOW)


async def test_资料页显示交往(db):
    from utils.views import bot_actions
    await world(db)
    assert not any(l.startswith("交往") for l in await bot_actions.profile_lines(H, B))
    await bm.remember(H, B, "chat")
    assert any(l.startswith("交往：聊过 1 次") for l in await bot_actions.profile_lines(H, B))


# ---- 接进对话 ---------------------------------------------------------------

async def test_say_有记忆且抽中_就追加一句回忆(db, monkeypatch):
    await world(db)
    await bm.remember(H, B, "defeated", "", "release")
    _always_recall(monkeypatch)
    line = await bs.say("greet", H, B)
    assert any(t.format(count=1) in line for t in bd._load("豪爽")["recall_defeat"]["陌生"]), line
    assert any(line.startswith(t.format(player=f"甲{H}", bot=f"甲{B}")) for t in bd._load("豪爽")["greet"]["陌生"]), line


def _always_recall(monkeypatch):
    real = bm.pick_recall
    monkeypatch.setattr(bm, "pick_recall", lambda *a, **k: real(*a, rng=FixedRng(0.0), **k))


async def test_say_没记忆就不追加_也不多调一次取台词(db, monkeypatch):
    await world(db)
    calls = []
    real = bs.get_line
    monkeypatch.setattr(bs, "get_line", lambda *a, **k: calls.append(a[1]) or real(*a, **k))
    await bs.say("greet", H, B)
    assert calls == ["greet"]


async def test_say_不在回忆场景里的话不追加(db, monkeypatch):
    await world(db)
    await bm.remember(H, B, "robbed")
    _always_recall(monkeypatch)
    line = await bs.say("bot_robbed", H, B)
    assert not any(t in line for t in bd._load("豪爽")["recall_grudge"]["仇视"])


async def test_say_回忆用同一个人的口吻_带上特质(db, monkeypatch):
    traits = bt.roll_traits("豪爽", 50, random.Random(1))
    await world(db, traits=traits)
    await bm.remember(H, B, "defeated", "", "release")
    _always_recall(monkeypatch)
    seen = []
    real = bs.get_line
    monkeypatch.setattr(bs, "get_line", lambda *a, **k: seen.append((a[1], k.get("traits"))) or real(*a, **k))
    await bs.say("greet", H, B)
    assert [s for s, _ in seen] == ["greet", "recall_defeat"] and all(t == traits for _, t in seen)


# ---- 台词数据 ---------------------------------------------------------------

RECALL = sorted(bd.RECALL_VARS)


def test_默认台词_回忆场景每个档位都有且至少两句():
    lines = bd._load(bd.DEFAULT)
    for s in RECALL:
        for t in bd.TIERS:
            assert len(lines[s][t]) >= 2, (s, t)


def test_每个原型都有自己的回忆台词_全部格子():
    from utils.bot_social import load_archetypes
    for a in load_archetypes():
        cov = bd.coverage(a)
        for s in RECALL:
            for t in bd.TIERS:
                assert cov[s][t] >= 1, (a, s, t)


def test_回忆台词只用本场景的变量():
    for path in bd.DIR.glob("*.json"):
        assert bd.validate_file(path, require_complete=path.name == "_default.json") == [], path.name


def test_回忆场景用了别的场景的变量会被校验拦住(tmp_path):
    import json
    bad = tmp_path / "豪爽.坏.json"
    bad.write_text(json.dumps({"archetype": "豪爽", "lines": {"recall_chat": {"陌生": ["{days}天了。"]}}}), encoding="utf-8")
    assert any("days" in e for e in bd.validate_file(bad))
    ok = tmp_path / "豪爽.好.json"
    ok.write_text(json.dumps({"archetype": "豪爽", "lines": {"recall_absence": {"陌生": ["{days}天了。"]}}}), encoding="utf-8")
    assert bd.validate_file(ok) == []


def test_回忆台词能填进去且不超长():
    fmt = {"player": "甲", "bot": "乙", "item": "丙", "days": 12, "count": 7, "city": "丁"}
    for a in ["豪爽", "贪财", "话痨", "憨直", "痴丹", "阴鸷", "迂腐", "高冷", bd.DEFAULT]:
        for s in RECALL:
            for t in bd.TIERS:
                for tpl in bd._load(a)[s][t]:
                    out = bd.fill(tpl, **fmt)
                    assert "{" not in out and len(out) <= bd.MAX_LINE_LEN, tpl
