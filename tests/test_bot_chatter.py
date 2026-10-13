"""机器人主动搭话（utils/bot_chatter.py、utils/views/chatter.py、cogs/chatter.py、data/bot_chatter_config.json）。

用户 2026-10-12 的设计：每次搭话都要有『小契机』（到城 / 突破 / 公共事件 / 冲突后），不凭空骚扰；每人每天最多 3 条；
按钮回应影响好感；可屏蔽（只屏蔽搭话，不影响仇恨 / 拦路）；台词按条件挑选。
"""

import copy
import json
import random
import time
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from tests.conftest import make_player
from tests.discord_fakes import FakeContext, FakeInteraction
from utils import bot_chatter as bc
from utils import bot_social as bs
from utils.views import chatter as cv

H, CITY = "1001", "灵虚城"
NOW = 1_800_000_000.0


def R(seed=0):
    return random.Random(seed)


class Z(random.Random):
    def __init__(self, value=0.0):
        super().__init__(0)
        self.value = value

    def random(self):
        return self.value


# ---- 配置与纯函数 -----------------------------------------------------------

def test_配置合法_上限是用户定的3():
    assert bc.validate(bc.load()) == []
    assert bc.load()["daily_cap"] == 3


@pytest.mark.parametrize("mutate,expect", [
    (lambda c: c.update(daily_cap=0), "daily_cap"),
    (lambda c: c.update(pair_cooldown_hours=-1), "pair_cooldown_hours"),
    (lambda c: c["arrive"]["chance_by_relation"].update(朋友=2), "arrive.chance_by_relation"),
    (lambda c: c["arrive"]["chance_by_tier"].pop("至交"), "arrive.chance_by_tier"),
    (lambda c: c["arrive"].update(max_lines=0), "arrive.max_lines"),
    (lambda c: c["congrats"]["relation_chance"].update(朋友=2), "congrats.relation_chance"),
    (lambda c: c["congrats"]["relation_chance"].pop("无"), "congrats.relation_chance"),
    (lambda c: c["congrats"].update(stranger_chance=2), "stranger_chance"),
    (lambda c: c["conflict"].update(max_messages=-1), "conflict.max_messages"),
    (lambda c: c["conflict"].pop("mediators_max"), "conflict.mediators_max"),
    (lambda c: c["congrats"].update(delay_seconds=[9, 1]), "congrats.delay_seconds"),
    (lambda c: c["event"].update(delay_seconds=[9, 1]), "event.delay_seconds"),
    (lambda c: c["conflict"].update(delay_minutes=[9, 1]), "conflict.delay_minutes"),
    (lambda c: c["reply"].pop("cold"), "reply"),
])
def test_校验能拦住坏配置(mutate, expect):
    cfg = copy.deepcopy(bc.load())
    mutate(cfg)
    assert any(expect in e for e in bc.validate(cfg)), bc.validate(cfg)


def test_境界差():
    assert bc.realm_gap("元婴期初期", "筑基期1层") == "higher"
    assert bc.realm_gap("筑基期1层", "筑基期9层") == "equal"
    assert bc.realm_gap("炼气期1层", "筑基期1层") == "lower"


def W(**kw):
    base = dict(kindness=50, pride=50, greed=50, vengeful=50, tier="陌生", relation="无", gap="equal")
    return bc.attitude_weights(**{**base, **kw})


def test_道贺态度_善良交情深的更真心():
    assert W(kindness=100, tier="至交", relation="结拜")["真心"] > W(kindness=0, tier="仇视", relation="无")["真心"] * 3


def test_道贺态度_好胜的对头更酸_境界比你高就不酸():
    assert W(pride=100, tier="仇视", gap="lower")["酸"] > W(pride=0, tier="熟识", gap="lower")["酸"] * 3
    assert W(pride=100, gap="higher")["酸"] < W(pride=100, gap="lower")["酸"]


def test_道贺态度_好胜记仇的更不服_比你低很多就不服不起来():
    assert W(pride=100, vengeful=100, gap="equal")["不服"] > W(pride=0, vengeful=0, gap="equal")["不服"] * 3
    assert W(pride=100, gap="lower")["不服"] < W(pride=100, gap="higher")["不服"]


def test_道贺态度_贪婪的更觊觎_朋友不太觊觎():
    assert W(greed=100)["觊觎"] > W(greed=0)["觊觎"] * 2
    assert W(greed=100, relation="朋友", tier="熟识")["觊觎"] < W(greed=100, relation="无", tier="陌生")["觊觎"]


# ---- 夹具 -------------------------------------------------------------------

async def mk_human(db, uid=H, city=CITY, realm="筑基期5层", active=True, **kw):
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        p = make_player(D, uid)
        p.name, p.lifespan, p.current_city, p.realm = f"人{uid}", 80, city, realm
        p.last_active = time.time() if active else 0
        for k, v in kw.items():
            setattr(p, k, v)
        s.add(p)
        await s.commit()


async def mk_bot(db, uid, arche="豪爽", city=CITY, realm="筑基期5层", profile=None, kindness=50, pride=50, greed=50, traits=None, alive=True):
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        p = make_player(D, uid)
        p.name, p.is_bot, p.lifespan, p.current_city, p.realm, p.is_dead = f"机{uid[-3:]}", True, 80, city, realm, not alive
        s.add(p)
        prof = {"lawful": 50, "impulse": 50, "loyalty": 60, "vengeful": 50, "capacity": 30, "deviance": 0, **(profile or {})}
        s.add(D.BotPersonality(bot_id=uid, archetype=arche, tier="正常", home_city=city, kindness=kindness, pride=pride, greed=greed,
                               profile=json.dumps(prof), traits=json.dumps(traits) if traits else ""))
        await s.commit()


async def tie(db, a, b, kind="朋友", strength=70):
    from utils import bot_ties
    D = db["db_async"]
    x, y = bot_ties.pair(a, b)
    async with D.AsyncSessionLocal() as s:
        s.add(D.BotTie(a_id=x, b_id=y, kind=kind, strength=strength))
        await s.commit()


async def favor(db, bot, value, uid=H):
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        s.add(D.BotRelation(player_id=uid, bot_id=bot, favor=value))
        await s.commit()


async def queue(db):
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        return list((await s.execute(select(D.ChatterQueue).order_by(D.ChatterQueue.due_at))).scalars())


async def state(db, uid=H):
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        return await s.get(D.ChatterState, uid)


# ---- 门槛：屏蔽 / 每日上限 / 冷却 / 活跃 ------------------------------------

async def test_没有任何限制时可以搭话(db):
    await mk_human(db)
    assert await bc.gate(H, None, time.time()) is None


async def test_屏蔽_只屏蔽搭话(db):
    await mk_human(db)
    assert not await bc.is_muted(H)
    await bc.set_muted(H, True)
    assert await bc.is_muted(H) and await bc.gate(H, None, time.time()) == "muted"
    await bc.set_muted(H, False)
    assert await bc.gate(H, None, time.time()) is None


async def test_每天最多三条_第二天重新算(db):
    await mk_human(db)
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        (await s.get(D.Player, H)).last_active = NOW
        await s.commit()
    for i in range(3):
        assert await bc.gate(H, f"bot_{i}", NOW) is None
        await bc.record(H, f"bot_{i}", NOW)
    assert await bc.gate(H, "bot_9", NOW) == "cap"
    assert (await state(db)).count == 3
    async with D.AsyncSessionLocal() as s:
        (await s.get(D.Player, H)).last_active = NOW + 86400
        await s.commit()
    assert await bc.gate(H, "bot_9", NOW + 86400) is None, "第二天重新计"
    await bc.record(H, "bot_9", NOW + 86400)
    assert (await state(db)).count == 1


async def test_同一个机器人对同一个玩家有冷却(db):
    await mk_human(db, last_active=NOW)
    await bc.record(H, "bot_1", NOW)
    assert await bc.gate(H, "bot_1", NOW + 3600) == "pair"
    assert await bc.gate(H, "bot_2", NOW + 3600) is None, "别的机器人不受影响"
    assert await bc.gate(H, "bot_1", NOW + 4 * 3600 + 1) is None


async def test_很久没上线的玩家不打扰(db):
    await mk_human(db, last_active=NOW - 25 * 3600)
    assert await bc.gate(H, None, NOW) == "inactive"


async def test_已坐化_机器人_不存在的玩家不搭话(db):
    await mk_human(db, is_dead=True)
    assert await bc.gate(H, None, time.time()) == "player"
    assert await bc.gate("bot_00001", None, time.time()) == "player"
    assert await bc.gate("9999", None, time.time()) == "player"


# ---- 上下文与台词 -----------------------------------------------------------

async def test_上下文_好感档位_关系_境界差_标签_特质(db):
    await mk_human(db, realm="筑基期5层")
    traits = {"origin": "书香", "zodiac": "白羊", "introversion": "外向", "habits": [], "catchphrases": [], "hobby": "养花", "past": "游历"}
    await mk_bot(db, "bot_00001", "憨直", realm="元婴期初期", kindness=90, traits=traits, profile={"lawful": 90, "impulse": 80})
    await favor(db, "bot_00001", 60)
    await tie(db, H, "bot_00001", "结拜")
    ctx = await bc.build_context(H, "bot_00001", {"attitude": "真心"})
    assert (ctx["archetype"], ctx["tier"], ctx["relation"], ctx["realm_gap"]) == ("憨直", "至交", "结拜", "higher")
    assert (ctx["origin"], ctx["zodiac"], ctx["introversion"], ctx["attitude"]) == ("书香", "白羊", "外向", "真心")
    assert "守序善良" in ctx["tags"] and "冲动" in ctx["tags"]
    assert ctx["_bot_name"] == "机001" and ctx["_player_name"] == f"人{H}"


async def test_上下文_没有关系没有好感就是陌生_无(db):
    await mk_human(db)
    await mk_bot(db, "bot_00001")
    ctx = await bc.build_context(H, "bot_00001")
    assert (ctx["tier"], ctx["relation"], ctx["origin"]) == ("陌生", "无", None)
    assert await bc.build_context(H, "bot_99999") is None
    assert await bc.build_context("9999", "bot_00001") is None


async def test_台词_按条件挑选_填占位符(db):
    await mk_human(db)
    await mk_bot(db, "bot_00001", "阴鸷")
    await favor(db, "bot_00001", -50)
    got = {(await bc.compose("chatter_arrive", H, "bot_00001", {"city": "落云城"}, rng=R(s)))["line"] for s in range(60)}
    assert got and all("{" not in t for t in got)
    assert any("落云城" in t for t in got)
    c = await bc.compose("chatter_arrive", H, "bot_00001", {"city": CITY}, rng=R(1))
    assert c["bot_name"] == "机001" and c["tier"] == "仇视" and c["scene"] == "chatter_arrive" and c["player_id"] == H


async def test_台词_说话特质会改写(db, monkeypatch):
    await mk_human(db)
    await mk_bot(db, "bot_00001", traits={"origin": "农户", "introversion": "外向"})
    seen = []
    from utils import bot_voice
    monkeypatch.setattr(bot_voice, "style", lambda template, traits, scene, tier, rng=None: seen.append((scene, tier, traits["origin"])) or "改写后的话。")
    c = await bc.compose("chatter_arrive", H, "bot_00001", {"city": CITY})
    assert c["line"] == "改写后的话。" and seen == [("chatter_arrive", "陌生", "农户")]


async def test_台词_库里挑不出来返回None(db, monkeypatch):
    await mk_human(db)
    await mk_bot(db, "bot_00001")
    from utils import bot_chatter_lines as cl
    monkeypatch.setattr(cl, "pick", lambda *a, **k: None)
    assert await bc.compose("chatter_arrive", H, "bot_00001", {"city": CITY}) is None


# ---- 熟人 -------------------------------------------------------------------

async def test_熟人_关系网加好感记录_权重(db):
    await mk_human(db)
    for i in (1, 2, 3):
        await mk_bot(db, f"bot_{i:05d}")
    await tie(db, H, "bot_00001", "结拜", 100)
    await favor(db, "bot_00002", 80)
    await favor(db, "bot_00003", -50)
    fam = await bc.familiars(H)
    assert set(fam) == {"bot_00001", "bot_00002", "bot_00003"} and fam["bot_00001"]["relation"] == "结拜"
    w = {b: bc.familiar_weight(i) for b, i in fam.items()}
    assert w["bot_00001"] > w["bot_00002"] > w["bot_00003"] > 0, "对头也会出来，只是少"


async def test_熟人_陌生人不算(db):
    await mk_human(db)
    await mk_bot(db, "bot_00001")
    assert await bc.familiars(H) == {}


# ---- 到城 -------------------------------------------------------------------

async def test_到城_很熟的几乎必来_不熟的才可能不理你_陌生人不主动(db):
    cfg = bc.load()["arrive"]
    assert bc.arrive_chance("结拜", 80, bc.load()) >= 0.95 and bc.arrive_chance("朋友", 30, bc.load()) == cfg["chance_by_relation"]["朋友"]
    assert bc.arrive_chance("无", 60, bc.load()) == cfg["chance_by_tier"]["至交"] >= 0.9, "没有关系网，但好感到了至交，也几乎必来"
    assert bc.arrive_chance("无", 0, bc.load()) == cfg["chance_by_tier"]["陌生"] < 0.1
    assert bc.arrive_chance("相识", 0, bc.load()) == cfg["chance_by_relation"]["相识"], "取较大的那个"
    assert bc.arrive_chance("仇敌", -50, bc.load()) == max(cfg["chance_by_relation"]["仇敌"], cfg["chance_by_tier"]["仇视"])
    assert cfg["chance_by_relation"]["结拜"] > cfg["chance_by_relation"]["朋友"] > cfg["chance_by_relation"]["相识"]


async def test_到城_同城的熟人各自掷骰_来的一起说话_合并成一条(db):
    await mk_human(db, last_active=NOW)
    for i in range(1, 5):
        await mk_bot(db, f"bot_{i:05d}", city="落云城")
        await favor(db, f"bot_{i:05d}", 40)
    await mk_bot(db, "bot_00009", city="天水镇")
    await favor(db, "bot_00009", 40)                                   # 不在这座城
    out = await bc.maybe_arrive(H, "落云城", Z(0.0), NOW)
    assert out["scene"] == "chatter_arrive" and len(out["entries"]) == 4 and out["more"] == 0
    assert set(out["all_bot_ids"]) == {f"bot_{i:05d}" for i in range(1, 5)}
    assert out["bot_id"] == out["entries"][0]["bot_id"] and all(e["line"] for e in out["entries"])
    assert await bc.maybe_arrive(H, "落云城", Z(0.99), NOW) is None, "每个人都没掷中"


async def test_到城_展示行数有上限_其余写另有几位(db, monkeypatch):
    await mk_human(db, last_active=NOW)
    for i in range(1, 10):
        await mk_bot(db, f"bot_{i:05d}", city="落云城")
        await favor(db, f"bot_{i:05d}", 40)
    out = await bc.maybe_arrive(H, "落云城", Z(0.0), NOW)
    assert len(out["entries"]) == bc.load()["arrive"]["max_lines"] == 6 and out["more"] == 3 and len(out["all_bot_ids"]) == 9


async def test_到城_没熟人_熟人不在这座城_都不搭话(db):
    await mk_human(db, last_active=NOW)
    await mk_bot(db, "bot_00001", city="天水镇")
    await favor(db, "bot_00001", 40)
    assert await bc.maybe_arrive(H, "落云城", Z(0.0), NOW) is None
    await mk_bot(db, "bot_00002", city="落云城")                       # 陌生人
    assert await bc.maybe_arrive(H, "落云城", Z(0.99), NOW) is None


async def test_到城_死了的_屏蔽的_冷却中的_不搭话(db):
    await mk_human(db, last_active=NOW)
    await mk_bot(db, "bot_00001", city="落云城", alive=False)
    await favor(db, "bot_00001", 40)
    assert await bc.maybe_arrive(H, "落云城", Z(0.0), NOW) is None
    await mk_bot(db, "bot_00002", city="落云城")
    await favor(db, "bot_00002", 40)
    await bc.record(H, "bot_00002", NOW)
    assert await bc.maybe_arrive(H, "落云城", Z(0.0), NOW + 60) is None, "冷却中"
    assert await bc.maybe_arrive(H, "落云城", Z(0.0), NOW + 5 * 3600) is not None
    await bc.set_muted(H, True)
    assert await bc.maybe_arrive(H, "落云城", Z(0.0), NOW + 5 * 3600) is None


async def test_到城_冷却只挡住说过话的那一位(db):
    await mk_human(db, last_active=NOW)
    for i in (1, 2):
        await mk_bot(db, f"bot_{i:05d}", city="落云城")
        await favor(db, f"bot_{i:05d}", 40)
    await bc.record(H, "bot_00001", NOW)
    out = await bc.maybe_arrive(H, "落云城", Z(0.0), NOW + 60)
    assert out["all_bot_ids"] == ["bot_00002"]


async def test_一次搭话事件算一次_多个人同时说话也只占一个名额(db):
    await mk_human(db, last_active=NOW)
    for i in range(1, 6):
        await mk_bot(db, f"bot_{i:05d}", city="落云城")
        await favor(db, f"bot_{i:05d}", 40)
    out = await bc.maybe_arrive(H, "落云城", Z(0.0), NOW)
    await bc.record(H, out["all_bot_ids"], NOW)
    assert (await state(db)).count == 1
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        assert len((await s.execute(select(D.ChatterPair))).scalars().all()) == 5, "每个说话的人各自冷却"


# ---- 突破道贺 ---------------------------------------------------------------

def result(old="筑基期9层", new="结丹期初期", ok=True):
    return {"breakthrough": ok, "old_realm": old, "new_realm": new}


async def pdict(uid=H):
    from utils.player import get_player
    return await get_player(uid)


async def test_道贺_只有大境界突破才有人来(db):
    await mk_human(db)
    await mk_bot(db, "bot_00001")
    await tie(db, H, "bot_00001", "结拜")
    assert await bc.on_breakthrough(await pdict(), result("筑基期1层", "筑基期2层"), Z(0.0)) == 0
    assert await bc.on_breakthrough(await pdict(), {"breakthrough": False}, Z(0.0)) == 0
    assert await queue(db) == []
    assert await bc.on_breakthrough(await pdict(), result(), Z(0.0), NOW) == 1


async def test_道贺_入队内容_态度_延迟_境界(db):
    await mk_human(db)
    await mk_bot(db, "bot_00001")
    await tie(db, H, "bot_00001", "朋友")
    await bc.on_breakthrough(await pdict(), result(), Z(0.0), NOW)
    (q,) = await queue(db)
    fmt = json.loads(q.fmt)
    cfg = bc.load()["congrats"]["delay_seconds"]
    assert (q.player_id, q.speaker_id, q.scene) == (H, "bot_00001", "chatter_congrats")
    assert fmt["vars"] == {"realm": "结丹期初期"} and fmt["ctx"]["attitude"] in ("真心", "酸", "不服", "觊觎") and fmt["group"]
    assert NOW + cfg[0] <= q.due_at <= NOW + cfg[1]


async def test_道贺_认识你的人基本都来_人数不设上限_同一次突破共用一个组和到点时间(db):
    await mk_human(db)
    for i in range(1, 21):
        await mk_bot(db, f"bot_{i:05d}")
        await tie(db, H, f"bot_{i:05d}", "朋友", strength=i)
    assert await bc.on_breakthrough(await pdict(), result(), Z(0.0), NOW) == 20
    rows = await queue(db)
    assert len({json.loads(q.fmt)["group"] for q in rows}) == 1 and len({q.due_at for q in rows}) == 1


async def test_道贺_不认识你的人最多两个_且概率很低(db):
    await mk_human(db)
    for i in range(1, 8):
        await mk_bot(db, f"bot_{i:05d}")                              # 同城的陌生人
    assert await bc.on_breakthrough(await pdict(), result(), Z(0.0), NOW) == bc.load()["congrats"]["stranger_max"] == 2
    assert {q.speaker_id for q in await queue(db)} <= {f"bot_{i:05d}" for i in range(1, 8)}
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        for q in (await s.execute(select(D.ChatterQueue))).scalars().all():
            await s.delete(q)
        await s.commit()
    assert await bc.on_breakthrough(await pdict(), result(), Z(0.5), NOW) == 0, "陌生人只有 10% 的概率"


async def test_道贺_陌生人不在同城就不来(db):
    await mk_human(db)
    await mk_bot(db, "bot_00001", city="落云城")
    assert await bc.on_breakthrough(await pdict(), result(), Z(0.0), NOW) == 0


async def test_道贺_不在同城的朋友不来_结拜兄弟会捎话(db):
    await mk_human(db)
    await mk_bot(db, "bot_00001", city="落云城")
    await mk_bot(db, "bot_00002", city="落云城")
    await tie(db, H, "bot_00001", "朋友")
    await tie(db, H, "bot_00002", "结拜")
    await bc.on_breakthrough(await pdict(), result(), Z(0.0), NOW)
    assert {q.speaker_id for q in await queue(db)} == {"bot_00002"}


async def test_道贺_按关系概率_不熟的人少来_很熟的几乎必来(db):
    await mk_human(db)
    await mk_bot(db, "bot_00001")
    await tie(db, H, "bot_00001", "相识")
    assert await bc.on_breakthrough(await pdict(), result(), Z(0.8), NOW) == 0        # 相识 0.7
    await mk_bot(db, "bot_00002")
    await tie(db, H, "bot_00002", "结拜")
    assert await bc.on_breakthrough(await pdict(), result(), Z(0.8), NOW) == 1        # 结拜 0.98
    assert bc.load()["congrats"]["relation_chance"]["结拜"] > bc.load()["congrats"]["relation_chance"]["相识"]


async def test_道贺_死了的不来(db):
    await mk_human(db)
    await mk_bot(db, "bot_00001", alive=False)
    await tie(db, H, "bot_00001", "结拜")
    assert await bc.on_breakthrough(await pdict(), result(), Z(0.0), NOW) == 0


async def test_道贺_出错只记警告(db, monkeypatch, caplog):
    async def boom(*a, **k):
        raise RuntimeError("库坏了")
    monkeypatch.setattr(bc, "familiars", boom)
    await mk_human(db)
    assert await bc.on_breakthrough(await pdict(), result(), Z(0.0)) == 0
    assert "道贺入队失败" in caplog.text


# ---- 公共事件 ---------------------------------------------------------------

async def event_world(db):
    await mk_human(db, "1001")
    await mk_human(db, "1002")
    for i in range(1, 5):
        await mk_bot(db, f"bot_{i:05d}")
    await tie(db, "1001", "bot_00001", "朋友")
    await tie(db, "1002", "bot_00002", "朋友")
    await tie(db, "1001", "bot_00003", "朋友")
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        s.add(D.PublicEvent(event_id="e1", event_type="spirit_rain", title="灵雨", started_at=NOW, ends_at=NOW + 3600, status="active"))
        for uid in ("1001", "1002", "bot_00001"):
            s.add(D.PublicEventParticipant(event_id="e1", discord_id=uid, activity="", joined_at=NOW))
        await s.commit()


async def test_事件_结束后_参与的熟人玩家和在场机器人配对(db):
    await event_world(db)
    assert await bc.queue_event("e1", CITY, "after", False, Z(0.0), NOW) == 2
    rows = await queue(db)
    assert {(q.player_id, q.scene) for q in rows} == {("1001", "chatter_event_after"), ("1002", "chatter_event_after")}
    assert json.loads(rows[0].fmt)["vars"] == {"event": "灵雨", "city": CITY}
    assert len({q.speaker_id for q in rows}) == 2


async def test_事件_兽潮叫兽潮(db):
    await event_world(db)
    await bc.queue_event("e1", CITY, "after", True, Z(0.0), NOW)
    assert all(json.loads(q.fmt)["ctx"]["event"] == "兽潮" for q in await queue(db))


async def test_事件_开始时没人报名_用城里的玩家(db):
    await event_world(db)
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        for p in (await s.execute(select(D.PublicEventParticipant))).scalars().all():
            await s.delete(p)
        await s.commit()
    assert await bc.queue_event("e1", CITY, "before", False, Z(0.0), NOW) == 2
    assert await bc.queue_event("e1", CITY, "after", False, Z(0.0), NOW) == 0, "结束后没人参与就没人可说"


async def test_事件_总数有上限_概率不过就不说(db, monkeypatch):
    await event_world(db)
    assert await bc.queue_event("e1", CITY, "after", False, Z(0.99), NOW) == 0
    cfg = copy.deepcopy(bc.load())
    cfg["event"]["max_pairs"] = 1
    monkeypatch.setattr(bc, "load", lambda: cfg)
    assert await bc.queue_event("e1", CITY, "after", False, Z(0.0), NOW) == 1


# ---- 冲突后放话 -------------------------------------------------------------

def holder(h, victim="bot_00001"):
    return {"holder": h, "victim": victim}


async def conflict_world(db):
    await mk_human(db)
    await mk_bot(db, "bot_00001")                                     # 受害者
    await mk_bot(db, "bot_00002", "豪爽")                              # 替它出头的结拜兄弟
    await mk_bot(db, "bot_00003", "迂腐", kindness=80)                 # 劝架的
    await tie(db, "bot_00001", "bot_00002", "结拜")
    await tie(db, "bot_00001", "bot_00003", "朋友")


async def test_冲突_当事机器人和出头的朋友几分钟后放话(db):
    await conflict_world(db)
    n = await bc.queue_conflict(H, "bot_00001", "rob", [holder("bot_00001"), holder("bot_00002")], Z(0.99), NOW)
    assert n == 2
    rows = {q.speaker_id: q for q in await queue(db)}
    assert rows["bot_00001"].scene == "chatter_conflict_self" and json.loads(rows["bot_00001"].fmt)["ctx"] == {"kind": "rob"}
    friend = rows["bot_00002"]
    assert friend.scene == "chatter_conflict_friend"
    fmt = json.loads(friend.fmt)
    assert fmt["vars"] == {"victim": "机001"} and fmt["ctx"] == {"kind": "rob", "bond": "结拜"} and fmt["group"]
    lo, hi = bc.load()["conflict"]["delay_minutes"]
    assert NOW + lo * 60 <= rows["bot_00001"].due_at <= NOW + hi * 60
    assert friend.due_at > NOW + lo * 60, "朋友陆续出来"


async def test_冲突_击杀_受害者已死_只有朋友说话(db):
    await conflict_world(db)
    n = await bc.queue_conflict(H, "bot_00001", "kill", [holder("bot_00002")], Z(0.99), NOW)
    assert n == 1 and [q.scene for q in await queue(db)] == ["chatter_conflict_friend"]


async def test_冲突_有概率出来一个劝架的_善良或守序的才劝(db):
    await conflict_world(db)
    assert await bc.queue_conflict(H, "bot_00001", "rob", [holder("bot_00001")], Z(0.99), NOW) == 1, "概率没过就不劝"
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        for q in (await s.execute(select(D.ChatterQueue))).scalars().all():
            await s.delete(q)
        await s.commit()
    assert await bc.queue_conflict(H, "bot_00001", "rob", [holder("bot_00001")], Z(0.0), NOW) == 2
    mediator = next(q for q in await queue(db) if q.scene == "chatter_mediate")
    assert mediator.speaker_id == "bot_00003" and json.loads(mediator.fmt)["vars"] == {"victim": "机001"}


async def test_冲突_凶恶的朋友不会来劝架(db):
    await mk_human(db)
    await mk_bot(db, "bot_00001")
    await mk_bot(db, "bot_00003", "阴鸷", kindness=10, profile={"lawful": 10})
    await tie(db, "bot_00001", "bot_00003", "朋友")
    assert await bc.queue_conflict(H, "bot_00001", "rob", [holder("bot_00001")], Z(0.0), NOW) == 1


async def test_冲突_朋友人数不设上限_一起出来_共用一个组(db):
    await mk_human(db)
    await mk_bot(db, "bot_00001")
    holders = [holder("bot_00001")]
    for i in range(2, 14):
        await mk_bot(db, f"bot_{i:05d}")
        await tie(db, "bot_00001", f"bot_{i:05d}", "朋友")
        holders.append(holder(f"bot_{i:05d}"))
    assert bc.load()["conflict"]["max_messages"] is None
    assert await bc.queue_conflict(H, "bot_00001", "cripple", holders, Z(0.99), NOW) == 13
    friends = [q for q in await queue(db) if q.scene == "chatter_conflict_friend"]
    assert len(friends) == 12 and len({json.loads(q.fmt)["group"] for q in friends}) == 1 and len({q.due_at for q in friends}) == 1


async def test_冲突_配置里设了上限就遵守(db, monkeypatch):
    await mk_human(db)
    await mk_bot(db, "bot_00001")
    holders = [holder("bot_00001")]
    for i in range(2, 8):
        await mk_bot(db, f"bot_{i:05d}")
        await tie(db, "bot_00001", f"bot_{i:05d}", "朋友")
        holders.append(holder(f"bot_{i:05d}"))
    cfg = copy.deepcopy(bc.load())
    cfg["conflict"]["max_messages"] = 3
    monkeypatch.setattr(bc, "load", lambda: cfg)
    assert await bc.queue_conflict(H, "bot_00001", "cripple", holders, Z(0.99), NOW) == 3


async def test_冲突_劝架的数量按配置_默认最多一个(db, monkeypatch):
    await mk_human(db)
    await mk_bot(db, "bot_00001")
    for i in range(2, 6):
        await mk_bot(db, f"bot_{i:05d}", kindness=90)
        await tie(db, "bot_00001", f"bot_{i:05d}", "朋友")
    assert await bc.queue_conflict(H, "bot_00001", "rob", [holder("bot_00001")], Z(0.0), NOW) == 2
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        for q in (await s.execute(select(D.ChatterQueue))).scalars().all():
            await s.delete(q)
        await s.commit()
    cfg = copy.deepcopy(bc.load())
    cfg["conflict"]["mediators_max"] = None
    monkeypatch.setattr(bc, "load", lambda: cfg)
    assert await bc.queue_conflict(H, "bot_00001", "rob", [holder("bot_00001")], Z(0.0), NOW) == 5, "不限时四个朋友都来劝"


# ---- 到点发送 ---------------------------------------------------------------

async def test_到点才发_没到点不动(db):
    await mk_human(db, last_active=NOW)
    await mk_bot(db, "bot_00001")
    await bc.enqueue(H, "bot_00001", "chatter_congrats", {"realm": "结丹期初期"}, {"attitude": "真心"}, 100, NOW)
    assert await bc.claim_due(NOW + 50) == []
    items = await bc.claim_due(NOW + 101, rng=R(1))
    assert len(items) == 1 and items[0]["scene"] == "chatter_congrats" and items[0]["payload"]["line"]
    assert (await state(db)).count == 1
    assert (await queue(db))[0].outcome == "sent"


async def test_认领是条件更新_同一条不会发两遍(db):
    await mk_human(db, last_active=NOW)
    await mk_bot(db, "bot_00001")
    qid = await bc.enqueue(H, "bot_00001", "chatter_arrive", {"city": CITY}, {}, 0, NOW)
    assert await bc.claim(qid, NOW + 1) is True
    assert await bc.claim(qid, NOW + 2) is False, "已经被认领过"
    assert await bc.claim("不存在", NOW) is False
    assert await bc.claim_due(NOW + 3) == [], "认领过的不会再发"


async def test_发送时才检查_屏蔽_上限_冷却_不发的记在outcome里(db):
    await mk_human(db, last_active=NOW)
    for i in range(1, 6):
        await mk_bot(db, f"bot_{i:05d}")
        await bc.enqueue(H, f"bot_{i:05d}", "chatter_arrive", {"city": CITY}, {}, i, NOW)
    items = await bc.claim_due(NOW + 100)
    assert len(items) == 3, "每天最多 3 条"
    assert [q.outcome for q in await queue(db)] == ["sent", "sent", "sent", "cap", "cap"]
    await bc.set_muted(H, True)
    await bc.enqueue(H, "bot_00001", "chatter_arrive", {"city": CITY}, {}, 0, NOW + 200)
    assert await bc.claim_due(NOW + 300) == []
    assert (await queue(db))[-1].outcome == "muted"


async def test_台词挑不出来_丢弃并标记(db, monkeypatch):
    await mk_human(db, last_active=NOW)
    await mk_bot(db, "bot_00001")
    from utils import bot_chatter_lines as cl
    monkeypatch.setattr(cl, "pick", lambda *a, **k: None)
    await bc.enqueue(H, "bot_00001", "chatter_arrive", {"city": CITY}, {}, 0, NOW)
    assert await bc.claim_due(NOW + 1) == []
    assert (await queue(db))[0].outcome == "nolines" and (await state(db)) is None


async def test_清理旧队列记录(db):
    await mk_human(db, last_active=NOW)
    await mk_bot(db, "bot_00001")
    await bc.enqueue(H, "bot_00001", "chatter_arrive", {"city": CITY}, {}, 0, NOW)
    await bc.claim_due(NOW + 1)
    assert await bc.purge_old(NOW + 86400) == 0
    assert await bc.purge_old(NOW + 3 * 86400) == 1


# ---- 玩家回应 ---------------------------------------------------------------

async def test_回应_好感小幅变化_机器人回一句(db):
    await mk_human(db)
    await mk_bot(db, "bot_00001")
    cfg = bc.load()["reply"]
    for key, delta in cfg.items():
        before = await bs.get_favor(H, "bot_00001")
        res = await bc.respond(H, "bot_00001", key, R(1))
        assert res["ok"] and res["delta"] == delta and res["favor"] == before + delta and res["line"]
    assert not (await bc.respond(H, "bot_00001", "跳舞"))["ok"]


async def test_回应_淡淡的不改好感(db):
    await mk_human(db)
    await mk_bot(db, "bot_00001")
    assert (await bc.respond(H, "bot_00001", "neutral"))["favor"] == 0


# ---- 清理 -------------------------------------------------------------------

async def test_清理机器人_它没发的搭话和冷却一并删(db):
    from utils import bot_world
    await mk_human(db, last_active=NOW)
    await mk_bot(db, "bot_00001")
    await bc.enqueue(H, "bot_00001", "chatter_arrive", {"city": CITY}, {}, 999, NOW)
    await bc.record(H, "bot_00001", NOW)
    res = await bot_world.remove_bots(["bot_00001"])
    assert res["rows"]["chatter"] == 2 and await queue(db) == []


async def test_转世_没发的搭话作废_冷却清掉_屏蔽偏好保留(db):
    from utils.character_create_logic import commit_character
    await mk_human(db, last_active=NOW, is_dead=True)
    await mk_bot(db, "bot_00001")
    await bc.enqueue(H, "bot_00001", "chatter_arrive", {"city": CITY}, {}, 999, NOW)
    await bc.record(H, "bot_00001", NOW)
    await bc.set_muted(H, True)
    assert await commit_character(H, "新名字", "男", {})
    assert await queue(db) == []
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        assert await s.get(D.ChatterPair, (H, "bot_00001")) is None
    assert await bc.is_muted(H), "屏蔽是玩家本人的偏好"


# ---- 界面 -------------------------------------------------------------------

def payload(scene="chatter_arrive", **kw):
    return {"scene": scene, "line": "你好。", "bot_id": "bot_00001", "bot_name": "机001", "bot_realm": "筑基期5层", "player_id": H, **kw}


def test_消息样式():
    e = cv.chatter_embed(payload())
    assert e.title == "💬 机001（筑基期5层）" and e.description == "「你好。」" and "屏蔽" in e.footer.text


def test_普通搭话有四个回应按钮和屏蔽_冲突放话是化解和屏蔽():
    assert [c.label for c in cv.ChatterView(payload()).children] == ["💞 热情", "🙂 客气", "😐 淡淡", "😒 冷淡", "🔕 屏蔽"]
    for scene in ("chatter_conflict_self", "chatter_conflict_friend"):
        assert [c.label for c in cv.ChatterView(payload(scene)).children] == ["🕊️ 化解", "🔕 屏蔽"]
    assert [c.label for c in cv.ChatterView(payload("chatter_mediate")).children][-1] == "🔕 屏蔽"


async def test_面板_只有被搭话的人能点():
    view = cv.ChatterView(payload())
    assert await view.interaction_check(FakeInteraction(user_id=7)) is False
    assert await view.interaction_check(FakeInteraction(user_id=int(H))) is True


async def test_面板_回应一次_好感变化_消息换成带回复的版本_收起按钮(db):
    await mk_human(db)
    await mk_bot(db, "bot_00001")
    view = cv.ChatterView(payload())
    i = FakeInteraction(user_id=int(H))
    await next(c for c in view.children if c.label == "💞 热情").callback(i)
    assert await bs.get_favor(H, "bot_00001") == bc.load()["reply"]["warm"]
    msg = i.edited[-1]
    assert msg.view is None and any("回应" in f.name for f in msg.embed.fields)
    j = FakeInteraction(user_id=int(H))
    await next(c for c in view.children if c.label == "😒 冷淡").callback(j)
    assert j.response.said("已经回应过") and await bs.get_favor(H, "bot_00001") == bc.load()["reply"]["warm"]


async def test_面板_屏蔽按钮(db):
    await mk_human(db)
    view = cv.ChatterView(payload())
    i = FakeInteraction(user_id=int(H))
    await next(c for c in view.children if "屏蔽" in c.label).callback(i)
    assert await bc.is_muted(H) and i.response.said("已屏蔽") and i.response.last.ephemeral


async def test_发送_带mention_embed_按钮_记下消息():
    sent = []

    async def send(content=None, **kw):
        sent.append((content, kw))
        return SimpleNamespace(id=1)
    msg = await cv.send_payload(send, payload())
    assert sent[0][0] == f"<@{H}>" and sent[0][1]["embed"].title.startswith("💬") and sent[0][1]["view"].message is msg


async def test_到城钩子_有人搭话就发并记账_没有就不发(db, monkeypatch):
    await mk_human(db, last_active=time.time())
    await mk_bot(db, "bot_00001", city="落云城")
    await favor(db, "bot_00001", 40)
    c = FakeContext(user_id=int(H))
    assert await cv.run_arrive(c.send, c.author, "天水镇") is False and c.messages == []
    monkeypatch.setattr(bc, "maybe_arrive", lambda pid, city: _arrive(pid, city))
    assert await cv.run_arrive(c.send, c.author, "落云城") is True
    assert c.last.embed.title.startswith("💬") and (await state(db)).count == 1


async def _arrive(pid, city):
    return await bc.compose("chatter_arrive", pid, "bot_00001", {"city": city}, rng=R(1))


# ---- 接入点 -----------------------------------------------------------------

async def test_接入_突破逻辑会调用道贺(db, monkeypatch):
    from utils import breakthrough_logic as bl
    await mk_human(db)
    calls = []

    async def spy(player, res, rng=None, now=None):
        calls.append((player["discord_id"], res["new_realm"]))
        return 0
    monkeypatch.setattr(bc, "on_breakthrough", spy)
    await bl._rumor(await pdict(), result())
    assert calls == [(H, "结丹期初期")]


async def test_接入_公共事件开始结束会调用搭话入队(db, monkeypatch):
    from utils import bot_events
    calls = []

    async def spy(event_id, city, when, beast_tide, rng=None, now=None):
        calls.append((event_id, city, when, beast_tide))
        return 0
    monkeypatch.setattr(bc, "queue_event", spy)
    await bot_events.on_spirit_rain_start("e9", CITY, True)
    await bot_events.on_spirit_rain_end({"event_id": "e9", "data": json.dumps({"city": CITY, "beast_tide": True})})
    assert calls == [("e9", CITY, "before", True), ("e9", CITY, "after", True)]


async def test_接入_打劫废修为击杀会入队冲突放话(db, monkeypatch):
    from utils import bot_combat
    calls = []

    async def spy(actor, victim, kind, holders, rng=None, now=None):
        calls.append((actor, victim, kind, [h["holder"] for h in holders]))
        return 0
    monkeypatch.setattr(bc, "queue_conflict", spy)
    await mk_human(db, city="万妖岭")
    await mk_bot(db, "bot_00001", city="万妖岭")
    await mk_bot(db, "bot_00002", city="万妖岭", profile={"loyalty": 100})
    await tie(db, "bot_00001", "bot_00002", "结拜", 100)
    assert (await bot_combat.rob_bot(H, "bot_00001"))["ok"]
    assert (await bot_combat.cripple_bot(H, "bot_00001"))["ok"]
    assert (await bot_combat.kill_bot(H, "bot_00001"))["ok"]
    assert [c[2] for c in calls] == ["rob", "cripple", "kill"] and all(c[:2] == (H, "bot_00001") for c in calls)
    assert "bot_00001" in calls[0][3]


async def test_接入_进城触发搭话_进秘地不触发(db, monkeypatch):
    from cogs.travel import TravelCog
    from utils.world import SPECIAL_REGIONS
    await mk_human(db, realm="结丹期初期")
    seen = []

    async def arrive(send, user, city):
        seen.append(city)
        return False

    async def hook(send, user, context):
        return False
    monkeypatch.setattr("utils.views.chatter.run_arrive", arrive)
    monkeypatch.setattr("utils.views.ambush.run_hook", hook)
    cog = TravelCog(SimpleNamespace(cogs={}))
    await cog.travel.callback(cog, FakeContext(user_id=int(H)), city_name=SPECIAL_REGIONS[0]["name"])
    assert seen == []
    await cog.travel.callback(cog, FakeContext(user_id=int(H)), city_name="落云城")
    assert seen == ["落云城"]


# ---- 后台循环与命令 ---------------------------------------------------------

async def test_后台循环_到点的发到传闻频道(db, monkeypatch):
    from cogs import chatter as cog_mod
    await mk_human(db, last_active=time.time())
    await mk_bot(db, "bot_00001")
    await bc.enqueue(H, "bot_00001", "chatter_arrive", {"city": CITY}, {}, 0, time.time() - 5)
    sent = []

    class Chan:
        async def send(self, content=None, **kw):
            sent.append((content, kw))
            return SimpleNamespace(id=1)
    monkeypatch.setattr(cog_mod, "get_rumor_channel", lambda bot: Chan())
    cog = cog_mod.ChatterCog(SimpleNamespace())
    await cog._deliver.coro(cog)
    assert len(sent) == 1 and sent[0][0] == f"<@{H}>"


async def test_后台循环_没配频道_丢弃不报错(db, monkeypatch):
    from cogs import chatter as cog_mod
    await mk_human(db, last_active=time.time())
    await mk_bot(db, "bot_00001")
    await bc.enqueue(H, "bot_00001", "chatter_arrive", {"city": CITY}, {}, 0, time.time() - 5)
    monkeypatch.setattr(cog_mod, "get_rumor_channel", lambda bot: None)
    cog = cog_mod.ChatterCog(SimpleNamespace())
    await cog._deliver.coro(cog)
    assert (await queue(db))[0].outcome == "sent", "已经认领并记账；没频道只是发不出去"


async def test_屏蔽命令(db):
    from cogs.chatter import ChatterCog
    await mk_human(db)
    cog = ChatterCog(SimpleNamespace())
    c = FakeContext(user_id=int(H))
    await cog.mute.callback(cog, c, "")
    assert c.said("未屏蔽") and c.said("用法")
    await cog.mute.callback(cog, c, "开")
    assert await bc.is_muted(H) and c.said("已屏蔽")
    c2 = FakeContext(user_id=int(H))
    await cog.mute.callback(cog, c2, "")
    assert c2.said("已屏蔽")
    await cog.mute.callback(cog, c2, "关")
    assert not await bc.is_muted(H) and c2.said("已恢复")


# ---- 补：变异测试里发现的漏洞 -------------------------------------------------

def test_道贺态度_交情档位和关系各自独立起作用():
    base = W(kindness=50, tier="陌生", relation="无")["真心"]
    assert W(kindness=50, tier="熟识", relation="无")["真心"] > base + 1
    assert W(kindness=50, tier="陌生", relation="朋友")["真心"] > base + 0.5
    assert W(greed=100, tier="陌生", relation="朋友")["觊觎"] < W(greed=100, tier="陌生", relation="无")["觊觎"]


def test_熟人权重_有仇的减半():
    assert bc.familiar_weight({"relation": "无", "strength": 0, "favor": 0}) == 1.0
    assert bc.familiar_weight({"relation": "无", "strength": 0, "favor": -50}) == 0.5
    assert bc.familiar_weight({"relation": "朋友", "strength": 50, "favor": 50}) == 3.0


async def test_道贺_有仇的人按仇敌的概率算_没关系只有好感记录的按无关系算(db, monkeypatch):
    cfg = copy.deepcopy(bc.load())
    cfg["congrats"]["relation_chance"].update({"无": 0.2, "仇敌": 0.5})
    cfg["congrats"]["stranger_max"] = 0
    monkeypatch.setattr(bc, "load", lambda: cfg)
    await mk_human(db)
    await mk_bot(db, "bot_00001")
    await favor(db, "bot_00001", -50)
    assert await bc.on_breakthrough(await pdict(), result(), Z(0.3), NOW) == 1, "好感 ≤ -30：按『仇敌』的 0.5 算"
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        for q in (await s.execute(select(D.ChatterQueue))).scalars().all():
            await s.delete(q)
        (await s.get(D.BotRelation, (H, "bot_00001"))).favor = 5
        await s.commit()
    assert await bc.on_breakthrough(await pdict(), result(), Z(0.3), NOW) == 0, "好感正常：按『无关系』的 0.2 算"


async def test_冲突_击杀时就算名单里有受害者本人也不让死人说话(db):
    await conflict_world(db)
    n = await bc.queue_conflict(H, "bot_00001", "kill", [holder("bot_00001"), holder("bot_00002")], Z(0.99), NOW)
    assert n == 1 and [q.speaker_id for q in await queue(db)] == ["bot_00002"]


async def test_冲突_劝架的不会是已经开口的人_真人_动手的人(db):
    await mk_human(db)
    await mk_human(db, "1002")
    await mk_bot(db, "bot_00001")
    await mk_bot(db, "bot_00002", kindness=90)
    await tie(db, "bot_00001", "bot_00002", "朋友")             # 已经替朋友出头的人，不再兼任劝架
    await tie(db, "bot_00001", "1002", "朋友")                  # 真人朋友不会被安排说话
    assert await bc.queue_conflict(H, "bot_00001", "rob", [holder("bot_00001"), holder("bot_00002")], Z(0.0), NOW) == 2
    assert {q.scene for q in await queue(db)} == {"chatter_conflict_self", "chatter_conflict_friend"}
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        for q in (await s.execute(select(D.ChatterQueue))).scalars().all():
            await s.delete(q)
        await s.commit()
    assert await bc.queue_conflict(H, "bot_00001", "rob", [holder("bot_00001")], Z(0.0), NOW) == 2, "没开口的 bot_00002 可以来劝"
    assert "1002" not in {q.speaker_id for q in await queue(db)}


async def test_冲突_动手的机器人本人不会来劝架(db):
    await mk_human(db)
    await mk_bot(db, "bot_00001")
    await mk_bot(db, "bot_00002", kindness=90)
    await tie(db, "bot_00001", "bot_00002", "朋友")
    assert await bc.queue_conflict("bot_00002", "bot_00001", "rob", [holder("bot_00001")], Z(0.0), NOW) == 1


async def test_冲突_设了总数上限_满额之后不再加劝架的(db, monkeypatch):
    await mk_human(db)
    await mk_bot(db, "bot_00001")
    holders = [holder("bot_00001")]
    for i in range(2, 8):
        await mk_bot(db, f"bot_{i:05d}", kindness=90)
        await tie(db, "bot_00001", f"bot_{i:05d}", "朋友")
        holders.append(holder(f"bot_{i:05d}"))
    cfg = copy.deepcopy(bc.load())
    cfg["conflict"]["max_messages"] = 3
    monkeypatch.setattr(bc, "load", lambda: cfg)
    assert await bc.queue_conflict(H, "bot_00001", "cripple", holders, Z(0.0), NOW) == 3
    assert "chatter_mediate" not in {q.scene for q in await queue(db)}


async def test_转世_已经发过的搭话记录不动(db):
    from utils.character_create_logic import commit_character
    await mk_human(db, last_active=NOW, is_dead=True)
    await mk_bot(db, "bot_00001")
    qid = await bc.enqueue(H, "bot_00001", "chatter_arrive", {"city": CITY}, {}, 0, NOW)
    await bc.claim(qid, NOW + 1)
    await bc.enqueue(H, "bot_00001", "chatter_arrive", {"city": CITY}, {}, 999, NOW)
    assert await commit_character(H, "新名字", "男", {})
    assert [q.id for q in await queue(db)] == [qid]


async def test_到城_主说话人是交情最深的_排在第一行(db):
    await mk_human(db, last_active=NOW)
    await mk_bot(db, "bot_00001", city="落云城")
    await mk_bot(db, "bot_00002", city="落云城")
    await favor(db, "bot_00001", 45)
    await tie(db, H, "bot_00002", "结拜", 100)
    out = await bc.maybe_arrive(H, "落云城", Z(0.0), NOW)
    assert out["bot_id"] == "bot_00002" and [e["bot_id"] for e in out["entries"]] == ["bot_00002", "bot_00001"]


async def test_同组的合并成一条_不同组的各发各的_每个说话的人都记冷却(db):
    await mk_human(db, last_active=NOW)
    for i in range(1, 5):
        await mk_bot(db, f"bot_{i:05d}")
    for sid in ("bot_00001", "bot_00002"):
        await bc.enqueue(H, sid, "chatter_congrats", {"realm": "结丹期初期"}, {"attitude": "真心"}, 0, NOW, group="甲组")
    await bc.enqueue(H, "bot_00003", "chatter_congrats", {"realm": "结丹期初期"}, {"attitude": "真心"}, 0, NOW, group="乙组")
    items = await bc.claim_due(NOW + 1, rng=R(1))
    assert len(items) == 2
    merged = next(i for i in items if len(i["payload"]["entries"]) == 2)
    assert set(merged["payload"]["all_bot_ids"]) == {"bot_00001", "bot_00002"} and len(merged["queue_ids"]) == 2
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        paired = {p.bot_id for p in (await s.execute(select(D.ChatterPair))).scalars()}
    assert paired == {"bot_00001", "bot_00002", "bot_00003"}, "合并消息里每个说话的人都有冷却"
    assert (await state(db)).count == 2, "两条消息，算两次搭话事件"
