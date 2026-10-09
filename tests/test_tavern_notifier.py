"""茶馆任务通知循环（cogs/tavern.py::_quest_notifier）。

每分钟扫一遍到期的任务并自动结算、私信玩家。两个问题：

B23 —— 循环体没有任何保护，而且
    self._notified.add(uid); await self._auto_resolve_quest(uid); self._notified.discard(uid)
  没有 try/finally：结算抛一次异常，这个玩家就**永久卡在 `_notified` 里**（B14 的翻版），
  同时异常冒出循环体，整个任务结算循环永久停止。
B22 —— `_notified` 只能防「循环自己和自己」（本来就串行），防不住循环与玩家手动『完成任务』同时到达。
  现在由 `resolve_quest` 在数据库里原子认领，进程内集合已删除。
"""

import asyncio
import json
import logging
import time

import pytest

from cogs import tavern as tavern_mod
from cogs.tavern import TavernCog
from tests.conftest import make_player
from tests.test_dual_cultivation import _FakeBot
from utils import quest_logic

GATHER_QUEST = {"id": "g1", "title": "采集百草", "type": "gather", "rewards": {"spirit_stones": 500}}


class ReadyBot(_FakeBot):
    async def wait_until_ready(self):
        return None


@pytest.fixture
def cog(monkeypatch):
    monkeypatch.setattr(quest_logic.random, "choice", lambda seq: seq[0])      # 采集事件取第一个，倍率 1.0
    return TavernCog(bot=ReadyBot())


async def _add_player(db, uid, due_in=-1, quest=GATHER_QUEST, **fields):
    D = db["db_async"]
    p = make_player(D, uid, stones=0)
    p.name = f"道友{uid}"
    p.active_quest = json.dumps(quest, ensure_ascii=False)
    p.quest_due = time.time() + due_in
    for k, v in fields.items():
        setattr(p, k, v)
    async with D.AsyncSessionLocal() as s:
        s.add(p)
        await s.commit()


async def _row(db, uid):
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        return await s.get(D.Player, uid)


async def tick(cog):
    await cog._quest_notifier.coro(cog)


async def test_到期的任务被自动结算并私信(db, cog):
    await _add_player(db, "123456")

    await tick(cog)

    p = await _row(db, "123456")
    assert p.spirit_stones == 500 and p.active_quest is None and p.quest_due is None
    sent = cog.bot.users[123456].sent
    assert len(sent) == 1 and sent[0]["embed"] is not None


async def test_没到期_已坐化的不处理(db, cog):
    await _add_player(db, "111111", due_in=3600)
    await _add_player(db, "222222", is_dead=True)

    await tick(cog)

    assert (await _row(db, "111111")).active_quest is not None
    assert (await _row(db, "222222")).spirit_stones == 0 and not cog.bot.users


async def test_没有进程内去重集合(db, cog):
    assert not hasattr(cog, "_notified")


async def test_一个玩家结算出错_不影响排在他后面的人_自己下一轮可以重试(db, cog, monkeypatch, caplog):
    """B23：以前抛异常时 `_notified.discard` 被跳过，这个玩家永久卡住；异常还冒出循环让它永久停止。"""
    await _add_player(db, "111111")
    await _add_player(db, "222222")
    real = quest_logic.resolve_quest
    fail = {"on": True}

    async def _flaky(uid):
        if uid == "111111" and fail["on"]:
            raise RuntimeError("结算时出错")
        return await real(uid)
    monkeypatch.setattr(quest_logic, "resolve_quest", _flaky)

    with caplog.at_level(logging.DEBUG, logger="cogs.tavern"):
        await tick(cog)

    assert (await _row(db, "222222")).spirit_stones == 500, "排在后面的人也要被结算"
    assert (await _row(db, "111111")).spirit_stones == 0
    assert [r for r in caplog.records if r.levelno >= logging.ERROR and "111111" in r.getMessage()]

    fail["on"] = False                                                         # 下一分钟恢复正常
    await tick(cog)

    assert (await _row(db, "111111")).spirit_stones == 500, "出过错的玩家下一轮要能重试，不能永久卡住"
    assert (await _row(db, "222222")).spirit_stones == 500                      # 也没有被重复发放


async def test_整轮出错不外抛(db, cog, monkeypatch, caplog):
    class _Boom:
        def __call__(self):
            raise RuntimeError("数据库抖了一下")
    monkeypatch.setattr(tavern_mod, "AsyncSessionLocal", _Boom())
    with caplog.at_level(logging.DEBUG, logger="cogs.tavern"):
        await tick(cog)
    assert [r for r in caplog.records if r.levelno >= logging.ERROR]


async def test_真实循环_出错一次之后仍在运行(db, monkeypatch):
    calls = []
    c = TavernCog(bot=ReadyBot())
    real_time = tavern_mod.time.time

    class _T:
        @staticmethod
        def time():
            calls.append(1)
            if len(calls) == 1:
                raise RuntimeError("出错一次")
            return real_time()
    monkeypatch.setattr(tavern_mod, "time", _T)
    c._quest_notifier.change_interval(seconds=0.05)
    c._quest_notifier.start()
    try:
        await asyncio.sleep(0.4)
        assert len(calls) >= 2 and c._quest_notifier.is_running() and not c._quest_notifier.failed()
    finally:
        c._quest_notifier.cancel()


async def test_通知循环与手动结算同时到达_奖励只发一次(db, cog):
    """B22 的端到端：循环那一分钟恰好撞上玩家手动『完成任务』。"""
    await _add_player(db, "123456")

    await asyncio.gather(tick(cog), quest_logic.resolve_quest("123456"))

    assert (await _row(db, "123456")).spirit_stones == 500


async def test_队伍任务_循环结算整队只发一份(db, cog):
    for uid in ("100001", "100002", "100003"):
        await _add_player(db, uid, party_id="p1")

    await tick(cog)

    assert [(await _row(db, u)).spirit_stones for u in ("100001", "100002", "100003")] == [500, 500, 500]
