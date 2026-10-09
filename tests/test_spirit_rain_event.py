"""灵雨活动逻辑测试（utils/events/public/spirit_rain.py）。

这是真正发奖励的地方：灵雨结晶 / 感悟 / 淬体、守城、结算时的灵石、声望、稀有装备，
以及万兽齐鸣对「袖手旁观」者的寿元惩罚。此前只有 16% 覆盖，几乎全是奖励与惩罚的数值逻辑。

随机性：模块里 `import random` 用的是模块级的 random，这里换成一个只覆盖指定函数的代理，
其余仍用真实 random（装备生成等不受影响）。

结构：A 查询  B 触发  C 结算入口  D 普通结算  E 万兽齐鸣结算  F 摸鱼榜翻页  G 参与活动  H 频道缺失
"""

import asyncio
import json
import random as real_random
import time
import types

import pytest

from tests.conftest import make_player
from tests.discord_fakes import FakeInteraction, SentMessage
from utils.events.public import spirit_rain as ev
from utils.events.public.spirit_rain import SlackerView, SpiritRainEvent, SpiritRainView

CITY = "铁甲城"
EID = "ev1"


class RandomProxy:
    """覆盖指定的 random 函数，其余透传给真实的 random。"""

    def __init__(self, **overrides):
        self._o = overrides

    def __getattr__(self, name):
        return self._o.get(name, getattr(real_random, name))


def pin_random(monkeypatch, **overrides):
    monkeypatch.setattr(ev, "random", RandomProxy(**overrides))


class FakeChannel:
    def __init__(self):
        self.sent: list[SentMessage] = []

    async def send(self, content=None, *, embed=None, view=None, **_):
        self.sent.append(SentMessage(content=content, embed=embed, view=view))
        return types.SimpleNamespace(id=9000 + len(self.sent))

    @property
    def last(self):
        return self.sent[-1]


async def _add_player(db, uid, city=CITY, **fields):
    D = db["db_async"]
    p = make_player(D, uid, stones=1000)
    p.name = f"道友{uid}"
    p.current_city = city
    for k, v in fields.items():
        setattr(p, k, v)
    async with D.AsyncSessionLocal() as s:
        s.add(p)
        await s.commit()


async def _row(db, uid):
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        return await s.get(D.Player, uid)


async def _add_event(db, event_id=EID, status="active", city=CITY, beast_tide=False, ends_in=3600):
    D = db["db_async"]
    now = time.time()
    async with D.AsyncSessionLocal() as s:
        s.add(D.PublicEvent(event_id=event_id, event_type="spirit_rain", title="天降灵雨", status=status,
                            started_at=now - 60, ends_at=now + ends_in,
                            data=json.dumps({"city": city, "beast_tide": beast_tide})))
        await s.commit()


async def _join(db, uid, activity="defense", contribution=0, event_id=EID, joined_ago=0):
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        s.add(D.PublicEventParticipant(event_id=event_id, discord_id=uid, activity=activity,
                                       joined_at=time.time() - joined_ago, contribution=contribution))
        await s.commit()


async def _event_dict(db, event_id=EID):
    D = db["db_async"]
    from sqlalchemy import text
    async with D.AsyncSessionLocal() as s:
        row = (await s.execute(text("SELECT * FROM public_events WHERE event_id=:e"), {"e": event_id})).fetchone()
    return dict(row._mapping)


async def _status(db, event_id=EID):
    return (await _event_dict(db, event_id))["status"]


async def _equipment(db, uid):
    from sqlalchemy import select
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        return (await s.execute(select(D.Equipment).where(D.Equipment.discord_id == uid))).scalars().all()


# =============================================================================
# A. 查询
# =============================================================================

def test_随机城市是真实城市():
    from utils.world import CITIES
    assert ev._pick_city() in {c["name"] for c in CITIES}


async def test_参与者按贡献从高到低_带上玩家信息(db):
    await _add_event(db)
    await _add_player(db, "1", realm="筑基期3层")
    await _add_player(db, "2")
    await _join(db, "1", "defense", 100)
    await _join(db, "2", "crystal", 300)
    await _add_event(db, "other")
    await _join(db, "1", "defense", 999, event_id="other")                 # 别的事件不混进来

    rows = await ev._get_participants(EID)

    assert [r["discord_id"] for r in rows] == ["2", "1"]
    assert rows[1]["name"] == "道友1" and rows[1]["realm"] == "筑基期3层" and rows[1]["current_city"] == CITY


async def test_守城参与者只取守城活动(db):
    await _add_event(db)
    for uid, act, c in [("1", "defense", 5), ("2", "crystal", 9), ("3", "defense", 50)]:
        await _add_player(db, uid)
        await _join(db, uid, act, c)
    rows = await ev._get_defense_participants(EID)
    assert [r["discord_id"] for r in rows] == ["3", "1"]


async def test_空闲玩家_同城活着没在忙且没参与活动(db):
    now = time.time()
    await _add_player(db, "idle")
    await _add_player(db, "elsewhere", city="别处")
    await _add_player(db, "dead", is_dead=True)
    await _add_player(db, "cult", cultivating_until=now + 999)
    await _add_player(db, "gath", gathering_until=now + 999)
    await _add_player(db, "quest", active_quest="{}")
    await _add_player(db, "joined")
    await _add_player(db, "cult_done", cultivating_until=now - 1)         # 闭关已结束算空闲

    rows = await ev._get_idle_in_city(CITY, {"joined"})

    assert sorted(r["discord_id"] for r in rows) == ["cult_done", "idle"]


# =============================================================================
# B. 触发
# =============================================================================

async def test_触发_发出降临公告并记下消息id(db):
    await _add_event(db)
    ch = FakeChannel()

    await ev.on_trigger(None, ch, EID, CITY)

    m = ch.last
    assert "降临" in m.embed.title and CITY in m.embed.description and "+150%" in m.embed.description
    assert [f.name for f in m.embed.fields] == ["💎 灵雨结晶", "🧘 灵雨感悟", "💪 灵雨淬体"]
    assert EID in m.embed.footer.text
    assert isinstance(m.view, SpiritRainView) and m.view.event_id == EID and m.view.city == CITY
    assert (await _event_dict(db))["message_id"] == "9001"


# =============================================================================
# C. 结算入口
# =============================================================================

async def test_结算_标记事件结束_再分流(db, monkeypatch):
    calls = []

    async def _rain(channel, city, participants):
        calls.append(("rain", city, len(participants)))

    async def _tide(bot, channel, event_id, city, defense, participants, ids):
        calls.append(("tide", city, len(defense), sorted(ids)))
    monkeypatch.setattr(ev, "_settle_spirit_rain_only", _rain)
    monkeypatch.setattr(ev, "_settle_beast_tide", _tide)
    await _add_event(db, "r", beast_tide=False)
    await _add_event(db, "t", beast_tide=True)
    for uid, eid, act in [("1", "r", "crystal"), ("2", "t", "defense"), ("3", "t", "crystal")]:
        await _add_player(db, uid)
        await _join(db, uid, act, 1, event_id=eid)

    await ev.on_settle(None, FakeChannel(), await _event_dict(db, "r"))
    await ev.on_settle(None, FakeChannel(), await _event_dict(db, "t"))

    assert calls == [("rain", CITY, 1), ("tide", CITY, 1, ["2", "3"])]
    assert await _status(db, "r") == "ended" and await _status(db, "t") == "ended"


async def test_结算_事件数据缺城市时用未知城市(db, monkeypatch):
    seen = {}

    async def _rain(channel, city, participants):
        seen["city"] = city
    monkeypatch.setattr(ev, "_settle_spirit_rain_only", _rain)
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        s.add(D.PublicEvent(event_id="x", event_type="spirit_rain", title="t", status="active",
                            started_at=time.time(), ends_at=time.time(), data="{}"))
        await s.commit()
    await ev.on_settle(None, FakeChannel(), await _event_dict(db, "x"))
    assert seen["city"] == "未知城市"


# =============================================================================
# D. 普通灵雨结算
# =============================================================================

def P(uid, name=None, city=CITY, activity="crystal", **extra):
    return {"discord_id": uid, "name": name or f"道友{uid}", "current_city": city, "activity": activity,
            "contribution": 0, "realm": "炼气期1层", **extra}


async def test_普通结算_守城者在城内按区间领灵石和声望(db, monkeypatch):
    pin_random(monkeypatch, randint=lambda a, b: b)
    await _add_player(db, "1", spirit_stones=0, reputation=0)
    await _add_player(db, "2", spirit_stones=0)
    ch = FakeChannel()

    await ev._settle_spirit_rain_only(ch, CITY, [P("1", activity="defense"), P("2", activity="crystal")])

    d, other = await _row(db, "1"), await _row(db, "2")
    assert (d.spirit_stones, d.reputation) == (300, 5)
    assert other.spirit_stones == 0                                         # 没守城的没有守城奖励
    assert any("守城奖励" in f.name for f in ch.last.embed.fields)


async def test_普通结算_守城奖励的区间(db):
    await _add_player(db, "1", spirit_stones=0)
    for _ in range(30):
        await ev._settle_spirit_rain_only(FakeChannel(), CITY, [P("1", activity="defense")])
    # 30 次，每次 100~300
    assert 30 * 100 <= (await _row(db, "1")).spirit_stones <= 30 * 300


async def test_普通结算_守城者已离城_不发奖励_点名临阵脱逃(db, monkeypatch):
    pin_random(monkeypatch, randint=lambda a, b: b)
    await _add_player(db, "1", spirit_stones=0, city="别处")
    ch = FakeChannel()

    await ev._settle_spirit_rain_only(ch, CITY, [P("1", city="别处", activity="defense")])

    assert (await _row(db, "1")).spirit_stones == 0
    fled = next(f for f in ch.last.embed.fields if f.name.endswith("临阵脱逃"))
    assert "道友1" in fled.value


async def test_普通结算_同一人多次参与只列一次_最多十五人(db):
    parts = [P("1"), P("1", activity="enlighten")] + [P(str(i)) for i in range(2, 30)]
    ch = FakeChannel()
    await ev._settle_spirit_rain_only(ch, CITY, parts)
    names = next(f for f in ch.last.embed.fields if f.name == "参与修士").value.split("\n")
    assert len(names) == 15 and names.count("· **道友1**") == 1


async def test_普通结算_没人参与时只发结束公告(db):
    ch = FakeChannel()
    await ev._settle_spirit_rain_only(ch, CITY, [])
    assert "结束" in ch.last.embed.title and ch.last.embed.fields == []


async def test_普通结算_脱逃名单最多五个(db):
    parts = [P(str(i), city="别处") for i in range(8)]
    ch = FakeChannel()
    await ev._settle_spirit_rain_only(ch, CITY, parts)
    fled = next(f for f in ch.last.embed.fields if f.name.endswith("临阵脱逃")).value
    assert fled.count("**") == 5 * 2


# =============================================================================
# E. 万兽齐鸣结算
# =============================================================================

async def _tide(db, defenders, others=(), idle=(), monkeypatch=None, channel=None):
    """defenders: [(uid, contribution, realm)]，others: [(uid, activity, city)]，idle: [uid]。"""
    await _add_event(db, beast_tide=True)
    for uid, contribution, realm in defenders:
        await _add_player(db, uid, spirit_stones=0, reputation=0, realm=realm)
        await _join(db, uid, "defense", contribution)
    for uid, activity, city in others:
        await _add_player(db, uid, city=city, spirit_stones=0)
        await _join(db, uid, activity, 0)
    for uid in idle:
        await _add_player(db, uid, lifespan=100)
    ch = channel or FakeChannel()
    parts = await ev._get_participants(EID)
    defense = await ev._get_defense_participants(EID)
    await ev._settle_beast_tide(None, ch, EID, CITY, defense, parts, {p["discord_id"] for p in parts})
    return ch


async def test_万兽齐鸣_第一名两件稀有装备_大额灵石_声望五十(db, monkeypatch):
    pin_random(monkeypatch, randint=lambda a, b: b, random=lambda: 0.99)

    ch = await _tide(db, [("1", 900, "筑基期3层"), ("2", 500, "炼气期1层")])

    first = await _row(db, "1")
    assert (first.spirit_stones, first.reputation) == (5000, 50)
    eq = await _equipment(db, "1")
    assert len(eq) == 2 and all(e.quality == "稀有" for e in eq)
    assert "🥇" in ch.sent[0].embed.fields[0].value and "2件稀有装备" in ch.sent[0].embed.fields[0].value


async def test_万兽齐鸣_二三名各一件稀有装备(db, monkeypatch):
    pin_random(monkeypatch, randint=lambda a, b: a, random=lambda: 0.99)

    await _tide(db, [("1", 900, "炼气期1层"), ("2", 800, "炼气期1层"), ("3", 700, "炼气期1层")])

    for uid in ("2", "3"):
        p = await _row(db, uid)
        assert (p.spirit_stones, p.reputation) == (1500, 30)
        assert len(await _equipment(db, uid)) == 1
    assert len(await _equipment(db, "1")) == 2


async def test_万兽齐鸣_其余守城者只有灵石和声望_没有装备(db, monkeypatch):
    pin_random(monkeypatch, randint=lambda a, b: a, random=lambda: 0.99)
    defenders = [(str(i), 1000 - i, "炼气期1层") for i in range(1, 6)]

    await _tide(db, defenders)

    p = await _row(db, "5")
    assert (p.spirit_stones, p.reputation) == (300, 10)
    assert await _equipment(db, "5") == [] and await _equipment(db, "4") == []


async def test_万兽齐鸣_装备档位跟随境界(db, monkeypatch):
    from utils.equipment import get_player_tier
    pin_random(monkeypatch, random=lambda: 0.99)
    await _tide(db, [("1", 900, "结丹期初期")])
    assert all(e.tier == get_player_tier("结丹期初期") for e in await _equipment(db, "1"))
    assert get_player_tier("结丹期初期") > get_player_tier("炼气期1层")


async def test_万兽齐鸣_榜单最多列八人_超出显示总数(db, monkeypatch):
    pin_random(monkeypatch, random=lambda: 0.99)
    ch = await _tide(db, [(str(i), 1000 - i, "炼气期1层") for i in range(1, 12)])
    text = ch.sent[0].embed.fields[0].value
    assert "共 11 名修士坚守城池" in text
    assert text.count("贡献") == 8


async def test_万兽齐鸣_守城者离城不发奖励_且点名脱逃(db, monkeypatch):
    pin_random(monkeypatch, random=lambda: 0.99)
    await _add_event(db, beast_tide=True)
    await _add_player(db, "1", city="别处", spirit_stones=0)
    await _join(db, "1", "defense", 500)
    await _add_player(db, "2", city="别处", spirit_stones=0)
    await _join(db, "2", "crystal", 0)
    ch = FakeChannel()
    parts = await ev._get_participants(EID)

    await ev._settle_beast_tide(None, ch, EID, CITY, await ev._get_defense_participants(EID), parts, {"1", "2"})

    assert (await _row(db, "1")).spirit_stones == 0 and await _equipment(db, "1") == []
    text = ch.sent[0].embed.fields[0].value
    assert "无人参与守城" not in text or "脱逃" in text
    assert "道友2" in text and "临阵脱逃" in text                           # 参加了灵雨活动又离城的人


async def test_万兽齐鸣_无人守城(db, monkeypatch):
    pin_random(monkeypatch, random=lambda: 0.99)
    ch = await _tide(db, [])
    assert ch.sent[0].embed.fields[0].value == "无人参与守城。"


async def test_万兽齐鸣_袖手旁观者按概率损失寿元_最低剩一年(db, monkeypatch):
    pin_random(monkeypatch, randint=lambda a, b: 15, random=lambda: 0.0)
    await _add_event(db, beast_tide=True)
    await _add_player(db, "weak", lifespan=10)
    await _add_player(db, "strong", lifespan=100)

    ch = await _tide_with_existing(db, ch=None)

    assert (await _row(db, "weak")).lifespan == 1                           # MAX(1, 10-15)
    assert (await _row(db, "strong")).lifespan == 85
    assert isinstance(ch.last.view, SlackerView) and "摸鱼榜" in ch.last.embed.title


async def _tide_with_existing(db, ch=None):
    ch = ch or FakeChannel()
    parts = await ev._get_participants(EID)
    await ev._settle_beast_tide(None, ch, EID, CITY, await ev._get_defense_participants(EID), parts,
                                {p["discord_id"] for p in parts})
    return ch


async def test_万兽齐鸣_运气好没被袭击就不发摸鱼榜(db, monkeypatch):
    pin_random(monkeypatch, random=lambda: 0.99)
    await _add_event(db, beast_tide=True)
    await _add_player(db, "lucky", lifespan=100)

    ch = await _tide_with_existing(db)

    assert (await _row(db, "lucky")).lifespan == 100
    assert len(ch.sent) == 1                                               # 只有守城结算，没有摸鱼榜


async def test_万兽齐鸣_参加了灵雨活动或守城的人不会被袭击(db, monkeypatch):
    pin_random(monkeypatch, random=lambda: 0.0)
    await _tide(db, [("d", 100, "炼气期1层")], others=[("c", "crystal", CITY)])
    assert (await _row(db, "d")).lifespan == 100 and (await _row(db, "c")).lifespan == 100


async def test_万兽齐鸣_闭关采集接任务中的人不算袖手旁观(db, monkeypatch):
    pin_random(monkeypatch, random=lambda: 0.0)
    await _add_event(db, beast_tide=True)
    await _add_player(db, "cult", cultivating_until=time.time() + 999)
    await _add_player(db, "gath", gathering_until=time.time() + 999)
    await _add_player(db, "quest", active_quest="{}")
    await _tide_with_existing(db)
    for uid in ("cult", "gath", "quest"):
        assert (await _row(db, uid)).lifespan == 100


async def test_万兽齐鸣_摸鱼榜十人一页(db, monkeypatch):
    pin_random(monkeypatch, randint=lambda a, b: 5, random=lambda: 0.0)
    await _add_event(db, beast_tide=True)
    for i in range(25):
        await _add_player(db, f"s{i:02d}", lifespan=100)

    ch = await _tide_with_existing(db)

    assert len(ch.last.view.pages) == 3 and [len(p) for p in ch.last.view.pages] == [10, 10, 5]
    assert "第 1 页 / 共 3 页" in ch.last.embed.footer.text


# =============================================================================
# F. 摸鱼榜翻页
# =============================================================================

def _slacker(n=25):
    pages = [[(f"n{i}", "炼气期1层", 5) for i in range(j, min(j + 10, n))] for j in range(0, n, 10)]
    return SlackerView(pages, CITY)


async def test_摸鱼榜_第一页上一页禁用_最后一页下一页禁用():
    v = _slacker()
    assert v.prev_btn.disabled and not v.next_btn.disabled
    i = FakeInteraction(user_id=1)
    await v.next_btn.callback(i)
    assert v.page == 1 and not v.prev_btn.disabled and not v.next_btn.disabled
    assert "第 2 页 / 共 3 页" in i.last.embed.footer.text
    await v.next_btn.callback(FakeInteraction(user_id=1))
    assert v.page == 2 and v.next_btn.disabled
    await v.prev_btn.callback(FakeInteraction(user_id=1))
    assert v.page == 1


def test_摸鱼榜_只有一页时两个按钮都禁用():
    v = _slacker(3)
    assert v.prev_btn.disabled and v.next_btn.disabled


def test_摸鱼榜_页面内容():
    embed = ev._build_slacker_embed([[("甲", "炼气期1层", 7)]], 0, CITY)
    assert "甲" in embed.fields[0].value and "损失 **7年** 寿元" in embed.fields[0].value and CITY in embed.description


# =============================================================================
# G. 参与活动（灵雨结晶 / 感悟 / 淬体 / 守城）
# =============================================================================

def it(uid="1"):
    return FakeInteraction(user_id=int(uid))


@pytest.fixture
async def active(db):
    await _add_event(db)
    await _add_player(db, "1", spirit_stones=0, physique=8, cultivation=0)


async def _participations(db, uid="1"):
    from sqlalchemy import text
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        rows = (await s.execute(text("SELECT activity FROM public_event_participants WHERE event_id=:e AND discord_id=:u"),
                                {"e": EID, "u": uid})).fetchall()
    return sorted(r[0] for r in rows)


async def test_参与_没有角色(db):
    await _add_event(db)
    i = it()
    await ev._handle_activity(i, EID, CITY, "crystal")
    assert i.said("尚未踏入修仙之路") and i.last.ephemeral


async def test_参与_事件已结束(db):
    await _add_event(db, status="ended")
    await _add_player(db, "1")
    i = it()
    await ev._handle_activity(i, EID, CITY, "crystal")
    assert i.said("此事件已结束")


async def test_参与_已坐化与不在城内(db, active):
    await _add_player(db, "2", is_dead=True)
    await _add_player(db, "3", city="别处")
    for uid, phrase in [("2", "已坐化"), ("3", "你不在 **铁甲城**")]:
        i = it(uid)
        await ev._handle_activity(i, EID, CITY, "crystal")
        assert i.said(phrase)
        assert await _participations(db, uid) == []


async def test_参与_灵雨结晶_发灵石_按概率发材料(db, active, monkeypatch):
    pin_random(monkeypatch, randint=lambda a, b: b, random=lambda: 0.0)
    i = it()

    await ev._handle_activity(i, EID, CITY, "crystal")

    assert (await _row(db, "1")).spirit_stones == 400
    inv = await db["inventory"].get_inventory("1")
    assert inv and all(q in (1, 2) for q in inv.values())
    assert i.said("获得 **400 灵石**") and "材料：" in i.last.content and "无" not in i.last.content.split("材料：")[1]
    assert await _participations(db) == ["crystal"]


async def test_参与_灵雨结晶_没出材料时显示无(db, active, monkeypatch):
    pin_random(monkeypatch, randint=lambda a, b: a, random=lambda: 0.99)
    i = it()
    await ev._handle_activity(i, EID, CITY, "crystal")
    assert i.said("材料：无") and (await _row(db, "1")).spirit_stones == 150
    assert await db["inventory"].get_inventory("1") == {}


async def test_参与_灵雨结晶_稀有材料每份只给一个(db, active, monkeypatch):
    from utils.items import ITEMS
    rare = next(k for k, v in ITEMS.items() if v.get("type") == "herb" and v.get("rarity") in ("珍贵", "绝世"))
    pin_random(monkeypatch, random=lambda: 0.0, choices=lambda pop, weights, k: [rare], randint=lambda a, b: b)
    await ev._handle_activity(it(), EID, CITY, "crystal")
    assert (await db["inventory"].get_inventory("1")).get(rare) == 1


async def test_参与_灵雨感悟_修为到账_小概率涨属性(db, active, monkeypatch):
    pin_random(monkeypatch, randint=lambda a, b: 200, random=lambda: 0.0, choice=lambda seq: "soul")
    i = it()
    await ev._handle_activity(i, EID, CITY, "enlighten")
    p = await _row(db, "1")
    assert p.cultivation == 200 and p.soul == 6 and i.said("神识 +1")

    await _add_player(db, "2", soul=5)
    pin_random(monkeypatch, randint=lambda a, b: 80, random=lambda: 0.99, choice=lambda seq: "soul")
    i2 = it("2")
    await ev._handle_activity(i2, EID, CITY, "enlighten")
    p2 = await _row(db, "2")
    assert p2.cultivation == 80 and p2.soul == 5 and i2.said("打坐，修为 +80")


async def test_参与_灵雨淬体_体魄不足拒绝(db, active):
    await _add_player(db, "2", physique=6)
    i = it("2")
    await ev._handle_activity(i, EID, CITY, "temper")
    assert i.said("体魄不足") and await _participations(db, "2") == []         # 被拒绝不占名额


async def test_参与_灵雨淬体_按概率涨体魄和根骨(db, active, monkeypatch):
    pin_random(monkeypatch, randint=lambda a, b: 250, random=lambda: 0.0)
    i = it()
    await ev._handle_activity(i, EID, CITY, "temper")
    p = await _row(db, "1")
    assert (p.cultivation, p.physique, p.bone) == (250, 9, 6)
    assert i.said("体魄 +1") and i.said("根骨 +1")


async def test_参与_灵雨淬体_没涨属性时只有修为(db, active, monkeypatch):
    pin_random(monkeypatch, randint=lambda a, b: 100, random=lambda: 0.99)
    i = it()
    await ev._handle_activity(i, EID, CITY, "temper")
    p = await _row(db, "1")
    assert (p.cultivation, p.physique, p.bone) == (100, 8, 5) and not i.said("体魄 +1")


async def test_参与_守城_记下战力贡献_不能重复加入(db, active, monkeypatch):
    pin_random(monkeypatch, uniform=lambda a, b: 1.0)
    i = it()
    await ev._handle_activity(i, EID, CITY, "defense")
    from sqlalchemy import text
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        power = (await s.execute(text("SELECT contribution FROM public_event_participants WHERE discord_id='1' AND activity='defense'"))).scalar()
    assert power > 0 and i.said(f"战力贡献：**{power}**")

    again = it()
    await ev._handle_activity(again, EID, CITY, "defense")
    assert again.said("你已参与守城") and await _participations(db) == ["defense"]


async def test_参与_两次非守城活动上限(db, active):
    await _join(db, "1", "crystal", joined_ago=3000)
    await _join(db, "1", "enlighten", joined_ago=2000)
    i = it()
    await ev._handle_activity(i, EID, CITY, "temper")
    assert i.said("已参与 2 次活动，已达上限") and await _participations(db) == ["crystal", "enlighten"]


async def test_参与_十分钟冷却(db, active):
    await _join(db, "1", "crystal", joined_ago=60)
    i = it()
    await ev._handle_activity(i, EID, CITY, "enlighten")
    assert i.said("冷却中") and (i.said("9 分") or i.said("8 分"))        # 刚好差一点点到九分钟
    assert await _participations(db) == ["crystal"]


async def test_参与_冷却过了可以再参与(db, active):
    await _join(db, "1", "crystal", joined_ago=601)
    await ev._handle_activity(it(), EID, CITY, "enlighten")
    assert await _participations(db) == ["crystal", "enlighten"]


async def test_参与_守城不占活动名额也不受冷却限制(db, active):
    await _join(db, "1", "crystal", joined_ago=10)
    await _join(db, "1", "enlighten", joined_ago=5)
    i = it()
    await ev._handle_activity(i, EID, CITY, "defense")
    assert i.said("加入守城队伍")


async def test_参与_同一活动连点_奖励只发一次(db, active, monkeypatch):
    """两次点击都读到『还没参与过』再去 INSERT：参与记录的主键是（事件, 玩家, 活动），
    第二次被数据库拒绝（『操作失败』）或在检查阶段就撞上冷却 —— 无论哪条路，奖励都只发一次。"""
    pin_random(monkeypatch, randint=lambda a, b: 300, random=lambda: 0.99)
    its = [it(), it()]

    await asyncio.gather(*(ev._handle_activity(i, EID, CITY, "crystal") for i in its))

    assert (await _row(db, "1")).spirit_stones == 300                      # 只发了一次
    assert await _participations(db) == ["crystal"]
    assert len([i for i in its if i.said("操作失败") or i.said("冷却中")]) == 1


async def test_参与_同一活动的第二次插入被主键拒绝(db, active, monkeypatch):
    """绕过检查阶段直接验证数据库那一层：已有同一活动的记录时，INSERT 失败 → 提示操作失败，且不发奖励。"""
    pin_random(monkeypatch, randint=lambda a, b: 300)
    await _join(db, "1", "crystal", joined_ago=99999)                       # 很久以前的记录，冷却与上限检查都放行
    i = it()
    await ev._handle_activity(i, EID, CITY, "crystal")
    assert i.said("操作失败") and (await _row(db, "1")).spirit_stones == 0


async def test_参与_面板按钮分别对应四种活动(db, active, monkeypatch):
    seen = []

    async def _spy(interaction, event_id, city, activity):
        seen.append((event_id, city, activity))
    monkeypatch.setattr(ev, "_handle_activity", _spy)
    view = SpiritRainView(EID, CITY)

    for name in ("crystal", "enlighten", "temper", "join_defense"):
        await getattr(view, name).callback(it())

    assert seen == [(EID, CITY, a) for a in ("crystal", "enlighten", "temper", "defense")]
    assert view.timeout is None


async def test_参与_面板返回主菜单(db, active):
    class _Msg:
        def __init__(self):
            self.edits = []

        async def edit(self, **kw):
            self.edits.append(kw)

    cult = types.SimpleNamespace()
    view = SpiritRainView(EID, CITY, types.SimpleNamespace(bot=types.SimpleNamespace(cogs={"Cultivation": cult})))
    i = it()
    i.message = _Msg()

    await view.back_menu.callback(i)

    assert i.response.deferred and i.message.edits and i.message.edits[0]["view"] is not None   # 主菜单覆盖在原消息上

    for pe in (None, types.SimpleNamespace(bot=types.SimpleNamespace(cogs={}))):
        i2 = it()
        await SpiritRainView(EID, CITY, pe).back_menu.callback(i2)
        assert i2.said("无法返回")


def test_事件模块导出的入口():
    assert SpiritRainEvent.META["type"] == "spirit_rain" and SpiritRainEvent.META["duration_real_mins"] == 60
    assert SpiritRainEvent.on_trigger is ev.on_trigger and SpiritRainEvent.on_settle is ev.on_settle


# =============================================================================
# H. 频道取不到时（B16）
# =============================================================================

async def test_频道取不到时_守城奖励照发_普通灵雨(db, monkeypatch):
    """B16 回归：结算函数曾在最前面 `if not channel: return`，频道取不到（没配环境变量、
    bot 刚重启频道还没缓存）时守城奖励根本不发，而 on_settle 已把事件标成 ended —— 奖励永久丢失。"""
    pin_random(monkeypatch, randint=lambda a, b: b)
    await _add_player(db, "1", spirit_stones=0, reputation=0)

    await ev._settle_spirit_rain_only(None, CITY, [P("1", activity="defense")])

    p = await _row(db, "1")
    assert (p.spirit_stones, p.reputation) == (300, 5)


async def test_频道取不到时_守城奖励照发_万兽齐鸣(db, monkeypatch):
    pin_random(monkeypatch, randint=lambda a, b: b, random=lambda: 0.99)
    await _add_event(db, beast_tide=True)
    await _add_player(db, "1", spirit_stones=0, reputation=0)
    await _join(db, "1", "defense", 900)
    parts = await ev._get_participants(EID)

    await ev._settle_beast_tide(None, None, EID, CITY, await ev._get_defense_participants(EID), parts, {"1"})

    p = await _row(db, "1")
    assert (p.spirit_stones, p.reputation) == (5000, 50) and len(await _equipment(db, "1")) == 2


async def test_频道取不到时_不对袖手旁观者扣寿元(db, monkeypatch):
    """惩罚需要公告才执行：玩家看不到公告，就不该悄悄被扣寿元。奖励照发，惩罚不执行。"""
    pin_random(monkeypatch, randint=lambda a, b: 15, random=lambda: 0.0)
    await _add_event(db, beast_tide=True)
    await _add_player(db, "idle", lifespan=100)
    await _add_player(db, "def", spirit_stones=0)
    await _join(db, "def", "defense", 100)
    parts = await ev._get_participants(EID)

    await ev._settle_beast_tide(None, None, EID, CITY, await ev._get_defense_participants(EID), parts, {"def"})

    assert (await _row(db, "idle")).lifespan == 100
    assert (await _row(db, "def")).spirit_stones > 0


async def test_结算入口_频道缺失时整条链路仍然发奖励并结束事件(db, monkeypatch):
    pin_random(monkeypatch, randint=lambda a, b: b)
    await _add_event(db, beast_tide=False)
    await _add_player(db, "1", spirit_stones=0)
    await _join(db, "1", "defense", 100)

    await ev.on_settle(None, None, await _event_dict(db))

    assert (await _row(db, "1")).spirit_stones == 300 and await _status(db) == "ended"


# =============================================================================
# I. 奖励表与概率阈值（把数值本身钉住：改动应当是有意的）
# =============================================================================

def spy_randint(calls, ret="low"):
    def _ri(a, b):
        calls.append((a, b))
        return a if ret == "low" else b
    return _ri


def sequence(*values):
    it_ = iter(values)
    return lambda: next(it_)


async def test_万兽齐鸣_各名次的灵石区间(db, monkeypatch):
    calls = []
    pin_random(monkeypatch, randint=spy_randint(calls), random=lambda: 0.99)
    await _tide(db, [(str(i), 1000 - i, "炼气期1层") for i in range(1, 6)])
    assert {(3000, 5000), (1500, 2500), (300, 800)} <= set(calls)
    assert calls.count((1500, 2500)) == 2                                  # 二、三名各一次
    assert calls.count((300, 800)) == 2                                    # 四、五名


async def test_万兽齐鸣_寿元损失区间(db, monkeypatch):
    calls = []
    pin_random(monkeypatch, randint=spy_randint(calls), random=lambda: 0.0)
    await _add_event(db, beast_tide=True)
    await _add_player(db, "idle", lifespan=100)
    await _tide_with_existing(db)
    assert calls == [(5, 15)] and (await _row(db, "idle")).lifespan == 95


async def test_万兽齐鸣_袭击概率是百分之三十(db, monkeypatch):
    await _add_event(db, beast_tide=True)
    await _add_player(db, "a", lifespan=100)
    await _add_player(db, "b", lifespan=100)
    pin_random(monkeypatch, randint=lambda a, b: 5, random=sequence(0.29, 0.31))
    await _tide_with_existing(db)
    lifespans = sorted([(await _row(db, "a")).lifespan, (await _row(db, "b")).lifespan])
    assert lifespans == [95, 100]                                          # 恰好一个被袭击


async def test_万兽齐鸣_离城的守城者不在脱逃名单里_参加灵雨活动后离城的才在(db, monkeypatch):
    pin_random(monkeypatch, random=lambda: 0.99)
    await _add_event(db, beast_tide=True)
    await _add_player(db, "1", city="别处", spirit_stones=0)
    await _join(db, "1", "defense", 500)
    await _add_player(db, "2", city="别处", spirit_stones=0)
    await _join(db, "2", "crystal", 0)
    ch = FakeChannel()
    parts = await ev._get_participants(EID)

    await ev._settle_beast_tide(None, ch, EID, CITY, await ev._get_defense_participants(EID), parts, {"1", "2"})

    text = ch.sent[0].embed.fields[0].value
    assert "道友2" in text and "临阵脱逃" in text
    assert "道友1" not in text


async def test_参与_各活动的奖励区间(db, active, monkeypatch):
    calls = []
    pin_random(monkeypatch, randint=spy_randint(calls), random=lambda: 0.99, uniform=lambda a, b: (calls.append(("u", a, b)), 1.0)[1])
    await _add_player(db, "2", physique=8)
    await _add_player(db, "3", physique=8)
    await _add_player(db, "4", physique=8)
    await ev._handle_activity(it("1"), EID, CITY, "crystal")
    await ev._handle_activity(it("2"), EID, CITY, "enlighten")
    await ev._handle_activity(it("3"), EID, CITY, "temper")
    await ev._handle_activity(it("4"), EID, CITY, "defense")
    assert (150, 400) in calls and (80, 200) in calls and (100, 250) in calls
    assert ("u", 0.9, 1.1) in calls                                         # 守城战力 ±10% 浮动


async def test_参与_灵雨结晶出材料的概率是百分之六十五(db, active, monkeypatch):
    for uid, roll, expect_items in [("11", 0.64, True), ("12", 0.66, False)]:
        await _add_player(db, uid, spirit_stones=0)
        pin_random(monkeypatch, randint=lambda a, b: a, random=lambda r=roll: r)
        await ev._handle_activity(it(uid), EID, CITY, "crystal")
        got = await db["inventory"].get_inventory(uid)
        assert bool(got) is expect_items, roll


async def test_参与_灵雨感悟涨属性的概率是百分之十五(db, active, monkeypatch):
    for uid, roll, gained in [("21", 0.14, True), ("22", 0.16, False)]:
        await _add_player(db, uid, soul=5)
        pin_random(monkeypatch, randint=lambda a, b: 100, random=lambda r=roll: r, choice=lambda seq: "soul")
        await ev._handle_activity(it(uid), EID, CITY, "enlighten")
        assert (await _row(db, uid)).soul == (6 if gained else 5), roll


async def test_参与_灵雨淬体体魄百分之十二_根骨百分之八(db, active, monkeypatch):
    # (玩家, 依次掷出的两个随机数: 体魄、根骨, 期望的 (体魄, 根骨))
    cases = [("31", (0.11, 0.09), (9, 5)), ("32", (0.13, 0.07), (8, 6)),
             ("33", (0.13, 0.09), (8, 5)), ("34", (0.11, 0.07), (9, 6))]
    for uid, rolls, (phys, bone) in cases:
        await _add_player(db, uid, physique=8, bone=5)
        pin_random(monkeypatch, randint=lambda a, b: 100, random=sequence(*rolls))
        await ev._handle_activity(it(uid), EID, CITY, "temper")
        p = await _row(db, uid)
        assert (p.physique, p.bone) == (phys, bone), rolls


async def test_触发_没有公告频道时不抛异常_事件不受影响(db):
    """on_trigger 曾在频道为空时直接 channel.send，抛 AttributeError（调度器因此被弄死，见 B17）。"""
    await _add_event(db)
    await ev.on_trigger(None, None, EID, CITY)
    assert (await _event_dict(db))["message_id"] is None and await _status(db) == "active"
