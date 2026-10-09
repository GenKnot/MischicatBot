"""移动面板（utils/views/travel.py）：地区 → 城市 / 秘地 → 交给 TravelCog 移动；以及世界页的城市列表面板。"""

import time
from types import SimpleNamespace

import discord
import pytest

from cogs.travel import TravelCog
from tests.conftest import make_player
from tests.discord_fakes import FakeContext, FakeInteraction
from utils.realms import get_realm_index
from utils.views.travel import (CityListView, CityRegionButton, CityRegionView, TravelAfterMoveView, TravelCityButton,
                                TravelCityView, TravelRegionView, TravelSecretButton,
                                TravelSecretView, _BackToMenuButton, _BackToTravelRegionButton, _BackToWorldButton)
from utils.world import CITIES, SPECIAL_REGIONS, cities_by_region

U = "1001"
REGIONS = ["东域", "南域", "西域", "北域", "中州"]


class Message:
    def __init__(self):
        self.edits = []

    async def edit(self, **kw):
        self.edits.append(kw)


class Bot:
    def __init__(self, **cogs):
        self.cogs = cogs

    async def get_context(self, message):
        return FakeContext(user_id=0)


class BoundTravel:
    """真实的 TravelCog，按它被 bot 注册后的样子调用（命令对象在 add_cog 之后才绑定 cog）。"""

    def __init__(self):
        self.real = TravelCog(Bot())

    async def travel(self, ctx, city_name=None):
        return await self.real.travel.callback(self.real, ctx, city_name=city_name)


def inter(uid=U):
    i = FakeInteraction(uid)
    i.message = Message()
    return i


async def _add(db, uid=U, **kw):
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        p = make_player(D, uid, stones=0)
        p.name = f"道友{uid}"
        p.current_city = kw.pop("city", "灵虚城")
        for k, v in kw.items():
            setattr(p, k, v)
        s.add(p)
        await s.commit()


async def city_of(db, uid=U):
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        return (await s.get(D.Player, uid)).current_city


def region_view(cog=None):
    return TravelRegionView(inter().user, cog)


def btn(view, cls=None, label=None):
    return next(c for c in view.children if (cls is None or isinstance(c, cls)) and (label is None or c.label == label))


# --- 地区选择 -----------------------------------------------------------------

def test_地区面板_五大洲加秘地加返回():
    v = region_view()
    labels = [c.label for c in v.children]
    assert labels == REGIONS + ["秘地", "返回主菜单"]
    assert btn(v, label="秘地").style == discord.ButtonStyle.danger


async def test_只有本人能点():
    assert await region_view().interaction_check(inter("2002")) is False


@pytest.mark.parametrize("region", REGIONS)
async def test_选择大洲_列出该洲城市(db, region):
    v = region_view()
    i = inter()
    await btn(v, label=region).callback(i)
    cities = cities_by_region(region)
    assert region in i.last.embed.title and [f.name for f in i.last.embed.fields] == [c["name"] for c in cities]
    cv = i.last.view
    assert isinstance(cv, TravelCityView) and [c.label for c in cv.children if isinstance(c, TravelCityButton)] == [c["name"] for c in cities]


async def test_选择秘地_按境界标出锁(db):
    await _add(db, realm="筑基期1层")
    v = region_view()
    i = inter()
    await btn(v, label="秘地").callback(i)
    names = {f.name.split()[0]: f.name for f in i.last.embed.fields}
    assert "🔒" in names["昆仑秘境"] and "🔒" not in names["百草谷"]
    sv = i.last.view
    assert isinstance(sv, TravelSecretView)
    disabled = {c.label: c.disabled for c in sv.children if isinstance(c, TravelSecretButton)}
    assert disabled["昆仑秘境"] is True and disabled["百草谷"] is False and disabled["幽冥海"] is False


async def test_选择秘地_没有玩家记录按炼气期算(db):
    v = region_view()
    i = inter("9999")
    await btn(v, label="秘地").callback(i)
    sv = i.last.view
    needs = {r["name"]: get_realm_index(r["min_realm"]) > get_realm_index("炼气期1层") for r in SPECIAL_REGIONS}
    assert {c.label: c.disabled for c in sv.children if isinstance(c, TravelSecretButton)} == needs


async def test_高境界玩家秘地全部解锁(db):
    await _add(db, realm="大乘期初期")
    i = inter()
    await btn(region_view(), label="秘地").callback(i)
    sv = i.last.view
    locked = [c.label for c in sv.children if isinstance(c, TravelSecretButton) and c.disabled]
    assert all(get_realm_index(r["min_realm"]) > get_realm_index("大乘期初期") for r in SPECIAL_REGIONS if r["name"] in locked)


def test_秘地按钮_按类型配表情():
    assert TravelSecretButton("x", "秘境", False).emoji.name == "🌀"
    assert TravelSecretButton("x", "采药", False).emoji.name == "🌿"
    assert TravelSecretButton("x", "未知类型", True).emoji.name == "📍" and TravelSecretButton("x", "未知类型", True).disabled


def test_城市面板与秘地面板都有两个返回():
    cv = TravelCityView(inter().user, None, cities_by_region("东域"))
    assert [type(c) for c in cv.children[-2:]] == [_BackToTravelRegionButton, _BackToMenuButton]
    sv = TravelSecretView(inter().user, None, 0)
    assert [type(c) for c in sv.children[-2:]] == [_BackToTravelRegionButton, _BackToMenuButton]
    assert len([c for c in sv.children if isinstance(c, TravelSecretButton)]) == len(SPECIAL_REGIONS)


# --- 点城市 / 秘地 → 交给 TravelCog -------------------------------------------

async def test_点城市_交给TravelCog移动并编辑原消息(db):
    await _add(db)
    cog = SimpleNamespace(bot=Bot(Travel=BoundTravel()))
    v = TravelCityView(inter().user, cog, [{"name": "天京城"}])
    i = inter()
    await btn(v, TravelCityButton).callback(i)
    assert i.response.deferred and await city_of(db) == "天京城"
    edit = i.message.edits[-1]
    assert "抵达 天京城" in edit["embed"].title and isinstance(edit["view"], TravelAfterMoveView)


async def test_点城市_没有Travel_cog时用面板自己的cog(db):
    await _add(db)
    called = {}

    class Own:
        bot = Bot()

        async def travel(self, ctx, city_name=None):
            called["name"], called["author"], called["has_component"] = city_name, ctx.author.id, hasattr(ctx, "_component_interaction")
    v = TravelCityView(inter().user, Own(), [{"name": "天京城"}])
    await btn(v, TravelCityButton).callback(inter())
    assert called == {"name": "天京城", "author": int(U), "has_component": True}


async def test_点秘地_境界不够时被cog拒绝(db):
    await _add(db, realm="炼气期1层")
    cog = SimpleNamespace(bot=Bot(Travel=BoundTravel()))
    v = TravelSecretView(inter().user, cog, 99)                   # 面板认为够（旧面板），cog 重新核对
    i = inter()
    await btn(v, TravelSecretButton, "昆仑秘境").callback(i)
    assert await city_of(db) == "灵虚城" and "境界不足" in i.message.edits[-1]["content"]


async def test_点秘地_成功(db):
    await _add(db)
    cog = SimpleNamespace(bot=Bot(Travel=BoundTravel()))
    v = TravelSecretView(inter().user, cog, 0)
    await btn(v, TravelSecretButton, "百草谷").callback(inter())
    assert await city_of(db) == "百草谷"


async def test_点城市_闭关中被cog拒绝(db):
    await _add(db, cultivating_until=time.time() + 3600)
    cog = SimpleNamespace(bot=Bot(Travel=BoundTravel()))
    v = TravelCityView(inter().user, cog, [{"name": "天京城"}])
    i = inter()
    await btn(v, TravelCityButton).callback(i)
    assert await city_of(db) == "灵虚城" and "正在闭关" in i.message.edits[-1]["content"]


# --- 返回 ---------------------------------------------------------------------

async def test_返回地区选择():
    v = TravelAfterMoveView(inter().user, None)
    i = inter()
    await btn(v, _BackToTravelRegionButton).callback(i)
    assert "选择地区" in i.last.embed.title and isinstance(i.last.view, TravelRegionView)


async def test_返回主菜单_无cog与有cog(monkeypatch):
    sent = {}

    async def fake(interaction, cog):
        sent["cog"] = cog
    monkeypatch.setattr("utils.views.world._send_main_menu", fake)
    i = inter()
    await btn(region_view(None), _BackToMenuButton).callback(i)
    assert "无法返回" in i.last and i.last.ephemeral and not sent
    marker = object()
    i = inter()
    await btn(region_view(marker), _BackToMenuButton).callback(i)
    assert i.response.deferred and sent["cog"] is marker


async def test_返回世界():
    v = CityRegionView(inter().user, None)
    i = inter()
    await btn(v, _BackToWorldButton).callback(i)
    assert i.last.embed is not None and not isinstance(i.last.view, CityRegionView)


# --- 世界页的城市列表 ---------------------------------------------------------

def test_城市地区面板_五大洲加两个返回():
    v = CityRegionView(inter().user, None)
    assert [c.label for c in v.children] == REGIONS + ["返回世界", "返回主菜单"]


@pytest.mark.parametrize("region", REGIONS)
async def test_世界页选择大洲_展示城市简介(region):
    v = CityRegionView(inter().user, None)
    i = inter()
    await btn(v, CityRegionButton, region).callback(i)
    assert region in i.last.embed.title and len(i.last.embed.fields) == len(cities_by_region(region))
    assert isinstance(i.last.view, CityListView)


def test_城市列表面板只有返回():
    v = CityListView(inter().user, None, cities_by_region("东域"))
    assert [c.label for c in v.children] == ["返回世界", "返回主菜单"]
    assert CityListView(inter().user).cog is None


def test_所有城市都出现在某个大洲():
    assert {c["name"] for r in REGIONS for c in cities_by_region(r)} == {c["name"] for c in CITIES}
