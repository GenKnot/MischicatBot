"""失踪调查（utils/bot_investigation.py、utils/views/investigation.py、data/bot_investigation.json）。

用户 2026-10-12 的设计（A5 / K3）：没名气的机器人被杀，它的朋友不会立刻知道是谁干的——会发现人不见了，在城里问玩家『见过某某吗』，玩家按钮回答；
影响多大取决于名望、关系网和传播过程。
"""

import copy
import json
import random
import time

import pytest
from sqlalchemy import select

from tests.conftest import make_player
from tests.discord_fakes import FakeContext, FakeInteraction
from utils import bot_grudges as bg
from utils import bot_investigation as bi
from utils.views import investigation as iv

H, CITY = "1001", "灵虚城"
NOW = 1_800_000_000.0
DAY = 86400


class Z(random.Random):
    def __init__(self, value=0.0):
        super().__init__(0)
        self.value = value

    def random(self):
        return self.value


class Seq(random.Random):
    def __init__(self, *values):
        super().__init__(0)
        self.values, self.i = list(values), 0

    def random(self):
        v = self.values[min(self.i, len(self.values) - 1)]
        self.i += 1
        return v


# ---- 配置与纯函数 -----------------------------------------------------------

def test_配置合法():
    assert bi.validate(bi.load()) == []


@pytest.mark.parametrize("mutate,expect", [
    (lambda c: c["ask"].update(chance=2), "ask:"),
    (lambda c: c["progress"].update(give_up_days=0), "progress:"),
    (lambda c: c["answer"].update(killer_confess=150), "killer_confess"),
    (lambda c: c["answer"].update(killer_slip_chance=2), "killer_slip_chance"),
    (lambda c: c["answer"].update(false_lead=5), "false_lead"),
])
def test_校验能拦住坏配置(mutate, expect):
    cfg = copy.deepcopy(bi.load())
    mutate(cfg)
    assert any(expect in e for e in bi.validate(cfg)), bi.validate(cfg)


def test_回答让进度变多少():
    d = bi.progress_delta
    assert d(True, "seen", False, False) == 60 and d(True, "silent", False, False) == 25
    assert d(True, "unseen", False, False) == 0 and d(True, "unseen", False, True) == 40
    assert d(False, "seen", True, False) == 12 and d(False, "seen", False, False) == -3
    assert d(False, "unseen", True, False) == 0 and d(False, "silent", True, False) == 0
    assert d(True, "seen", True, False) == 60, "凶手有没有『证据』都一样"


def test_每天自己查_谨慎的更快():
    assert bi.daily_gain(50) == 6 and bi.daily_gain(0) == 10 and bi.daily_gain(100) == 2
    assert bi.daily_gain(100) < bi.daily_gain(50) < bi.daily_gain(0)


# ---- 夹具 -------------------------------------------------------------------

async def mk_human(db, uid=H, city=CITY, fame=0, **kw):
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        p = make_player(D, uid)
        p.name, p.lifespan, p.current_city, p.last_active, p.fame = f"人{uid}", 80, city, NOW, fame
        for k, v in kw.items():
            setattr(p, k, v)
        s.add(p)
        await s.commit()


async def mk_bot(db, uid, city=CITY, fame=0, impulse=50, alive=True):
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        p = make_player(D, uid)
        p.name, p.is_bot, p.lifespan, p.current_city, p.is_dead, p.fame = f"机{uid[-3:]}", True, 80, city, not alive, fame
        s.add(p)
        prof = {"lawful": 50, "impulse": impulse, "loyalty": 70, "vengeful": 50, "capacity": 30, "deviance": 0}
        s.add(D.BotPersonality(bot_id=uid, archetype="豪爽", tier="正常", home_city=city, kindness=50, profile=json.dumps(prof)))
        await s.commit()


async def tie(db, a, b, kind="朋友", strength=70):
    from utils import bot_ties
    D = db["db_async"]
    x, y = bot_ties.pair(a, b)
    async with D.AsyncSessionLocal() as s:
        s.add(D.BotTie(a_id=x, b_id=y, kind=kind, strength=strength))
        await s.commit()


async def missing_rows(db):
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        return list((await s.execute(select(D.BotMissing).order_by(D.BotMissing.started_at))).scalars())


def item(seeker="bot_00002", missing="bot_00001", culprit=H, **kw):
    return {"seeker": seeker, "missing": missing, "missing_name": "机001", "culprit": culprit, "culprit_name": f"人{culprit}",
            "kind": "kill", "rel": "朋友", "severity": 40, "reason": f"人{culprit}杀害了你的朋友机001", "city": CITY, **kw}


async def case(db, culprit=H, **kw):
    """一份开着的调查：bot_00002 在找失踪的 bot_00001，凶手是玩家 H。"""
    await mk_human(db)
    await mk_bot(db, "bot_00002", **kw)
    assert await bi.start([item(culprit=culprit)], Z(0.0), NOW) == 1
    return (await missing_rows(db))[0].id


async def remember(player, bot):
    from utils import bot_memory
    await bot_memory.remember(player, bot, "chat")


# ---- 开案 -------------------------------------------------------------------

async def test_开案_同一个人找同一个失踪者对同一个凶手只开一份(db):
    await mk_human(db)
    await mk_bot(db, "bot_00002")
    assert await bi.start([item(), item()], Z(0.0), NOW) == 1
    assert await bi.start([item()], Z(0.0), NOW) == 0
    assert await bi.start([item(culprit="1002")], Z(0.0), NOW) == 1
    assert len(await missing_rows(db)) == 2


async def test_开案出错只记警告(db, monkeypatch, caplog):
    def boom(*a, **k):
        raise RuntimeError("库坏了")
    monkeypatch.setattr(bi, "AsyncSessionLocal", boom)
    assert await bi.start([item()], Z(0.0), NOW) == 0
    assert "开失踪调查失败" in caplog.text


async def test_有名气的受害者_不开调查_直接记仇(db):
    await mk_human(db)
    await mk_bot(db, "bot_00001", fame=300)
    await mk_bot(db, "bot_00002")
    await tie(db, "bot_00001", "bot_00002")
    got = await bg.on_offense(H, "bot_00001", "kill", rng=Z(0.0), now=NOW)
    assert [g["holder"] for g in got] == ["bot_00002"] and await missing_rows(db) == []


# ---- 问话 -------------------------------------------------------------------

async def test_碰到在找人的机器人_可能被问_问话摘要和台词(db):
    rid = await case(db)
    q = await bi.maybe_question(H, ["bot_00002", "bot_00009"], Z(0.0), NOW)
    assert q and q["id"] == rid and q["seeker_id"] == "bot_00002" and q["missing_name"] == "机001" and q["line"]
    assert q["seeker_name"] == "机002"


async def test_它不在场_概率没过_都不问(db):
    await case(db)
    assert await bi.maybe_question(H, ["bot_00009"], Z(0.0), NOW) is None, "找人的不在场"
    assert await bi.maybe_question(H, ["bot_00002"], Z(0.99), NOW) is None, "概率没过"


async def test_同一个玩家12小时内不重复问_别的玩家照问(db):
    await case(db)
    await mk_human(db, "1002")
    assert await bi.maybe_question(H, ["bot_00002"], Z(0.0), NOW)
    assert await bi.maybe_question(H, ["bot_00002"], Z(0.0), NOW + 6 * 3600) is None, "过了机器人搭话的 4 小时冷却，但还没到 12 小时"
    assert await bi.maybe_question("1002", ["bot_00002"], Z(0.0), NOW + 6 * 3600)
    assert await bi.maybe_question(H, ["bot_00002"], Z(0.0), NOW + 13 * 3600)


async def test_问话算一次搭话事件_屏蔽的人不被问_调查结了不问(db):
    rid = await case(db)
    assert await bi.maybe_question(H, ["bot_00002"], Z(0.0), NOW)
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        assert (await s.get(D.ChatterState, H)).count == 1 and await s.get(D.ChatterPair, (H, "bot_00002")) is not None
    from utils import bot_chatter as bc
    await bc.set_muted(H, True)
    assert await bi.maybe_question(H, ["bot_00002"], Z(0.0), NOW + 20 * 3600) is None
    await bc.set_muted(H, False)
    async with D.AsyncSessionLocal() as s:
        (await s.get(D.BotMissing, rid)).state = "resolved"
        await s.commit()
    assert await bi.maybe_question(H, ["bot_00002"], Z(0.0), NOW + 40 * 3600) is None


# ---- 回答 -------------------------------------------------------------------

async def progress_of(db, rid):
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        r = await s.get(D.BotMissing, rid)
        return r.progress, r.state


async def test_凶手承认见过_露馅_进度大涨(db):
    rid = await case(db)
    res = await bi.answer(rid, H, "seen", Z(0.99), NOW)
    assert res["ok"] and res["delta"] == 60 and res["progress"] == 60 and not res["resolved"]
    assert await progress_of(db, rid) == (60, "active")


async def test_凶手不想说_让它起疑(db):
    rid = await case(db)
    assert (await bi.answer(rid, H, "silent", Z(0.99), NOW))["delta"] == 25


async def test_凶手撒谎说没见过_有一定概率被识破(db):
    rid = await case(db)
    assert (await bi.answer(rid, H, "unseen", Z(0.99), NOW))["delta"] == 0, "没被识破"
    assert (await bi.answer(rid, H, "unseen", Z(0.1), NOW))["delta"] == 40, "被识破（0.15 的概率）"


async def test_凶手被问到两次_累积到100_结案_它记仇_被点破(db):
    rid = await case(db)
    await bi.answer(rid, H, "seen", Z(0.99), NOW)
    res = await bi.answer(rid, H, "silent", Z(0.99), NOW + 100)
    assert not res["resolved"] and res["progress"] == 85
    res = await bi.answer(rid, H, "silent", Z(0.99), NOW + 200)
    assert res["resolved"] and res["exposed"] and res["progress"] == 100
    assert "机001" in res["line"], "点破的台词都会提到失踪的人"
    assert (await progress_of(db, rid))[1] == "resolved"
    (g,) = await bg.grudges_against(H)
    assert g["holder"] == "bot_00002" and g["victim"] == "bot_00001" and g["kind"] == "kill" and g["reason"] == f"人{H}杀害了你的朋友机001"


async def test_旁人有交情_说见过_是真线索_进度加好感加_台词是道谢(db):
    from utils import bot_social as bs
    rid = await case(db, culprit="9999")
    await mk_human(db, "9999")
    await remember(H, "bot_00001")                                  # 玩家和失踪者打过交道
    res = await bi.answer(rid, H, "seen", Z(0.99), NOW)
    assert res["delta"] == 12 and res["progress"] == 12 and not res["exposed"] and res["line"]
    assert await bs.get_favor(H, "bot_00002") == 3


async def test_旁人和凶手打过交道_也算有线索(db):
    rid = await case(db, culprit="bot_00005")
    await mk_bot(db, "bot_00005")
    await remember(H, "bot_00005")
    assert (await bi.answer(rid, H, "seen", Z(0.99), NOW))["delta"] == 12


async def test_旁人没打过交道却说见过_是假线索_进度下降_不会低于0(db):
    from utils import bot_social as bs
    rid = await case(db, culprit="9999")
    res = await bi.answer(rid, H, "seen", Z(0.99), NOW)
    assert res["delta"] == -3 and res["progress"] == 0 and await bs.get_favor(H, "bot_00002") == 0
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        (await s.get(D.BotMissing, rid)).progress = 20
        await s.commit()
    assert (await bi.answer(rid, H, "seen", Z(0.99), NOW))["progress"] == 17


async def test_凶手不想说_不扣好感_只有旁人沉默才扣(db):
    from utils import bot_social as bs
    rid = await case(db)
    await bi.answer(rid, H, "silent", Z(0.99), NOW)
    assert await bs.get_favor(H, "bot_00002") == 0


async def test_旁人说没见过_不动进度_说不想说_好感小降(db):
    from utils import bot_social as bs
    rid = await case(db, culprit="9999")
    assert (await bi.answer(rid, H, "unseen", Z(0.99), NOW))["delta"] == 0
    assert (await bi.answer(rid, H, "silent", Z(0.99), NOW))["delta"] == 0
    assert await bs.get_favor(H, "bot_00002") == -1


async def test_已结案的调查_不能再答_回答不认识_调查不存在(db):
    rid = await case(db)
    assert not (await bi.answer(rid, H, "跳舞", Z(0.0), NOW))["ok"]
    assert not (await bi.answer("不存在", H, "seen", Z(0.0), NOW))["ok"]
    await bi.answer(rid, H, "seen", Z(0.99), NOW)
    await bi.answer(rid, H, "seen", Z(0.99), NOW)
    res = await bi.answer(rid, H, "seen", Z(0.99), NOW)
    assert not res["ok"] and "已经有结果" in res["reason"]


async def test_旁人帮忙帮到100_结案_凶手被记仇_旁人没被点破(db):
    rid = await case(db, culprit="9999")
    await mk_human(db, "9999")
    await remember(H, "bot_00001")
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        (await s.get(D.BotMissing, rid)).progress = 90
        await s.commit()
    res = await bi.answer(rid, H, "seen", Z(0.99), NOW)
    assert res["resolved"] and not res["exposed"]
    (g,) = await bg.grudges_against("9999")
    assert g["holder"] == "bot_00002"
    assert await bg.grudges_against(H) == []


# ---- 每天 -------------------------------------------------------------------

async def test_每天自己查_谨慎的涨得快_按日认领_force可重跑(db):
    await mk_human(db)
    await mk_bot(db, "bot_00002", impulse=0)
    await mk_bot(db, "bot_00003", impulse=100)
    await bi.start([item(seeker="bot_00002"), item(seeker="bot_00003")], Z(0.0), NOW)
    sm = await bi.investigation_day("d1", Z(0.0), now=NOW + DAY)
    assert sm == {"progressed": 2, "resolved": 0, "gave_up": 0}
    got = {r.seeker_id: r.progress for r in await missing_rows(db)}
    assert got == {"bot_00002": 10, "bot_00003": 2}
    assert await bi.investigation_day("d1", Z(0.0), now=NOW + DAY) == {}
    assert (await bi.investigation_day("d1", Z(0.0), force=True, now=NOW + DAY))["progressed"] == 2


async def test_查满100_结案_记仇(db):
    rid = await case(db)
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        (await s.get(D.BotMissing, rid)).progress = 95
        await s.commit()
    sm = await bi.investigation_day("d1", Z(0.0), now=NOW + DAY)
    assert sm["resolved"] == 1 and (await progress_of(db, rid)) == (100, "resolved")
    (g,) = await bg.grudges_against(H)
    assert g["holder"] == "bot_00002" and g["reason"].endswith("杀害了你的朋友机001")


async def test_拖太久放弃_找的人没了也放弃(db):
    rid = await case(db)
    await mk_bot(db, "bot_00003", alive=False)
    await bi.start([item(seeker="bot_00003")], Z(0.0), NOW)
    sm = await bi.investigation_day("d1", Z(0.0), now=NOW + 41 * DAY)
    assert sm["gave_up"] == 2 and (await progress_of(db, rid))[1] == "gave_up"
    assert await bg.grudges_against(H) == []


async def test_找的人死了就放弃(db):
    rid = await case(db)
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        (await s.get(D.Player, "bot_00002")).is_dead = True
        await s.commit()
    assert (await bi.investigation_day("d1", Z(0.0), now=NOW + DAY))["gave_up"] == 1


async def test_每日处理接在每日结算里(db):
    from utils import bot_settle
    await case(db)
    res = await bot_settle.run_settlement(force=True, rng=random.Random(1))
    assert set(res["investigation"]) == {"progressed", "resolved", "gave_up"}


async def test_每日处理出错只记警告(db, monkeypatch, caplog):
    def boom(*a, **k):
        raise RuntimeError("库坏了")
    monkeypatch.setattr(bi, "AsyncSessionLocal", boom)
    assert await bi.investigation_day("d1") == {}
    assert "失踪调查每日处理失败" in caplog.text


# ---- 清理 -------------------------------------------------------------------

async def test_清理机器人_找人的那个没了_调查跟着删(db):
    from utils import bot_world
    await case(db)
    res = await bot_world.remove_bots(["bot_00002"])
    assert res["rows"]["bot_missing"] == 1 and await missing_rows(db) == []


async def test_转世_针对旧角色的调查作废(db):
    from utils.character_create_logic import commit_character
    await case(db)
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        (await s.get(D.Player, H)).is_dead = True
        await s.commit()
    assert await bi.active_for_culprit(H) == 1
    assert await commit_character(H, "新名字", "男", {})
    assert await bi.active_for_culprit(H) == 0 and await missing_rows(db) == []


# ---- 界面 -------------------------------------------------------------------

async def test_问话面板_三个按钮_别人点不动(db):
    q = {"id": "x", "seeker_id": "bot_00002", "seeker_name": "机002", "seeker_realm": "筑基期1层", "missing_name": "机001", "line": "见过吗？"}
    view = iv.QuestionView(q, FakeInteraction(user_id=int(H)).user)
    assert [c.label for c in view.children] == ["见过", "没见过", "不想说"]
    assert await view.interaction_check(FakeInteraction(user_id=7)) is False
    e = iv.question_embed(q)
    assert "机002" in e.title and e.description == "「见过吗？」"


async def test_点按钮回答_消息换成带回应的版本_只能答一次(db):
    rid = await case(db, culprit="9999")
    await mk_human(db, "9999")
    await remember(H, "bot_00001")
    q = await bi.maybe_question(H, ["bot_00002"], Z(0.0), NOW)
    me = FakeInteraction(user_id=int(H))
    view = iv.QuestionView(q, me.user)
    await next(c for c in view.children if c.label == "见过").callback(me)
    assert me.edited[-1].view is None and any("你答：见过" in f.name for f in me.edited[-1].embed.fields)
    assert (await progress_of(db, rid))[0] == 12
    j = FakeInteraction(user_id=int(H))
    await next(c for c in view.children if c.label == "没见过").callback(j)
    assert j.response.said("已经回答过了")


async def test_回答时调查已经结案_面板给出提示(db):
    rid = await case(db)
    q = {"id": rid, "seeker_id": "bot_00002", "seeker_name": "机002", "seeker_realm": "筑基期1层", "missing_name": "机001", "line": "x"}
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        (await s.get(D.BotMissing, rid)).state = "resolved"
        await s.commit()
    me = FakeInteraction(user_id=int(H))
    await next(c for c in iv.QuestionView(q, me.user).children if c.label == "见过").callback(me)
    assert any("已经有结果" in f.value for f in me.edited[-1].embed.fields)


async def test_碰面钩子_问话发出带按钮_没有就不发(db, monkeypatch):
    await case(db)
    c = FakeContext(user_id=int(H))
    monkeypatch.setattr(bi, "maybe_question", lambda pid, present, rng=None, now=None: _real_q(pid, present, Z(0.0), NOW))
    assert await iv.run_question(c.send, c.author, ["bot_00002"]) is True
    assert c.last.embed.title.endswith("在打听人") and [b.label for b in c.last.view.children] == ["见过", "没见过", "不想说"]
    c2 = FakeContext(user_id=int(H))
    assert await iv.run_question(c2.send, c2.author, ["bot_00009"]) is False and c2.messages == []


_real_q = bi.maybe_question


async def test_机器人请求开口时_不再叠加问话(db, monkeypatch):
    from utils.views import requests as rv
    await case(db)
    seen = []

    async def fake_meet(pid, present, rng=None, now=None):
        return {"events": [], "offer": {"id": "o", "bot_id": "bot_00002", "bot_name": "机002", "bot_realm": "筑基期1层", "template": "borrow_stones",
                                         "kind": "loan_stones", "params": {"amount": 100}, "line": "借点钱", "expires_at": NOW}}
    monkeypatch.setattr(rv.br, "on_meet", fake_meet)
    monkeypatch.setattr(bi, "maybe_question", lambda *a, **k: seen.append(1))
    c = FakeContext(user_id=int(H))
    assert await rv.run_meet(c.send, c.author, ["bot_00002"]) is True
    assert seen == [], "有请求在身边时不追问"
