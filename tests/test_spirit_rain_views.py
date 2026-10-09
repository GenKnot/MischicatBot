"""灵雨活动的面板测试（utils/views/spirit_rain.py）。

这是公共事件广播里的那组按钮：前往事件城市、确认「停止并前往」、事件详情、返回。
它们会改玩家的位置，还会**提前结束闭关 / 采集**，之前零覆盖 ——
S9 合并停止闭关逻辑时，这个文件还在调用被删掉的旧方法，测试一个都没红（只是靠全仓 grep 才抓到）。

结构：A 查询辅助  B 前往城市  C 确认停止并前往  D 事件详情  E 返回公共事件 / 主菜单  F 主菜单构造
"""

import json
import time
import types
from datetime import datetime
from zoneinfo import ZoneInfo


from tests.conftest import make_player
from tests.discord_fakes import FakeInteraction
from utils.character import calc_cultivation_gain, years_to_seconds
from utils.views import spirit_rain as sr
from utils.views.spirit_rain import (
    ConfirmStopAndTravelView, TravelToEventView, _BackToOverviewView, _EventDetailButton,
)

UID = "1"
CITY = "铁甲城"


async def _add_player(db, uid=UID, **fields):
    D = db["db_async"]
    p = make_player(D, uid, stones=500)
    p.name = f"道友{uid}"
    p.current_city = "灵虚城"
    for k, v in fields.items():
        setattr(p, k, v)
    async with D.AsyncSessionLocal() as s:
        s.add(p)
        await s.commit()


async def _row(db, uid=UID):
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        return await s.get(D.Player, uid)


async def _add_event(db, event_id="ev1", status="active", city=CITY, started_ago=60, ends_in=3600, title="天降灵雨"):
    D = db["db_async"]
    now = time.time()
    async with D.AsyncSessionLocal() as s:
        s.add(D.PublicEvent(event_id=event_id, event_type="spirit_rain", title=title, status=status,
                            started_at=now - started_ago, ends_at=now + ends_in, data=json.dumps({"city": city})))
        await s.commit()


async def _participate(db, event_id="ev1", uid=UID, activity="defense"):
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        s.add(D.PublicEventParticipant(event_id=event_id, discord_id=uid, activity=activity, joined_at=time.time()))
        await s.commit()


def it(uid=UID, cogs=None):
    i = FakeInteraction(user_id=int(uid))
    i.client = types.SimpleNamespace(cogs=cogs or {})
    return i


def pe_cog_with(cultivation_cog=None):
    cogs = {"Cultivation": cultivation_cog} if cultivation_cog else {}
    return types.SimpleNamespace(bot=types.SimpleNamespace(cogs=cogs))


def _mid(elapsed, total=10, **extra):
    now = time.time()
    return dict(cultivating_until=now + years_to_seconds(total - elapsed), cultivating_years=total,
                last_active=now - years_to_seconds(elapsed), **extra)


# =============================================================================
# A. 查询辅助
# =============================================================================

async def test_进行中的事件_取最近开始且未结束的(db):
    await _add_event(db, "old", started_ago=500)
    await _add_event(db, "new", started_ago=10)
    await _add_event(db, "expired", started_ago=5, ends_in=-1)             # 已过结束时间
    await _add_event(db, "done", status="ended", started_ago=1)

    ev = await sr._get_active_event()

    assert ev["event_id"] == "new"


async def test_没有进行中的事件返回空(db):
    await _add_event(db, "p", status="pending")
    assert await sr._get_active_event() is None


async def test_待开始的事件_取最近的(db):
    await _add_event(db, "p1", status="pending", started_ago=500)
    await _add_event(db, "p2", status="pending", started_ago=10)
    await _add_event(db, "a", status="active")
    assert (await sr._get_pending_event())["event_id"] == "p2"


async def test_没有待开始的事件返回空(db):
    assert await sr._get_pending_event() is None


def test_今日触发时间是蒙特利尔时间二十一点():
    ts = sr._today_trigger_ts()
    dt = datetime.fromtimestamp(ts, ZoneInfo("America/Montreal"))
    assert (dt.hour, dt.minute, dt.second) == (21, 0, 0)
    assert dt.date() == datetime.now(ZoneInfo("America/Montreal")).date()


# =============================================================================
# B. 前往城市
# =============================================================================

def travel_view(pe_cog=None):
    return TravelToEventView(CITY, "ev1", pe_cog)


async def test_前往_是公共广播面板_没有超时(db):
    view = travel_view()
    assert view.public is True and view.timeout is None


async def test_前往_没有角色(db):
    i = it()
    await travel_view().travel.callback(i)
    assert i.said("尚未踏入修仙之路") and i.last.ephemeral


async def test_前往_已坐化(db):
    await _add_player(db, is_dead=True)
    i = it()
    await travel_view().travel.callback(i)
    assert i.said("已坐化")


async def test_前往_已经在那座城(db):
    await _add_player(db, current_city=CITY)
    i = it()
    await travel_view().travel.callback(i)
    assert i.said("无需移动")


async def test_前往_成功_改城市_记最近活动时间(db):
    await _add_player(db)
    before = time.time()
    i = it()

    await travel_view().travel.callback(i)

    p = await _row(db)
    assert p.current_city == CITY and p.last_active >= before
    assert i.said(f"已传送至 **{CITY}**") and i.last.ephemeral


async def test_前往_闭关中_先问是否停止(db):
    await _add_player(db, **_mid(3))
    i = it()

    await travel_view().travel.callback(i)

    assert isinstance(i.last.view, ConfirmStopAndTravelView)
    assert i.said("闭关修炼") and i.said("是否停止并前往")
    assert (await _row(db)).current_city == "灵虚城"                       # 还没走
    assert i.last.view.is_cultivating and not i.last.view.is_gathering


async def test_前往_采集中_先问是否停止_并带上采集类型(db):
    await _add_player(db, gathering_until=time.time() + 3600, gathering_type="采药")
    i = it()

    await travel_view().travel.callback(i)

    assert isinstance(i.last.view, ConfirmStopAndTravelView)
    assert i.said("正在**采药**中") and i.last.view.is_gathering


async def test_前往_有任务_不能移动(db):
    await _add_player(db, active_quest=json.dumps({"title": "护送"}))
    i = it()
    await travel_view().travel.callback(i)
    assert i.said("正在执行任务") and (await _row(db)).current_city == "灵虚城"


async def test_前往_正在守城_不能离开(db):
    await _add_event(db, "ev1", status="active")
    await _participate(db, "ev1", activity="defense")
    await _add_player(db)
    i = it()

    await travel_view().travel.callback(i)

    assert i.said("你正在守城，无法离开") and (await _row(db)).current_city == "灵虚城"


async def test_前往_守城的事件已结束_可以走(db):
    await _add_event(db, "ev1", status="ended")
    await _participate(db, "ev1", activity="defense")
    await _add_player(db)
    i = it()
    await travel_view().travel.callback(i)
    assert (await _row(db)).current_city == CITY


async def test_前往_参加的不是守城_不受限(db):
    await _add_event(db, "ev1", status="active")
    await _participate(db, "ev1", activity="crystal")
    await _add_player(db)
    i = it()
    await travel_view().travel.callback(i)
    assert (await _row(db)).current_city == CITY


async def test_前往面板_返回主菜单(db):
    from utils.views.menu import MainMenuView
    await _add_player(db)
    cult = types.SimpleNamespace()
    view = travel_view(pe_cog_with(cult))
    i = it()

    await view.back_menu.callback(i)

    assert isinstance(i.last.view, MainMenuView) and i.last.ephemeral


async def test_前往面板_没有闭关cog或没有来源时无法返回(db):
    for view in (travel_view(None), travel_view(pe_cog_with(None))):
        i = it()
        await view.back_menu.callback(i)
        assert i.said("无法返回")


# =============================================================================
# C. 确认「停止并前往」
# =============================================================================

def confirm_view(player, *, cultivating=False, gathering=False, activity="闭关修炼"):
    return ConfirmStopAndTravelView(UID, CITY, activity, cultivating, gathering, player)


async def _snapshot(uid=UID):
    from utils.player import get_player
    return await get_player(uid)


async def test_确认_别人不能替我点(db):
    await _add_player(db)
    view = confirm_view(await _snapshot(), cultivating=True)
    for button in (view.confirm, view.cancel):
        i = it("999")
        await button.callback(i)
        assert i.said("这不是你的操作")
    assert not view.is_finished()


async def test_确认_取消(db):
    await _add_player(db, **_mid(3))
    view = confirm_view(await _snapshot(), cultivating=True)
    i = it()

    await view.cancel.callback(i)

    assert i.said("已取消") and view.is_finished()
    assert (await _row(db)).current_city == "灵虚城" and (await _row(db)).cultivating_until is not None


async def test_确认_有闭关cog_交给它结算再传送(db):
    from cogs.cultivation import CultivationCog
    cog = CultivationCog(bot=types.SimpleNamespace(cogs={}))
    await _add_player(db, lifespan=50, **_mid(4))
    view = confirm_view(await _snapshot(), cultivating=True)
    i = it(cogs={"Cultivation": cog})

    await view.confirm.callback(i)

    p = await _row(db)
    assert p.current_city == CITY and p.cultivating_until is None
    assert p.cultivation == int(calc_cultivation_gain(4, 5, "单灵根")) and p.lifespan == 50 - 4
    assert i.said(f"已停止**闭关修炼**，传送至 **{CITY}**") and view.is_finished()


async def test_确认_没有闭关cog_走兜底结算(db):
    """闭关 cog 取不到时的兜底：按实际闭关的年数结算修为和寿元，再传送。这条分支此前没人跑过。"""
    await _add_player(db, lifespan=50, cultivation=7, **_mid(4))
    view = confirm_view(await _snapshot(), cultivating=True)
    i = it()

    await view.confirm.callback(i)

    p = await _row(db)
    assert p.current_city == CITY and p.cultivating_until is None and p.cultivating_years is None
    assert p.cultivation == 7 + int(calc_cultivation_gain(4, 5, "单灵根"))
    assert p.lifespan == 50 - 4 and p.cultivation_overflow == 0


async def test_确认_兜底结算_有预存收益时按已过比例兑现(db):
    """双修留下的 cultivation_overflow 是整段闭关的总收益，提前停止按已过年数的比例兑现。"""
    await _add_player(db, cultivation=0, cultivation_overflow=1000, **_mid(4, total=10))
    view = confirm_view(await _snapshot(), cultivating=True)

    await view.confirm.callback(it())

    p = await _row(db)
    assert p.cultivation == 1000 * 4 // 10 and p.cultivation_overflow == 0


async def test_确认_兜底结算_实际年数不超过计划(db):
    await _add_player(db, lifespan=50, **_mid(elapsed=15, total=10))
    view = confirm_view(await _snapshot(), cultivating=True)
    await view.confirm.callback(it())
    p = await _row(db)
    assert p.lifespan == 50 - 10 and p.cultivation == int(calc_cultivation_gain(10, 5, "单灵根"))


async def test_确认_兜底结算_寿元不会扣成负数(db):
    await _add_player(db, lifespan=2, **_mid(elapsed=6, total=10))
    view = confirm_view(await _snapshot(), cultivating=True)
    await view.confirm.callback(it())
    assert (await _row(db)).lifespan == 0


async def test_确认_停止采集_清掉采集状态_不发材料(db):
    await _add_player(db, gathering_until=time.time() + 3600, gathering_type="采药")
    view = confirm_view(await _snapshot(), gathering=True, activity="采药")
    i = it()

    await view.confirm.callback(i)

    p = await _row(db)
    assert p.gathering_until is None and p.gathering_type is None and p.current_city == CITY
    assert await db["inventory"].get_inventory(UID) == {}                  # 中途停止没有产出
    assert i.said("已停止**采药**")


async def test_确认_连点_结算只发生一次(db):
    """兜底分支靠『仍在闭关』当条件：第二次点击落空，不会再扣一遍寿元、再加一遍修为。"""
    await _add_player(db, lifespan=50, **_mid(4))
    view = confirm_view(await _snapshot(), cultivating=True)
    first, second = it(), it()

    await view.confirm.callback(first)
    after_first = await _row(db)
    await view.confirm.callback(second)

    assert second.said("状态已变化")
    after_second = await _row(db)
    assert (after_second.cultivation, after_second.lifespan) == (after_first.cultivation, after_first.lifespan)


async def test_确认_采集连点_第二次落空(db):
    await _add_player(db, gathering_until=time.time() + 3600, gathering_type="采药")
    view = confirm_view(await _snapshot(), gathering=True, activity="采药")
    await view.confirm.callback(it())
    again = it()
    await view.confirm.callback(again)
    assert again.said("状态已变化")


async def test_确认_期间闭关已被别处结束_不再结算也不传送(db):
    """点确认之前，闭关已经被别的入口（比如定时任务）结算掉了：条件不成立，不能重复结算。"""
    await _add_player(db, lifespan=50, **_mid(4))
    view = confirm_view(await _snapshot(), cultivating=True)
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        p = await s.get(D.Player, UID)
        p.cultivating_until = None
        p.cultivating_years = None
        await s.commit()
    i = it()

    await view.confirm.callback(i)

    assert i.said("状态已变化")
    p = await _row(db)
    assert p.cultivation == 0 and p.lifespan == 50 and p.current_city == "灵虚城"


# =============================================================================
# D. 事件详情按钮
# =============================================================================

async def test_详情_当前没有事件_给出说明和返回(db):
    i = it()
    await _EventDetailButton("天降灵雨", None, None).callback(i)
    m = i.last
    assert "天降灵雨" in m.embed.title and "当前无进行中的事件" in m.embed.footer.text
    assert isinstance(m.view, _BackToOverviewView) and m.ephemeral


async def test_详情_进行中_显示城市剩余时间与参与人数(db):
    from utils.events.public.spirit_rain import SpiritRainView
    await _add_event(db, "ev1", status="active", ends_in=1800)
    await _participate(db, "ev1", "1", "crystal")
    await _participate(db, "ev1", "2", "defense")
    event = await sr._get_active_event()
    i = it()

    await _EventDetailButton("天降灵雨", event, None).callback(i)

    m = i.last
    fields = {f.name: f.value for f in m.embed.fields}
    assert "进行中" in m.embed.title and fields["当前城市"] == CITY and fields["参与人数"] == "2"
    assert 29 <= int(fields["剩余时间"].split()[0]) <= 30
    assert isinstance(m.view, SpiritRainView)


async def test_详情_待开始_显示降临城市与倒计时_并带前往按钮(db):
    await _add_event(db, "ev1", status="pending")
    event = await sr._get_pending_event()
    i = it()

    await _EventDetailButton("天降灵雨", event, None).callback(i)

    m = i.last
    fields = {f.name: f.value for f in m.embed.fields}
    assert "即将开始" in m.embed.title and fields["降临城市"] == CITY and "距开始" in fields
    assert isinstance(m.view, TravelToEventView) and m.view.city == CITY


async def test_详情_事件数据里没有城市时显示未知(db):
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        s.add(D.PublicEvent(event_id="x", event_type="spirit_rain", title="t", status="pending",
                            started_at=time.time(), ends_at=time.time() + 60, data="{}"))
        await s.commit()
    i = it()
    await _EventDetailButton("t", await sr._get_pending_event(), None).callback(i)
    assert i.said("未知城市") or any(f.value == "未知城市" for f in i.last.embed.fields)


# =============================================================================
# E. 返回公共事件 / 主菜单
# =============================================================================

async def test_返回公共事件_没有来源无法返回(db):
    view = _BackToOverviewView(types.SimpleNamespace(), None)
    i = it()
    await view.back_overview.callback(i)
    assert i.said("无法返回")


async def test_返回公共事件_进行中(db):
    from utils.views.public_event_overview import PublicEventOverviewView
    await _add_event(db, "ev1", status="active")
    view = _BackToOverviewView(types.SimpleNamespace(), pe_cog_with(None))
    i = it()

    await view.back_overview.callback(i)

    m = i.last
    assert "进行中" in m.embed.fields[0].name and CITY in m.embed.fields[0].value
    assert isinstance(m.view, PublicEventOverviewView) and m.ephemeral


async def test_返回公共事件_待开始(db):
    await _add_event(db, "ev1", status="pending")
    view = _BackToOverviewView(types.SimpleNamespace(), pe_cog_with(None))
    i = it()
    await view.back_overview.callback(i)
    assert "即将开始" in i.last.embed.fields[0].name


async def test_返回公共事件_进行中优先于待开始(db):
    await _add_event(db, "a", status="active")
    await _add_event(db, "p", status="pending")
    view = _BackToOverviewView(types.SimpleNamespace(), pe_cog_with(None))
    i = it()
    await view.back_overview.callback(i)
    assert len(i.last.embed.fields) == 1 and "进行中" in i.last.embed.fields[0].name
    assert i.last.view.active["event_id"] == "a" and i.last.view.pending is None       # 总览面板拿到的也是进行中的那个


async def test_返回公共事件_暂无事件(db):
    view = _BackToOverviewView(types.SimpleNamespace(), pe_cog_with(None))
    i = it()
    await view.back_overview.callback(i)
    assert i.last.embed.fields[0].name == "暂无事件" and "21:00" in i.last.embed.fields[0].value


async def test_事件详情的返回主菜单(db):
    from utils.views.menu import MainMenuView
    await _add_player(db)
    ok = _BackToOverviewView(types.SimpleNamespace(), pe_cog_with(types.SimpleNamespace()))
    i = it()
    await ok.back_menu.callback(i)
    assert isinstance(i.last.view, MainMenuView)

    for view in (_BackToOverviewView(types.SimpleNamespace(), None),
                 _BackToOverviewView(types.SimpleNamespace(), pe_cog_with(None))):
        i = it()
        await view.back_menu.callback(i)
        assert i.said("无法返回")


# =============================================================================
# F. 主菜单构造
# =============================================================================

async def test_主菜单_有角色_结算时间并带同城玩家(db):
    await _add_player(db, lifespan=50, last_active=time.time() - years_to_seconds(4))
    await _add_player(db, "3003")
    await _add_player(db, "4004", current_city="别处")
    await _add_player(db, "5005", is_dead=True)
    i = it()

    embed, view = await sr._build_main_menu(i, types.SimpleNamespace())

    assert embed is not None
    assert [p["discord_id"] for p in view._city_players] == ["3003"]
    assert (await _row(db)).lifespan < 50                                  # settle_time 已按空闲时间扣寿元


async def test_主菜单_没有角色或已坐化_给出创建角色入口(db):
    i = it()
    _, view = await sr._build_main_menu(i, types.SimpleNamespace())
    assert any(getattr(b, "label", "") == "创建角色" for b in view.children)

    await _add_player(db, "2", is_dead=True)
    _, view = await sr._build_main_menu(it("2"), types.SimpleNamespace())
    assert any(getattr(b, "label", "") == "创建角色" for b in view.children)


async def test_主菜单_修为圆满时出现突破按钮(db):
    from utils.realms import cultivation_needed
    await _add_player(db, realm="炼气期1层", cultivation=cultivation_needed("炼气期1层"))
    _, view = await sr._build_main_menu(it(), types.SimpleNamespace())
    assert any(getattr(b, "label", "") == "突破" for b in view.children)
