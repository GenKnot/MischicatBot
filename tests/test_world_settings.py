"""江湖设置（utils/world_settings.py、cogs/world_setup.py）、名望（utils/fame.py）、转世遗忘（U1·江湖百态 P0）。

用户 2026-10-12 的决定：三种世界模式（幸福 / 正常 / 真实）决定谁能杀谁；服务器管理员初始化时逐项看到后果；
拦路总开关随时可关、立即生效；死亡保护期可配（默认 1 天）；名望和道德声望分开；玩家转世后机器人默认不认识新的他。
"""

import time
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from cogs import world_setup
from tests.conftest import make_player
from tests.discord_fakes import FakeContext, FakeInteraction
from utils import bot_memory, fame
from utils import world_settings as ws


async def add_player(db, uid, **kw):
    D = db["db_async"]
    p = make_player(D, uid)
    p.name, p.lifespan = f"道友{uid}", 80
    for k, v in kw.items():
        setattr(p, k, v)
    async with D.AsyncSessionLocal() as s:
        s.add(p)
        await s.commit()


# ---- 模式 -------------------------------------------------------------------

async def test_默认是正常模式_机器人不杀人_拦路开_保护一天(db):
    s = await ws.get_all()
    assert s["mode"] == "正常" and s["initialized"] is False and s["ambush_enabled"] is True
    assert s["death_protect_days"] == 1.0 and s["admin_ids"] == []
    assert not await ws.bots_can_kill_humans() and await ws.humans_can_kill_humans()


@pytest.mark.parametrize("mode,bots,humans", [("幸福", False, False), ("正常", False, True), ("真实", True, True)])
async def test_三种模式的致死权限(db, mode, bots, humans):
    await ws.set_values(mode=mode)
    assert await ws.bots_can_kill_humans() is bots and await ws.humans_can_kill_humans() is humans


def test_每种模式的说明都写清楚了后果():
    assert set(ws.MODES) == {"幸福", "正常", "真实"}
    for name, m in ws.MODES.items():
        assert m["title"] and len(m["short"]) > 10 and len(m["detail"]) > 60, name
    assert "击杀玩家" in ws.MODES["真实"]["detail"] and "不可逆" in ws.MODES["真实"]["detail"]
    assert "不会" in ws.MODES["正常"]["detail"] and "不能" in ws.MODES["幸福"]["detail"]


async def test_设置持久化_坏值被拒绝(db):
    await ws.set_values(mode="真实", death_protect_days=3.0, ambush_enabled=False)
    s = await ws.get_all()
    assert (s["mode"], s["death_protect_days"], s["ambush_enabled"]) == ("真实", 3.0, False)
    with pytest.raises(ValueError):
        await ws.set_values(mode="天下大同")
    with pytest.raises(ValueError):
        await ws.set_values(death_protect_days=-1)
    with pytest.raises(KeyError):
        await ws.set_values(没有这项=1)
    assert (await ws.get_all())["mode"] == "真实"


async def test_数据库里的坏值回退到默认_不抛(db):
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        s.add(D.BotWorldState(key="ws.mode", value="不是JSON"))
        s.add(D.BotWorldState(key="ws.death_protect_days", value="2.5"))
        await s.commit()
    got = await ws.get_all()
    assert got["mode"] == "正常" and got["death_protect_days"] == 2.5


async def test_初始化记下管理员_追加不覆盖(db):
    await ws.initialize("111", "真实", 2.0)
    await ws.initialize("222", "幸福", 0.5)
    s = await ws.get_all()
    assert s["initialized"] and s["mode"] == "幸福" and s["death_protect_days"] == 0.5
    assert s["admin_ids"] == ["111", "222"]
    assert await ws.is_admin(111) and not await ws.is_admin("333")


async def test_拦路开关_即时生效(db):
    assert await ws.ambush_enabled()
    await ws.set_values(ambush_enabled=False)
    assert not await ws.ambush_enabled()


# ---- 命令 -------------------------------------------------------------------

def make_cog(owner_ids=("1",)):
    async def is_owner(user):
        return str(user.id) in owner_ids
    return world_setup.WorldSetupCog(SimpleNamespace(is_owner=is_owner))


def ctx_with(uid, manage_guild=False):
    c = FakeContext(user_id=uid)
    c.author.guild_permissions = SimpleNamespace(manage_guild=manage_guild)
    return c


async def test_命令_未初始化时有管理服务器权限的人可以设置_普通人不行(db):
    cog = make_cog()
    c = ctx_with(5)
    await cog.setup_world.callback(cog, c)
    assert c.said("只有服务器管理员")
    c = ctx_with(6, manage_guild=True)
    await cog.setup_world.callback(cog, c)
    assert c.last.embed is not None and "幸福" in str(c.last.embed.fields[0].name)
    assert len(c.last.embed.fields) == 4                       # 三种模式各一栏 + 保护期


async def test_命令_初始化之后只有记下的管理员和所有者能改(db):
    await ws.initialize("6", "正常")
    cog = make_cog()
    c = ctx_with(7, manage_guild=True)                         # 有权限但不是记下的管理员
    await cog.show_world.callback(cog, c)
    assert c.said("只有服务器管理员")
    for uid in (6, 1):
        c = ctx_with(uid)
        await cog.show_world.callback(cog, c)
        assert c.said("正常模式") and c.said("已初始化")


async def test_命令_拦路开关(db):
    cog = make_cog()
    c = ctx_with(1)
    await cog.ambush_switch.callback(cog, c, "关")
    assert c.said("已关闭") and not await ws.ambush_enabled()
    await cog.ambush_switch.callback(cog, c, "开")
    assert c.said("已开启") and await ws.ambush_enabled()
    c = ctx_with(1)
    await cog.ambush_switch.callback(cog, c, "")
    assert c.said("用法")
    c = ctx_with(9)
    await cog.ambush_switch.callback(cog, c, "关")
    assert c.said("只有服务器管理员") and await ws.ambush_enabled()


async def test_初始化面板_选模式_确认才生效_别人点不了(db):
    view = world_setup.SetupView(6, await ws.get_all())
    mode_select = next(c for c in view.children if isinstance(c, world_setup.ModeSelect))
    protect_select = next(c for c in view.children if isinstance(c, world_setup.ProtectSelect))
    confirm = next(c for c in view.children if getattr(c, "label", "") == "确认")

    other = FakeInteraction(user_id=7)
    assert await view.interaction_check(other) is False

    me = FakeInteraction(user_id=6)
    assert await view.interaction_check(me) is True
    await confirm.callback(me)                                  # 还没选模式
    assert me.response.said("还没有选世界模式") and not (await ws.get_all())["initialized"]

    mode_select._values = ["真实"]
    protect_select._values = ["3.0"]
    await mode_select.callback(me)
    await protect_select.callback(me)
    assert not (await ws.get_all())["initialized"], "只选不确认不生效"
    await confirm.callback(me)
    s = await ws.get_all()
    assert (s["mode"], s["death_protect_days"], s["initialized"], s["admin_ids"]) == ("真实", 3.0, True, ["6"])


# ---- 名望 -------------------------------------------------------------------

def test_名望分档和传播范围():
    assert [fame.tier(n) for n in (0, 49, 50, 199, 200, 799, 800, 2999, 3000)] == [
        "无名之辈", "无名之辈", "小有名气", "小有名气", "远近闻名", "远近闻名", "名动一方", "名动一方", "名震天下"]
    assert [fame.reach(n) for n in (0, 49, 50, 199, 200, 10**6)] == ["none", "none", "city", "city", "server", "server"]


async def test_加名望_原子自增_不动道德声望(db):
    await add_player(db, "1001", reputation=7)
    await fame.add_fame("1001", 5)
    await fame.add_fame("1001", 3)
    await fame.add_fame("1001", 0)
    await fame.add_fame("1001", -4)
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        p = await s.get(D.Player, "1001")
        assert (p.fame, p.reputation) == (8, 7)


async def test_传闻让主角出名_分数的一半_恶名也是名(db):
    from utils import rumors
    await add_player(db, "1001", name="甲")
    await add_player(db, "bot_00001", name="乙", is_bot=True)
    await rumors.record_rumor("breakthrough_major", "1001", "甲", city="灵虚城", realm="筑基期1层")        # score 40 → +20
    await rumors.record_rumor("kill_human", "1001", "甲", target="某人", city="灵虚城")   # 负面 score 60 → +30
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        assert (await s.get(D.Player, "1001")).fame == 50


# ---- 转世 -------------------------------------------------------------------

async def test_转世重建角色_机器人忘了你_名望清零(db):
    from utils.character_create_logic import commit_character
    await add_player(db, "1001", is_dead=True, fame=300, reputation=9)
    await add_player(db, "bot_00001", is_bot=True)
    await bot_memory.remember("1001", "bot_00001", "chat")
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        s.add(D.BotRelation(player_id="1001", bot_id="bot_00001", favor=60))
        s.add(D.BotRelation(player_id="1002", bot_id="bot_00001", favor=60))        # 别人的不动
        await s.commit()
    res = await commit_character("1001", "新名字", "男", {})
    assert res is not None
    async with D.AsyncSessionLocal() as s:
        assert (await s.get(D.Player, "1001")).fame == 10, "旧的 300 清零；只剩『转世』传闻本身的 10"
        assert await s.get(D.BotRelation, ("1001", "bot_00001")) is None
        assert (await s.get(D.BotRelation, ("1002", "bot_00001"))).favor == 60
        assert (await s.execute(select(D.BotMemory))).first() is None


async def test_活着的玩家创建不了_也不会忘(db):
    from utils.character_create_logic import commit_character
    await add_player(db, "1001", fame=300)
    await bot_memory.remember("1001", "bot_00001", "chat")
    assert await commit_character("1001", "新名字", "男", {}) is None
    assert len(await bot_memory.recall("1001", "bot_00001")) == 1
