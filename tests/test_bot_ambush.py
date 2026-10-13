"""拦路遭遇（utils/bot_ambush.py、utils/views/ambush.py、cogs/ambush.py、data/bot_ambush.json）。

用户 2026-10-12 的设计 / 我的默认：只在玩家在线做野外动作时判定；幸福模式不拦路、正常模式最重废修为、真实模式才可能杀人；
概率按境界差，几人一起找叠加；全局冷却 3 游戏年；结拜 / 朋友可能赶来；逃跑 / 迎战 1 分钟，超时算逃跑；输了先交涉（道歉 / 敷衍 / 拒绝 / 挑衅 / 买命），超时算拒绝；
处置按性格 × 仇恨 × 画像 × 回应；被废被杀有保护期；公共事件优先；管理员开关随时关。
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
from utils import bot_ambush as ba
from utils import bot_grudges as bg
from utils import world_settings
from utils.bot_social import load_archetypes
from utils.character import years_to_seconds
from utils.views import ambush as av
from utils.world import SPECIAL_REGIONS

H, CITY = "1001", "灵虚城"
YEAR = years_to_seconds(1)
NOW = 1_800_000_000.0


class Z(random.Random):
    def __init__(self, value=0.0, seed=0):
        super().__init__(seed)
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


def R(seed=0):
    return random.Random(seed)


# ---- 数据与纯函数 -----------------------------------------------------------

def test_配置合法():
    assert ba.validate(ba.load(), list(load_archetypes())) == []


@pytest.mark.parametrize("mutate,expect", [
    (lambda c: c["chance"].update(equal=2), "chance.equal"),
    (lambda c: c.update(modes=["幸福", "天堂"]), "modes"),
    (lambda c: c.update(global_cooldown_years=-1), "冷却"),
    (lambda c: c["timeouts"].update(choose_seconds=1), "choose_seconds"),
    (lambda c: c["outcome"].pop("阴鸷"), "outcome 应覆盖"),
    (lambda c: c["outcome"]["阴鸷"].pop("release"), "outcome.阴鸷"),
    (lambda c: c["outcome"]["阴鸷"].update(饶了你=5), "outcome.阴鸷"),
    (lambda c: c["responses"].pop("provoke"), "responses"),
    (lambda c: c["responses"]["refuse"].pop("kill"), "responses.refuse"),
    (lambda c: c["buyout"]["accept"].pop("贪财"), "buyout.accept"),
    (lambda c: c["rob"].update(share=0), "rob"),
    (lambda c: c["flee"].update(min=0.9, max=0.1), "flee"),
])
def test_校验能拦住坏配置(mutate, expect):
    cfg = copy.deepcopy(ba.load())
    mutate(cfg)
    assert any(expect in e for e in ba.validate(cfg, list(load_archetypes()))), ba.validate(cfg, list(load_archetypes()))


def test_全局冷却是用户定的3游戏年():
    assert ba.load()["global_cooldown_years"] == 3 and ba.load()["timeouts"] == {"choose_seconds": 60, "bargain_seconds": 60}


def test_触发概率_比你强_同阶_比你弱_不在同城打折():
    c = ba.load()["chance"]
    assert ba.encounter_chance("元婴期初期", "筑基期1层", True) == c["stronger"]
    assert ba.encounter_chance("筑基期1层", "筑基期9层", True) == c["equal"]
    assert ba.encounter_chance("炼气期1层", "筑基期1层", True) == c["weaker"]
    assert ba.encounter_chance("元婴期初期", "筑基期1层", False) == c["stronger"] * c["other_city_factor"]
    assert c["stronger"] > c["equal"] > c["weaker"]


def test_多人找你_概率叠加_封顶_动作类型有系数():
    cfg = ba.load()
    assert ba.combine_chances([0.4]) == pytest.approx(0.4)
    assert ba.combine_chances([0.4, 0.4]) == pytest.approx(0.64)
    assert ba.combine_chances([0.65] * 10) == cfg["chance"]["multi_cap"]
    assert ba.combine_chances([]) == 0
    cfg2 = copy.deepcopy(cfg)
    cfg2["contexts"]["gathering"] = 0.5
    assert ba.combine_chances([0.4], "gathering", cfg2) == pytest.approx(0.2)
    assert ba.combine_chances([0.4], "没有的动作") == pytest.approx(0.4)


def test_逃跑成功率_境界差_同伴_援手_上下限():
    f = ba.flee_rate
    assert f(0.5, "筑基期1层", "筑基期9层") == 0.5
    assert f(0.5, "结丹期初期", "筑基期1层") == pytest.approx(0.5 - 0.08)
    assert f(0.5, "炼气期1层", "筑基期1层") == pytest.approx(0.5 + 0.08)
    assert f(0.5, "筑基期1层", "筑基期1层", companions=2) == pytest.approx(0.5 - 0.05 * 2 ** 0.5)
    assert f(0.5, "筑基期1层", "筑基期1层", companions=10) == pytest.approx(0.5 - 0.05 * 10 ** 0.5)
    assert f(0.5, "筑基期1层", "筑基期1层", rescued=True) == pytest.approx(0.7)
    assert f(0.0, "元婴期初期", "炼气期1层") == ba.load()["flee"]["min"]
    assert f(0.99, "炼气期1层", "元婴期初期", rescued=True) == ba.load()["flee"]["max"]


def W(arche="阴鸷", severity=0, gkind="rob", kindness=50, profile=None, response="perfunctory", can_kill=True):
    return ba.outcome_weights(arche, severity, gkind, kindness, profile, response, can_kill, R(1))


def test_处置权重_性格底子_仇越重越狠():
    assert W("憨直") == {"release": 70 * 1.0, "rob": 5, "cripple": 25 * 0.5}
    low, high = W("阴鸷", severity=0), W("阴鸷", severity=100)
    assert high["kill"] > low["kill"] * 2 and high["cripple"] > low["cripple"] * 2 and high["release"] < low["release"]
    assert W("阴鸷", severity=100)["release"] >= 5 * ba.load()["severity_weight"]["release_floor"] - 1e-9


def test_处置权重_杀了我朋友的更想杀():
    assert W("阴鸷", 50, "kill")["kill"] == pytest.approx(W("阴鸷", 50, "rob")["kill"] * ba.load()["kill_grudge_bonus"])


def test_处置权重_不能杀就并入废修为():
    w = W("阴鸷", 50, can_kill=False)
    assert "kill" not in w and w["cripple"] == pytest.approx(W("阴鸷", 50)["cripple"] + W("阴鸷", 50)["kill"])
    assert "kill" not in W("憨直", can_kill=False)


def test_处置权重_玩家的回应():
    base, ap, pro, ref = W("阴鸷", 50), W("阴鸷", 50, response="apologize"), W("阴鸷", 50, response="provoke"), W("阴鸷", 50, response="refuse")
    assert ap["release"] > base["release"] * 2 and ap["kill"] < base["kill"] * 0.5
    assert pro["kill"] > base["kill"] * 1.5 and pro["release"] < base["release"] * 0.5
    assert ref["kill"] > base["kill"] and W("阴鸷", 50, response="perfunctory") == base


def test_处置权重_行为画像_善良的更愿意放():
    prof = {"lawful": 50, "impulse": 50, "loyalty": 50, "vengeful": 50, "capacity": 5, "deviance": 0}
    good, evil = W("阴鸷", 50, kindness=95, profile=prof), W("阴鸷", 50, kindness=5, profile=prof)
    assert good["release"] > evil["release"] * 2 and good["kill"] < evil["kill"] / 3


def test_买命概率_看性格_仇越重越难收买():
    assert ba.buyout_chance("贪财", 0) == 0.9 and ba.buyout_chance("迂腐", 0) == 0.2
    assert ba.buyout_chance("贪财", 100) == pytest.approx(0.45) and ba.buyout_chance("贪财", 200) == 0


# ---- 夹具 -------------------------------------------------------------------

async def mk_human(db, uid=H, city=CITY, realm="筑基期5层", stones=1000, **kw):
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        p = make_player(D, uid, stones=stones)
        p.name, p.lifespan, p.current_city, p.realm = f"人{uid}", 80, city, realm
        for k, v in kw.items():
            setattr(p, k, v)
        s.add(p)
        await s.commit()


async def mk_bot(db, uid, arche="阴鸷", city=CITY, realm="结丹期初期", profile=None, kindness=50, stones=1000, alive=True):
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        p = make_player(D, uid, stones=stones)
        p.name, p.is_bot, p.lifespan, p.current_city, p.realm, p.is_dead = f"机{uid[-3:]}", True, 80, city, realm, not alive
        s.add(p)
        prof = {"lawful": 50, "impulse": 50, "loyalty": 60, "vengeful": 50, "capacity": 30, "deviance": 0, **(profile or {})}
        s.add(D.BotPersonality(bot_id=uid, archetype=arche, tier="正常", home_city=city, kindness=kindness, profile=json.dumps(prof)))
        await s.commit()


async def hostile(db, uid="bot_00001", severity=50, kind="rob", style="直接", **bot_kw):
    """一个正蹲着玩家的机器人：窗口开着、已得知、敢动手。"""
    await mk_bot(db, uid, **bot_kw)
    await bg.on_offense(H, uid, kind, rng=Z(0.99), now=NOW - 10)
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        g = (await s.execute(select(D.BotGrudge).where(D.BotGrudge.holder_id == uid))).scalars().one()
        g.severity, g.style, g.known_at, g.window_until, g.kind = severity, style, NOW - 10, NOW + 100 * YEAR, kind
        await s.commit()


async def tie(db, a, b, kind="朋友", strength=70):
    from utils import bot_ties
    D = db["db_async"]
    x, y = bot_ties.pair(a, b)
    async with D.AsyncSessionLocal() as s:
        s.add(D.BotTie(a_id=x, b_id=y, kind=kind, strength=strength))
        await s.commit()


async def ambush(db, rng=None, context="explore", now=NOW):
    return await ba.maybe_ambush(H, context, rng or Z(0.0), now)


async def player(db, uid=H):
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        p = await s.get(D.Player, uid)
        return SimpleNamespace(**{c.key: getattr(p, c.key) for c in p.__table__.columns})


async def state(db, uid=H):
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        return await s.get(D.PlayerAmbush, uid)


async def enc_rows(db):
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        return list((await s.execute(select(D.BotEncounter))).scalars())


async def real_mode():
    await world_settings.set_values(mode="真实")


# ---- 门槛 -------------------------------------------------------------------

async def test_正常情况_有人蹲着_就会找上门(db):
    await mk_human(db)
    await hostile(db)
    out = await ambush(db)
    assert out and not out["aborted"] and out["leader"]["id"] == "bot_00001" and out["taunt"]
    assert out["reason"].endswith("劫走了你的灵石") and out["expires_at"] == NOW + 60
    (e,) = await enc_rows(db)
    assert (e.stage, e.target_id, e.leader_id, e.context) == ("choose", H, "bot_00001", "explore")


async def test_没人蹲着_什么都不发生(db):
    await mk_human(db)
    assert await ambush(db) is None and await enc_rows(db) == []


@pytest.mark.parametrize("mode,fires", [("幸福", False), ("正常", True), ("真实", True)])
async def test_幸福模式不拦路(db, mode, fires):
    await mk_human(db)
    await hostile(db)
    await world_settings.set_values(mode=mode)
    assert bool(await ambush(db)) is fires


async def test_管理员关了拦路开关_立刻生效(db):
    await mk_human(db)
    await hostile(db)
    await world_settings.set_values(ambush_enabled=False)
    assert await ambush(db) is None
    await world_settings.set_values(ambush_enabled=True)
    assert await ambush(db)


async def test_概率没过_不拦_也不开冷却(db):
    await mk_human(db)
    await hostile(db)
    assert await ambush(db, Z(0.99)) is None
    assert await state(db) is None
    assert await ambush(db, Z(0.0))


async def test_全局冷却_3游戏年_之内不再拦_之后可以(db):
    await mk_human(db)
    await hostile(db, "bot_00001")
    await hostile(db, "bot_00002")
    first = await ambush(db)
    assert first
    await ba.choose_flee(first["id"], Z(0.0), NOW)                              # 脱身，遭遇结束
    assert await ambush(db, now=NOW + 3 * YEAR - 10) is None, "冷却没过"
    assert await ambush(db, now=NOW + 3 * YEAR + 10), "冷却过了，另一个蹲守者（本人那个还在 1 年冷却外）"


async def test_同一个蹲守者对同一个玩家_至少隔1游戏年(db, monkeypatch):
    await mk_human(db)
    await hostile(db)
    cfg = copy.deepcopy(ba.load())
    cfg["global_cooldown_years"] = 0                                          # 去掉全局冷却，只看『每对』冷却
    monkeypatch.setattr(ba, "load", lambda: cfg)
    out = await ambush(db)
    await ba.choose_flee(out["id"], Z(0.0), NOW)
    assert await ambush(db, now=NOW + YEAR - 10) is None
    assert await ambush(db, now=NOW + YEAR + 10)


async def test_保护期内不拦(db):
    await mk_human(db)
    await hostile(db)
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        s.add(D.PlayerAmbush(player_id=H, last_at=0, protect_until=NOW + 100, count=0))
        await s.commit()
    assert await ambush(db) is None
    assert await ambush(db, now=NOW + 200)


async def test_已有遭遇进行中_不再叠加(db):
    await mk_human(db)
    await hostile(db, "bot_00001")
    await hostile(db, "bot_00002")
    assert await ambush(db)
    assert await ambush(db, now=NOW + 999 * YEAR) is None, "上一场没结束"


async def test_公共事件进行中_优先(db):
    await mk_human(db)
    await hostile(db)
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        s.add(D.PublicEvent(event_id="e1", event_type="spirit_rain", title="灵雨", started_at=NOW - 100, ends_at=NOW + 100, status="active"))
        s.add(D.PublicEventParticipant(event_id="e1", discord_id=H, activity="", joined_at=NOW - 50))
        await s.commit()
    assert await ambush(db) is None
    assert await ambush(db, now=NOW + 200), "事件结束后可以"


async def test_已坐化的真人_机器人_不拦(db):
    await mk_human(db, is_dead=True)
    await hostile(db)
    assert await ambush(db) is None
    assert await ba.maybe_ambush("bot_00001", "explore", Z(0.0), NOW) is None
    assert await ba.maybe_ambush("9999", "explore", Z(0.0), NOW) is None


async def test_谨慎的人没把握不来(db):
    await mk_human(db, realm="元婴期初期")
    await hostile(db, style="隐忍", realm="筑基期1层")
    assert await ambush(db) is None
    await hostile(db, "bot_00002", style="直接", realm="筑基期1层")
    assert (await ambush(db))["leader"]["id"] == "bot_00002"


async def test_潜伏的_窗口过了的_死了的蹲守者不来(db):
    await mk_human(db)
    await hostile(db, "bot_00001")
    await hostile(db, "bot_00002")
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        (await s.execute(select(D.BotGrudge).where(D.BotGrudge.holder_id == "bot_00001"))).scalars().one().state = "dormant"
        (await s.get(D.Player, "bot_00002")).is_dead = True
        await s.commit()
    assert await ambush(db) is None


async def test_概率_比你强的更容易找上门(db):
    await mk_human(db, realm="筑基期5层")
    await hostile(db, realm="元婴期初期")
    hits = 0
    for seed in range(400):
        D = db["db_async"]
        async with D.AsyncSessionLocal() as s:                                     # 重置状态，反复掷骰
            for t in (await s.execute(select(D.BotEncounter))).scalars().all():
                await s.delete(t)
            for t in (await s.execute(select(D.PlayerAmbush))).scalars().all():
                await s.delete(t)
            for g in (await s.execute(select(D.BotGrudge))).scalars().all():
                g.last_ambush_at = 0
            await s.commit()
        hits += bool(await ba.maybe_ambush(H, "explore", R(seed), NOW))
    assert abs(hits / 400 - ba.load()["chance"]["stronger"]) < 0.08


# ---- 建遭遇 -----------------------------------------------------------------

async def test_建遭遇_机器人赶到玩家所在的城_记冷却_记蹲守时间(db):
    await mk_human(db, city="万妖岭")
    await hostile(db, city=CITY)
    out = await ambush(db)
    assert out
    assert (await player(db, "bot_00001")).current_city == "万妖岭"
    st = await state(db)
    assert st.last_at == NOW and st.count == 1
    assert (await bg.grudges_of("bot_00001"))[0]["last_ambush_at"] == NOW


async def test_重义气的叫上结拜和朋友一起来_只叫活着的_人数不设上限(db):
    await mk_human(db)
    await hostile(db, "bot_00001", profile={"loyalty": 100})
    for i in range(2, 22):
        await mk_bot(db, f"bot_{i:05d}", alive=(i != 3), profile={"loyalty": 100})
        await tie(db, "bot_00001", f"bot_{i:05d}", "结拜" if i < 6 else "朋友")
    out = await ambush(db)
    ids = [c["id"] for c in out["companions"]]
    assert len(ids) > 10 and "bot_00003" not in ids, "Z(0.0) 下每个活着的亲友都会来，没有人数上限"
    assert len(set(ids)) == len(ids)
    for cid in ids:
        assert (await player(db, cid)).current_city == CITY
    (e,) = await enc_rows(db)
    assert json.loads(e.companions) == ids


async def test_组团_同城爱打抱不平的路人和同样记恨你的蹲守者也会加入(db):
    await mk_human(db)
    await hostile(db, "bot_00001")
    await hostile(db, "bot_00002", severity=20)                                   # 另一个也恨你的蹲守者
    await mk_bot(db, "bot_00003", "豪爽", kindness=90, profile={"loyalty": 90})    # 爱打抱不平的路人
    await mk_bot(db, "bot_00004", "阴鸷", kindness=10, profile={"loyalty": 10, "impulse": 10})   # 事不关己
    await mk_bot(db, "bot_00005", "豪爽", city="落云城", kindness=90, profile={"loyalty": 90})   # 不在同城的好人
    out = await ambush(db)
    assert out["leader"]["id"] == "bot_00001"
    ids = {c["id"] for c in out["companions"]}
    assert ids == {"bot_00002", "bot_00003"}


def test_同伴战力加成递减():
    m = ba.companion_multiplier
    assert m(0) == 1 and m(1) == pytest.approx(1.25)
    assert m(2) - m(1) > m(10) - m(9) > 0, "人越多，每多一个人的加成越小"
    assert m(10) < 1 + 0.25 * 10 / 1.5


async def test_没人叫就一个人来(db):
    await mk_human(db)
    await hostile(db, profile={"loyalty": 100})
    await mk_bot(db, "bot_00002")
    await tie(db, "bot_00001", "bot_00002", "朋友")
    assert (await ba.maybe_ambush(H, "explore", Seq(0.0, 0.99), NOW))["companions"] == []


async def test_结拜兄弟碰巧在同城_比拦路者强_拦路者悻悻而去_也算被拦过(db):
    await mk_human(db)
    await hostile(db, realm="筑基期5层")
    await mk_bot(db, "bot_00009", "豪爽", realm="结丹期初期", profile={"loyalty": 100})
    await tie(db, H, "bot_00009", "结拜", 100)
    out = await ambush(db)
    assert out["aborted"] and out["rescuer"]["id"] == "bot_00009" and out["leader"]["id"] == "bot_00001"
    assert await enc_rows(db) == [] and (await state(db)).last_at == NOW


async def test_结拜兄弟比拦路者弱_赶来帮忙_逃得掉的概率更大(db):
    await mk_human(db)
    await hostile(db, realm="结丹期初期")
    await mk_bot(db, "bot_00009", "豪爽", realm="炼气期1层", profile={"loyalty": 100})
    await tie(db, H, "bot_00009", "结拜", 100)
    out = await ambush(db)
    assert not out["aborted"] and out["rescuer"]["id"] == "bot_00009"
    assert "援手" in av.encounter_embed(out).fields[-1].name


async def test_朋友不在同城_不会来(db):
    await mk_human(db)
    await hostile(db)
    await mk_bot(db, "bot_00009", city="落云城", realm="元婴期初期")
    await tie(db, H, "bot_00009", "结拜", 100)
    out = await ambush(db)
    assert out and not out["aborted"] and out["rescuer"] is None


async def test_拦路出错只记警告_不影响探险(db, monkeypatch, caplog):
    await mk_human(db)

    async def boom(*a, **k):
        raise RuntimeError("库坏了")
    monkeypatch.setattr(bg, "candidates_against", boom)
    assert await ba.maybe_ambush(H, "explore") is None
    assert "拦路判定失败" in caplog.text


# ---- 逃跑 -------------------------------------------------------------------

async def started(db, **hostile_kw):
    await mk_human(db)
    await hostile(db, **hostile_kw)
    return await ambush(db)


async def test_逃跑成功_脱身_仇恨还在_遭遇结束(db):
    out = await started(db)
    res = await ba.choose_flee(out["id"], Z(0.0), NOW + 5)
    assert res["stage"] == "escaped" and 0.05 <= res["rate"] <= 0.9
    assert (await ba.get_encounter(out["id"]))["stage"] == "done"
    assert len(await bg.grudges_of("bot_00001")) == 1


async def test_逃跑失败_进入交涉_带买命价和要个交代的话(db):
    out = await started(db)
    res = await ba.choose_flee(out["id"], Z(0.999), NOW + 5)
    cfg = ba.load()
    assert res["stage"] == "bargain" and res["demand"] and res["expires_at"] == NOW + 5 + cfg["timeouts"]["bargain_seconds"]
    assert res["price"] == min(int(1000 * cfg["buyout"]["share"]), cfg["buyout"]["cap"]) == 400
    e = await ba.get_encounter(out["id"])
    assert e["stage"] == "bargain" and e["price"] == 400


async def test_点两次按钮_第二次是gone(db):
    out = await started(db)
    assert (await ba.choose_flee(out["id"], Z(0.0)))["stage"] == "escaped"
    assert (await ba.choose_flee(out["id"], Z(0.0)))["stage"] == "gone"
    assert (await ba.choose_fight(out["id"], Z(0.0)))["stage"] == "gone"
    assert (await ba.respond(out["id"], "apologize"))["stage"] == "gone"
    assert (await ba.choose_flee("不存在", Z(0.0)))["stage"] == "gone"


async def test_拦路者在遭遇中途死了_遭遇作废(db):
    out = await started(db)
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        (await s.get(D.Player, "bot_00001")).is_dead = True
        await s.commit()
    assert (await ba.choose_flee(out["id"], Z(0.0)))["stage"] == "gone"
    assert (await ba.get_encounter(out["id"]))["result"] == "gone"


async def test_同伴越多越难逃_但递减():
    f = lambda n: ba.flee_rate(0.5, "筑基期1层", "筑基期1层", n)           # noqa: E731
    assert f(0) > f(1) > f(2) > f(10)
    assert f(1) - f(2) > f(9) - f(10), "递减"
    assert ba.load()["companions"]["max"] is None, "同伴不设上限（用户定）"


# ---- 迎战 -------------------------------------------------------------------

def powers(monkeypatch, mine, theirs):
    from utils import combat

    async def fake(player):
        return mine if not player.get("is_bot") else theirs
    monkeypatch.setattr(combat, "calc_power", fake)

    async def one(player):
        return 1.0
    from utils import bot_combat
    monkeypatch.setattr(bot_combat, "power_multiplier", one)


async def test_迎战赢了_遭遇结束_由玩家处置(db, monkeypatch):
    out = await started(db)
    powers(monkeypatch, 1000, 10)
    res = await ba.choose_fight(out["id"], R(1))
    assert res["stage"] == "won" and res["leader"] == "bot_00001" and (await ba.get_encounter(out["id"]))["result"] == "won"


async def test_迎战输了_进入交涉_带上双方战力(db, monkeypatch):
    out = await started(db)
    powers(monkeypatch, 10, 1000)
    res = await ba.choose_fight(out["id"], R(1))
    assert res["stage"] == "bargain" and res["powers"][0] < res["powers"][1] and res["price"] > 0


async def test_同伴和援手都影响战力(db, monkeypatch):
    out = await started(db)
    powers(monkeypatch, 101, 100)                                   # 浮动相同时刚好略胜
    D = db["db_async"]

    async def reopen(companions=(), rescuer=""):
        async with D.AsyncSessionLocal() as s:
            e = await s.get(D.BotEncounter, out["id"])
            e.stage, e.companions, e.rescuer_id = "choose", json.dumps(list(companions)), rescuer
            await s.commit()
    await reopen()
    assert (await ba.choose_fight(out["id"], Z(0.5)))["stage"] == "won"
    await reopen(companions=["bot_00002", "bot_00003"])
    assert (await ba.choose_fight(out["id"], Z(0.5)))["stage"] == "bargain", "对方带了两个同伴，战力 ×1.5"
    await reopen(companions=["bot_00002", "bot_00003"], rescuer="bot_00009")
    powers(monkeypatch, 130, 100)
    assert (await ba.choose_fight(out["id"], Z(0.5)))["stage"] == "won", "朋友赶来，战力 ×1.2：130×1.2 > 100×1.5"


# ---- 交涉与处置 -------------------------------------------------------------

async def bargain(db, arche="阴鸷", severity=50, **kw):
    out = await started(db, arche=arche, severity=severity, **kw)
    res = await ba.choose_flee(out["id"], Z(0.999), NOW + 5)
    assert res["stage"] == "bargain"
    return out["id"]


def pinned(monkeypatch, **weights):
    """把阴鸷的处置权重钉成指定的几项（响应倍数仍然生效）。"""
    cfg = copy.deepcopy(ba.load())
    cfg["outcome"]["阴鸷"] = {"release": 0, **weights}
    monkeypatch.setattr(ba, "load", lambda: cfg)


async def test_处置_放走_什么都不丢(db, monkeypatch):
    enc = await bargain(db)
    pinned(monkeypatch, release=1)
    res = await ba.respond(enc, "apologize", R(1), NOW + 10)
    assert res["stage"] == "done" and res["outcome"] == "release" and res["amount"] == 0 and res["line"]
    p = await player(db)
    assert p.spirit_stones == 1000 and not p.is_dead


async def test_处置_劫财_按比例有上限_给了拦路者(db, monkeypatch):
    enc = await bargain(db)
    pinned(monkeypatch, rob=1)
    res = await ba.respond(enc, "refuse", R(1), NOW + 10)
    assert res["outcome"] == "rob" and res["amount"] == 300                       # 1000 × 30%
    assert (await player(db)).spirit_stones == 700 and (await player(db, "bot_00001")).spirit_stones == 1300


async def test_处置_劫财_有上限(db, monkeypatch):
    await mk_human(db, stones=100_000)
    await hostile(db)
    out = await ambush(db)
    await ba.choose_flee(out["id"], Z(0.999), NOW + 5)
    pinned(monkeypatch, rob=1)
    res = await ba.respond(out["id"], "refuse", R(1), NOW + 10)
    assert res["amount"] == ba.load()["rob"]["cap"]


async def test_处置_身上没钱可劫_就放走(db, monkeypatch):
    await mk_human(db, stones=0)
    await hostile(db)
    out = await ambush(db)
    await ba.choose_flee(out["id"], Z(0.999), NOW + 5)
    pinned(monkeypatch, rob=1)
    assert (await ba.respond(out["id"], "refuse", R(1), NOW + 10))["outcome"] == "release"


async def test_处置_废修为_归零_送到别的城_有保护期(db, monkeypatch):
    enc = await bargain(db)
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        (await s.get(D.Player, H)).cultivation = 77
        await s.commit()
    pinned(monkeypatch, cripple=1)
    res = await ba.respond(enc, "refuse", R(1), NOW + 10)
    p = await player(db)
    assert res["outcome"] == "cripple" and p.cultivation == 0 and p.current_city != CITY and res["new_city"] == p.current_city
    assert not p.is_dead and (await state(db)).protect_until == pytest.approx(NOW + 10 + 1 * 86400)
    assert await ba.maybe_ambush(H, "explore", Z(0.0), NOW + 3600) is None, "保护期内不再拦"


async def test_处置_保护期按管理员设置(db, monkeypatch):
    await world_settings.set_values(death_protect_days=3.0)
    enc = await bargain(db)
    pinned(monkeypatch, cripple=1)
    await ba.respond(enc, "refuse", R(1), NOW + 10)
    assert (await state(db)).protect_until == pytest.approx(NOW + 10 + 3 * 86400)


async def test_处置_杀_真实模式_角色坐化_记前世仇人_朋友替他出头(db, monkeypatch):
    await real_mode()
    await mk_human(db, created_at=4321.0)
    await hostile(db)
    await mk_bot(db, "bot_00002", "豪爽", city="落云城", profile={"loyalty": 100})       # 玩家的结拜兄弟，不在同城，来不了现场
    await tie(db, H, "bot_00002", "结拜", 100)
    real = bg.on_offense
    monkeypatch.setattr(bg, "on_offense", lambda a, v, k, **kw: real(a, v, k, rng=Z(0.0), now=NOW + 10))
    out = await ambush(db)
    assert out and not out["aborted"]
    await ba.choose_flee(out["id"], Z(0.999), NOW + 5)
    pinned(monkeypatch, kill=1, release=0)
    res = await ba.respond(out["id"], "provoke", R(1), NOW + 10)
    p = await player(db)
    assert res["outcome"] == "kill" and res["killed"] and p.is_dead and p.lifespan == 0
    assert res["amount"] == 300 and p.spirit_stones == 700, "杀之前先搜走一份"
    (e,) = await bg.previous_enemies(H)
    assert e["enemy"] == "bot_00001" and e["life"] == 4321 and e["reason"] == "机001杀害了你"
    assert (await state(db)).protect_until > NOW
    (g,) = [g for g in await bg.grudges_of("bot_00002")]
    assert g["target"] == "bot_00001" and g["reason"] == "机001杀害了你的结拜兄弟人1001", "连环复仇：玩家的兄弟记下了这笔账"


async def test_处置_杀_正常模式降级成废修为(db, monkeypatch):
    enc = await bargain(db)                                 # 默认正常模式
    pinned(monkeypatch, kill=1)
    res = await ba.respond(enc, "provoke", R(1), NOW + 10)
    assert res["outcome"] == "cripple" and not res["killed"] and not (await player(db)).is_dead


async def test_处置_杀_新手受保护_只能废修为(db, monkeypatch):
    await real_mode()
    await mk_human(db, realm="炼气期9层")
    await hostile(db)
    out = await ambush(db)
    await ba.choose_flee(out["id"], Z(0.999), NOW + 5)
    pinned(monkeypatch, kill=1)
    res = await ba.respond(out["id"], "provoke", R(1), NOW + 10)
    assert res["outcome"] == "cripple" and not (await player(db)).is_dead


async def test_处置_配置里关掉can_kill_humans_也不杀(db, monkeypatch):
    await real_mode()
    enc = await bargain(db)
    pinned(monkeypatch, kill=1)
    from utils import bot_economy as be
    cfg = be.load_config()
    cfg["combat"]["can_kill_humans"] = False
    monkeypatch.setattr(be, "load_config", lambda: copy.deepcopy(cfg))
    assert (await ba.respond(enc, "provoke", R(1), NOW + 10))["outcome"] == "cripple"


async def test_处置_回应真的影响分布(db):
    cfg = ba.load()
    prof = None
    def dist(response, n=3000):
        rng, out = R(5), {"release": 0, "rob": 0, "cripple": 0, "kill": 0}
        for _ in range(n):
            w = ba.outcome_weights("阴鸷", 50, "rob", 50, prof, response, True, rng, cfg)
            out[rng.choices(list(w), weights=list(w.values()))[0]] += 1
        return out
    sorry, defiant = dist("apologize"), dist("provoke")
    assert sorry["release"] > defiant["release"] * 4 and defiant["kill"] > sorry["kill"] * 3


async def test_买命_接受_灵石转给对方_放走(db):
    enc = await bargain(db, arche="贪财")
    res = await ba.respond(enc, "buyout", Z(0.0), NOW + 10)
    assert res["outcome"] == "release" and res["bought"] and res["amount"] == 400
    assert (await player(db)).spirit_stones == 600 and (await player(db, "bot_00001")).spirit_stones == 1400


async def test_买命_被拒_钱没动_继续按敷衍处置(db, monkeypatch):
    enc = await bargain(db, arche="阴鸷")
    pinned(monkeypatch, cripple=1)
    res = await ba.respond(enc, "buyout", Z(0.99), NOW + 10)
    assert res["outcome"] == "cripple" and not res["bought"]
    assert (await player(db)).spirit_stones == 1000


async def test_买命_灵石不够_留在交涉阶段可以改选(db):
    enc = await bargain(db, arche="贪财")
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        (await s.get(D.Player, H)).spirit_stones = 100
        await s.commit()
    res = await ba.respond(enc, "buyout", Z(0.0), NOW + 10)
    assert res["stage"] == "bargain" and "灵石不够" in res["error"]
    assert (await ba.get_encounter(enc))["stage"] == "bargain"
    assert (await ba.respond(enc, "apologize", Z(0.0), NOW + 11))["stage"] == "done"


async def test_没钱的人没有买命价(db):
    await mk_human(db, stones=0)
    await hostile(db)
    out = await ambush(db)
    assert (await ba.choose_flee(out["id"], Z(0.999), NOW + 5))["price"] == 0
    assert (await ba.respond(out["id"], "buyout", Z(0.0), NOW + 6))["stage"] == "bargain"


async def test_回应不认识_交涉没结束(db):
    enc = await bargain(db)
    assert (await ba.respond(enc, "跳舞"))["stage"] == "error"
    assert (await ba.get_encounter(enc))["stage"] == "bargain"


async def test_处置的副作用_记忆_仇人列表_传闻(db, monkeypatch):
    from utils import bot_memory
    enc = await bargain(db)
    pinned(monkeypatch, rob=1)
    await ba.respond(enc, "refuse", R(1), NOW + 10)
    mem = await bot_memory.recall(H, "bot_00001")
    assert mem["defeated"][0].extra == "rob"
    (g,) = [g for g in await bg.grudges_of(H) if g["target"] == "bot_00001"]
    assert g["kind"] == "rob"
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        kinds = {r.kind for r in (await s.execute(select(D.Rumor))).scalars()}
    assert "bot_robs_human" in kinds


# ---- 超时 / 重启 ------------------------------------------------------------

async def test_超时_选择阶段算逃跑_交涉阶段算拒绝(db, monkeypatch):
    out = await started(db)
    assert await ba.process_expired(NOW + 30) == [], "还没到 1 分钟"
    items = await ba.process_expired(NOW + 61, Z(0.0))
    assert len(items) == 1 and items[0]["result"]["stage"] == "escaped" and items[0]["timed_out"]
    enc = await bargain_from_scratch(db)
    pinned(monkeypatch, cripple=1)
    items = await ba.process_expired(NOW + 5 + 61, R(1))
    assert items[0]["result"]["stage"] == "done" and items[0]["result"]["outcome"] == "cripple"
    assert (await ba.get_encounter(enc))["stage"] == "done"


async def bargain_from_scratch(db):
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        for t in (await s.execute(select(D.BotEncounter))).scalars().all():
            await s.delete(t)
        for t in (await s.execute(select(D.PlayerAmbush))).scalars().all():
            await s.delete(t)
        for g in (await s.execute(select(D.BotGrudge))).scalars().all():
            g.last_ambush_at = 0
        await s.commit()
    out = await ambush(db)
    assert out
    assert (await ba.choose_flee(out["id"], Z(0.999), NOW + 5))["stage"] == "bargain"
    return out["id"]


async def test_收尾卡在处理中的遭遇(db):
    out = await started(db)
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        e = await s.get(D.BotEncounter, out["id"])
        e.stage, e.expires_at = "resolving", NOW - 1000
        await s.commit()
    assert await ba.sweep_stuck(NOW) == 1
    assert (await ba.get_encounter(out["id"]))["result"] == "stuck"
    assert await ba.sweep_stuck(NOW) == 0


async def test_清理机器人_以它为拦路者的遭遇删掉(db):
    from utils import bot_world
    out = await started(db)
    res = await bot_world.remove_bots(["bot_00001"])
    assert res["rows"]["bot_encounters"] == 1 and await enc_rows(db) == []
    assert (await ba.choose_flee(out["id"], Z(0.0)))["stage"] == "gone"


async def test_转世_进行中的遭遇作废_保护期保留(db):
    from utils.character_create_logic import commit_character
    out = await started(db)
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        (await s.get(D.Player, H)).is_dead = True
        s.add(D.PlayerAmbush(player_id=H, last_at=NOW, protect_until=NOW + 999, count=1)) if await s.get(D.PlayerAmbush, H) is None else None
        st = await s.get(D.PlayerAmbush, H)
        st.protect_until = NOW + 999
        await s.commit()
    assert await commit_character(H, "新名字", "男", {})
    assert await enc_rows(db) == []
    assert (await state(db)).protect_until == NOW + 999, "刚被杀的新角色也受保护"


# ---- 界面 -------------------------------------------------------------------

async def test_钩子_没人找上门_返回False_不发消息(db):
    await mk_human(db)
    c = FakeContext(user_id=1001)
    assert await av.run_hook(c.send, c.author, "explore") is False and c.messages == []


_real_maybe = ba.maybe_ambush


async def _ambush_now(uid, ctx):
    return await _real_maybe(uid, ctx, Z(0.0), NOW)


async def test_钩子_找上门_发消息带按钮_记下消息位置(db, monkeypatch):
    await mk_human(db)
    await hostile(db)
    monkeypatch.setattr(ba, "maybe_ambush", _ambush_now)
    sent = []

    async def send(content=None, **kw):
        sent.append((content, kw))
        return SimpleNamespace(id=555, channel=SimpleNamespace(id=777))
    c = FakeContext(user_id=1001)
    assert await av.run_hook(send, c.author, "explore") is True
    content, kw = sent[0]
    assert content == "<@1001>" and kw["embed"].title.startswith("⚔️ 拦路") and [b.label for b in kw["view"].children] == ["🏃 逃跑", "⚔️ 迎战"]
    (e,) = await enc_rows(db)
    assert (e.channel_id, e.message_id) == ("777", "555")


async def test_钩子_援手赶到_发一条化解的消息(db, monkeypatch):
    await mk_human(db)
    await hostile(db, realm="筑基期5层")
    await mk_bot(db, "bot_00009", "豪爽", realm="结丹期初期", profile={"loyalty": 100})
    await tie(db, H, "bot_00009", "结拜", 100)
    monkeypatch.setattr(ba, "maybe_ambush", _ambush_now)
    c = FakeContext(user_id=1001)
    assert await av.run_hook(c.send, c.author, "explore") is True
    assert c.said("悻悻而去") and c.said("机009")


async def test_面板_别人点不动(db):
    view = av.AmbushView("x", SimpleNamespace(id=1001), "机001")
    i = FakeInteraction(user_id=7)
    assert await view.interaction_check(i) is False


async def press(view, label_part, interaction):
    await next(c for c in view.children if label_part in c.label).callback(interaction)


async def test_面板_逃跑成功_换成脱身消息_收起按钮(db, monkeypatch):
    await mk_human(db)
    await hostile(db)
    out = await _ambush_now("1001", "explore")
    me = FakeInteraction(user_id=1001)
    orig = ba.choose_flee
    monkeypatch.setattr(ba, "choose_flee", lambda enc_id, rng=None, now=None: orig(enc_id, Z(0.0), NOW + 5))
    await press(av.AmbushView(out["id"], me.user, "机001"), "逃跑", me)
    assert me.edited[-1].view is None and "脱身" in me.edited[-1].embed.title


async def test_面板_逃跑失败_出现交涉面板_点回应_收尾(db, monkeypatch):
    await mk_human(db)
    await hostile(db)
    out = await _ambush_now("1001", "explore")
    me = FakeInteraction(user_id=1001)
    orig = ba.choose_flee
    monkeypatch.setattr(ba, "choose_flee", lambda enc_id, rng=None, now=None: orig(enc_id, Z(0.999), NOW + 5))
    await next(c for c in av.AmbushView(out["id"], me.user, "机001").children if "逃跑" in c.label).callback(me)
    msg = me.edited[-1]
    assert "交涉" in msg.embed.title and isinstance(msg.view, av.BargainView)
    labels = [c.label for c in msg.view.children]
    assert labels[:4] == ["诚恳道歉", "敷衍认错", "拒绝道歉", "继续挑衅"] and labels[4].startswith("💰 买命（400）")
    orig_resp = ba.respond
    monkeypatch.setattr(ba, "respond", lambda enc_id, key, rng=None, now=None: orig_resp(enc_id, key, R(1), NOW + 10))
    pinned(monkeypatch, release=1)
    me2 = FakeInteraction(user_id=1001)
    await next(c for c in msg.view.children if c.label == "诚恳道歉").callback(me2)
    assert me2.edited[-1].view is None and "拦路了结" in me2.edited[-1].embed.title


async def test_面板_买命钱不够_提示_面板还在(db, monkeypatch):
    await mk_human(db)
    await hostile(db, arche="贪财")
    out = await _ambush_now("1001", "explore")
    await ba.choose_flee(out["id"], Z(0.999), NOW + 5)
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        (await s.get(D.Player, H)).spirit_stones = 1
        await s.commit()
    me = FakeInteraction(user_id=1001)
    view = av.BargainView(out["id"], me.user, "机001", 400)
    await next(c for c in view.children if c.label.startswith("💰")).callback(me)
    assert me.followup.said("灵石不够") and me.edited == []


async def test_面板_迎战赢了_给战后面板(db, monkeypatch):
    await mk_human(db)
    await hostile(db)
    out = await _ambush_now("1001", "explore")
    powers(monkeypatch, 1000, 10)
    me = FakeInteraction(user_id=1001)
    await next(c for c in av.AmbushView(out["id"], me.user, "机001").children if "迎战" in c.label).callback(me)
    assert "击退" in me.edited[-1].embed.title
    from utils.views.combat import VictoryActionView
    assert isinstance(me.followup.messages[-1].view, VictoryActionView)


def test_结果文案():
    leader = "机001"
    assert "脱身" in av.outcome_embed({"stage": "escaped", "rate": 0.4, "line": "哼"}, leader).title
    assert "击退" in av.outcome_embed({"stage": "won", "mine": 1, "theirs": 0}, leader).title
    killed = av.outcome_embed({"stage": "done", "outcome": "kill", "amount": 30, "killed": True, "line": "再见"}, leader)
    assert "坐化" in killed.description and "30" in killed.description
    bought = av.outcome_embed({"stage": "done", "outcome": "release", "amount": 400, "bought": True, "line": ""}, leader)
    assert "买命" in bought.description or "奉上灵石" in bought.description
    assert "已经结束" in av.outcome_embed({"stage": "gone"}, leader).description


# ---- 后台循环 ---------------------------------------------------------------

async def test_后台循环_超时收尾后编辑原消息_并发一条结果(db):
    from cogs.ambush import AmbushCog
    out = await started(db)
    await ba.set_message(out["id"], 777, 555)
    edits, sends = [], []

    class Msg:
        async def edit(self, **kw):
            edits.append(kw)

    class Chan:
        async def fetch_message(self, mid):
            assert mid == 555
            return Msg()

        async def send(self, content=None, **kw):
            sends.append((content, kw))

    cog = AmbushCog(SimpleNamespace(get_channel=lambda cid: Chan() if cid == 777 else None))
    items = await ba.process_expired(NOW + 61, Z(0.0))
    await cog._announce(items[0])
    assert edits and edits[0]["view"] is None and sends and "<@1001>" in sends[0][0]


async def test_后台循环_找不到频道_静静跳过(db):
    from cogs.ambush import AmbushCog
    out = await started(db)
    cog = AmbushCog(SimpleNamespace(get_channel=lambda cid: None))
    items = await ba.process_expired(NOW + 61, Z(0.0))
    await cog._announce(items[0])
    await ba.set_message(out["id"], 1, 2)
    await cog._announce({"encounter": {"channel_id": "", "id": "x"}, "result": {"stage": "gone"}})


# ---- 补：变异测试里发现的漏洞 -------------------------------------------------

async def test_已在别的遭遇里的蹲守者_不会同时去拦第二个人(db):
    await mk_human(db, "1001")
    await mk_human(db, "1002")
    await mk_bot(db, "bot_00001")
    for uid in ("1001", "1002"):
        await bg.on_offense(uid, "bot_00001", "rob", rng=Z(0.99), now=NOW - 10)
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        for g in (await s.execute(select(D.BotGrudge))).scalars():
            g.style, g.known_at, g.window_until = "直接", NOW - 10, NOW + 100 * YEAR
        await s.commit()
    assert await ba.maybe_ambush("1001", "explore", Z(0.0), NOW)
    assert await ba.maybe_ambush("1002", "explore", Z(0.0), NOW) is None, "它正忙着拦 1001"


async def test_不在同城的蹲守者_概率打对折(db):
    """同阶 / 比你强时基础概率 0.65：掷 0.5 同城会来，不同城（×0.5 = 0.325）不来。"""
    await mk_human(db, city="万妖岭")
    await hostile(db, city=CITY)
    assert await ba.maybe_ambush(H, "explore", Seq(0.5), NOW) is None
    await mk_human(db, "1002", city=CITY)
    await mk_bot(db, "bot_00002", city=CITY)
    await bg.on_offense("1002", "bot_00002", "rob", rng=Z(0.99), now=NOW - 10)
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        for g in (await s.execute(select(D.BotGrudge).where(D.BotGrudge.holder_id == "bot_00002"))).scalars():
            g.style, g.known_at, g.window_until = "直接", NOW - 10, NOW + 100 * YEAR
        await s.commit()
    assert await ba.maybe_ambush("1002", "explore", Seq(0.5), NOW)


async def test_迎战_战力相同算输(db, monkeypatch):
    out = await started(db)
    powers(monkeypatch, 100, 100)
    assert (await ba.choose_fight(out["id"], Z(0.5)))["stage"] == "bargain"


async def test_逃跑_按成功率掷骰_而不是只要掷到0(db):
    from utils.combat import calc_escape_rate
    out = await started(db)
    rate = ba.flee_rate(await calc_escape_rate((await get_p())), "结丹期初期", "筑基期5层")
    assert 0.2 < rate < 0.9
    assert (await ba.choose_flee(out["id"], Z(rate - 0.01), NOW + 5))["stage"] == "escaped"
    out2 = await restart(db)
    assert (await ba.choose_flee(out2["id"], Z(rate + 0.01), NOW + 5))["stage"] == "bargain"


async def get_p():
    from utils.player import get_player
    return await get_player(H)


async def restart(db):
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        for t in (await s.execute(select(D.BotEncounter))).scalars().all():
            await s.delete(t)
        for t in (await s.execute(select(D.PlayerAmbush))).scalars().all():
            await s.delete(t)
        for g in (await s.execute(select(D.BotGrudge))).scalars().all():
            g.last_ambush_at = 0
        await s.commit()
    out = await ambush(db)
    assert out
    return out


async def test_买命价有上限(db):
    await mk_human(db, stones=100_000)
    await hostile(db)
    out = await ambush(db)
    assert (await ba.choose_flee(out["id"], Z(0.999), NOW + 5))["price"] == ba.load()["buyout"]["cap"]


async def test_买命被拒_当作敷衍而不是拒绝(db, monkeypatch):
    enc = await bargain(db, arche="阴鸷")
    seen = []
    real = ba.outcome_weights

    def spy(*a, **k):
        seen.append(a[5])
        return real(*a, **k)
    monkeypatch.setattr(ba, "outcome_weights", spy)
    await ba.respond(enc, "buyout", Z(0.99), NOW + 10)
    assert seen == ["perfunctory"]


async def test_废修为也进玩家的仇人列表(db, monkeypatch):
    enc = await bargain(db)
    pinned(monkeypatch, cripple=1)
    await ba.respond(enc, "refuse", R(1), NOW + 10)
    mine = [g for g in await bg.grudges_of(H) if g["target"] == "bot_00001"]
    assert mine and mine[0]["kind"] == "cripple" and mine[0]["reason"] == "机001废了你的修为"


async def test_处理中的遭遇_不到十分钟不算卡死(db):
    out = await started(db)
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        e = await s.get(D.BotEncounter, out["id"])
        e.stage, e.expires_at = "resolving", NOW - 100
        await s.commit()
    assert await ba.sweep_stuck(NOW) == 0, "才过去 100 秒，可能还在处理"
    assert await ba.sweep_stuck(NOW + 1000) == 1


async def test_清理机器人_援手被清理时遭遇也作废(db):
    from utils import bot_world
    out = await started(db)
    await mk_bot(db, "bot_00009")
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        (await s.get(D.BotEncounter, out["id"])).rescuer_id = "bot_00009"
        await s.commit()
    assert (await bot_world.remove_bots(["bot_00009"]))["rows"]["bot_encounters"] == 1


# ---- 野外动作的钩子 ---------------------------------------------------------

def spy_hook(monkeypatch, result):
    calls = []

    async def hook(send, user, context):
        calls.append(context)
        return result
    monkeypatch.setattr("utils.views.ambush.run_hook", hook)
    return calls


async def test_探险命令_被拦就不再出探险事件(db, monkeypatch):
    from cogs.explore import ExploreCog
    await mk_human(db, "1")
    calls = spy_hook(monkeypatch, True)
    ctx = FakeContext(user_id=1)
    cog = ExploreCog(bot=None)
    await cog.explore.callback(cog, ctx)
    assert calls == ["explore"] and ctx.messages == []


async def test_继续探险按钮_被拦也不再出事件(db, monkeypatch):
    from cogs.explore import ExploreCog, ExploreResultView
    from tests.discord_fakes import FakeUser
    await mk_human(db, "1")
    calls = spy_hook(monkeypatch, True)
    it = FakeInteraction(user_id=1)
    await ExploreResultView(FakeUser(id=1), ExploreCog(bot=None)).continue_explore.callback(it)
    assert calls == ["explore"] and it.followup.messages == []


async def test_前往秘地_触发拦路_去普通城市不触发(db, monkeypatch):
    from cogs.travel import TravelCog
    await mk_human(db, "1001", realm="结丹期初期")
    calls = spy_hook(monkeypatch, False)
    cog = TravelCog(SimpleNamespace(cogs={}))
    secret = SPECIAL_REGIONS[0]["name"]
    await cog.travel.callback(cog, FakeContext(user_id=1001), city_name=secret)
    assert calls == ["travel_wild"]
    calls.clear()
    await cog.travel.callback(cog, FakeContext(user_id=1001), city_name="落云城")
    assert calls == []


async def test_开始采集_触发拦路(db, monkeypatch):
    from utils.views.gathering import GatherView
    await mk_human(db, "1001")
    calls = spy_hook(monkeypatch, False)
    v = GatherView(FakeInteraction(1001).user, None, {"lifespan": 100}, "采药", "百草谷")
    await next(b for b in v.children if b.years == 1).callback(FakeInteraction(1001))
    assert calls == ["gathering"]


async def companions_of(db, leader, rng, others=None):
    return await ba._pick_companions(leader, H, CITY, rng, ba.load(), others)


async def test_组团_亲友是否加入看关系权重和是否同城(db):
    await mk_human(db)
    await hostile(db, "bot_00001")
    await mk_bot(db, "bot_00002", profile={"loyalty": 50})                     # 朋友：0.5 × 0.7 × 1.0 = 0.35
    await mk_bot(db, "bot_00003", profile={"loyalty": 50})                     # 结拜：0.5 × 1.0 × 1.0 = 0.5
    await tie(db, "bot_00001", "bot_00002", "朋友")
    await tie(db, "bot_00001", "bot_00003", "结拜")
    assert await companions_of(db, "bot_00001", Z(0.4)) == ["bot_00003"], "掷 0.4：结拜(0.5)来，朋友(0.35)不来"
    assert set(await companions_of(db, "bot_00001", Z(0.3))) == {"bot_00002", "bot_00003"}


async def test_组团_不同城的亲友加入概率打折(db):
    await mk_human(db)
    await hostile(db, "bot_00001")
    await mk_bot(db, "bot_00002", city="落云城", profile={"loyalty": 50})          # 朋友 0.35 × 0.5 = 0.175
    await tie(db, "bot_00001", "bot_00002", "朋友")
    assert await companions_of(db, "bot_00001", Z(0.3)) == []
    assert await companions_of(db, "bot_00001", Z(0.1)) == ["bot_00002"]
