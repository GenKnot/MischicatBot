"""排行榜（utils/views/leaderboard.py）。

B70 —— 境界榜只按境界下标排序，同境界的人顺序取决于数据库行序（基本是注册先后）：同一境界里修为最高的人
  可能排在最后、甚至被挤出前十。同境界按修为从高到低排。
"""

import pytest

from tests.conftest import make_player
from tests.discord_fakes import FakeInteraction
from utils.views import leaderboard as lb
from utils.views.leaderboard import (LeaderboardView, _BOARDS, _build_alchemy_embed, _build_lifespan_embed,
                                     _build_power_embed, _build_realm_embed, _build_reputation_embed,
                                     _build_wealth_embed, _medal)

U = "1001"


async def _add(db, uid, **kw):
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        p = make_player(D, uid, stones=kw.pop("stones", 0))
        p.name = kw.pop("name", f"道友{uid}")
        for k, v in kw.items():
            setattr(p, k, v)
        s.add(p)
        await s.commit()


def lines(embed):
    return embed.description.splitlines()


def test_奖牌():
    assert [_medal(i) for i in range(5)] == ["🥇", "🥈", "🥉", "`4.`", "`5.`"]


# --- 各榜 ---------------------------------------------------------------------

@pytest.mark.parametrize("builder,empty", [
    (_build_realm_embed, "暂无数据"), (_build_power_embed, "暂无数据"), (_build_lifespan_embed, "暂无数据"),
    (_build_reputation_embed, "暂无数据"), (_build_alchemy_embed, "暂无入门炼丹师"), (_build_wealth_embed, "暂无数据"),
])
async def test_空榜单(db, builder, empty):
    assert (await builder()).description == empty


async def test_境界榜_按境界排序_带轮回次数(db):
    await _add(db, "1", name="甲", realm="炼气期1层")
    await _add(db, "2", name="乙", realm="结丹期初期", rebirth_count=2)
    await _add(db, "3", name="丙", realm="筑基期1层")
    e = await _build_realm_embed()
    assert e.title == "✦ 境界榜 ✦"
    ls = lines(e)
    assert ls[0] == "🥇 **乙** — 结丹期初期（轮回 2 次）" and ls[1].startswith("🥈 **丙**") and ls[2].startswith("🥉 **甲**")
    assert "轮回" not in ls[1]


async def test_B70_境界榜_同境界按修为排_不是注册先后(db):
    for n in range(12):                                         # 12 个同境界，修为递增：最后注册的修为最高
        await _add(db, f"{100 + n}", name=f"修士{n}", realm="筑基期1层", cultivation=n * 10)
    e = await _build_realm_embed()
    ls = lines(e)
    assert len(ls) == 10 and "修士11" in ls[0] and "修士10" in ls[1] and "修士2" in ls[-1]
    assert "修士1**" not in e.description and "修士0**" not in e.description         # 修为最低的两位被挤出前十


async def test_榜单_不含已坐化的人(db):
    await _add(db, "1", name="活人", realm="炼气期1层")
    await _add(db, "2", name="死人", realm="大乘期初期", is_dead=1, lifespan=999, reputation=999, stones=10**9,
               alchemy_level=9)
    for builder in (_build_realm_embed, _build_power_embed, _build_lifespan_embed, _build_reputation_embed,
                    _build_alchemy_embed, _build_wealth_embed):
        assert "死人" not in (await builder()).description, builder.__name__


async def test_榜单_最多十名(db):
    for n in range(13):
        await _add(db, f"{100 + n}", realm="炼气期1层", lifespan=50 + n, reputation=n, stones=n, alchemy_level=1, alchemy_exp=n)
    for builder in (_build_realm_embed, _build_power_embed, _build_lifespan_embed, _build_reputation_embed,
                    _build_alchemy_embed, _build_wealth_embed):
        assert len(lines(await builder())) == 10, builder.__name__


async def test_战力榜_按战力排序_用calc_power(db, monkeypatch):
    await _add(db, "1", name="弱")
    await _add(db, "2", name="强")
    await _add(db, "3", name="中")
    powers = {"1": 10.0, "2": 99.0, "3": 50.0}

    async def fake(p):
        return powers[p["discord_id"]]
    import utils.combat as combat_mod
    monkeypatch.setattr(combat_mod, "calc_power", fake)
    e = await _build_power_embed()
    ls = lines(e)
    assert e.title == "✦ 战力榜 ✦" and ls[0].startswith("🥇 **强** — 99.0")
    assert ls[1].startswith("🥈 **中** — 50.0") and ls[2].startswith("🥉 **弱** — 10.0")


async def test_战力榜_真实战力_属性高的在前(db):
    await _add(db, "1", name="普通人")
    await _add(db, "2", name="天才", comprehension=30, physique=30, bone=30, soul=30, fortune=30)
    ls = lines(await _build_power_embed())
    assert "天才" in ls[0] and "普通人" in ls[1]


async def test_寿元榜(db):
    await _add(db, "1", name="甲", lifespan=50)
    await _add(db, "2", name="乙", lifespan=500, realm="结丹期初期")
    e = await _build_lifespan_embed()
    assert lines(e)[0] == "🥇 **乙** — 500 年　结丹期初期" and lines(e)[1].startswith("🥈 **甲** — 50 年")


async def test_声望榜(db):
    await _add(db, "1", name="甲", reputation=10)
    await _add(db, "2", name="乙", reputation=300)
    assert lines(await _build_reputation_embed())[0].startswith("🥇 **乙** — 300 声望")


async def test_炼丹榜_只列入门炼丹师_按品级再按经验(db):
    await _add(db, "1", name="凡人", alchemy_level=0, alchemy_exp=999)
    await _add(db, "2", name="三品", alchemy_level=3, alchemy_exp=10)
    await _add(db, "3", name="三品强", alchemy_level=3, alchemy_exp=90)
    await _add(db, "4", name="五品", alchemy_level=5, alchemy_exp=0)
    e = await _build_alchemy_embed()
    ls = lines(e)
    assert "凡人" not in e.description
    assert [("五品" in ls[0]), ("三品强" in ls[1]), ("三品**" in ls[2])] == [True, True, True]
    assert ls[1].endswith("3 品　经验 90")


async def test_富豪榜_千分位(db):
    await _add(db, "1", name="穷", stones=5)
    await _add(db, "2", name="富", stones=1234567)
    e = await _build_wealth_embed()
    assert lines(e)[0].startswith("🥇 **富** — 1,234,567 灵石") and lines(e)[1].startswith("🥈 **穷** — 5 灵石")


# --- 面板 ---------------------------------------------------------------------

def view(cog=None):
    return LeaderboardView(FakeInteraction(U).user, cog)


async def test_六个按钮对应六个榜单():
    v = view()
    labels = [c.label for c in v.children if c.label != "返回世界"]
    assert sorted(labels) == sorted(_BOARDS)


@pytest.mark.parametrize("attr,title", [("realm_btn", "境界榜"), ("power_btn", "战力榜"), ("lifespan_btn", "寿元榜"),
                                        ("reputation_btn", "声望榜"), ("alchemy_btn", "炼丹榜"), ("wealth_btn", "富豪榜")])
async def test_按钮切换榜单(db, attr, title):
    await _add(db, "1")
    v = view()
    i = FakeInteraction(U)
    await getattr(v, attr).callback(i)
    assert title in i.last.embed.title and i.last.embed.footer.text == "仅显示存活修士 · 前十名" and i.last.view is v


async def test_只有本人能切换(db):
    assert await view().interaction_check(FakeInteraction("2002")) is False


async def test_返回世界(db):
    v = view()
    i = FakeInteraction(U)
    await v.back_btn.callback(i)
    assert i.last.embed is not None and not isinstance(i.last.view, LeaderboardView)


async def test_世界菜单进入排行榜(db):
    from utils.views.world import WorldMenuView
    await _add(db, "1")
    w = WorldMenuView(FakeInteraction(U).user, None)
    i = FakeInteraction(U)
    await w.leaderboard_btn.callback(i)
    assert "境界榜" in i.last.embed.title and isinstance(i.last.view, LeaderboardView)
    assert i.last.embed.footer.text == "仅显示存活修士 · 前十名"


def test_模块导出():
    assert lb._BOARDS["境界榜"] is _build_realm_embed
