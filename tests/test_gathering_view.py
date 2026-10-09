"""采集（utils/views/gathering.py）：掉落表、开始采集的各项检查与扣费。结算见 test_notifiers.py。

B55 —— 点『开始采集』时只检查了闭关 / 采集中 / 寿元，其余条件要么只在打开菜单时查过一次、要么根本没查：
  · 已坐化的玩家（旧面板）还能开始采集、照扣寿元；
  · 手上有进行中的任务也能同时采集（茶馆接任务时反过来会拒绝『采集中』），一份时间拿两份奖励；
  · 守城期间、万宝楼拍卖进行中也能采集（菜单入口挡了，旧面板里的按钮没挡）；
  · 闭关的检查只在读库之后，写入的 UPDATE 里没有这个条件。
  现在这些条件统一写进 UPDATE 的 WHERE，并补上守城 / 拍卖检查。
B56 —— 观察（未改）：`速灵丹` 的描述是『持续 24 小时』的限时 buff，但开始采集时 `consume_once_buff` 把它当一次性的
  用掉了，24 小时里只有第一次采集受益。`百草增益丹` 描述是一次性，却和它用同一个 buff 键、也带 24 小时到期。
  到底该限时还是一次性要你定（两种丹药的描述互相矛盾），这里先把现状钉住。
"""

import asyncio
import json
import math
import random
import time

import pytest

from tests.conftest import make_player
from tests.discord_fakes import FakeInteraction
from utils.items.fish import FISH
from utils.items.herbs import HERBS
from utils.items.materials import MATERIALS
from utils.items.wood import WOOD
from utils.views import gathering as gv
from utils.views.gathering import (GATHER_OPTIONS, RARITY_WEIGHTS_BASE, GatherView, _ore_pool,
                                   _pick_rarity, _rarity_weights, roll_gathering_rewards)

U = "1001"
YEAR = 7200


# --- 掉落：纯函数 -------------------------------------------------------------

def test_稀有度权重_随时间与境界增加稀有项():
    base = _rarity_weights(0, 0)
    assert base == RARITY_WEIGHTS_BASE
    w = _rarity_weights(2, 10)                                  # 时间加成 3，境界加成 3
    assert w["稀有"] == pytest.approx(20 + 3 + 3) and w["珍贵"] == pytest.approx(5 + 0.9 + 0.9)
    assert w["普通"] == 70


def test_稀有度权重_加成封顶():
    w = _rarity_weights(1000, 1000)
    assert w["稀有"] == pytest.approx(20 + 8 + 10) and w["绝世"] == pytest.approx(0.3 + 8 * 0.05 + 10 * 0.08)


def test_挑选稀有度_只会选出权重表里有的(monkeypatch):
    seen = {}
    monkeypatch.setattr(gv.random, "choices", lambda pop, weights, k: (seen.update(pop=pop, w=weights), [pop[-1]])[1])
    assert _pick_rarity({"普通": 1, "稀有": 2}) == "稀有" and seen["w"] == [1, 2]


@pytest.mark.parametrize("gtype,source", [("采矿", MATERIALS), ("采药", HERBS), ("伐木", WOOD), ("钓鱼", FISH)])
def test_掉落池_按采集类型(gtype, source):
    pool = {m["name"] for m in _ore_pool("某地", gtype)}
    expected = {m["name"] for m in source.values() if gtype != "采矿" or m["type"] == "ore"}
    assert pool == expected


def test_掉落池_未知类型当采矿():
    assert {m["name"] for m in _ore_pool("某地", "未知")} == {m["name"] for m in _ore_pool("某地", "采矿")}


@pytest.mark.parametrize("gtype", ["采矿", "采药", "伐木", "钓鱼"])
def test_掉落_产出都是池里的东西_按数量降序(gtype):
    random.seed(1)
    result = roll_gathering_rewards(2, 5, "某地", gtype)
    names = {m["name"] for m in _ore_pool("某地", gtype)}
    assert result and all(n in names and q > 0 for n, q in result)
    assert [q for _, q in result] == sorted([q for _, q in result], reverse=True)


def test_掉落_总次数下限(monkeypatch):
    monkeypatch.setattr(gv.random, "randint", lambda a, b: a)
    total = sum(q for _, q in roll_gathering_rewards(0.25, 0, "某地"))
    assert total == 1                                           # max(1, int(0.5)) = 1 次
    total = sum(q for _, q in roll_gathering_rewards(3, 10, "某地"))
    assert total == 6 + 2 + 0                                   # int(3*2) + 10//5 + randint 下限 0


def test_掉落_采集加成按倍数放大(monkeypatch):
    monkeypatch.setattr(gv.random, "randint", lambda a, b: a)
    base = sum(q for _, q in roll_gathering_rewards(2, 0, "某地"))
    boosted = sum(q for _, q in roll_gathering_rewards(2, 0, "某地", gather_bonus=0.5))
    assert base == 4 and boosted == int(4 * 1.5)


def test_掉落_寒玉窟偏向水属性(monkeypatch):
    monkeypatch.setattr(gv.random, "random", lambda: 0.0)       # 偏向必中
    monkeypatch.setattr(gv, "_pick_rarity", lambda w: "稀有")
    water = {m["name"] for m in MATERIALS.values() if m["type"] == "ore" and m["rarity"] == "稀有" and m.get("element") == "水"}
    assert water
    result = roll_gathering_rewards(5, 0, "寒玉窟")
    assert {n for n, _ in result} <= water


def test_掉落_偏向只有四成概率生效(monkeypatch):
    monkeypatch.setattr(gv.random, "random", lambda: 0.99)      # 偏向不中：候选还是整个稀有池
    monkeypatch.setattr(gv, "_pick_rarity", lambda w: "稀有")
    monkeypatch.setattr(gv.random, "choice", lambda seq: seq[-1])
    result = roll_gathering_rewards(1, 0, "寒玉窟")
    last = [m for m in MATERIALS.values() if m["type"] == "ore" and m["rarity"] == "稀有"][-1]["name"]
    assert result == [(last, sum(q for _, q in result))]


def test_掉落_非偏向地区不受影响(monkeypatch):
    monkeypatch.setattr(gv.random, "random", lambda: 0.0)
    monkeypatch.setattr(gv, "_pick_rarity", lambda w: "稀有")
    monkeypatch.setattr(gv.random, "choice", lambda seq: seq[-1])
    last = [m for m in MATERIALS.values() if m["type"] == "ore" and m["rarity"] == "稀有"][-1]["name"]
    assert roll_gathering_rewards(1, 0, "漠北荒漠")[0][0] == last


def test_掉落_某稀有度没有候选时退回普通(monkeypatch):
    monkeypatch.setattr(gv, "_pick_rarity", lambda w: "不存在的稀有度")
    result = roll_gathering_rewards(1, 0, "某地")
    pool_names = {m["name"] for m in _ore_pool("某地", "采矿") if m["rarity"] == "普通"}
    assert result and {n for n, _ in result} <= pool_names


def test_掉落_连普通都没有时跳过(monkeypatch):
    monkeypatch.setattr(gv, "_ore_pool", lambda r, t: [{"name": "x", "rarity": "稀有"}])
    monkeypatch.setattr(gv, "_pick_rarity", lambda w: "珍贵")
    assert roll_gathering_rewards(1, 0, "某地") == []


def test_掉落_池为空返回空(monkeypatch):
    monkeypatch.setattr(gv, "_ore_pool", lambda r, t: [])
    assert roll_gathering_rewards(1, 0, "某地") == []


# --- 面板 ---------------------------------------------------------------------

def test_面板_寿元不足的时长按钮被禁用():
    v = GatherView(FakeInteraction(U).user, None, {"lifespan": 2}, "采药", "百草谷")
    flags = {b.years: b.disabled for b in v.children}
    assert flags == {y: y > 2 for y, *_ in GATHER_OPTIONS}
    assert all("🌿" in b.label for b in v.children)


def test_面板_按钮文案含现实时长():
    v = GatherView(FakeInteraction(U).user, None, {"lifespan": 100}, "采矿", "漠北荒漠")
    assert "3个月" in v.children[0].label and "现实 30 分钟" in v.children[0].label


# --- 开始采集 -----------------------------------------------------------------

async def _add(db, uid=U, **kw):
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        p = make_player(D, uid, stones=0)
        p.name = f"道友{uid}"
        p.lifespan = 100
        for k, v in kw.items():
            setattr(p, k, v)
        s.add(p)
        await s.commit()


async def row(db, uid=U):
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        return await s.get(D.Player, uid)


async def start(years=1, uid=U, gtype="采药", region="百草谷", lifespan=100):
    v = GatherView(FakeInteraction(uid).user, None, {"lifespan": lifespan}, gtype, region)
    btn = next(b for b in v.children if b.years == years)
    i = FakeInteraction(uid)
    await btn.callback(i)
    return i, v


async def test_开始采集_成功_扣寿元_记录结束时间与类型(db):
    await _add(db)
    i, v = await start(2)
    p = await row(db)
    assert p.lifespan == 98 and p.gathering_type == "采药" and p.gathering_until == pytest.approx(time.time() + 2 * YEAR, abs=5)
    assert p.gathering_bonus == 0
    assert "开始在 **百草谷** 采药" in i.last and "4 小时" in i.last and i.response.deferred
    assert v.is_finished()


async def test_开始采集_短时长也至少扣1年寿元(db):
    """现状：寿元按 ceil(年数) 扣，3个月也要 1 年。"""
    await _add(db)
    await start(0.25)
    assert (await row(db)).lifespan == 99


@pytest.mark.parametrize("years", [y for y, *_ in GATHER_OPTIONS])
async def test_开始采集_各时长扣费等于向上取整(db, years):
    await _add(db)
    await start(years)
    assert (await row(db)).lifespan == 100 - math.ceil(years)


async def test_开始采集_分钟显示(db):
    await _add(db)
    i, _ = await start(0.25)
    assert "30 分钟" in i.last


async def test_开始采集_没有角色(db):
    i, v = await start(1, uid="9999")
    assert "数据异常" in i.last and i.last.ephemeral and v.is_finished()


async def test_开始采集_寿元不足(db):
    await _add(db, lifespan=1)
    i, _ = await start(5, lifespan=100)                         # 面板数据过期，库里只剩 1
    assert "寿元不足" in i.last and (await row(db)).lifespan == 1 and (await row(db)).gathering_until is None


async def test_开始采集_闭关中_采集中被拒(db):
    await _add(db, cultivating_until=time.time() + 3600)
    i, _ = await start(1)
    assert "正在闭关" in i.last and (await row(db)).lifespan == 100
    await _add(db, "1002", gathering_until=time.time() + 3600)
    i, _ = await start(1, uid="1002")
    assert "正在采集中" in i.last and (await row(db, "1002")).lifespan == 100


async def test_开始采集_上次已结束的闭关和采集不算占用(db):
    await _add(db, cultivating_until=time.time() - 5, gathering_until=time.time() - 5)
    i, _ = await start(1)
    assert (await row(db)).gathering_until > time.time()


# --- B55 ----------------------------------------------------------------------

async def test_B55_已坐化不能采集(db):
    await _add(db, is_dead=1)
    i, v = await start(1)
    assert "坐化" in i.last and (await row(db)).lifespan == 100 and (await row(db)).gathering_until is None


async def test_B55_有进行中的任务不能采集(db):
    await _add(db, active_quest=json.dumps({"id": "q"}), quest_due=time.time() + 3600)
    i, _ = await start(1)
    assert "任务" in i.last and (await row(db)).lifespan == 100 and (await row(db)).gathering_until is None


async def test_B55_守城期间不能采集(db):
    from sqlalchemy import text
    await _add(db)
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        await s.execute(text("INSERT INTO public_events (event_id, event_type, title, started_at, ends_at, status, data) "
                             "VALUES ('E1', 'x', 't', 0, 9e12, 'active', '{}')"))
        await s.execute(text("INSERT INTO public_event_participants (event_id, discord_id, activity, joined_at) "
                             "VALUES ('E1', :u, 'defense', 0)"), {"u": U})
        await s.commit()
    i, _ = await start(1)
    assert "守城" in i.last and (await row(db)).gathering_until is None


async def test_B55_拍卖进行中的万宝楼内不能采集(db, monkeypatch):
    await _add(db)

    async def locked(uid):
        return True
    monkeypatch.setattr("utils.events.public.wanbao.is_auction_locked", locked)
    i, _ = await start(1)
    assert "拍卖会进行中" in i.last and (await row(db)).gathering_until is None


async def test_B55_检查之后才开始闭关_写入被条件挡住(db, monkeypatch):
    await _add(db)
    D = db["db_async"]
    from sqlalchemy import update
    # 在 UPDATE 之前插入另一个事务：开始闭关
    from sqlalchemy.ext.asyncio import AsyncSession
    orig_exec, state = AsyncSession.execute, {"done": False}

    async def hooked(self, stmt, *a, **k):
        if not state["done"] and "UPDATE players SET gathering_until" in str(stmt):
            state["done"] = True
            async with D.AsyncSessionLocal() as other:
                await other.execute(update(D.Player).values(cultivating_until=time.time() + 3600))
                await other.commit()
        return await orig_exec(self, stmt, *a, **k)
    monkeypatch.setattr(AsyncSession, "execute", hooked)
    i, _ = await start(1)
    monkeypatch.undo()
    p = await row(db)
    assert p.gathering_until is None and p.lifespan == 100 and "状态已变化" in i.last


async def test_连点只开始一次(db):
    await _add(db)
    v = GatherView(FakeInteraction(U).user, None, {"lifespan": 100}, "采药", "百草谷")
    btn = next(b for b in v.children if b.years == 1)
    inters = [FakeInteraction(U) for _ in range(5)]
    await asyncio.gather(*[btn.callback(i) for i in inters])
    assert (await row(db)).lifespan == 99
    started = [i for i in inters if "开始在" in (i.messages[-1].content or "")]
    assert len(started) == 1


# --- buff ---------------------------------------------------------------------

def buffs_json(**entries):
    return json.dumps(entries, ensure_ascii=False)


async def test_采集加成_记录到玩家并消耗一次性buff(db):
    await _add(db, active_buffs=buffs_json(gather_bonus_once={"value": 50}, other={"value": 1}))
    i, _ = await start(1)
    p = await row(db)
    assert p.gathering_bonus == pytest.approx(0.5) and "采集量 +50%" in i.last
    assert json.loads(p.active_buffs) == {"other": {"value": 1}}


async def test_采集冷却缩短_缩短时间_并按缩短后的年数扣寿元(db):
    exp = time.time() + 3600
    await _add(db, active_buffs=buffs_json(gather_cooldown_reduction={"value": 50, "expires_at": exp}))
    i, _ = await start(2)
    p = await row(db)
    assert p.gathering_until == pytest.approx(time.time() + 1 * YEAR, abs=5) and p.lifespan == 99
    assert "时间缩短 50%" in i.last


async def test_采集冷却缩短_不会短过3个月(db):
    await _add(db, active_buffs=buffs_json(gather_cooldown_reduction={"value": 95, "expires_at": time.time() + 3600}))
    await start(0.25)
    assert (await row(db)).gathering_until == pytest.approx(time.time() + 0.25 * YEAR, abs=5)


async def test_B56_限时冷却buff现状_第一次采集就被用掉(db):
    """现状钉住：速灵丹描述『持续 24 小时』，实际第一次采集就把 buff 消耗掉了。要不要改见 ISSUES.md B56。"""
    await _add(db, active_buffs=buffs_json(gather_cooldown_reduction={"value": 30, "expires_at": time.time() + 86400}))
    await start(1)
    assert "gather_cooldown_reduction" not in json.loads((await row(db)).active_buffs)


async def test_过期的buff不生效(db):
    await _add(db, active_buffs=buffs_json(gather_bonus_once={"value": 50, "expires_at": time.time() - 5}))
    await start(1)
    assert (await row(db)).gathering_bonus == 0


async def test_buff表被别处改过_写入失败不重复用(db, monkeypatch):
    """CAS：读到的 buff 表与写回时不一致就放弃（连点时同一个一次性 buff 不能用两遍）。"""
    await _add(db, active_buffs=buffs_json(gather_bonus_once={"value": 50}))
    D = db["db_async"]
    from sqlalchemy import update
    from sqlalchemy.ext.asyncio import AsyncSession
    orig_exec, state = AsyncSession.execute, {"done": False}

    async def hooked(self, stmt, *a, **k):
        if not state["done"] and "UPDATE players SET gathering_until" in str(stmt):
            state["done"] = True
            async with D.AsyncSessionLocal() as other:
                await other.execute(update(D.Player).values(active_buffs=buffs_json(x={"value": 1})))
                await other.commit()
        return await orig_exec(self, stmt, *a, **k)
    monkeypatch.setattr(AsyncSession, "execute", hooked)
    i, _ = await start(1)
    monkeypatch.undo()
    assert "状态已变化" in i.last and (await row(db)).gathering_until is None


def test_掉落_偏向判定是四成不是更高(monkeypatch):
    monkeypatch.setattr(gv.random, "random", lambda: 0.5)       # 不到 0.4 才偏向：0.5 不偏向
    monkeypatch.setattr(gv, "_pick_rarity", lambda w: "稀有")
    monkeypatch.setattr(gv.random, "choice", lambda seq: seq[-1])
    last = [m for m in MATERIALS.values() if m["type"] == "ore" and m["rarity"] == "稀有"][-1]["name"]
    assert roll_gathering_rewards(1, 0, "寒玉窟")[0][0] == last


async def _race_before_update(db, monkeypatch, **values):
    """在 UPDATE 之前，另一个事务改了玩家状态。"""
    from sqlalchemy import update
    from sqlalchemy.ext.asyncio import AsyncSession
    D = db["db_async"]
    orig_exec, state = AsyncSession.execute, {"done": False}

    async def hooked(self, stmt, *a, **k):
        if not state["done"] and "UPDATE players SET gathering_until" in str(stmt):
            state["done"] = True
            async with D.AsyncSessionLocal() as other:
                await other.execute(update(D.Player).values(**values))
                await other.commit()
        return await orig_exec(self, stmt, *a, **k)
    monkeypatch.setattr(AsyncSession, "execute", hooked)


async def test_B55_检查之后才接了任务_写入被条件挡住(db, monkeypatch):
    await _add(db)
    await _race_before_update(db, monkeypatch, active_quest=json.dumps({"id": "q"}))
    i, _ = await start(1)
    monkeypatch.undo()
    p = await row(db)
    assert p.gathering_until is None and p.lifespan == 100 and "状态已变化" in i.last


async def test_检查之后寿元被扣到不够_写入被条件挡住(db, monkeypatch):
    await _add(db)
    await _race_before_update(db, monkeypatch, lifespan=0)
    i, _ = await start(1)
    monkeypatch.undo()
    p = await row(db)
    assert p.gathering_until is None and p.lifespan == 0 and "状态已变化" in i.last


async def test_B55_检查之后才坐化_写入被条件挡住(db, monkeypatch):
    await _add(db)
    await _race_before_update(db, monkeypatch, is_dead=1)
    i, _ = await start(1)
    monkeypatch.undo()
    assert (await row(db)).gathering_until is None and "状态已变化" in i.last
