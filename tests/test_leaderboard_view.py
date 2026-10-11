"""排行榜（utils/views/leaderboard.py）。

B70 —— 境界榜只按境界下标排序，同境界的人顺序取决于数据库行序（基本是注册先后）：同一境界里修为最高的人
  可能排在最后、甚至被挤出前十。同境界按修为从高到低排。
"""

import asyncio

import pytest

from tests.conftest import make_player
from tests.discord_fakes import FakeInteraction
from utils.views import leaderboard as lb
from utils.views.leaderboard import (LeaderboardView, _BOARDS, _build_alchemy_embed, _build_lifespan_embed,
                                     _build_power_embed, _build_realm_embed, _build_reputation_embed,
                                     _build_wealth_embed, _medal)

U = "1001"


@pytest.fixture(autouse=True)
def _fresh_power_cache():
    """战力榜有进程内缓存：每个测试从空缓存开始，别的测试留下的排名不能串过来。"""
    lb.reset_power_cache()
    yield
    lb.reset_power_cache()


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

    async def fake(p, equipped=None):
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
    footer = i.last.embed.footer.text
    assert title in i.last.embed.title and footer.startswith("仅显示存活修士 · 前十名") and i.last.view is v
    assert ("5 分钟" in footer) == (attr == "power_btn")


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


# =============================================================================
# 战力榜缓存（U1 前置：机器人进来之后玩家会是几千个）
#
# 原来每点一次战力榜：SELECT * 读出全部存活玩家，再对每个人 calc_power —— 其中每次又查一次装备表，
# 也就是 N+1 次查询、N 次完整战力计算。现在：
#   · 装备一次查出来（`get_all_equipped`），calc_power 接受传入的装备，不再逐人查库；
#   · 排名结果缓存 5 分钟，并发点击只算一次（单飞锁）；
#   · 重新计算失败时优先返回旧榜，没有旧榜才报错（失败不缓存）。
# =============================================================================

async def test_calc_power传入装备_与自己去查结果一致_且不再查库(db, monkeypatch):
    from utils.combat import calc_power
    from utils.equipment_db import get_equipped, give_equipment
    await _add(db, U, comprehension=9, physique=8)
    await give_equipment(U, {"equip_id": "e1", "name": "剑", "slot": "武器", "quality": "稀有", "tier": 1, "tier_req": 0,
                             "stats": {"physique": 5, "soul": 3}, "flavor": ""})
    await db["equipment_db"].equip_item(U, "e1", 0)
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        p = await s.get(D.Player, U)
        d = {c.key: getattr(p, c.key) for c in p.__table__.columns}
    expected = await calc_power(d)
    eq = await get_equipped(U)
    assert eq and expected > await calc_power({**d, "discord_id": "nobody"})                 # 装备确实在起作用

    async def boom(_):
        raise AssertionError("传了装备就不该再去查库")
    monkeypatch.setattr("utils.equipment_db.get_equipped", boom)
    assert await calc_power(d, equipped=eq) == pytest.approx(expected)


async def test_获取全部已装备_按玩家分组_只含已装备的(db):
    from utils.equipment_db import get_all_equipped, give_equipment
    await _add(db, "1")
    await _add(db, "2")
    for uid, eid, slot in (("1", "a", "武器"), ("1", "b", "防具"), ("2", "c", "武器")):
        await give_equipment(uid, {"equip_id": eid, "name": eid, "slot": slot, "quality": "普通", "tier": 0, "tier_req": 0,
                                   "stats": {"bone": 1}, "flavor": ""})
    await db["equipment_db"].equip_item("1", "a", 0)
    await db["equipment_db"].equip_item("2", "c", 0)
    got = await get_all_equipped()
    assert sorted(got) == ["1", "2"] and [e["equip_id"] for e in got["1"]] == ["a"] and got["1"][0]["stats"] == {"bone": 1}


async def test_战力榜_不再逐人查装备(db, monkeypatch):
    for n in range(8):
        await _add(db, f"{100 + n}")
    calls = []
    real = __import__("utils.equipment_db", fromlist=["get_equipped"]).get_equipped

    async def counting(uid):
        calls.append(uid)
        return await real(uid)
    monkeypatch.setattr("utils.equipment_db.get_equipped", counting)
    await _build_power_embed()
    assert calls == []                                                     # 以前是 8 次


async def test_战力榜_装备加成体现在排名里(db):
    from utils.equipment_db import give_equipment
    await _add(db, "1", name="空手")
    await _add(db, "2", name="带剑")
    await give_equipment("2", {"equip_id": "e1", "name": "神剑", "slot": "武器", "quality": "传说", "tier": 3, "tier_req": 0,
                               "stats": {"physique": 30, "bone": 30, "soul": 30}, "flavor": ""})
    await db["equipment_db"].equip_item("2", "e1", 0)
    ls = lines(await _build_power_embed())
    assert "带剑" in ls[0] and "空手" in ls[1]


async def test_战力榜_缓存期内不重算(db, monkeypatch):
    await _add(db, "1", name="甲")
    calls = []
    import utils.combat as combat_mod
    orig = combat_mod.calc_power

    async def counting(p, equipped=None):
        calls.append(p["discord_id"])
        return await orig(p, equipped=equipped)
    monkeypatch.setattr(combat_mod, "calc_power", counting)
    first = await _build_power_embed()
    await _add(db, "2", name="乙", comprehension=40, physique=40, bone=40, soul=40, fortune=40)    # 缓存期内新来的强者
    second = await _build_power_embed()
    assert len(calls) == 1 and lines(first) == lines(second) and "乙" not in second.description


async def test_战力榜_缓存过期后重算(db, monkeypatch):
    await _add(db, "1", name="甲")
    clock = {"t": 1000.0}
    monkeypatch.setattr(lb, "_now", lambda: clock["t"])
    await _build_power_embed()
    await _add(db, "2", name="乙", comprehension=40, physique=40, bone=40, soul=40, fortune=40)
    clock["t"] += lb.POWER_TTL - 1
    assert "乙" not in (await _build_power_embed()).description
    clock["t"] += 2
    assert "乙" in (await _build_power_embed()).description


async def test_战力榜_并发点击只算一次(db, monkeypatch):
    for n in range(4):
        await _add(db, f"{100 + n}")
    import utils.combat as combat_mod
    orig = combat_mod.calc_power
    started = []

    async def slow(p, equipped=None):
        started.append(p["discord_id"])
        await asyncio.sleep(0.01)
        return await orig(p, equipped=equipped)
    monkeypatch.setattr(combat_mod, "calc_power", slow)
    embeds = await asyncio.gather(*[_build_power_embed() for _ in range(6)])
    assert len(started) == 4 and len({e.description for e in embeds}) == 1          # 4 个人只算一遍，不是 6 遍


async def test_战力榜_重算失败_有旧榜就用旧榜(db, monkeypatch):
    await _add(db, "1", name="甲")
    clock = {"t": 1000.0}
    monkeypatch.setattr(lb, "_now", lambda: clock["t"])
    first = await _build_power_embed()
    clock["t"] += lb.POWER_TTL + 1

    async def boom(*a, **k):
        raise RuntimeError("库挂了")
    import utils.combat as combat_mod
    monkeypatch.setattr(combat_mod, "calc_power", boom)
    stale = await _build_power_embed()
    assert lines(stale) == lines(first)


async def test_战力榜_重算失败_没有旧榜就抛出_且不缓存失败(db, monkeypatch):
    await _add(db, "1", name="甲")
    import utils.combat as combat_mod
    orig = combat_mod.calc_power

    async def boom(*a, **k):
        raise RuntimeError("库挂了")
    monkeypatch.setattr(combat_mod, "calc_power", boom)
    with pytest.raises(RuntimeError):
        await _build_power_embed()
    monkeypatch.setattr(combat_mod, "calc_power", orig)
    assert "甲" in (await _build_power_embed()).description                          # 下次点击能恢复


async def test_战力榜_重置缓存(db):
    await _add(db, "1", name="甲")
    await _build_power_embed()
    await _add(db, "2", name="乙", comprehension=40, physique=40, bone=40, soul=40, fortune=40)
    lb.reset_power_cache()
    assert "乙" in (await _build_power_embed()).description


async def test_战力榜_按钮页脚提示每5分钟刷新(db):
    await _add(db, "1")
    v = view()
    i = FakeInteraction(U)
    await v.power_btn.callback(i)
    footer = i.last.embed.footer.text
    assert "前十名" in footer and "5 分钟" in footer
    i = FakeInteraction(U)
    await v.realm_btn.callback(i)
    assert "5 分钟" not in i.last.embed.footer.text                                  # 别的榜是实时的
