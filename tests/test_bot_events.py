"""机器人参与公共事件（utils/bot_events.py，接入 cogs/public_events.py、utils/events/public/）。

用户 2026-10-11 的决定：灵雨活动奖励和真人一样；兽潮守城和真人一起排名领奖；灵雨降临时 25% 的机器人赶往事件城；
万宝楼按偏好和钱包竞拍（只用随身灵石、出价 ≤ 起拍价 3 倍、每场最多 1 件）。

· 迁徙：比例、只动在世 / 没闭关 / 不在秘地的、不动已在事件城的、结束后回常驻城市；
· 灵雨：每人最多 2 次、体魄不够不淬体、奖励走和真人同一份 `grant_activity`、每场灵晶灵石有保险丝、重复参与不重复发；
· 守城：贡献含机器人档位加成、名单带 🤖、和真人同榜领奖，榜首记传闻；
· 拍卖：想要什么（喜好 / 性格原型）、出得起多少、什么时候出价、被超过就认输、落槌后不再出价、得标者不再拍；
· 接入：触发 / 结算 / 逐件计时都会调用，出错不影响事件本身。
"""

import asyncio
import json
import logging
import random
import time

import pytest
from sqlalchemy import select, text

from cogs import public_events as pe
from tests.conftest import make_player
from tests.test_spirit_rain_event import FakeChannel, P
from utils import bot_economy as be
from utils import bot_events as bev
from utils.events.public import spirit_rain as ev
from utils.events.public import wanbao as wb

CITY, EID = "铁甲城", "evt1"


@pytest.fixture
def cfg(monkeypatch):
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


async def bot(db, uid, city=CITY, home=None, tier="正常", archetype="豪爽", stones=1000, **kw):
    D = db["db_async"]
    p = make_player(D, uid, stones=stones)
    p.name, p.is_bot, p.current_city, p.lifespan, p.lifespan_max = f"散修{uid[-2:]}", True, city, 80, 100
    for k, v in kw.items():
        setattr(p, k, v)
    async with D.AsyncSessionLocal() as s:
        s.add(p)
        s.add(D.BotPersonality(bot_id=uid, archetype=archetype, tier=tier, home_city=home or city,
                               likes=json.dumps(kw.pop("likes", {})) if False else "{}", dislikes="{}"))
        await s.commit()


async def set_persona(db, uid, likes=None, dislikes=None, archetype=None):
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        row = await s.get(D.BotPersonality, uid)
        row.likes, row.dislikes = json.dumps(likes or {}), json.dumps(dislikes or {})
        if archetype:
            row.archetype = archetype
        await s.commit()


async def human(db, uid="1001", city=CITY, **kw):
    D = db["db_async"]
    p = make_player(D, uid, stones=kw.pop("stones", 1000))
    p.name, p.current_city = f"真人{uid}", city
    for k, v in kw.items():
        setattr(p, k, v)
    async with D.AsyncSessionLocal() as s:
        s.add(p)
        await s.commit()


async def city_of(db, uid):
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        return (await s.get(D.Player, uid)).current_city


async def rows(db, event_id=EID):
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        return list((await s.execute(select(D.PublicEventParticipant).where(D.PublicEventParticipant.event_id == event_id)
                                     .order_by(D.PublicEventParticipant.discord_id, D.PublicEventParticipant.activity))).scalars())


async def add_event(db, beast_tide=False, city=CITY):
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        s.add(D.PublicEvent(event_id=EID, event_type="spirit_rain", title="天降灵雨", status="active",
                            started_at=time.time() - 60, ends_at=time.time() + 3600,
                            data=json.dumps({"city": city, "beast_tide": beast_tide})))
        await s.commit()


def test_配置合法():
    assert be.validate_config(be.load_config()) == []
    pe_cfg = be.load_config()["public_events"]
    assert (pe_cfg["migrate_share"], pe_cfg["auction"]["max_multiple"]) == (0.25, 3.0)


# ---- 迁徙 -------------------------------------------------------------------

async def test_迁徙_按比例取在世机器人(db):
    for i in range(1, 9):
        await bot(db, f"bot_{i:05d}", city="落云城")
    moved = await bev.migrate_to_city(CITY, random.Random(1))
    assert moved == 2                                              # 8 × 25%
    here = [i for i in range(1, 9) if await city_of(db, f"bot_{i:05d}") == CITY]
    assert len(here) == 2


async def test_迁徙_不动已在事件城的_秘地的_闭关的_死的(db):
    await bot(db, "bot_00001", city=CITY)
    await bot(db, "bot_00002", city="万妖岭")
    await bot(db, "bot_00003", city="落云城", cultivating_until=time.time() + 3600)
    await bot(db, "bot_00004", city="落云城", is_dead=True)
    for i in range(5, 9):
        await bot(db, f"bot_{i:05d}", city="落云城")
    await bev.migrate_to_city(CITY, random.Random(1))
    assert await city_of(db, "bot_00002") == "万妖岭"
    assert await city_of(db, "bot_00003") == "落云城" and await city_of(db, "bot_00004") == "落云城"


async def test_迁徙_真人不动(db):
    await human(db, "1001", city="落云城")
    for i in range(1, 5):
        await bot(db, f"bot_{i:05d}", city="落云城")
    await bev.migrate_to_city(CITY, random.Random(1))
    assert await city_of(db, "1001") == "落云城"


async def test_迁徙_比例可调(db, cfg):
    cfg(public_events={"migrate_share": 1.0})
    for i in range(1, 5):
        await bot(db, f"bot_{i:05d}", city="落云城")
    assert await bev.migrate_to_city(CITY, random.Random(1)) == 4
    cfg(public_events={"migrate_share": 0.0})
    await bot(db, "bot_00009", city="落云城")
    assert await bev.migrate_to_city(CITY, random.Random(1)) == 0


# ---- 灵雨活动 ---------------------------------------------------------------

async def test_灵雨_参与最多两次_体魄不够不淬体(db, cfg):
    cfg(public_events={"join_chance": 1.0})
    await add_event(db)
    await bot(db, "bot_00001", physique=5)
    out = await bev.join_spirit_rain(EID, CITY, False, random.Random(1))
    acts = sorted(r.activity for r in await rows(db))
    assert acts == ["crystal", "enlighten"] and out["activities"] == 2 and out["joined"] == 1


async def test_灵雨_体魄够了三选二(db, cfg):
    cfg(public_events={"join_chance": 1.0})
    await add_event(db)
    await bot(db, "bot_00001", physique=9)
    await bev.join_spirit_rain(EID, CITY, False, random.Random(2))
    acts = [r.activity for r in await rows(db)]
    assert len(acts) == 2 and set(acts) <= {"crystal", "enlighten", "temper"} and len(set(acts)) == 2


async def test_灵雨_奖励和真人同一份发放(db, cfg, monkeypatch):
    cfg(public_events={"join_chance": 1.0})
    await add_event(db)
    await bot(db, "bot_00001", stones=0, physique=5)
    calls = []
    real = ev.grant_activity

    async def spy(uid, activity, player, event_id):
        calls.append((uid, activity, player["is_bot"]))
        return await real(uid, activity, player, event_id)
    monkeypatch.setattr(ev, "grant_activity", spy)
    out = await bev.join_spirit_rain(EID, CITY, False, random.Random(1))
    assert {c[1] for c in calls} == {"crystal", "enlighten"} and all(c[2] for c in calls)
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        p = await s.get(D.Player, "bot_00001")
    assert 150 <= p.spirit_stones <= 400 and p.spirit_stones == out["stones"] and p.cultivation >= 80


async def test_灵雨_不是每个机器人都参与(db, cfg):
    cfg(public_events={"join_chance": 0.0})
    await add_event(db)
    await bot(db, "bot_00001")
    out = await bev.join_spirit_rain(EID, CITY, False, random.Random(1))
    assert out["joined"] == 0 and await rows(db) == []


async def test_灵雨_只有事件城里在世没闭关的机器人参与(db, cfg):
    cfg(public_events={"join_chance": 1.0})
    await add_event(db)
    await bot(db, "bot_00001", city="别处")
    await bot(db, "bot_00002", is_dead=True)
    await bot(db, "bot_00003", cultivating_until=time.time() + 3600)
    await human(db, "1001")
    await bev.join_spirit_rain(EID, CITY, False, random.Random(1))
    assert await rows(db) == []


async def test_灵雨_灵晶灵石有保险丝(db, cfg):
    cfg(public_events={"join_chance": 1.0, "activity_reward_budget_per_event": 0})
    await add_event(db)
    for i in range(1, 6):
        await bot(db, f"bot_{i:05d}", physique=5)
    out = await bev.join_spirit_rain(EID, CITY, False, random.Random(1))
    assert out["stones"] == 0 and out["skipped_budget"] == 5
    assert all(r.activity != "crystal" for r in await rows(db))


async def test_灵雨_保险丝耗尽后只剩不给灵石的活动(db, cfg):
    cfg(public_events={"join_chance": 1.0, "activity_reward_budget_per_event": 200})
    await add_event(db)
    for i in range(1, 9):
        await bot(db, f"bot_{i:05d}", physique=5)
    out = await bev.join_spirit_rain(EID, CITY, False, random.Random(3))
    crystals = [r for r in await rows(db) if r.activity == "crystal"]
    assert 1 <= len(crystals) <= 2 and out["stones"] <= 200 + 400, "最多多发最后一份（保险丝是近似的）"
    assert out["skipped_budget"] >= 5


async def test_灵雨_重复调用不重复发(db, cfg):
    cfg(public_events={"join_chance": 1.0})
    await add_event(db)
    await bot(db, "bot_00001", stones=0)
    await bev.join_spirit_rain(EID, CITY, False, random.Random(1))
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        before = (await s.get(D.Player, "bot_00001")).spirit_stones
    again = await bev.join_spirit_rain(EID, CITY, False, random.Random(1))
    async with D.AsyncSessionLocal() as s:
        assert (await s.get(D.Player, "bot_00001")).spirit_stones == before
    assert again["activities"] == 0 and len(await rows(db)) == 2


async def test_灵雨_一个机器人出错不影响别的(db, cfg, monkeypatch, caplog):
    cfg(public_events={"join_chance": 1.0})
    await add_event(db)
    await bot(db, "bot_00001")
    await bot(db, "bot_00002")
    real = ev.grant_activity

    async def flaky(uid, activity, player, event_id):
        if uid == "bot_00001":
            raise RuntimeError("坏了")
        return await real(uid, activity, player, event_id)
    monkeypatch.setattr(ev, "grant_activity", flaky)
    with caplog.at_level(logging.ERROR):
        out = await bev.join_spirit_rain(EID, CITY, False, random.Random(1))
    assert out["joined"] == 1 and "bot_00001" in caplog.text


# ---- 守城 -------------------------------------------------------------------

async def test_守城_贡献含档位加成(db, cfg, monkeypatch):
    cfg(public_events={"join_chance": 0.0, "defense_chance": 1.0})
    await add_event(db, beast_tide=True)
    await bot(db, "bot_00001", tier="炮灰")
    await bot(db, "bot_00002", tier="正常")
    await bot(db, "bot_00003", tier="天骄")
    await human(db, "1001")

    async def flat(player, equipped=None):
        return 100.0
    monkeypatch.setattr(ev, "calc_power", flat)
    monkeypatch.setattr(ev.random, "uniform", lambda a, b: 1.0)
    out = await bev.join_spirit_rain(EID, CITY, True, random.Random(1))
    got = {r.discord_id: r.contribution for r in await rows(db)}
    assert got == {"bot_00001": 100, "bot_00002": 120, "bot_00003": 150} and out["defenders"] == 3


async def test_守城_没有兽潮就不守(db, cfg):
    cfg(public_events={"join_chance": 0.0, "defense_chance": 1.0})
    await add_event(db)
    await bot(db, "bot_00001")
    await bev.join_spirit_rain(EID, CITY, False, random.Random(1))
    assert await rows(db) == []


async def test_守城_概率可调(db, cfg):
    cfg(public_events={"join_chance": 0.0, "defense_chance": 0.0})
    await add_event(db, beast_tide=True)
    await bot(db, "bot_00001")
    assert (await bev.join_spirit_rain(EID, CITY, True, random.Random(1)))["defenders"] == 0


async def test_守城结算_机器人和真人同榜_带标记_领奖励(db):
    """榜首是机器人：拿到灵石 / 声望 / 装备，战报里带 🤖，并记一条守城传闻。"""
    await bot(db, "bot_00001", stones=0, reputation=0) if False else None
    await bot(db, "bot_00001", stones=0)
    await human(db, "1001", stones=0)
    await add_event(db, beast_tide=True)
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        s.add(D.PublicEventParticipant(event_id=EID, discord_id="bot_00001", activity="defense", joined_at=time.time(), contribution=900))
        s.add(D.PublicEventParticipant(event_id=EID, discord_id="1001", activity="defense", joined_at=time.time(), contribution=500))
        await s.commit()
    ch = FakeChannel()
    async with D.AsyncSessionLocal() as s:
        event = dict((await s.execute(text("SELECT * FROM public_events WHERE event_id=:e"), {"e": EID})).fetchone()._mapping)
    await ev.on_settle(None, ch, event)
    battle = next(m for m in ch.sent if m.embed and "守城结算" in m.embed.title)
    top, second = battle.embed.fields[0].value.split("\n")[:2]
    assert "🤖" in top and "散修01" in top and "🤖" not in second
    async with D.AsyncSessionLocal() as s:
        b = await s.get(D.Player, "bot_00001")
        eq = (await s.execute(select(D.Equipment).where(D.Equipment.discord_id == "bot_00001"))).scalars().all()
        rumor = (await s.execute(select(D.Rumor).where(D.Rumor.kind == "beast_tide_hero"))).scalars().all()
    assert b.spirit_stones >= 3000 and len(eq) == 2
    assert len(rumor) == 1 and rumor[0].subject_id == "bot_00001" and not rumor[0].is_human


async def test_守城结算_临阵脱逃的机器人也带标记(db):
    await bot(db, "bot_00001", city="落云城", stones=0)
    await add_event(db, beast_tide=True)
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        s.add(D.PublicEventParticipant(event_id=EID, discord_id="bot_00001", activity="crystal", joined_at=time.time(), contribution=0))
        await s.commit()
    ch = FakeChannel()
    async with D.AsyncSessionLocal() as s:
        event = dict((await s.execute(text("SELECT * FROM public_events WHERE event_id=:e"), {"e": EID})).fetchone()._mapping)
    await ev.on_settle(None, ch, event)
    battle = next(m for m in ch.sent if m.embed and "守城结算" in m.embed.title)
    assert "临阵脱逃" in battle.embed.fields[0].value and "🤖 **散修01**" in battle.embed.fields[0].value


async def test_普通结算_机器人参与名单带标记(db):
    ch = FakeChannel()
    await ev._settle_spirit_rain_only(ch, CITY, [P("1"), {**P("2"), "is_bot": True}])
    names = next(f for f in ch.last.embed.fields if f.name == "参与修士").value.split("\n")
    assert names == ["· **道友1**", "· 🤖 **道友2**"]


async def test_参与者查询带上_is_bot(db):
    await bot(db, "bot_00001")
    await add_event(db)
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        s.add(D.PublicEventParticipant(event_id=EID, discord_id="bot_00001", activity="defense", joined_at=time.time(), contribution=1))
        await s.commit()
    assert (await ev._get_participants(EID))[0]["is_bot"] == 1
    assert (await ev._get_defense_participants(EID))[0]["is_bot"] == 1


# ---- 触发 / 结束 / 回城 -----------------------------------------------------

async def test_一次完整流程_迁徙参与回城(db, cfg):
    cfg(public_events={"join_chance": 1.0, "defense_chance": 0.0, "migrate_share": 1.0})
    await add_event(db)
    await bot(db, "bot_00001", city="落云城", home="落云城")
    await bot(db, "bot_00002", city=CITY, home=CITY)
    out = await bev.on_spirit_rain_start(EID, CITY, False, random.Random(1))
    assert out["migrated"] == 1 and await city_of(db, "bot_00001") == CITY and out["joined"] == 2
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        event = dict((await s.execute(text("SELECT * FROM public_events WHERE event_id=:e"), {"e": EID})).fetchone()._mapping)
    assert await bev.on_spirit_rain_end(event) == 1
    assert await city_of(db, "bot_00001") == "落云城" and await city_of(db, "bot_00002") == CITY


async def test_回城_不碰真人_没参与的_没有常驻城市的(db):
    await add_event(db)
    await bot(db, "bot_00001", city=CITY, home="落云城")
    await bot(db, "bot_00002", city=CITY, home="落云城")
    await bot(db, "bot_00003", city=CITY, home="")
    await human(db, "1001")
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        for uid in ("bot_00001", "bot_00003", "1001"):
            s.add(D.PublicEventParticipant(event_id=EID, discord_id=uid, activity="crystal", joined_at=time.time(), contribution=0))
        await s.commit()
    assert await bev.send_home(EID, CITY) == 1
    assert await city_of(db, "bot_00001") == "落云城" and await city_of(db, "bot_00002") == CITY
    assert await city_of(db, "bot_00003") == CITY and await city_of(db, "1001") == CITY


async def test_触发时出错只记日志(db, monkeypatch, caplog):
    async def boom(city, rng=None):
        raise RuntimeError("库挂了")
    monkeypatch.setattr(bev, "migrate_to_city", boom)
    with caplog.at_level(logging.ERROR):
        assert await bev.on_spirit_rain_start(EID, CITY, False) == {}
    assert "机器人参与灵雨失败" in caplog.text


async def test_结束时出错只记日志(db, caplog):
    with caplog.at_level(logging.ERROR):
        assert await bev.on_spirit_rain_end({"event_id": EID, "data": "不是json"}) == 0
    assert "机器人回城失败" in caplog.text


# ---- 拍卖：想要什么 ---------------------------------------------------------

PERSONA = {"archetype": "豪爽", "likes": {"categories": ["丹药"], "items": ["灵芝草"]},
           "dislikes": {"categories": ["矿石"], "items": ["筑基丹"]}}


def lot(item_type="item", name="聚气丸", start=500, **kw):
    return {"lot_id": "L", "item_type": item_type, "item_name": name, "start_price": start, "current_bid": None,
            "bidder_id": None, **kw}


def test_想要_喜欢的类别和具体物品():
    c = be.load_config()
    assert bev.wants_lot(PERSONA, lot(name="聚气丸"), c) is True                     # 丹药类
    assert bev.wants_lot(PERSONA, lot(name="灵芝草"), c) is True                     # 具体喜欢
    assert bev.wants_lot(PERSONA, lot(name="铜矿石"), c) is False                    # 讨厌的类别
    assert bev.wants_lot(PERSONA, lot(name="筑基丹"), c) is False, "具体讨厌压过类别喜欢"
    assert bev.wants_lot(PERSONA, lot(name="灵溪鲫"), c) is False                    # 无所谓的不拍
    assert bev.wants_lot(None, lot(), c) is False


def test_想要_装备和功法看性格():
    c = be.load_config()
    for arche, eq, tech in (("贪财", True, False), ("阴鸷", True, False), ("豪爽", True, False),
                            ("迂腐", False, True), ("高冷", False, True), ("痴丹", False, True), ("憨直", False, False)):
        persona = {"archetype": arche}
        assert bev.wants_lot(persona, lot("equipment", "某剑"), c) is eq, arche
        assert bev.wants_lot(persona, lot("technique", "某功法"), c) is tech, arche


# ---- 拍卖：谁能出价 ---------------------------------------------------------

async def auction(db, start=500, item="聚气丸", item_type="item", seller=None):
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        s.add(D.WanbaoAuction(auction_id="A1", date_str="2026-10-11", status="active", started_at=time.time(),
                              ends_at=time.time() + 120, current_lot=0))
        s.add(D.WanbaoLot(lot_id="L1", auction_id="A1", lot_index=0, seller_id=seller, item_name=item, quantity=1,
                          item_type=item_type, start_price=start, status="active"))
        await s.commit()
    return (await wb.get_current_lot("A1"))


async def likes_pills(db, uid):
    await set_persona(db, uid, likes={"categories": ["丹药"]})


async def test_候选_出得起且想要且没得过标(db):
    lot_ = await auction(db, start=500)
    await bot(db, "bot_00001", stones=5000)                       # 够
    await bot(db, "bot_00002", stones=300)                        # 钱包不够起拍价
    await bot(db, "bot_00003", stones=50)                         # 不到 min_carry
    await bot(db, "bot_00004", stones=5000)                       # 不想要
    await bot(db, "bot_00005", stones=5000)                       # 这场已经得过标
    for uid in ("bot_00001", "bot_00002", "bot_00003", "bot_00005"):
        await likes_pills(db, uid)
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        s.add(D.WanbaoLot(lot_id="L0", auction_id="A1", lot_index=9, item_name="x", quantity=1, item_type="item",
                          start_price=1, status="sold", bidder_id="bot_00005", current_bid=1))
        await s.commit()
    got = await bev.auction_candidates("A1", lot_, random.Random(1))
    assert [uid for uid, _ in got] == ["bot_00001"]


async def test_候选_出价上限是钱包八成与起拍价三倍里较小的(db):
    lot_ = await auction(db, start=500)
    await bot(db, "bot_00001", stones=1000)
    await bot(db, "bot_00002", stones=100_000)
    for uid in ("bot_00001", "bot_00002"):
        await likes_pills(db, uid)
    got = dict(await bev.auction_candidates("A1", lot_, random.Random(1)))
    assert got == {"bot_00001": 800, "bot_00002": 1500}


async def test_候选_每件最多_bidders_per_lot_个(db, cfg):
    cfg.cfg["public_events"]["auction"]["bidders_per_lot"] = 2
    lot_ = await auction(db)
    for i in range(1, 7):
        await bot(db, f"bot_{i:05d}", stones=5000)
        await likes_pills(db, f"bot_{i:05d}")
    assert len(await bev.auction_candidates("A1", lot_, random.Random(1))) == 2


async def test_候选_真人和死去的机器人不算(db):
    lot_ = await auction(db)
    await human(db, "1001", stones=9999)
    await bot(db, "bot_00001", stones=5000, is_dead=True)
    await likes_pills(db, "bot_00001")
    assert await bev.auction_candidates("A1", lot_, random.Random(1)) == []


# ---- 拍卖：出价过程 ---------------------------------------------------------

async def instant(delays):
    return None


async def run_round(lot_, window=100.0, seed=1, sleeps=None):
    async def sleep(t):
        if sleeps is not None:
            sleeps.append(t)
    return await bev.auction_round("A1", lot_, window, random.Random(seed), sleep=sleep)


async def current(db):
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        return (await s.execute(select(D.WanbaoLot).where(D.WanbaoLot.lot_id == "L1"))).scalars().one()


async def test_竞拍_机器人出价_托管灵石(db):
    lot_ = await auction(db, start=500)
    await bot(db, "bot_00001", stones=5000)
    await likes_pills(db, "bot_00001")
    out = await run_round(lot_)
    cur = await current(db)
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        stones = (await s.get(D.Player, "bot_00001")).spirit_stones
    assert out["bidders"] == 1 and out["bids"] >= 1 and cur.bidder_id == "bot_00001" and cur.current_bid >= 500
    assert stones == 5000 - cur.current_bid, "出价即托管，和真人一样"


async def test_竞拍_两个机器人互相抬价_输的退款(db):
    lot_ = await auction(db, start=500)
    await bot(db, "bot_00001", stones=1000)                       # 上限 800
    await bot(db, "bot_00002", stones=100_000)                    # 上限 1500
    for uid in ("bot_00001", "bot_00002"):
        await likes_pills(db, uid)
    for seed in range(1, 6):
        await run_round(lot_, seed=seed)
    cur = await current(db)
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        loser = await s.get(D.Player, "bot_00001")
    if cur.bidder_id == "bot_00002":
        assert loser.spirit_stones == 1000, "被超过的立即全额退回"
    assert cur.current_bid <= 1500 and cur.bidder_id in ("bot_00001", "bot_00002")


async def test_竞拍_出价不会超过起拍价三倍(db):
    lot_ = await auction(db, start=500)
    for i in range(1, 4):
        await bot(db, f"bot_{i:05d}", stones=1_000_000)
        await likes_pills(db, f"bot_{i:05d}")
    for seed in range(1, 8):
        await run_round(lot_, seed=seed)
    assert (await current(db)).current_bid <= 1500


async def test_竞拍_真人出得更高_机器人认输(db):
    lot_ = await auction(db, start=500)
    await human(db, "1001", stones=100_000)
    ok, _ = await wb.place_bid("A1", "1001", 2000)
    assert ok
    await bot(db, "bot_00001", stones=100_000)
    await likes_pills(db, "bot_00001")
    out = await run_round(await wb.get_current_lot("A1"))
    cur = await current(db)
    assert out["bids"] == 0 and cur.bidder_id == "1001" and cur.current_bid == 2000


async def test_竞拍_时间点落在窗口的百分之十到八十五(db, monkeypatch):
    lot_ = await auction(db, start=500)
    for i in range(1, 4):
        await bot(db, f"bot_{i:05d}", stones=5000)
        await likes_pills(db, f"bot_{i:05d}")
    plans = []

    async def spy(auction_id, lot_id, uid, max_bid, delays, sleep, rng):
        plans.append(delays)
        return 0
    monkeypatch.setattr(bev, "_bot_bids", spy)
    for seed in range(1, 6):
        await run_round(lot_, window=100.0, seed=seed)
    flat = [t for d in plans for t in d]
    assert flat and all(10 - 1e-9 <= t <= 85 + 1e-9 for t in flat)
    assert all(d == sorted(d) and 1 <= len(d) <= 3 for d in plans)


async def test_竞拍_相邻出价之间睡的是时间差(db):
    lot_ = await auction(db, start=500)
    await bot(db, "bot_00001", stones=5000)
    await likes_pills(db, "bot_00001")
    sleeps = []
    await run_round(lot_, window=100.0, sleeps=sleeps)
    assert sleeps and all(s >= 0 for s in sleeps) and sum(sleeps) <= 85 + 1e-6


async def test_竞拍_这件已经落槌就不再出价(db):
    lot_ = await auction(db, start=500)
    await bot(db, "bot_00001", stones=5000)
    await likes_pills(db, "bot_00001")
    D = db["db_async"]

    async def sleep(t):
        async with D.AsyncSessionLocal() as s:                  # 等的时候这件被结算了
            await s.execute(text("UPDATE wanbao_lots SET status='unsold' WHERE lot_id='L1'"))
            await s.commit()
    out = await bev.auction_round("A1", lot_, 100.0, random.Random(1), sleep=sleep)
    assert out["bids"] == 0 and not (await current(db)).current_bid


async def test_竞拍_已经领先就不抬自己的价(db):
    lot_ = await auction(db, start=500)
    await bot(db, "bot_00001", stones=5000)
    await likes_pills(db, "bot_00001")
    ok, _ = await wb.place_bid("A1", "bot_00001", 500)
    assert ok
    out = await run_round(await wb.get_current_lot("A1"))
    assert out["bids"] == 0 and (await current(db)).current_bid == 500


async def test_竞拍_出错只记日志(db, monkeypatch, caplog):
    lot_ = await auction(db)

    async def boom(*a, **k):
        raise RuntimeError("库挂了")
    monkeypatch.setattr(bev, "auction_candidates", boom)
    with caplog.at_level(logging.ERROR):
        assert await bev.auction_round("A1", lot_, 100.0) == {"bidders": 0, "bids": 0}
    assert "机器人竞拍失败" in caplog.text


async def test_竞拍_一个机器人出错不影响别的(db, monkeypatch, caplog):
    lot_ = await auction(db, start=500)
    for uid in ("bot_00001", "bot_00002"):
        await bot(db, uid, stones=5000)
        await likes_pills(db, uid)
    real = wb.place_bid

    async def flaky(auction_id, uid, amount):
        if uid == "bot_00001":
            raise RuntimeError("坏了")
        return await real(auction_id, uid, amount)
    monkeypatch.setattr(wb, "place_bid", flaky)
    with caplog.at_level(logging.ERROR):
        out = await run_round(lot_)
    assert out["bids"] >= 1 and "机器人竞拍出错" in caplog.text


async def test_竞拍_被取消时不吞(db):
    lot_ = await auction(db, start=500)
    await bot(db, "bot_00001", stones=5000)
    await likes_pills(db, "bot_00001")

    async def slow(t):
        await asyncio.sleep(3600)
    task = asyncio.create_task(bev.auction_round("A1", lot_, 100.0, random.Random(1), sleep=slow))
    await asyncio.sleep(0.05)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


async def test_高价成交记传闻(db):
    await auction(db, start=5000)
    await bot(db, "bot_00001", stones=100_000)
    lot_ = await wb.get_current_lot("A1")
    ok, _ = await wb.place_bid("A1", "bot_00001", 4000 + 1000)
    assert ok
    await wb.settle_lot(await wb.get_current_lot("A1"))
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        r = (await s.execute(select(D.Rumor).where(D.Rumor.kind == "auction_win"))).scalars().all()
    assert len(r) == 1 and r[0].subject_id == "bot_00001" and "5000" in r[0].content


async def test_低价成交不记传闻(db):
    await auction(db, start=100)
    await bot(db, "bot_00001", stones=100_000)
    await wb.place_bid("A1", "bot_00001", 200)
    await wb.settle_lot(await wb.get_current_lot("A1"))
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        assert (await s.execute(select(D.Rumor))).scalars().all() == []


# ---- 接入 cog ---------------------------------------------------------------

async def test_cog_触发和结算都会调用机器人(db, monkeypatch):
    from tests.test_public_events_cog import FakeBot, PublicEventsCog
    from discord.ext import tasks
    monkeypatch.setattr(tasks.Loop, "start", lambda self, *a, **k: None)
    calls = []

    async def start(event_id, city, beast_tide, rng=None):
        calls.append(("start", city, beast_tide))
        return {}

    async def end(event):
        calls.append(("end", event["event_id"]))
        return 0
    monkeypatch.setattr(pe.bot_events, "on_spirit_rain_start", start)
    monkeypatch.setattr(pe.bot_events, "on_spirit_rain_end", end)
    cog = PublicEventsCog(FakeBot(FakeChannel()))
    try:
        await cog._trigger_spirit_rain("2026-10-11")
        D = db["db_async"]
        async with D.AsyncSessionLocal() as s:
            event = dict((await s.execute(text("SELECT * FROM public_events"))).fetchone()._mapping)
        await cog._settle_event(event)
        await cog._settle_event({"event_type": "不存在", "event_id": "z", "data": "{}"})
    finally:
        cog.cog_unload()
    assert [c[0] for c in calls] == ["start", "end"] and calls[0][2] in (True, False)


async def test_cog_逐件计时_每件开拍都叫一次机器人(db, monkeypatch):
    from tests.test_public_events_cog import FakeBot, PublicEventsCog, _auction, _expire_current_lot
    from discord.ext import tasks
    monkeypatch.setattr(tasks.Loop, "start", lambda self, *a, **k: None)
    monkeypatch.setenv(pe.PUBLIC_EVENT_CHANNEL_ENV, "1")
    real = asyncio.sleep

    async def nosleep(t, *a, **k):
        await real(0)
    monkeypatch.setattr(pe.asyncio, "sleep", nosleep)
    seen = []

    async def spy(auction_id, cur, window, rng=None, sleep=None):
        seen.append(cur["lot_id"])
        return {}
    monkeypatch.setattr(pe.bot_events, "auction_round", spy)
    aid = await _auction(db)
    await wb.start_auction(aid)
    await _expire_current_lot(db, aid)
    cog = PublicEventsCog(FakeBot(FakeChannel()))
    try:
        await cog._run_lot_timer(aid)
    finally:
        cog.cog_unload()
    assert len(seen) == 8 and len(set(seen)) == 8


# ---- 静态棘轮 / 其他 --------------------------------------------------------

def test_灵雨奖励只有一份实现():
    """真人点按钮和机器人参与必须共用 grant_activity，不能各抄一份（B31）。"""
    import inspect
    src = inspect.getsource(ev._handle_activity)
    assert "grant_activity(" in src and "random.randint(150, 400)" not in src
    assert inspect.getsource(bev.join_spirit_rain).count("grant_activity") >= 2


# ---- 属性点上限 -------------------------------------------------------------

def test_属性上限_档位上限加三():
    c = be.load_config()
    assert [bev.stat_cap(t, c) for t in ("炮灰", "正常", "天骄")] == [9, 11, 14]


async def test_属性点_事件里长到上限就不再长(db, cfg, monkeypatch):
    cfg(public_events={"join_chance": 1.0})
    await add_event(db)
    # 悟性已经到了正常档的上限（8 + 3 = 11）；再让感悟必定 +1
    await bot(db, "bot_00001", tier="正常", comprehension=11, soul=11, fortune=11, physique=5)
    await bot(db, "bot_00002", tier="正常", comprehension=5, soul=5, fortune=5, physique=5)
    monkeypatch.setattr(ev.random, "random", lambda: 0.0)                         # 15% / 12% 的几率全中
    monkeypatch.setattr(ev.random, "choice", lambda seq: seq[0])
    for seed in range(1, 4):
        await bev.join_spirit_rain(EID, CITY, False, random.Random(seed))
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        capped, free = await s.get(D.Player, "bot_00001"), await s.get(D.Player, "bot_00002")
    assert capped.comprehension == 11 and capped.soul == 11 and capped.fortune == 11, "到顶了就不再长"
    assert free.comprehension >= 5 and max(free.comprehension, free.soul, free.fortune) <= 11


async def test_属性点_已经高过上限的会被压回来(db, cfg):
    cfg(public_events={"join_chance": 1.0})
    await add_event(db)
    await bot(db, "bot_00001", tier="炮灰", comprehension=15)
    await bev.join_spirit_rain(EID, CITY, False, random.Random(1))
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        assert (await s.get(D.Player, "bot_00001")).comprehension == 9


async def test_属性点_真人不受上限影响(db, monkeypatch):
    """真人走的是原来的按钮流程，不经过 bev，属性点照常增长。"""
    from tests.discord_fakes import FakeInteraction
    await add_event(db)
    await human(db, "1001", comprehension=30, soul=30, fortune=30)
    monkeypatch.setattr(ev.random, "random", lambda: 0.0)
    monkeypatch.setattr(ev.random, "choice", lambda seq: seq[0])
    i = FakeInteraction(1001)
    await ev._handle_activity(i, EID, CITY, "enlighten")
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        assert (await s.get(D.Player, "1001")).comprehension == 31


async def test_应急开关_机器人不参与守城排名(db, cfg):
    """combat 之外最激进的选择（机器人和真人同榜领奖）留了一个开关：关掉后榜上和奖励只有真人。"""
    cfg(public_events={"bots_compete_for_defense_rewards": False})
    await bot(db, "bot_00001", stones=0)
    await human(db, "1001", stones=0)
    await add_event(db, beast_tide=True)
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        s.add(D.PublicEventParticipant(event_id=EID, discord_id="bot_00001", activity="defense", joined_at=time.time(), contribution=900))
        s.add(D.PublicEventParticipant(event_id=EID, discord_id="1001", activity="defense", joined_at=time.time(), contribution=500))
        await s.commit()
    ch = FakeChannel()
    async with D.AsyncSessionLocal() as s:
        event = dict((await s.execute(text("SELECT * FROM public_events WHERE event_id=:e"), {"e": EID})).fetchone()._mapping)
    await ev.on_settle(None, ch, event)
    battle = next(m for m in ch.sent if m.embed and "守城结算" in m.embed.title)
    lines = battle.embed.fields[0].value.split("\n")
    assert "🤖" not in battle.embed.fields[0].value and "真人1001" in lines[0] and "🥇" in lines[0]
    async with D.AsyncSessionLocal() as s:
        assert (await s.get(D.Player, "bot_00001")).spirit_stones == 0
        assert (await s.get(D.Player, "1001")).spirit_stones >= 3000
