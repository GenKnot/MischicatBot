"""技艺菜单（utils/views/crafting.py）：炼丹 / 锻造入口、尚未开放的三门技艺、返回。

B77 —— 与 B69（城市菜单）同类：点『炼丹』『锻造』时直接 `fetchone()._mapping` 读玩家 ——
  · 玩家记录不存在 → `AttributeError`（点击『交互失败』）；
  · 已坐化的玩家（旧面板）照样能进炼丹台 / 铸造坊，而炼丹和锻造的逻辑层并不检查 `is_dead`，
    死人可以接着开炉、领经验、升品级。
  入口统一核对：玩家存在、没坐化。
"""

from tests.conftest import make_player
from tests.discord_fakes import FakeInteraction
from utils.views.alchemy import AlchemyMainView
from utils.views.crafting import CraftingMenuView, CraftingView, _crafting_overview_embed
from utils.views.forging import ForgingMainView

U = "1001"


async def _add(db, uid=U, **kw):
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        p = make_player(D, uid, stones=0)
        p.name = f"道友{uid}"
        for k, v in kw.items():
            setattr(p, k, v)
        s.add(p)
        await s.commit()


def inter(uid=U):
    return FakeInteraction(uid)


def view(cog=None):
    return CraftingMenuView(inter().user, cog)


def test_技艺总览文案():
    e = _crafting_overview_embed()
    names = [f.name for f in e.fields]
    assert e.title == "✦ 技艺 ✦" and len(names) == 5
    assert "🔥 炼丹" in names and "⚙️ 锻造" in names and sum("敬请期待" in n for n in names) == 3


def test_按钮组成_三门未开放的被禁用():
    v = view()
    labels = {c.label: c.disabled for c in v.children}
    assert labels["🔥 炼丹"] is False and labels["⚙️ 锻造"] is False and labels["返回主菜单"] is False
    assert labels["🪆 练傀"] and labels["🔮 阵法"] and labels["📜 制符"]
    assert CraftingView is CraftingMenuView


async def test_只有本人能点():
    assert await view().interaction_check(inter("2002")) is False


async def test_未开放技艺的提示():
    v = view()
    for btn, word in ((v.puppet_btn, "练傀"), (v.array_btn, "阵法"), (v.talisman_btn, "制符")):
        i = inter()
        await btn.callback(i)
        assert word in i.last and "尚未开放" in i.last and i.last.ephemeral


# --- 炼丹入口 -----------------------------------------------------------------

async def test_炼丹_已入门进入炼丹台(db):
    await _add(db, alchemy_level=2)
    i = inter()
    await view().alchemy_btn.callback(i)
    assert isinstance(i.last.view, AlchemyMainView) and i.last.content == "炼丹台："


async def test_炼丹_未入门且不在丹阁被拒(db):
    await _add(db, alchemy_level=0, current_city="灵虚城")
    i = inter()
    await view().alchemy_btn.callback(i)
    assert "尚未入门炼丹" in i.last and i.last.ephemeral and i.last.view is None


async def test_炼丹_未入门但在丹阁可以进(db):
    await _add(db, alchemy_level=0, current_city="丹阁")
    i = inter()
    await view().alchemy_btn.callback(i)
    assert isinstance(i.last.view, AlchemyMainView)


async def test_炼丹_带上已知丹方与异火(db):
    await _add(db, alchemy_level=2)
    from utils.alchemy import unlock_recipe
    await unlock_recipe(U, "juling_1", [1])
    i = inter()
    await view().alchemy_btn.callback(i)
    v = i.last.view
    assert v.known_ids == {"juling_1"} and v.known_choices == {"juling_1": [1]} and v.has_yanhuo is False


async def test_B77_炼丹_玩家不存在(db):
    i = inter("9999")
    await view().alchemy_btn.callback(i)
    assert "尚未踏入修仙之路" in i.last and i.last.ephemeral


async def test_B77_炼丹_已坐化(db):
    await _add(db, alchemy_level=3, is_dead=1)
    i = inter()
    await view().alchemy_btn.callback(i)
    assert "已坐化" in i.last and i.last.ephemeral and i.last.view is None


# --- 锻造入口 -----------------------------------------------------------------

async def test_锻造_已入门进入铸造坊(db):
    await _add(db, forging_level=1, current_city="灵虚城")
    i = inter()
    await view().forge_btn.callback(i)
    assert isinstance(i.last.view, ForgingMainView) and "铸造坊" in i.last.embed.title


async def test_锻造_未入门且不在铸造城市被拒(db):
    await _add(db, forging_level=0, current_city="灵虚城")
    i = inter()
    await view().forge_btn.callback(i)
    assert "尚未入门炼器" in i.last and "铸剑城" in i.last and i.last.ephemeral


async def test_锻造_未入门但在铸造城市可以进(db):
    await _add(db, forging_level=0, current_city="铸剑城")
    i = inter()
    await view().forge_btn.callback(i)
    assert isinstance(i.last.view, ForgingMainView)


async def test_B77_锻造_玩家不存在(db):
    i = inter("9999")
    await view().forge_btn.callback(i)
    assert "尚未踏入修仙之路" in i.last and i.last.ephemeral


async def test_B77_锻造_已坐化(db):
    await _add(db, forging_level=2, is_dead=1)
    i = inter()
    await view().forge_btn.callback(i)
    assert "已坐化" in i.last and i.last.ephemeral and i.last.view is None


# --- 返回 ---------------------------------------------------------------------

async def test_返回主菜单(db, monkeypatch):
    sent = {}

    async def fake(interaction, cog):
        sent["cog"] = cog
    monkeypatch.setattr("utils.views.world._send_main_menu", fake)
    marker = object()
    i = inter()
    await view(marker).back_btn.callback(i)
    assert i.response.deferred and sent["cog"] is marker
