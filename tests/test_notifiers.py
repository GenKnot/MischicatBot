"""闭关 / 采集的定时结算任务测试（cogs/cultivation.py::_cultivation_notifier、_gathering_notifier）。

线上「闭关 / 采集自然结束」的入账全靠这两个每分钟一次的任务。

B14（本文件的重点）：它们曾经靠进程内的 `self._notified` 集合去重，而这个集合只在一个
从未上线的「领取」按钮里被清除 —— 玩家第一次出关之后，之后每一次出关 / 每一次采集结束都被
当成「已通知过」而跳过：修为不入账、采集材料不发放，直到 bot 重启。
现在改成在数据库里认领：条件 UPDATE + rowcount 裁决谁来结算这一次。

测试里的玩家 ID 取数字（cog 会 `int(uid)` 去 fetch_user，真实的 Discord ID 也是数字）。
"""

import asyncio
import logging
import time
import types

import discord
import pytest

from cogs import cultivation as cult_cog_mod
from cogs.cultivation import CultivationCog
from tests.conftest import make_player
from tests.test_dual_cultivation import _FakeBot
from utils.character import calc_cultivation_gain

UID = "123456"


@pytest.fixture
def cog():
    return CultivationCog(bot=_FakeBot())


async def _add_player(db, uid=UID, **fields):
    D = db["db_async"]
    p = make_player(D, uid, stones=0)
    p.name = f"道友{uid}"
    for k, v in fields.items():
        setattr(p, k, v)
    async with D.AsyncSessionLocal() as s:
        s.add(p)
        await s.commit()


async def _row(db, uid=UID):
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        return await s.get(D.Player, uid)


async def _patch(db, uid=UID, **fields):
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        p = await s.get(D.Player, uid)
        for k, v in fields.items():
            setattr(p, k, v)
        await s.commit()


def _gain(years=4):
    return int(calc_cultivation_gain(years, 5, "单灵根"))


def _forbidden():
    return discord.Forbidden(types.SimpleNamespace(status=403, reason="Forbidden"), "Cannot send messages to this user")


# =============================================================================
# 闭关结算
# =============================================================================

async def run_cult(cog):
    await cog._cultivation_notifier.coro(cog)


def _finish(**extra):
    return dict(cultivating_years=4, cultivating_until=time.time() - 1, **extra)


async def test_闭关结束_修为入账_闭关状态清除(db, cog):
    await _add_player(db, cultivation=10, **_finish())

    await run_cult(cog)

    p = await _row(db)
    assert p.cultivation == 10 + _gain()
    assert p.cultivating_until is None and p.cultivating_years is None


async def test_同一个玩家第二次闭关结束_照样结算(db, cog):
    """B14 回归：第一次出关之后，之后每一次出关都被 _notified 当成『已通知过』跳过，
    修为不入账、cultivating_until 一直挂着，直到 bot 重启。"""
    await _add_player(db, **_finish())
    await run_cult(cog)
    after_first = (await _row(db)).cultivation
    assert after_first == _gain()

    await _patch(db, **_finish())                         # 玩家又闭了一次关，这次也结束了
    await run_cult(cog)

    p = await _row(db)
    assert p.cultivation == after_first + _gain(), "第二次闭关结束没有结算"
    assert p.cultivating_until is None


async def test_连着十次闭关_每次都结算(db, cog):
    await _add_player(db, **_finish())
    for i in range(1, 11):
        await run_cult(cog)
        assert (await _row(db)).cultivation == _gain() * i, f"第 {i} 次没有结算"
        await _patch(db, **_finish())


async def test_两个任务同时跑_同一次闭关只结算一次(db, cog):
    """条件 UPDATE + rowcount：两轮都读到这一行，只有一个认领得到。"""
    await _add_player(db, **_finish())

    await asyncio.gather(run_cult(cog), run_cult(cog))

    assert (await _row(db)).cultivation == _gain()
    assert len(cog.bot.users[int(UID)].sent) == 1                      # 通知也只发一条


async def test_读完到写入之间别处加了修为_不会被覆盖(db, cog, monkeypatch):
    """修为用增量写，而不是把读到的旧值加上收益再写回绝对值：
    期间玩家探险拿到的修为（这里模拟 +1000）不能丢。"""
    await _add_player(db, cultivation=0, **_finish())
    real = cult_cog_mod.get_cultivation_bonus

    async def _bump_then_real(*a, **k):
        await _patch(db, cultivation=1000)                              # 通知任务读完这一行之后、写入之前
        return await real(*a, **k)
    monkeypatch.setattr(cult_cog_mod, "get_cultivation_bonus", _bump_then_real)

    await run_cult(cog)

    assert (await _row(db)).cultivation == 1000 + _gain()


async def test_读完到写入之间玩家撤销了闭关_本次让给撤销那边(db, cog, monkeypatch):
    """stop_cultivation 先一步把闭关清掉：通知任务的条件不再成立，不能再往里加一份收益、也不发通知。"""
    await _add_player(db, cultivation=0, **_finish())
    real = cult_cog_mod.get_cultivation_bonus

    async def _stop_then_real(*a, **k):
        await _patch(db, cultivating_until=None, cultivating_years=None)
        return await real(*a, **k)
    monkeypatch.setattr(cult_cog_mod, "get_cultivation_bonus", _stop_then_real)

    await run_cult(cog)

    assert (await _row(db)).cultivation == 0
    assert int(UID) not in cog.bot.users


async def test_没到点和已坐化的不处理(db, cog):
    await _add_player(db, "111111", cultivating_years=4, cultivating_until=time.time() + 999)
    await _add_player(db, "222222", cultivating_years=4, cultivating_until=time.time() - 1, is_dead=True)

    await run_cult(cog)

    assert (await _row(db, "111111")).cultivation == 0
    assert (await _row(db, "222222")).cultivation == 0


async def test_多个玩家各自结算_一个通知失败不影响其他人(db, cog):
    await _add_player(db, "111111", **_finish())
    await _add_player(db, "222222", **_finish())
    real = cog.bot.fetch_user

    async def _first_fails(uid):
        if uid == 111111:
            raise RuntimeError("boom")
        return await real(uid)
    cog.bot.fetch_user = _first_fails

    await run_cult(cog)

    assert (await _row(db, "111111")).cultivation == _gain() == (await _row(db, "222222")).cultivation
    assert cog.bot.users[222222].sent


async def test_没有_notified_集合_重启不影响(db):
    """进程内状态不该左右结算：全新实例（模拟 bot 重启）和用了很久的实例行为一致。"""
    await _add_player(db, **_finish())
    fresh = CultivationCog(bot=_FakeBot())
    assert not hasattr(fresh, "_notified")
    await run_cult(fresh)
    assert (await _row(db)).cultivation == _gain()


# =============================================================================
# 采集结算
# =============================================================================

REWARDS = [("灵芝草", 3), ("茯苓灵块", 1)]


@pytest.fixture
def fixed_rewards(monkeypatch):
    import utils.views.gathering as g
    calls = []

    def _roll(*a, **k):
        calls.append((a, k))
        return list(REWARDS)
    monkeypatch.setattr(g, "roll_gathering_rewards", _roll)
    return calls


async def run_gather(cog):
    await cog._gathering_notifier.coro(cog)


def _gathering(**extra):
    return dict(gathering_type="采药", gathering_until=time.time() - 1, last_active=time.time() - 7200, **extra)


async def _herbs(db, uid=UID):
    inv = await db["inventory"].get_inventory(uid)
    return inv.get("灵芝草", 0), inv.get("茯苓灵块", 0)


async def test_采集结束_材料发到背包_状态清除(db, cog, fixed_rewards):
    await _add_player(db, **_gathering())

    await run_gather(cog)

    assert await _herbs(db) == (3, 1)
    p = await _row(db)
    assert p.gathering_until is None and p.gathering_type is None


async def test_同一个玩家第二次采集结束_照样发奖励(db, cog, fixed_rewards):
    """B14 回归：同样的 _notified 问题，key 是 gather_{uid} —— 第二次采集的奖励不再发放。"""
    await _add_player(db, **_gathering())
    await run_gather(cog)

    await _patch(db, **_gathering())
    await run_gather(cog)

    assert await _herbs(db) == (6, 2), "第二次采集结束没有发奖励"
    assert (await _row(db)).gathering_until is None


async def test_连着十次采集_每次都发(db, cog, fixed_rewards):
    await _add_player(db, **_gathering())
    for i in range(1, 11):
        await run_gather(cog)
        assert (await _herbs(db))[0] == 3 * i, f"第 {i} 次没有发放"
        await _patch(db, **_gathering())


async def test_两个任务同时跑_同一次采集只发一份(db, cog, fixed_rewards):
    await _add_player(db, **_gathering())

    await asyncio.gather(run_gather(cog), run_gather(cog))

    assert await _herbs(db) == (3, 1)
    assert len(fixed_rewards) == 1                                      # 掷奖励也只掷了一次
    assert len(cog.bot.users[int(UID)].sent) == 1


async def test_采集时长与加成传给奖励计算(db, cog, fixed_rewards):
    await _add_player(db, gathering_type="采矿", current_city="灵虚城", gathering_bonus=0.5,
                      gathering_until=time.time() - 1, last_active=time.time() - 14400)         # 采了 2 游戏年

    await run_gather(cog)

    (years, realm_idx, region, gather_type), kw = fixed_rewards[0]
    assert 1.9 < years < 2.1 and gather_type == "采矿" and region == "灵虚城"
    assert kw["gather_bonus"] == 0.5


async def test_采集通知_列出材料_空手而归也有提示(db, cog, fixed_rewards, monkeypatch):
    await _add_player(db, **_gathering())
    await run_gather(cog)
    embed = cog.bot.users[int(UID)].sent[0]["embed"]
    assert "采药完成" in embed.title and "道友123456" in embed.description
    assert "灵芝草" in embed.fields[0].value and "×3" in embed.fields[0].value

    import utils.views.gathering as g
    monkeypatch.setattr(g, "roll_gathering_rewards", lambda *a, **k: [])
    await _add_player(db, "222222", **_gathering())
    await run_gather(cog)
    assert "一无所获" in cog.bot.users[222222].sent[0]["embed"].fields[0].value


async def test_采集没到点和已坐化的不处理(db, cog, fixed_rewards):
    await _add_player(db, "111111", gathering_type="采药", gathering_until=time.time() + 999)
    await _add_player(db, "222222", **_gathering(), is_dead=True)

    await run_gather(cog)

    assert await _herbs(db, "111111") == (0, 0) and await _herbs(db, "222222") == (0, 0)
    assert fixed_rewards == []


# =============================================================================
# 通知失败的分级（两个任务一致）
# =============================================================================

@pytest.mark.parametrize("setup,runner", [
    (lambda: _finish(), run_cult),
    (lambda: _gathering(), run_gather),
])
async def test_对方关了私信_是常态_入账不受影响_也不报错(db, cog, fixed_rewards, caplog, setup, runner):
    async def _closed(uid):
        raise _forbidden()
    cog.bot.fetch_user = _closed
    await _add_player(db, **setup())

    with caplog.at_level(logging.DEBUG, logger="cogs.cultivation"):
        await runner(cog)

    p = await _row(db)
    assert (p.cultivation > 0) or (await _herbs(db))[0] > 0              # 该入账的照常入账
    assert not [r for r in caplog.records if r.levelno >= logging.ERROR]


@pytest.mark.parametrize("setup,runner", [
    (lambda: _finish(), run_cult),
    (lambda: _gathering(), run_gather),
])
async def test_通知逻辑自己出错_要报错而不是吞成debug(db, cog, fixed_rewards, caplog, setup, runner):
    async def _boom(uid):
        raise RuntimeError("代码里的 bug")
    cog.bot.fetch_user = _boom
    await _add_player(db, **setup())

    with caplog.at_level(logging.DEBUG, logger="cogs.cultivation"):
        await runner(cog)

    errors = [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert errors and UID in errors[0].getMessage()
