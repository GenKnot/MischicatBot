"""公共事件 cog 测试（cogs/public_events.py）：灵雨与万宝楼拍卖的定时调度、公告和命令。

调度器每分钟跑一次，按蒙特利尔时间决定：19:00 起每半小时预告、21:00 触发灵雨、到点结算；
另有万宝楼 18:00/19:30 预告、20:00 开拍、逐件计时成交。全靠这个循环 ——
它一旦停了，灵雨与拍卖都不会再被触发、结算（B17）。

测试里的时间：把 `_montreal_now` 换成「今天的某时某分」，把 `_today_trigger_ts` 换成「已过 / 未到」，
这样不依赖真实时钟。调度逻辑放在 `_scheduler_tick`，循环只负责每分钟调一次并兜住异常。

结构：A 辅助  B 调度时间线  C 预告 / 触发 / 结算  D 循环存活（B17）  E 万宝楼调度  F 逐件计时与公告  G 命令
"""

import asyncio
import json
import time
from datetime import datetime

import pytest
from discord.ext import tasks

from cogs import public_events as pe
from cogs.public_events import MONTREAL_TZ, PublicEventsCog
from tests.conftest import make_player
from tests.discord_fakes import FakeContext
from tests.test_spirit_rain_event import FakeChannel
from utils.events.public import wanbao as wb

CITY = "铁甲城"


class FakeBot:
    def __init__(self, channel=None):
        self.channel = channel
        self.cogs = {}

    async def wait_until_ready(self):
        return None

    def get_channel(self, channel_id):
        return self.channel


def today_str():
    return datetime.now(MONTREAL_TZ).strftime("%Y-%m-%d")


def at(monkeypatch, h, m, *, past_trigger=True):
    """把调度器看到的『蒙特利尔现在』设为今天 h:m；past_trigger 表示 21:00 的触发时刻是否已过。"""
    now = datetime.now(MONTREAL_TZ).replace(hour=h, minute=m, second=0, microsecond=0)
    monkeypatch.setattr(pe, "_montreal_now", lambda: now)
    monkeypatch.setattr(pe, "_today_trigger_ts", lambda: time.time() - 1 if past_trigger else time.time() + 10 ** 6)
    return now


@pytest.fixture
def channel(monkeypatch):
    monkeypatch.setenv(pe.PUBLIC_EVENT_CHANNEL_ENV, "123456")
    return FakeChannel()


@pytest.fixture
def cog(channel, monkeypatch):
    # 不要真的启动每分钟一次的循环：测试里直接调 _scheduler_tick
    monkeypatch.setattr(tasks.Loop, "start", lambda self, *a, **k: None)
    c = PublicEventsCog(FakeBot(channel))
    yield c
    c.cog_unload()


@pytest.fixture
def cog_no_channel(monkeypatch):
    monkeypatch.delenv(pe.PUBLIC_EVENT_CHANNEL_ENV, raising=False)
    monkeypatch.setattr(tasks.Loop, "start", lambda self, *a, **k: None)
    c = PublicEventsCog(FakeBot(None))
    yield c
    c.cog_unload()


async def _add_player(db, uid, **fields):
    D = db["db_async"]
    p = make_player(D, uid, stones=5000)
    p.name = f"道友{uid}"
    for k, v in fields.items():
        setattr(p, k, v)
    async with D.AsyncSessionLocal() as s:
        s.add(p)
        await s.commit()


async def _row(db, uid):
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        return await s.get(D.Player, uid)


async def _add_event(db, event_id="e1", status="active", city=CITY, trigger_date=None, started_ago=60,
                     ends_in=3600, beast_tide=False, event_type="spirit_rain"):
    D = db["db_async"]
    now = time.time()
    data = {"city": city, "beast_tide": beast_tide}
    if trigger_date:
        data["trigger_date"] = trigger_date
    async with D.AsyncSessionLocal() as s:
        s.add(D.PublicEvent(event_id=event_id, event_type=event_type, title="天降灵雨", status=status,
                            started_at=now - started_ago, ends_at=now + ends_in, data=json.dumps(data)))
        await s.commit()


async def _events(db):
    from sqlalchemy import text
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        rows = (await s.execute(text("SELECT * FROM public_events ORDER BY started_at"))).fetchall()
    return [dict(r._mapping) for r in rows]


async def _sql(db, sql, **params):
    from sqlalchemy import text
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        res = await s.execute(text(sql), params)
        await s.commit()
        return res


# =============================================================================
# A. 辅助
# =============================================================================

def test_公告频道_没配环境变量是空(monkeypatch):
    monkeypatch.delenv(pe.PUBLIC_EVENT_CHANNEL_ENV, raising=False)
    assert pe._get_announce_channel(FakeBot(FakeChannel())) is None


def test_公告频道_按环境变量里的id去取(monkeypatch):
    seen = []
    bot = FakeBot(FakeChannel())
    bot.get_channel = lambda cid: seen.append(cid) or "ch"
    monkeypatch.setenv(pe.PUBLIC_EVENT_CHANNEL_ENV, "42")
    assert pe._get_announce_channel(bot) == "ch" and seen == [42]


def test_公告频道_取不到时是空(monkeypatch):
    monkeypatch.setenv(pe.PUBLIC_EVENT_CHANNEL_ENV, "42")
    assert pe._get_announce_channel(FakeBot(None)) is None


async def test_到期未结算的事件_取最早到期的(db):
    await _add_event(db, "late", ends_in=-10)
    await _add_event(db, "early", ends_in=-100)
    await _add_event(db, "running", ends_in=3600)
    await _add_event(db, "done", status="ended", ends_in=-500)
    assert (await pe._get_expired_event())["event_id"] == "early"


async def test_没有到期事件返回空(db):
    await _add_event(db, ends_in=3600)
    assert await pe._get_expired_event() is None


async def test_最近一次触发日期_只看进行中与已结束的灵雨(db):
    assert await pe._last_trigger_date_str() is None
    await _add_event(db, "old", status="ended", trigger_date="2026-01-01", started_ago=9000)
    await _add_event(db, "new", status="active", trigger_date="2026-01-02", started_ago=10)
    await _add_event(db, "pend", status="pending", trigger_date="2099-01-01", started_ago=1)      # pending 不算
    assert await pe._last_trigger_date_str() == "2026-01-02"


async def test_最近一次触发日期_数据损坏时当作没有(db):
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        s.add(D.PublicEvent(event_id="bad", event_type="spirit_rain", title="t", status="ended",
                            started_at=time.time(), ends_at=time.time(), data="{坏的"))
        await s.commit()
    assert await pe._last_trigger_date_str() is None


def test_蒙特利尔现在带时区():
    assert pe._montreal_now().tzinfo is not None


# =============================================================================
# B. 调度时间线
# =============================================================================

async def test_十九点_建待开始事件并发第一次预告(db, cog, channel, monkeypatch):
    at(monkeypatch, 19, 0, past_trigger=False)

    await cog._scheduler_tick()

    ev = await _events(db)
    assert len(ev) == 1 and ev[0]["status"] == "pending"
    assert json.loads(ev[0]["data"])["trigger_date"] == today_str()
    m = channel.last
    assert "预告" in m.embed.title and "120 分钟" in m.embed.description and "第 1/4 次预告" in m.embed.footer.text
    assert cog._preview_sent == {0}


async def test_同一分钟内重复运行_预告不重发(db, cog, channel, monkeypatch):
    at(monkeypatch, 19, 0, past_trigger=False)
    await cog._scheduler_tick()
    await cog._scheduler_tick()
    assert len(channel.sent) == 1 and len(await _events(db)) == 1


@pytest.mark.parametrize("h,m,mins,nth", [(19, 30, 90, 2), (20, 0, 60, 3), (20, 30, 30, 4)])
async def test_后续预告的倒计时(db, cog, channel, monkeypatch, h, m, mins, nth):
    await _add_event(db, "p", status="pending")
    at(monkeypatch, h, m, past_trigger=False)

    await cog._scheduler_tick()

    # 同一轮里万宝楼调度也可能发自己的公告，所以按标题挑灵雨预告
    m = next(x for x in channel.sent if x.embed and "天降灵雨 · 预告" in (x.embed.title or ""))
    assert f"{mins} 分钟" in m.embed.description and f"第 {nth}/4 次预告" in m.embed.footer.text


async def test_预告不会在非预告时刻发出(db, cog, channel, monkeypatch):
    for h, m in [(12, 0), (19, 15), (18, 59), (20, 45)]:
        at(monkeypatch, h, m, past_trigger=False)
        await cog._scheduler_tick()
    assert [s for s in channel.sent if s.embed and "预告" in (s.embed.title or "") and "灵雨" in s.embed.title] == []
    assert await _events(db) == []


async def test_二十一点_待开始事件转为进行中并发出降临公告(db, cog, channel, monkeypatch):
    await _add_event(db, "p", status="pending", trigger_date=today_str())
    at(monkeypatch, 21, 0, past_trigger=True)
    before = time.time()

    await cog._scheduler_tick()

    ev = (await _events(db))[0]
    assert ev["status"] == "active" and before <= ev["started_at"] and abs(ev["ends_at"] - ev["started_at"] - 3600) < 1
    assert "降临" in channel.last.embed.title and cog._preview_sent == {4}
    assert "beast_tide" in json.loads(ev["data"])


async def test_已经触发过的一天_不会再触发(db, cog, channel, monkeypatch):
    await _add_event(db, "done", status="ended", trigger_date=today_str(), started_ago=5000, ends_in=-1400)
    at(monkeypatch, 21, 30, past_trigger=True)

    await cog._scheduler_tick()

    assert [e["event_id"] for e in await _events(db)] == ["done"]
    assert not any(s.embed and "降临" in (s.embed.title or "") for s in channel.sent)


async def test_触发去重_触发成功之后同一天不会再调一次(db, cog, monkeypatch):
    calls = []

    async def _spy(today):
        calls.append(today)                                                # 不真的建事件：专门验证去重标记本身
    monkeypatch.setattr(cog, "_trigger_spirit_rain", _spy)
    at(monkeypatch, 21, 0, past_trigger=True)

    await cog._scheduler_tick()
    await cog._scheduler_tick()

    assert calls == [today_str()]


async def test_触发失败_标记会撤销_下一分钟重试(db, cog, monkeypatch):
    """触发时抛异常（数据库抖动之类）：标记已经打上的话要等到 22 点才补触发，一晚上的灵雨就没了。
    现在失败会撤销标记，异常继续往上抛给循环去记日志，下一分钟再来。"""
    calls = []

    async def _flaky(today):
        calls.append(today)
        if len(calls) == 1:
            raise RuntimeError("数据库抖了一下")
    monkeypatch.setattr(cog, "_trigger_spirit_rain", _flaky)
    at(monkeypatch, 21, 0, past_trigger=True)

    with pytest.raises(RuntimeError):
        await cog._scheduler_tick()
    assert 4 not in cog._preview_sent

    await cog._scheduler_tick()                                            # 下一分钟

    assert len(calls) == 2 and 4 in cog._preview_sent


async def test_机器人二十一点后才启动_也会补触发一次(db, cog, channel, monkeypatch):
    at(monkeypatch, 21, 40, past_trigger=True)

    await cog._scheduler_tick()
    await cog._scheduler_tick()

    ev = await _events(db)
    assert len(ev) == 1 and ev[0]["status"] == "active"                    # 没有待开始事件时现建一个，且只触发一次


async def test_触发时刻未到但分钟对上_也能走预告表里的最后一项触发(db, cog, channel, monkeypatch):
    await _add_event(db, "p", status="pending", trigger_date=today_str())
    at(monkeypatch, 21, 0, past_trigger=False)
    await cog._scheduler_tick()
    assert (await _events(db))[0]["status"] == "active"


async def test_事件进行中_不会再触发新的(db, cog, channel, monkeypatch):
    await _add_event(db, "a", status="active", trigger_date="2000-01-01")
    at(monkeypatch, 21, 10, past_trigger=True)
    await cog._scheduler_tick()
    assert len(await _events(db)) == 1 and channel.sent == []


async def test_到期的事件_被结算并清空预告记录(db, cog, channel, monkeypatch):
    await _add_event(db, "x", status="active", trigger_date=today_str(), ends_in=-5)
    cog._preview_sent = {0, 1, 4}
    at(monkeypatch, 22, 5, past_trigger=True)

    await cog._scheduler_tick()

    assert (await _events(db))[0]["status"] == "ended"
    assert "结束" in channel.last.embed.title and cog._preview_sent == set()


async def test_二十二点后没有事件时清空预告记录(db, cog, channel, monkeypatch):
    await _add_event(db, "x", status="ended", trigger_date=today_str(), started_ago=5000, ends_in=-1400)
    cog._preview_sent = {0, 1}
    at(monkeypatch, 22, 30, past_trigger=True)
    await cog._scheduler_tick()
    assert cog._preview_sent == set()


async def test_每次调度都会跑万宝楼调度(db, cog, monkeypatch):
    seen = []

    async def _spy(now_mt, today, h, m):
        seen.append((today, h, m))
    monkeypatch.setattr(cog, "_wanbao_scheduler", _spy)
    at(monkeypatch, 12, 34, past_trigger=False)

    await cog._scheduler_tick()

    assert seen == [(today_str(), 12, 34)]


async def test_没有公告频道时_仍建待开始事件_只是不发预告(db, cog_no_channel, monkeypatch):
    at(monkeypatch, 19, 0, past_trigger=False)
    await cog_no_channel._scheduler_tick()
    assert len((await _events(db))) == 1


# =============================================================================
# C. 预告 / 触发 / 结算
# =============================================================================

async def test_待开始事件_已有就不重复建(db, cog):
    await cog._prepare_pending_event("2026-10-09")
    await cog._prepare_pending_event("2026-10-09")
    ev = await _events(db)
    assert len(ev) == 1
    from utils.world import CITIES
    assert json.loads(ev[0]["data"])["city"] in {c["name"] for c in CITIES}


async def test_预告_没有频道或没有待开始事件时什么都不发(db, cog, channel, cog_no_channel):
    await cog._send_preview(0)                                              # 有频道但没有待开始事件
    assert channel.sent == []
    await _add_event(db, "p", status="pending")
    await cog_no_channel._send_preview(0)                                   # 有事件但没有频道
    assert channel.sent == []


async def test_预告带前往城市的按钮(db, cog, channel):
    from utils.views.spirit_rain import TravelToEventView
    await _add_event(db, "p", status="pending", city="灵虚城")
    await cog._send_preview(1)
    view = channel.last.view
    assert isinstance(view, TravelToEventView) and view.city == "灵虚城" and view.event_id == "p"
    assert "灵虚城" in channel.last.embed.description


async def test_触发_没有待开始事件就现建_并按概率决定是否万兽齐鸣(db, cog, channel, monkeypatch):
    monkeypatch.setattr(pe.random, "random", lambda: 0.29)
    await cog._trigger_spirit_rain("2026-10-09")
    ev = (await _events(db))[0]
    assert ev["status"] == "active" and json.loads(ev["data"])["beast_tide"] is True

    await _sql(db, "DELETE FROM public_events")
    monkeypatch.setattr(pe.random, "random", lambda: 0.31)
    await cog._trigger_spirit_rain("2026-10-09")
    assert json.loads((await _events(db))[0]["data"])["beast_tide"] is False


async def test_触发_沿用待开始事件的城市_并记下触发日期(db, cog, channel):
    await _add_event(db, "p", status="pending", city="灵虚城")
    await cog._trigger_spirit_rain("2026-10-09")
    ev = (await _events(db))[0]
    d = json.loads(ev["data"])
    assert ev["event_id"] == "p" and d["city"] == "灵虚城" and d["trigger_date"] == "2026-10-09"
    assert "灵虚城" in channel.last.embed.description


async def test_结算_交给对应类型的模块_并清空预告记录(db, cog, channel):
    await _add_event(db, "x", status="active", trigger_date=today_str(), ends_in=-1)
    cog._preview_sent = {1, 2}
    event = (await _events(db))[0]

    await cog._settle_event(event)

    assert (await _events(db))[0]["status"] == "ended" and cog._preview_sent == set()


async def test_结算_未知类型的事件不会炸(db, cog):
    cog._preview_sent = {1}
    await cog._settle_event({"event_type": "不存在", "event_id": "z", "data": "{}"})
    assert cog._preview_sent == set()


# =============================================================================
# D. 循环存活（B17）与频道缺失
# =============================================================================

async def test_调度循环_一轮出错不会让循环永久停止(db, cog, monkeypatch):
    """B17：discord.ext.tasks 的循环体里抛出非网络类异常，循环会永久停止（is_running=False, failed=True）。
    _scheduler 主体曾没有 try/except —— 一次数据库抖动、一次发消息被拒、一次频道为空时的 AttributeError，
    就让灵雨和万宝楼的调度一起停摆，直到 bot 重启。"""
    calls = []

    async def _tick():
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("某一轮出错了")
    monkeypatch.setattr(cog, "_scheduler_tick", _tick)

    await cog._scheduler.coro(cog)                                         # 第一轮：出错，但不能抛出来
    await cog._scheduler.coro(cog)                                         # 下一分钟照常再来

    assert calls == [1, 1]


async def test_调度循环_出错会记ERROR日志(db, cog, monkeypatch, caplog):
    import logging

    async def _tick():
        raise RuntimeError("boom")
    monkeypatch.setattr(cog, "_scheduler_tick", _tick)
    with caplog.at_level(logging.DEBUG, logger="cogs.public_events"):
        await cog._scheduler.coro(cog)
    assert [r for r in caplog.records if r.levelno >= logging.ERROR]


async def test_真实循环_出错一次之后仍在运行(db, channel, monkeypatch):
    """用真实的 tasks.Loop 验证：不是只测我们的包装，而是循环本身没有死。"""
    calls = []
    c = PublicEventsCog(FakeBot(channel))                                    # 真的启动循环
    try:
        async def _tick():
            calls.append(1)
            if len(calls) == 1:
                raise RuntimeError("出错一次")
        monkeypatch.setattr(c, "_scheduler_tick", _tick)
        c._scheduler.change_interval(seconds=0.05)
        c._scheduler.restart()
        await asyncio.sleep(0.4)
        assert len(calls) >= 2 and c._scheduler.is_running() and not c._scheduler.failed()
    finally:
        c.cog_unload()


async def test_触发灵雨时没有公告频道_事件照常进行中_不抛异常(db, cog_no_channel):
    """on_trigger 在频道为空时曾直接 channel.send 抛 AttributeError：事件已经是 active，
    调度器却因此死掉，没人再去结算它。"""
    await cog_no_channel._trigger_spirit_rain("2026-10-09")
    assert (await _events(db))[0]["status"] == "active"


async def test_没有频道的整条链路_触发到结算_守城奖励照发(db, cog_no_channel, monkeypatch):
    await _add_player(db, "1", spirit_stones=0, reputation=0, current_city=CITY)
    await _add_event(db, "p", status="pending", city=CITY)
    await cog_no_channel._trigger_spirit_rain("2026-10-09")
    await _sql(db, "INSERT INTO public_event_participants (event_id, discord_id, joined_at, contribution, activity) "
                   "VALUES ('p','1',:t,100,'defense')", t=time.time())
    await _sql(db, "UPDATE public_events SET ends_at = :t, data = :d WHERE event_id='p'",
               t=time.time() - 1, d=json.dumps({"city": CITY, "beast_tide": False}))

    await cog_no_channel._settle_event(await pe._get_expired_event())

    assert (await _row(db, "1")).spirit_stones > 0                         # B16：没频道也发奖励


# =============================================================================
# E. 万宝楼调度
# =============================================================================

async def _auction(db, status="pending", date=None):
    a = await wb.get_or_create_auction(date or today_str())
    if status != "pending":
        await _sql(db, "UPDATE wanbao_auctions SET status=:s WHERE auction_id=:a", s=status, a=a["auction_id"])
    return a["auction_id"]


@pytest.fixture
def no_timer(monkeypatch):
    """不真的跑逐件计时，只记录它被要求启动。替身一直挂着（像真的计时器那样还在跑），直到被取消。"""
    started = []

    async def _hang(self, auction_id):
        started.append(auction_id)
        await asyncio.sleep(3600)
    monkeypatch.setattr(PublicEventsCog, "_run_lot_timer", _hang)
    return started


async def test_万宝楼_十八点预告_建拍卖并发公告_每天只发一次(db, cog, channel, no_timer):
    now = datetime.now(MONTREAL_TZ).replace(hour=18, minute=0)
    await cog._wanbao_scheduler(now, today_str(), 18, 0)
    await cog._wanbao_scheduler(now, today_str(), 18, 0)

    assert len(channel.sent) == 1
    assert "预告" in channel.last.embed.title and "**8**" in channel.last.embed.description
    assert (await _sql(db, "SELECT COUNT(*) FROM wanbao_auctions")).scalar() == 1


async def test_万宝楼_十九点半预告(db, cog, channel, no_timer):
    now = datetime.now(MONTREAL_TZ).replace(hour=19, minute=30)
    await cog._wanbao_scheduler(now, today_str(), 19, 30)
    assert "30分钟后开始" in channel.last.embed.title and "**8**" in channel.last.embed.description


async def test_万宝楼_没有频道时只建拍卖不发公告(db, cog_no_channel, no_timer):
    now = datetime.now(MONTREAL_TZ).replace(hour=18, minute=0)
    await cog_no_channel._wanbao_scheduler(now, today_str(), 18, 0)
    assert (await _sql(db, "SELECT COUNT(*) FROM wanbao_auctions")).scalar() == 1


async def test_万宝楼_二十点开拍_发首件公告并启动计时(db, cog, channel, no_timer):
    from utils.views.wanbao import PublicBidView
    aid = await _auction(db)
    now = datetime.now(MONTREAL_TZ).replace(hour=20, minute=0)

    await cog._wanbao_scheduler(now, today_str(), 20, 0)
    await asyncio.sleep(0)

    assert "拍卖会开始" in channel.last.embed.title and "第 1/8 件" in channel.last.embed.title
    assert isinstance(channel.last.view, PublicBidView)
    assert cog._wanbao_auction_id == aid
    assert (await wb.get_active_auction())["status"] == "active" and no_timer == [aid]      # 只启动一次


async def test_万宝楼_二十点时拍卖已开始_不会重复开拍(db, cog, channel, no_timer):
    await _auction(db, "active")
    now = datetime.now(MONTREAL_TZ).replace(hour=20, minute=0)
    await cog._wanbao_scheduler(now, today_str(), 20, 0)
    assert channel.sent == []


async def test_万宝楼_没有频道时也能开拍_计时器仍会启动(db, cog_no_channel, no_timer):
    aid = await _auction(db)
    now = datetime.now(MONTREAL_TZ).replace(hour=20, minute=0)
    await cog_no_channel._wanbao_scheduler(now, today_str(), 20, 0)
    await asyncio.sleep(0)
    assert (await wb.get_active_auction())["status"] == "active" and no_timer == [aid]


async def test_万宝楼_重启后发现进行中的拍卖_恢复计时(db, cog, no_timer):
    aid = await _auction(db, "active")
    now = datetime.now(MONTREAL_TZ).replace(hour=21, minute=15)
    await cog._wanbao_scheduler(now, today_str(), 21, 15)
    await asyncio.sleep(0)
    assert no_timer == [aid]


async def test_万宝楼_计时器还在跑就不重复启动(db, cog, no_timer):
    await _auction(db, "active")
    cog._lot_task = asyncio.create_task(asyncio.sleep(60))
    try:
        now = datetime.now(MONTREAL_TZ).replace(hour=21, minute=15)
        await cog._wanbao_scheduler(now, today_str(), 21, 15)
        await asyncio.sleep(0)
        assert no_timer == []
    finally:
        cog._lot_task.cancel()


# =============================================================================
# F. 逐件计时与公告
# =============================================================================

@pytest.fixture
def fast(monkeypatch):
    """逐件计时里有 asyncio.sleep(剩余秒数)：换成立刻返回，整场拍卖几十毫秒跑完。"""
    real = asyncio.sleep

    async def _nosleep(t, *a, **k):
        await real(0)
    monkeypatch.setattr(pe.asyncio, "sleep", _nosleep)


async def _expire_current_lot(db, aid):
    await _sql(db, "UPDATE wanbao_auctions SET ends_at=:t WHERE auction_id=:a", t=time.time() - 1, a=aid)


async def test_计时器_无人出价_八件全部流拍并宣布结束(db, cog, channel, fast):
    aid = await _auction(db)
    await wb.start_auction(aid)
    await _expire_current_lot(db, aid)

    await cog._run_lot_timer(aid)

    lots = await wb.get_lots(aid)
    assert all(l["status"] == "unsold" for l in lots) and len(lots) == 8
    titles = [s.embed.title for s in channel.sent if s.embed]
    assert sum("流拍" in t for t in titles) == 8
    assert "圆满结束" in titles[-1] and "流拍 **8** 件" in channel.last.embed.description
    assert (await _sql(db, "SELECT status FROM wanbao_auctions WHERE auction_id=:a", a=aid)).scalar() == "ended"


async def test_计时器_有人出价_成交并结算(db, cog, channel, fast):
    await _add_player(db, "buyer", spirit_stones=100_000)
    aid = await _auction(db)
    first = await wb.start_auction(aid)
    price = first["start_price"] + 100
    ok, msg = await wb.place_bid(aid, "buyer", price)                      # 出价即托管：此刻就扣款
    assert ok, msg
    assert (await _row(db, "buyer")).spirit_stones == 100_000 - price
    await _expire_current_lot(db, aid)

    await cog._run_lot_timer(aid)

    sold = [s for s in channel.sent if s.embed and "成交" in s.embed.title]
    assert len(sold) == 1 and "道友buyer" in sold[0].embed.description
    assert (await _row(db, "buyer")).spirit_stones == 100_000 - price       # 结算不再二次扣款
    assert "拍出 **1** 件" in channel.last.embed.description


async def test_计时器_每件之间会发出下一件的公告(db, cog, channel, fast):
    aid = await _auction(db)
    await wb.start_auction(aid)
    await _expire_current_lot(db, aid)
    await cog._run_lot_timer(aid)
    from utils.views.wanbao import PublicBidView
    bids = [s for s in channel.sent if isinstance(s.view, PublicBidView)]
    assert len(bids) == 7                                                   # 第 2~8 件各一条


async def test_计时器_拍卖已被别处结束就退出(db, cog, channel, fast):
    aid = await _auction(db, "ended")
    await cog._run_lot_timer(aid)
    assert channel.sent == []


async def test_计时器_不是自己的拍卖就退出_不会去结算当前拍卖的拍品(db, cog, channel, fast):
    """比如手动重启计时后，旧拍卖的计时器还没退出：它不能去动现在这场拍卖的拍品。"""
    aid = await _auction(db)
    await wb.start_auction(aid)
    await _expire_current_lot(db, aid)                                      # 当前这件已到点，随时会被结算

    await cog._run_lot_timer("别的拍卖")

    assert channel.sent == []
    statuses = [l["status"] for l in await wb.get_lots(aid)]
    assert statuses[0] == "active" and set(statuses[1:]) == {"pending"}      # 一件都没动


async def test_计时器_出错只记日志_不外抛(db, cog, channel, fast, monkeypatch, caplog):
    import logging
    aid = await _auction(db)
    await wb.start_auction(aid)
    await _expire_current_lot(db, aid)

    async def _boom(lot):
        raise RuntimeError("结算炸了")
    monkeypatch.setattr(wb, "settle_lot", _boom)
    with caplog.at_level(logging.DEBUG, logger="cogs.public_events"):
        await cog._run_lot_timer(aid)
    assert [r for r in caplog.records if "lot timer 异常" in r.getMessage()]


async def test_计时器_被取消时往上传(db, cog, channel):
    aid = await _auction(db)
    await wb.start_auction(aid)
    await _sql(db, "UPDATE wanbao_auctions SET ends_at=:t WHERE auction_id=:a", t=time.time() + 3600, a=aid)
    task = asyncio.create_task(cog._run_lot_timer(aid))
    await asyncio.sleep(0.05)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


async def test_计时器_拍卖结束后清掉冻结资金_即使没有公告频道(db, cog_no_channel, fast):
    """拍卖结束时要清掉本场的冻结资金记录。它曾放在『发结束公告』的函数里，
    没有公告频道时就永远不清，wanbao_frozen 表越攒越多。"""
    aid = await _auction(db)
    await wb.start_auction(aid)
    await _sql(db, "INSERT INTO wanbao_frozen (discord_id, auction_id, amount) VALUES ('x', :a, 500)", a=aid)
    await _expire_current_lot(db, aid)

    await cog_no_channel._run_lot_timer(aid)

    assert (await _sql(db, "SELECT COUNT(*) FROM wanbao_frozen WHERE auction_id=:a", a=aid)).scalar() == 0


async def test_公告_成交与流拍的措辞(db, cog, channel):
    await _add_player(db, "w")
    lot = {"lot_id": "l", "item_name": "灵芝草", "quantity": 2, "item_type": "item", "seller_id": None}
    await cog._announce_lot_result(channel, {"lot": lot, "winner_id": "w", "final_price": 1000, "seller_income": 920}, "a")
    assert "成交" in channel.last.embed.title and "道友w" in channel.last.embed.description
    assert "920" in channel.last.embed.description and "8%" in channel.last.embed.description

    await cog._announce_lot_result(channel, {"lot": {**lot, "seller_id": "s"}, "winner_id": None, "final_price": 0, "seller_income": 0}, "a")
    assert "流拍" in channel.last.embed.title and "取回费" in channel.last.embed.description

    await cog._announce_lot_result(channel, {"lot": lot, "winner_id": None, "final_price": 0, "seller_income": 0}, "a")
    assert "取回费" not in channel.last.embed.description                   # 万宝楼自己的拍品流拍没有取回费


async def test_公告_成交者角色不存在时用提及(db, cog, channel):
    lot = {"lot_id": "l", "item_name": "灵芝草", "quantity": 1, "item_type": "item", "seller_id": "7"}
    await cog._announce_lot_result(channel, {"lot": lot, "winner_id": "999", "final_price": 10, "seller_income": 9}, "a")
    assert "<@999>" in channel.last.embed.description


async def test_公告_拍卖结束汇总(db, cog, channel):
    await _add_player(db, "b")
    aid = await _auction(db)
    lots = await wb.get_lots(aid)
    await _sql(db, "UPDATE wanbao_lots SET status='sold', bidder_id='b', current_bid=300 WHERE lot_id=:l", l=lots[0]["lot_id"])
    await _sql(db, "UPDATE wanbao_lots SET status='unsold' WHERE auction_id=:a AND lot_id != :l", a=aid, l=lots[0]["lot_id"])

    await cog._announce_auction_end(channel, aid)

    e = channel.last.embed
    assert "拍出 **1** 件" in e.description and "流拍 **7** 件" in e.description
    assert any("道友b" in f.value and "300" in f.value for f in e.fields)
    assert sum(f.value == "流拍" for f in e.fields) == 7


# =============================================================================
# G. 命令
# =============================================================================

def ctx(uid="1"):
    return FakeContext(user_id=int(uid))


async def test_万宝楼命令_没角色_已坐化_不在万宝楼(db, cog):
    c = ctx()
    await cog.wanbao.callback(cog, c)
    assert c.said("尚未踏入修仙之路")
    await _add_player(db, "1", is_dead=True)
    c = ctx()
    await cog.wanbao.callback(cog, c)
    assert c.said("已坐化")
    await _sql(db, "UPDATE players SET is_dead=0, current_city='灵虚城' WHERE discord_id='1'")
    c = ctx()
    await cog.wanbao.callback(cog, c)
    assert c.said("需前往 **万宝楼**")


async def test_万宝楼命令_拍卖待开始_显示拍品数与开始时间(db, cog):
    from utils.views.wanbao import WanbaoMainView
    await _add_player(db, "1", current_city="万宝楼")
    await _auction(db)
    c = ctx()

    await cog.wanbao.callback(cog, c)

    m = c.last
    assert "等待开始" in m.embed.description and "**8** 件" in m.embed.description
    assert any(f.name == "开始时间" for f in m.embed.fields) and isinstance(m.view, WanbaoMainView)


async def test_万宝楼命令_拍卖进行中(db, cog):
    await _add_player(db, "1", current_city="万宝楼")
    await _auction(db, "active")
    c = ctx()
    await cog.wanbao.callback(cog, c)
    assert "进行中" in c.last.embed.description and not any(f.name == "开始时间" for f in c.last.embed.fields)


async def test_万宝楼命令_今日拍卖已结束_显示上次记录(db, cog):
    await _add_player(db, "1", current_city="万宝楼")
    await _add_player(db, "b")
    aid = await _auction(db, "ended")
    lots = await wb.get_lots(aid)
    await _sql(db, "UPDATE wanbao_auctions SET started_at=:t WHERE auction_id=:a", t=time.time() - 100, a=aid)
    await _sql(db, "UPDATE wanbao_lots SET status='sold', bidder_id='b', current_bid=300 WHERE lot_id=:l", l=lots[0]["lot_id"])
    await _sql(db, "UPDATE wanbao_lots SET status='unsold' WHERE auction_id=:a AND lot_id != :l", a=aid, l=lots[0]["lot_id"])
    c = ctx()

    await cog.wanbao.callback(cog, c)

    rec = next(f for f in c.last.embed.fields if f.name == "上次拍卖记录").value
    assert "道友b · 300 灵石" in rec and rec.count("流拍") == 7


async def test_开启拍卖命令_只有主人能用(db, cog, monkeypatch):
    monkeypatch.setattr(pe, "is_master", lambda uid: False)
    c = ctx()
    await cog.debug_start_auction.callback(cog, c)
    assert c.messages == [] and await wb.get_active_auction() is None


async def test_开启拍卖命令_成功_已进行_已结束(db, cog, channel, no_timer, monkeypatch):
    monkeypatch.setattr(pe, "is_master", lambda uid: True)
    c = ctx()
    await cog.debug_start_auction.callback(cog, c)
    assert c.said("拍卖已启动") and "拍卖会开始" in channel.last.embed.title
    await asyncio.sleep(0)
    assert len(no_timer) == 1

    c2 = ctx()
    await cog.debug_start_auction.callback(cog, c2)
    assert c2.said("已在进行中")

    await _sql(db, "UPDATE wanbao_auctions SET status='ended'")
    c3 = ctx()
    await cog.debug_start_auction.callback(cog, c3)
    assert c3.said("今日拍卖已结束")


async def test_开启拍卖命令_没有频道也能启动(db, cog_no_channel, no_timer, monkeypatch):
    monkeypatch.setattr(pe, "is_master", lambda uid: True)
    c = ctx()
    await cog_no_channel.debug_start_auction.callback(cog_no_channel, c)
    assert c.said("拍卖已启动") and (await wb.get_active_auction())["status"] == "active"


async def test_重启拍卖计时命令(db, cog, no_timer, monkeypatch):
    monkeypatch.setattr(pe, "is_master", lambda uid: True)
    c = ctx()
    await cog.debug_restart_timer.callback(cog, c)
    assert c.said("当前没有进行中的拍卖")

    aid = await _auction(db, "active")
    c = ctx()
    await cog.debug_restart_timer.callback(cog, c)
    await asyncio.sleep(0)
    assert c.said("已重启 lot timer") and no_timer == [aid]

    monkeypatch.setattr(pe, "is_master", lambda uid: False)
    c = ctx()
    await cog.debug_restart_timer.callback(cog, c)
    assert c.messages == []


async def test_重启拍卖计时命令_会取消正在跑的旧计时(db, cog, no_timer, monkeypatch):
    monkeypatch.setattr(pe, "is_master", lambda uid: True)
    await _auction(db, "active")
    old = asyncio.create_task(asyncio.sleep(60))
    cog._lot_task = old
    await cog.debug_restart_timer.callback(cog, ctx())
    await asyncio.sleep(0)
    assert old.cancelled() or old.done()


async def test_公共事件命令_暂无事件(db, cog):
    c = ctx()
    await cog.show_active_event.callback(cog, c)
    names = [f.name for f in c.last.embed.fields]
    assert "暂无灵雨事件" in names and any("今日举行" in n for n in names)


async def test_公共事件命令_灵雨进行中(db, cog):
    from utils.views.public_event_overview import PublicEventOverviewView
    await _add_event(db, "a", status="active", city="灵虚城")
    c = ctx()
    await cog.show_active_event.callback(cog, c)
    f = c.last.embed.fields[0]
    assert "进行中" in f.name and "灵虚城" in f.value and isinstance(c.last.view, PublicEventOverviewView)


async def test_公共事件命令_灵雨待开始_进行中优先(db, cog):
    await _add_event(db, "p", status="pending", city="灵虚城")
    c = ctx()
    await cog.show_active_event.callback(cog, c)
    assert "即将开始" in c.last.embed.fields[0].name

    await _add_event(db, "a", status="active", city="铁甲城", started_ago=1)
    c = ctx()
    await cog.show_active_event.callback(cog, c)
    assert "进行中" in c.last.embed.fields[0].name and len([f for f in c.last.embed.fields if "灵雨" in f.name]) == 1


@pytest.mark.parametrize("status,phrase", [("pending", "开始"), ("active", "当前拍品剩余")])
async def test_公共事件命令_拍卖状态(db, cog, status, phrase):
    aid = await _auction(db, status)
    if status == "active":
        await _sql(db, "UPDATE wanbao_auctions SET ends_at=:t WHERE auction_id=:a", t=time.time() + 90, a=aid)
    c = ctx()
    await cog.show_active_event.callback(cog, c)
    f = next(f for f in c.last.embed.fields if f.name.startswith("万宝楼大型拍卖会"))
    assert phrase in f.value and "**8**" in f.value


async def test_公共事件命令_已结束的拍卖不会显示_按今日举行处理(db, cog):
    """记录现状：命令用 get_active_auction() 取拍卖，它只返回 active / pending，
    所以代码里『本次拍卖已结束』那个分支实际走不到（死分支）。已结束的拍卖显示成『今日举行』。"""
    await _auction(db, "ended")
    c = ctx()
    await cog.show_active_event.callback(cog, c)
    assert any("今日举行" in f.name for f in c.last.embed.fields)
    assert not any("已结束" in f.name or "已结束" in f.value for f in c.last.embed.fields)


async def test_cog启动时启动调度循环_卸载时取消(db, channel):
    c = PublicEventsCog(FakeBot(channel))
    try:
        assert c._scheduler.is_running()
    finally:
        c.cog_unload()
    await asyncio.sleep(0.05)
    assert not c._scheduler.is_running()


async def test_cog卸载时取消正在跑的拍卖计时(db, cog):
    task = asyncio.create_task(asyncio.sleep(60))
    cog._lot_task = task
    cog.cog_unload()
    await asyncio.sleep(0)
    assert task.cancelled() or task.cancelling()
