"""移动与世界命令（cogs/travel.py）。

B44 —— 移动的最后一步是无条件 `UPDATE players SET current_city = …`：前面检查过『没在闭关 / 采集』，
  但检查与写入之间隔着好几个 await（还有守城查询），期间开始闭关 / 采集的话，人照样被搬走。
  现在 UPDATE 自带『没在闭关 / 采集』条件，写不进就提示状态变了。
"""

import time
from types import SimpleNamespace

import pytest

from cogs.travel import TravelCog
from tests.conftest import make_player
from tests.discord_fakes import FakeContext
from utils import player as player_mod
from utils.views import travel as tv
from utils.world import CITIES, SPECIAL_REGIONS, cities_by_region

U = "1001"


class Bot:
    def __init__(self, **cogs):
        self.cogs = cogs


@pytest.fixture
def cog():
    return TravelCog(Bot())


async def _add(db, uid=U, city="灵虚城", realm="炼气期1层", **kw):
    D = db["db_async"]
    p = make_player(D, uid, stones=0)
    p.name = f"道友{uid}"
    p.current_city, p.realm = city, realm
    for k, v in kw.items():
        setattr(p, k, v)
    async with D.AsyncSessionLocal() as s:
        s.add(p)
        await s.commit()


async def city_of(db, uid=U):
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        return (await s.get(D.Player, uid)).current_city


def ctx(uid=U):
    return FakeContext(user_id=uid)


async def go(cog, c, arg=None):
    return await cog.travel.callback(cog, c, city_name=arg)


# --- 前置 ---------------------------------------------------------------------

async def test_没有角色_已坐化(db, cog):
    c = ctx()
    await go(cog, c, "天京城")
    assert c.said("尚未踏入修仙之路")
    await _add(db, is_dead=1)
    c = ctx()
    await go(cog, c, "天京城")
    assert c.said("已坐化") and await city_of(db) == "灵虚城"


# --- 菜单 ---------------------------------------------------------------------

async def test_无参数_列出五大洲所有城市(db, cog):
    await _add(db)
    c = ctx()
    await go(cog, c)
    e = c.last.embed
    assert [f.name for f in e.fields] == ["【东域】", "【南域】", "【西域】", "【北域】", "【中州】"]
    for city in CITIES:
        assert city["name"] in "".join(f.value for f in e.fields)
    assert isinstance(c.last.view, tv.TravelRegionView)


async def test_无参数_空格参数等同无参数(db, cog):
    await _add(db)
    c = ctx()
    await go(cog, c, "   ")
    assert isinstance(c.last.view, tv.TravelRegionView)


@pytest.mark.parametrize("region", ["东域", "南域", "西域", "北域", "中州"])
async def test_大洲参数_进入城市选择(db, cog, region):
    await _add(db)
    c = ctx()
    await go(cog, c, region)
    assert region in c.last.embed.title and isinstance(c.last.view, tv.TravelCityView)
    assert [f.name for f in c.last.embed.fields] == [x["name"] for x in cities_by_region(region)]


async def test_秘地参数_标出境界锁(db, cog):
    await _add(db, realm="筑基期1层")
    c = ctx()
    await go(cog, c, "秘地")
    names = {f.name.split()[0]: f.name for f in c.last.embed.fields}
    assert "🔒" in names["昆仑秘境"] and "🔒" not in names["百草谷"] and "🔒" not in names["幽冥海"]
    assert len(c.last.embed.fields) == len(SPECIAL_REGIONS) and isinstance(c.last.view, tv.TravelSecretView)


# --- 状态阻挡 -----------------------------------------------------------------

async def test_闭关中不能移动_闭关已结束可以(db, cog):
    await _add(db, cultivating_until=time.time() + 7200)
    c = ctx()
    await go(cog, c, "天京城")
    assert c.said("正在闭关") and c.said("1.0 年") and await city_of(db) == "灵虚城"
    D = db["db_async"]
    from sqlalchemy import update
    async with D.AsyncSessionLocal() as s:
        await s.execute(update(D.Player).values(cultivating_until=time.time() - 1))
        await s.commit()
    c = ctx()
    await go(cog, c, "天京城")
    assert await city_of(db) == "天京城"


async def test_采集中不能移动(db, cog):
    await _add(db, gathering_until=time.time() + 3600)
    c = ctx()
    await go(cog, c, "天京城")
    assert c.said("正在采集") and await city_of(db) == "灵虚城"


async def _defend(db, uid=U):
    from sqlalchemy import text
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        await s.execute(text("INSERT INTO public_events (event_id, event_type, title, started_at, ends_at, status, data) "
                             "VALUES ('E1', 'x', 't', 0, 9e12, 'active', '{}')"))
        await s.execute(text("INSERT INTO public_event_participants (event_id, discord_id, activity, joined_at) "
                             "VALUES ('E1', :u, 'defense', 0)"), {"u": uid})
        await s.commit()


async def test_守城中不能离开(db, cog):
    await _add(db)
    await _defend(db)
    c = ctx()
    await go(cog, c, "天京城")
    assert c.said("正在守城") and await city_of(db) == "灵虚城"


# --- 目的地解析 ---------------------------------------------------------------

async def test_精确城市名_移动成功(db, cog):
    await _add(db)
    c = ctx()
    await go(cog, c, "天京城")
    assert await city_of(db) == "天京城"
    e = c.last.embed
    assert "抵达 天京城" in e.title and "中州" in e.footer.text and "原驻地：灵虚城" in e.footer.text
    assert c.last.view is None


async def test_已在目的地(db, cog):
    await _add(db, city="天京城")
    c = ctx()
    await go(cog, c, "天京城")
    assert c.said("无需移动")


async def test_唯一模糊匹配(db, cog):
    await _add(db)
    c = ctx()
    await go(cog, c, "天京")
    assert await city_of(db) == "天京城"


async def test_多个匹配_要求完整名(db, cog):
    await _add(db)
    c = ctx()
    await go(cog, c, "城")
    assert c.said("找到多个匹配城市") and await city_of(db) == "灵虚城"


async def test_找不到城市(db, cog):
    await _add(db)
    c = ctx()
    await go(cog, c, "不存在的地方")
    assert c.said("未找到城市「不存在的地方」") and await city_of(db) == "灵虚城"


async def test_秘地_境界不足被拒_够了可去(db, cog):
    await _add(db, realm="炼气期1层")
    c = ctx()
    await go(cog, c, "昆仑秘境")
    assert c.said("境界不足") and c.said("结丹期初期") and await city_of(db) == "灵虚城"
    await _add(db, "1002", realm="结丹期初期")
    c = ctx("1002")
    await go(cog, c, "昆仑秘境")
    assert await city_of(db, "1002") == "昆仑秘境" and "秘地" in c.last.embed.footer.text


async def test_低门槛秘地直接去(db, cog):
    await _add(db)
    await go(cog, ctx(), "百草谷")
    assert await city_of(db) == "百草谷"


# --- 并发（B44） --------------------------------------------------------------

async def test_B44_检查之后才开始闭关_不会被搬走(db, cog, monkeypatch):
    await _add(db)
    real = player_mod.is_defending
    D = db["db_async"]

    async def racing(uid):
        from sqlalchemy import update
        async with D.AsyncSessionLocal() as s:               # 模拟：检查通过后，另一处刚好开始闭关
            await s.execute(update(D.Player).values(cultivating_until=time.time() + 3600))
            await s.commit()
        return await real(uid)
    monkeypatch.setattr("cogs.travel.is_defending", racing)
    c = ctx()
    await go(cog, c, "天京城")
    assert await city_of(db) == "灵虚城" and c.said("状态刚刚变化")


# --- 来自按钮 -----------------------------------------------------------------

class Msg:
    def __init__(self):
        self.edits = []

    async def edit(self, **kw):
        self.edits.append(kw)


async def test_来自按钮_编辑原消息而不是发新消息(db, cog):
    await _add(db)
    c = ctx()
    c._component_interaction = SimpleNamespace(message=Msg())
    await go(cog, c, "天京城")
    assert c.messages == [] and await city_of(db) == "天京城"
    edit = c._component_interaction.message.edits[-1]
    assert "抵达 天京城" in edit["embed"].title and isinstance(edit["view"], tv.TravelAfterMoveView)


async def test_来自按钮_错误提示也编辑原消息(db, cog):
    await _add(db, gathering_until=time.time() + 3600)
    c = ctx()
    c._component_interaction = SimpleNamespace(message=Msg())
    await go(cog, c, "天京城")
    assert c.messages == [] and "正在采集" in c._component_interaction.message.edits[-1]["content"]


async def test_主菜单cog优先取Cultivation(db):
    marker = object()
    c = TravelCog(Bot(Cultivation=marker))
    await _add(db)
    cc = ctx()
    await go(c, cc)
    assert cc.last.view.cog is marker


# --- 世界 ---------------------------------------------------------------------

async def test_世界命令_按大洲列出全部城市(db, cog):
    c = ctx()
    await cog.world_map.callback(cog, c)
    e = c.last.embed
    assert {f.name for f in e.fields} == {"东域", "南域", "西域", "北域", "中州"}
    assert sum(len(f.value.split("、")) for f in e.fields) == len(CITIES)


async def test_B44_检查之后才开始采集_不会被搬走(db, cog, monkeypatch):
    await _add(db)
    real = player_mod.is_defending
    D = db["db_async"]

    async def racing(uid):
        from sqlalchemy import update
        async with D.AsyncSessionLocal() as s:
            await s.execute(update(D.Player).values(gathering_until=time.time() + 3600))
            await s.commit()
        return await real(uid)
    monkeypatch.setattr("cogs.travel.is_defending", racing)
    c = ctx()
    await go(cog, c, "天京城")
    assert await city_of(db) == "灵虚城" and c.said("状态刚刚变化")
