"""茶馆任务功能测试。

`_apply_quest_rewards` 重写过。旧写法 `member.spirit_stones += X` 单次调用是对的
（变异测试确认过），问题在并发丢更新，以及装备/物品发放各自另开事务。
所以这里多数是功能回归，另有一个并发用例守住真正的修复。
"""

import json
import time

import pytest

from tests.conftest import make_player
from utils import quest_logic
from utils.quest_logic import (cancel_quest, get_active_quest, resolve_quest,
                               start_quest)

COMBAT_QUEST = {
    "id": "t001", "title": "测试战斗任务", "type": "combat",
    "enemy": {"name": "木桩", "power": 1},
    "rewards": {"spirit_stones": 700, "reputation": 8, "cultivation": 40},
}
GATHER_QUEST = {
    "id": "t002", "title": "测试采集任务", "type": "gather",
    "location": "百草谷",
    "rewards": {"spirit_stones": 500, "reputation": 10},
}


@pytest.fixture
async def solo(db):
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        s.add(make_player(D, "u", stones=0))
        await s.commit()
    return "u"


@pytest.fixture
async def party(db):
    """三人小队，party_id 相同。"""
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        for uid in ("a", "b", "c"):
            p = make_player(D, uid, stones=0)
            p.party_id = "party1"
            s.add(p)
        await s.commit()
    return ["a", "b", "c"]


async def _player(db, uid):
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        return await s.get(D.Player, uid)


async def _make_due(db, uid):
    """把任务截止时间拨到过去，模拟"时间到了"。"""
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        p = await s.get(D.Player, uid)
        p.quest_due = time.time() - 1
        await s.commit()


@pytest.fixture
def always_win(monkeypatch):
    """让战斗必胜、且不掉装备，使奖励断言可确定。"""
    monkeypatch.setattr(quest_logic.random, "uniform", lambda a, b: 1.0)
    monkeypatch.setattr(quest_logic.random, "random", lambda: 0.99)   # 普通任务掉率 0.3


# --- 接取 --------------------------------------------------------------------

async def test_接取任务写入玩家(db, solo):
    result = await start_quest(solo, COMBAT_QUEST, "普通")

    assert result["success"]
    assert result["quest_name"] == COMBAT_QUEST["title"]
    p = await _player(db, solo)
    assert json.loads(p.active_quest)["id"] == "t001"
    assert p.quest_due > time.time()


async def test_已有任务时不能再接(db, solo):
    await start_quest(solo, COMBAT_QUEST, "普通")
    result = await start_quest(solo, GATHER_QUEST, "普通")

    assert not result["success"]
    assert "已有" in result["message"]


async def test_闭关中不能接任务(db, solo):
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        p = await s.get(D.Player, solo)
        p.cultivating_until = time.time() + 3600
        await s.commit()

    result = await start_quest(solo, COMBAT_QUEST, "普通")
    assert not result["success"] and "闭关" in result["message"]


async def test_采集中不能接任务(db, solo):
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        p = await s.get(D.Player, solo)
        p.gathering_until = time.time() + 3600
        await s.commit()

    result = await start_quest(solo, COMBAT_QUEST, "普通")
    assert not result["success"] and "采集" in result["message"]


async def test_组队接取时全队都拿到任务(db, party):
    result = await start_quest(party[0], COMBAT_QUEST, "普通")

    assert result["success"]
    assert result["party_size"] == 3
    for uid in party:
        p = await _player(db, uid)
        assert p.active_quest is not None, f"{uid} 应当也接到了任务"


async def test_队员已有任务时整队不能接(db, party):
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        p = await s.get(D.Player, "b")
        p.active_quest = json.dumps({"id": "x"})
        await s.commit()

    result = await start_quest("a", COMBAT_QUEST, "普通")
    assert not result["success"] and "已有任务" in result["message"]


async def test_查询进行中的任务(db, solo):
    assert await get_active_quest(solo) is None

    await start_quest(solo, COMBAT_QUEST, "普通")
    active = await get_active_quest(solo)

    assert active["quest"]["id"] == "t001"
    assert active["player_dict"]["discord_id"] == solo


# --- 结算：时间与前置 --------------------------------------------------------

async def test_没有任务时结算被拒(db, solo):
    result = await resolve_quest(solo)
    assert not result["success"] and "没有" in result["message"]


async def test_时间未到不能结算(db, solo):
    await start_quest(solo, COMBAT_QUEST, "普通")
    result = await resolve_quest(solo)
    assert not result["success"] and "尚未完成" in result["message"]


# --- 结算：战斗胜利与奖励 ----------------------------------------------------

async def test_战斗胜利发放奖励(db, solo, always_win):
    await start_quest(solo, COMBAT_QUEST, "普通")
    await _make_due(db, solo)

    result = await resolve_quest(solo)

    assert result["success"] and result["victory"]
    p = await _player(db, solo)
    assert p.spirit_stones == 700
    assert p.reputation == 8
    assert p.cultivation == 40


async def test_组队胜利时每个队员都拿到全额奖励(db, party, always_win):
    """功能回归：重写后队伍分账仍然每人全额，而不是被平分或漏发。"""
    await start_quest(party[0], COMBAT_QUEST, "普通")
    await _make_due(db, party[0])

    result = await resolve_quest(party[0])

    assert result["success"] and result["victory"] and result["is_party"]
    for uid in party:
        p = await _player(db, uid)
        assert p.spirit_stones == 700, f"{uid} 没拿到灵石奖励"
        assert p.reputation == 8, f"{uid} 没拿到声望奖励"
        assert p.cultivation == 40, f"{uid} 没拿到修为奖励"


async def test_胜利后任务被清除(db, solo, always_win):
    await start_quest(solo, COMBAT_QUEST, "普通")
    await _make_due(db, solo)
    await resolve_quest(solo)

    p = await _player(db, solo)
    assert p.active_quest is None and p.quest_due is None


async def test_组队胜利后全队任务都被清除(db, party, always_win):
    await start_quest(party[0], COMBAT_QUEST, "普通")
    await _make_due(db, party[0])
    await resolve_quest(party[0])

    for uid in party:
        p = await _player(db, uid)
        assert p.active_quest is None, f"{uid} 的任务没被清除"


async def test_物品奖励进背包(db, solo, always_win):
    quest = dict(COMBAT_QUEST, rewards={"spirit_stones": 100, "items": ["灵芝草", "灵芝草"]})
    await start_quest(solo, quest, "普通")
    await _make_due(db, solo)

    await resolve_quest(solo)

    inventory = await db["inventory"].get_inventory(solo)
    assert inventory.get("灵芝草") == 2, "同名物品应当累加而不是互相覆盖"


async def test_装备掉落入库(db, solo, monkeypatch):
    """精英任务必掉装备 —— 验证装备真的落到了 equipment 表。"""
    monkeypatch.setattr(quest_logic.random, "uniform", lambda a, b: 1.0)
    await start_quest(solo, COMBAT_QUEST, "精英")
    await _make_due(db, solo)

    result = await resolve_quest(solo)

    assert result["equipment"] is not None
    equipment = await db["equipment_db"].get_equipment_list(solo)
    assert len(equipment) == 1
    assert equipment[0]["equip_id"] == result["equipment"]["equip_id"]


# --- 结算：采集 --------------------------------------------------------------

async def test_采集任务发放奖励(db, solo, monkeypatch):
    """把随机事件固定成 bonus=1.0 的那条，使奖励可断言。"""
    monkeypatch.setattr(quest_logic.random, "choice",
                        lambda seq: {"desc": "一路顺风。", "bonus": 1.0})
    await start_quest(solo, GATHER_QUEST, "普通")
    await _make_due(db, solo)

    result = await resolve_quest(solo)

    assert result["success"]
    p = await _player(db, solo)
    assert p.spirit_stones == 500
    assert p.reputation == 10


async def test_采集事件加成会放大奖励(db, solo, monkeypatch):
    monkeypatch.setattr(quest_logic.random, "choice",
                        lambda seq: {"desc": "发现罕见灵药。", "bonus": 1.5})
    await start_quest(solo, GATHER_QUEST, "普通")
    await _make_due(db, solo)

    result = await resolve_quest(solo)

    assert result["rewards"]["spirit_stones"] == 750      # 500 * 1.5
    assert (await _player(db, solo)).spirit_stones == 750


# --- 结算：失败 --------------------------------------------------------------

async def test_战败逃脱扣寿元并清任务(db, solo, monkeypatch):
    strong = dict(COMBAT_QUEST, enemy={"name": "大能", "power": 10**9})
    monkeypatch.setattr(quest_logic.random, "uniform", lambda a, b: 1.0)

    async def _always_escape(_player_dict):
        return True, 100
    monkeypatch.setattr("utils.combat.roll_escape", _always_escape)

    await start_quest(solo, strong, "普通")
    await _make_due(db, solo)
    before = (await _player(db, solo)).lifespan

    result = await resolve_quest(solo)

    assert result["success"] and not result["victory"] and result["escaped"]
    p = await _player(db, solo)
    assert p.lifespan == before - result["lifespan_loss"]
    assert p.active_quest is None


# --- 取消 --------------------------------------------------------------------

async def test_取消任务(db, solo):
    await start_quest(solo, COMBAT_QUEST, "普通")
    result = await cancel_quest(solo)

    assert result["success"]
    assert (await _player(db, solo)).active_quest is None


async def test_组队取消会清掉全队(db, party):
    await start_quest(party[0], COMBAT_QUEST, "普通")
    result = await cancel_quest(party[0])

    assert result["success"] and result["is_party"]
    for uid in party:
        assert (await _player(db, uid)).active_quest is None


async def test_没有任务时取消被拒(db, solo):
    result = await cancel_quest(solo)
    assert not result["success"]


# --- 并发（这才是重写真正修掉的东西）--------------------------------------

async def test_并发发放奖励不丢更新(db, solo):
    """两次结算同时进行时，奖励必须精确累加。

    旧写法「读出 ORM 对象 → `+=` → 提交」在并发下会丢更新：两次都读到
    同一份余额，后写的覆盖先写的，玩家少拿一份奖励。
    """
    import asyncio
    from utils.quest_logic import _apply_quest_rewards

    rewards = {"spirit_stones": 100, "reputation": 5, "cultivation": 10}
    times = 8

    await asyncio.gather(*[
        _apply_quest_rewards(solo, rewards, None, None, None) for _ in range(times)
    ])

    p = await _player(db, solo)
    assert p.spirit_stones == 100 * times, f"灵石应为 {100 * times}，实际 {p.spirit_stones}"
    assert p.reputation == 5 * times
    assert p.cultivation == 10 * times


# --- 结算只发生一次（B22）-----------------------------------------------------------
# 任务结算有三个入口会撞到一起：茶馆通知循环（每分钟）、玩家手动「完成任务」、队友的结算。
# 原先靠通知循环里一个进程内的集合去重，它只能防「循环自己和自己」（本来就串行），
# 防不住手动领取 —— 两次 resolve_quest 同时到达，奖励发两遍。现在在数据库里原子认领。

import asyncio


@pytest.fixture
def gather_fixed(monkeypatch):
    """采集任务的随机事件取第一个（奖励倍率 1.0），金额可预期。"""
    monkeypatch.setattr(quest_logic.random, "choice", lambda seq: seq[0])


async def _give_quest(db, uid, quest, party_id=None):
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        p = await s.get(D.Player, uid)
        p.active_quest = json.dumps(quest, ensure_ascii=False)
        p.quest_due = time.time() - 1
        await s.commit()


async def test_同时结算同一个任务_奖励只发一次(db, solo, gather_fixed):
    """B22：茶馆通知循环那一分钟恰好撞上玩家手动『完成任务』（或连点按钮）—— 500 灵石发成 1000。"""
    await _give_quest(db, solo, GATHER_QUEST)

    results = await asyncio.gather(resolve_quest(solo), resolve_quest(solo))

    assert sum(1 for r in results if r.get("success")) == 1
    assert (await _player(db, solo)).spirit_stones == 500


async def test_同时结算很多次_也只发一次(db, solo, gather_fixed):
    await _give_quest(db, solo, GATHER_QUEST)
    results = await asyncio.gather(*(resolve_quest(solo) for _ in range(6)))
    assert sum(1 for r in results if r.get("success")) == 1
    assert (await _player(db, solo)).spirit_stones == 500


async def test_先后两次结算_第二次提示没有任务(db, solo, gather_fixed):
    await _give_quest(db, solo, GATHER_QUEST)
    first = await resolve_quest(solo)
    second = await resolve_quest(solo)
    assert first["success"] and not second["success"] and "没有进行中的任务" in second["message"]
    assert (await _player(db, solo)).spirit_stones == 500


async def test_队伍里几个人同时触发结算_每人只拿一份(db, party, gather_fixed):
    """任何一个队员的结算都会处理整队：必须是整队只有一个赢家，否则每个人都被发多份。"""
    for uid in party:
        await _give_quest(db, uid, GATHER_QUEST)

    results = await asyncio.gather(*(resolve_quest(uid) for uid in party))

    assert sum(1 for r in results if r.get("success")) == 1
    for uid in party:
        assert (await _player(db, uid)).spirit_stones == 500, f"{uid} 应当只拿到一份奖励"
        assert (await _player(db, uid)).active_quest is None


async def test_队员先后各自结算_后到的拿不到第二份(db, party, gather_fixed):
    for uid in party:
        await _give_quest(db, uid, GATHER_QUEST)
    first = await resolve_quest(party[0])
    others = [await resolve_quest(uid) for uid in party[1:]]
    assert first["success"] and not any(r.get("success") for r in others)
    assert [(await _player(db, uid)).spirit_stones for uid in party] == [500, 500, 500]


async def test_战斗失败也只结算一次_惩罚不会扣两遍(db, solo, monkeypatch):
    """失败分支同样会写寿元：两次同时结算，寿元会被扣两次。"""
    import utils.combat as combat
    weak_quest = {**COMBAT_QUEST, "enemy": {"name": "巨兽", "power": 10 ** 9}}
    await _give_quest(db, solo, weak_quest)
    monkeypatch.setattr(quest_logic.random, "uniform", lambda a, b: 1.0)

    async def _escape(player):
        return True, 50
    monkeypatch.setattr(combat, "roll_escape", _escape)
    before = (await _player(db, solo)).lifespan

    results = await asyncio.gather(resolve_quest(solo), resolve_quest(solo))

    assert sum(1 for r in results if r.get("success")) == 1
    assert (await _player(db, solo)).lifespan == before - 2                    # 普通任务逃脱只损 2 年，不是 4


async def test_结算中途出错_任务原样恢复_下次可以重试(db, solo, gather_fixed, monkeypatch):
    """先认领后发奖，发奖出错时不能把任务白白吞掉：认领要撤销，留给下一轮重试。"""
    await _give_quest(db, solo, GATHER_QUEST)
    real = quest_logic._apply_quest_rewards

    async def _boom(*a, **k):
        raise RuntimeError("发奖时出错")
    monkeypatch.setattr(quest_logic, "_apply_quest_rewards", _boom)

    with pytest.raises(RuntimeError):
        await resolve_quest(solo)

    p = await _player(db, solo)
    assert p.active_quest is not None and p.quest_due is not None and p.spirit_stones == 0

    monkeypatch.setattr(quest_logic, "_apply_quest_rewards", real)
    retry = await resolve_quest(solo)
    assert retry["success"] and (await _player(db, solo)).spirit_stones == 500


async def test_队伍结算中途出错_全队的任务都恢复(db, party, gather_fixed, monkeypatch):
    for uid in party:
        await _give_quest(db, uid, GATHER_QUEST)

    async def _boom(*a, **k):
        raise RuntimeError("boom")
    monkeypatch.setattr(quest_logic, "_apply_quest_rewards", _boom)
    with pytest.raises(RuntimeError):
        await resolve_quest(party[0])

    for uid in party:
        assert (await _player(db, uid)).active_quest is not None
