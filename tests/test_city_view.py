"""城市菜单（utils/views/city.py）：城市简介、菜单按钮、各设施入口。

B69 —— 城市菜单上的按钮是『打开面板时』按当时状态生成的，面板能在聊天里留很久，点击时却不再核对：
  · 玩家记录不存在 → `fetchone()._mapping` 直接 AttributeError（点击『交互失败』）；
  · 已坐化的人照样能进赌坊 / 轮转 / 打工 / 签到 / 钱庄 / 交易坊 / 茶馆；
  · 玩家走进荒野（秘地）后旧菜单上的设施按钮照样能点（菜单入口只在生成时隐藏了它们）。
  现在点击时统一核对：存在、活着、不在荒野；『返回主菜单』除外。
"""

from types import SimpleNamespace

import discord
import pytest

from tests.conftest import make_player
from tests.discord_fakes import FakeContext, FakeInteraction
from utils.views import checkin as ckv
from utils.views import gamble as gbv
from utils.views import jobs as jbv
from utils.views import roulette as rtv
from utils.views.bank import BankMainView
from utils.views.city import CityMenuButton, CityMenuView, _city_menu_embed, _load_player
from utils.views.market import MarketMainView

U = "1001"
FACILITIES = ["tavern", "jobs", "checkin", "gamble", "roulette", "bank", "market"]


async def _add(db, uid=U, city="灵虚城", **kw):
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        p = make_player(D, uid, stones=1000)
        p.name = f"道友{uid}"
        p.current_city, p.lifespan = city, 80
        for k, v in kw.items():
            setattr(p, k, v)
        s.add(p)
        await s.commit()


def inter(uid=U):
    i = FakeInteraction(uid)
    i.message = SimpleNamespace(id=1)
    return i


class FakeBot:
    def __init__(self, **cogs):
        self.cogs = cogs

    async def get_context(self, message):
        return FakeContext(user_id=0)


class FakeCog:
    def __init__(self, **others):
        self.bot = FakeBot(**others)


class Tavern:
    def __init__(self):
        self.calls = []

    async def tavern(self, ctx):
        self.calls.append(ctx.author.id)


def make_view(player=None, cog=None):
    return CityMenuView(inter().user, player or {"current_city": "灵虚城"}, cog)


async def click(action, uid=U, cog=None):
    view = make_view(cog=cog)
    btn = CityMenuButton("x", action, discord.ButtonStyle.primary)
    btn._view = view
    i = inter(uid)
    await btn.callback(i)
    return i


# --- 简介卡片 -----------------------------------------------------------------

async def test_简介_城市(db):
    await _add(db)
    e = await _city_menu_embed({"current_city": "灵虚城", "discord_id": U})
    assert e.title == "✦ 灵虚城 ✦" and "所属地区：**中州**" in e.fields[0].value and "政治中心" in e.description


async def test_简介_秘地(db):
    e = await _city_menu_embed({"current_city": "百草谷", "discord_id": U})
    assert "秘地类型：**采药**" in e.fields[0].value


async def test_简介_未知地点(db):
    e = await _city_menu_embed({"current_city": "不存在", "discord_id": U})
    assert e.description == "此地信息不详。" and not e.fields
    e = await _city_menu_embed({"discord_id": U})
    assert e.title == "✦ 未知 ✦"


async def test_简介_在场修士_排除自己和死人_最多列5个(db):
    await _add(db, U)
    for n in range(7):
        await _add(db, f"20{n}")
    await _add(db, "299", is_dead=1)
    e = await _city_menu_embed({"current_city": "灵虚城", "discord_id": U})
    f = next(x for x in e.fields if x.name == "在场修士")
    lines = f.value.splitlines()
    assert len(lines) == 6 and "共 7 名修士在此" in lines[-1] and "道友1001" not in f.value and "道友299" not in f.value
    await _add(db, "3000", city="天京城")
    e = await _city_menu_embed({"current_city": "天京城", "discord_id": "other"})
    assert "道友3000" in next(x for x in e.fields if x.name == "在场修士").value


async def test_简介_没有别人时没有在场修士栏(db):
    await _add(db)
    e = await _city_menu_embed({"current_city": "灵虚城", "discord_id": U})
    assert not [x for x in e.fields if x.name == "在场修士"]


# --- 菜单组成 -----------------------------------------------------------------

def test_菜单_城市里有全部设施_荒野里只有返回():
    v = make_view({"current_city": "灵虚城"})
    assert [b.action for b in v.children] == FACILITIES + ["menu"]
    v = make_view({"current_city": "百草谷"})
    assert [b.action for b in v.children] == ["menu"]
    assert [b.action for b in make_view({}).children][-1] == "menu"


async def test_只有本人能点(db):
    v = make_view()
    assert await v.interaction_check(inter("2002")) is False


# --- 返回主菜单 ---------------------------------------------------------------

async def test_返回主菜单(db, monkeypatch):
    sent = {}

    async def fake(interaction, cog):
        sent["cog"] = cog
    monkeypatch.setattr("utils.views.world._send_main_menu", fake)
    i = await click("menu")
    assert "无法返回" in i.last
    marker = FakeCog()
    i = await click("menu", cog=marker)
    assert i.response.deferred and sent["cog"] is marker


async def test_返回主菜单_不受坐化和荒野限制(db, monkeypatch):
    await _add(db, is_dead=1, city="百草谷")
    sent = []

    async def fake(interaction, cog):
        sent.append(1)
    monkeypatch.setattr("utils.views.world._send_main_menu", fake)
    await click("menu", cog=FakeCog())
    assert sent == [1]


# --- B69：统一核对 ------------------------------------------------------------

@pytest.mark.parametrize("action", FACILITIES)
async def test_B69_玩家不存在_如实提示而不是崩(db, action):
    i = await click("%s" % action, uid="9999", cog=FakeCog(Tavern=Tavern()))
    assert "尚未踏入修仙之路" in i.last and i.last.ephemeral


@pytest.mark.parametrize("action", FACILITIES)
async def test_B69_已坐化不能用任何设施(db, action):
    await _add(db, is_dead=1)
    tavern = Tavern()
    i = await click(action, cog=FakeCog(Tavern=tavern))
    assert "已坐化" in i.last and i.last.ephemeral and not tavern.calls


@pytest.mark.parametrize("action", FACILITIES)
async def test_B69_走进荒野后旧菜单的设施按钮失效(db, action):
    await _add(db, city="百草谷")
    tavern = Tavern()
    i = await click(action, cog=FakeCog(Tavern=tavern))
    assert "秘地荒野" in i.last and i.last.ephemeral and not tavern.calls


# --- 各设施入口 ---------------------------------------------------------------

async def test_茶馆_转给茶馆cog_以点击者身份(db):
    await _add(db)
    tavern = Tavern()
    i = await click("tavern", cog=FakeCog(Tavern=tavern))
    assert i.response.deferred and tavern.calls == [int(U)]


async def test_茶馆_不可用(db):
    await _add(db)
    i = await click("tavern", cog=FakeCog())
    assert "茶馆暂时不可用" in i.last
    i = await click("tavern", cog=None)
    assert "茶馆暂时不可用" in i.last


async def test_打工入口(db):
    await _add(db)
    i = await click("jobs")
    assert isinstance(i.last.view, jbv.JobsView) and "打工" in i.last.embed.title


async def test_签到入口_未签与已签(db):
    await _add(db, checkin_last_date="2000-01-01")
    i = await click("checkin")
    assert isinstance(i.last.view, ckv.CheckinView) and "每日签到" in i.last.embed.title
    import time
    await _add(db, "1002", checkin_last_date=time.strftime("%Y-%m-%d", time.gmtime()))
    i = await click("checkin", uid="1002")
    assert "今日已签到" in i.last and i.last.ephemeral


async def test_赌坊与轮转入口(db):
    await _add(db)
    i = await click("gamble")
    assert isinstance(i.last.view, gbv.GambleView)
    i = await click("roulette")
    assert isinstance(i.last.view, rtv.RouletteView)


async def test_钱庄入口_在钱庄城市与不在(db):
    await _add(db)
    i = await click("bank")
    assert isinstance(i.last.view, BankMainView)
    await _add(db, "1002", city="天京城")
    i = await click("bank", uid="1002")
    assert "钱庄只在以下城市" in i.last and i.last.ephemeral


async def test_交易坊入口_在交易坊城市与不在(db):
    await _add(db)
    i = await click("market")
    assert isinstance(i.last.view, MarketMainView)
    await _add(db, "1002", city="天京城")
    i = await click("market", uid="1002")
    assert "交易坊只在以下城市" in i.last and i.last.ephemeral


async def test_读取玩家(db):
    await _add(db)
    assert (await _load_player(U))["current_city"] == "灵虚城" and await _load_player("nope") is None
