"""玩家互动 / PvP 面板（utils/views/combat.py）。打劫 / 废修为 / 击杀的一次性见 test_one_shot_views.py。

B62 —— `_attack_callback` 没有任何占位：同时点两下『发起攻击』会各打一场，各自生成一个胜者面板，
  于是可以打劫两次 / 又打劫又击杀。入口改用 `try_hold`，被拒绝时放回，打完 `finish()`。
B63 —— 攻击者败北、而防守方没能逃脱时，发出去的是 `VictoryActionView(author=攻击者, winner=防守方, loser=攻击者)`：
  面板的主人是输家自己，『打劫灵石 / 击杀』对的是他自己 —— 他能把自己的灵石转给对方、或者杀死自己，
  而真正的胜者（防守方）根本不在场点不了。败北的一方不该拿到处置权，这里只发战报；败者的『战斗回血』照旧。
B64 —— 攻击回调不再核对『此刻是否在可交战区域』『不是自己』：按钮在打开面板时就定了可不可点，
  两人一起走到安全区再点旧面板照样开打；目标是自己也能打。
B65 —— 胜者面板的『废去修为 / 击杀』不校验对方还活着：对已坐化的人也提示『你取了他的性命』。
B66 —— 邀请双修里 `except:`（裸）会吞掉 KeyboardInterrupt / CancelledError，改成 `except Exception`；
  并拒绝『邀请自己』。
"""

import asyncio
import json
import time
from types import SimpleNamespace

import discord
import pytest

from tests.conftest import make_player
from tests.discord_fakes import FakeInteraction
from utils import combat as combat_mod
from utils.views.combat import PlayerActionView, VictoryActionView

ATK, DEF = "1001", "1002"
ZONE = "百草谷"              # 可交战区域（秘地）
SAFE = "灵虚城"


async def _add(db, uid, city=ZONE, **kw):
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        p = make_player(D, uid, stones=kw.pop("stones", 1000))
        p.name = f"道友{uid}"
        p.current_city, p.lifespan, p.lifespan_max = city, 80, 100
        for k, v in kw.items():
            setattr(p, k, v)
        s.add(p)
        await s.commit()


async def row(db, uid):
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        return await s.get(D.Player, uid)


async def as_dict(db, uid):
    p = await row(db, uid)
    return {c.key: getattr(p, c.key) for c in p.__table__.columns}


def inter(uid=ATK):
    i = FakeInteraction(uid)
    i.client = SimpleNamespace(cogs={}, fetch_user=None)
    return i


async def make_view(db, in_pvp=True, viewer=ATK, target=DEF):
    return PlayerActionView(inter(viewer).user, await as_dict(db, viewer), await as_dict(db, target), in_pvp)


def buttons(view):
    return {getattr(c, "label", None): c for c in view.children}


def fix_fight(monkeypatch, won, escaped=False):
    async def rc(atk, dfn):
        return won, 100.0, 50.0

    async def re(dfn):
        return escaped, 30.0
    monkeypatch.setattr(combat_mod, "roll_combat", rc)
    monkeypatch.setattr(combat_mod, "roll_escape", re)


# --- 面板组成 -----------------------------------------------------------------

async def test_面板_按钮组成与攻击禁用(db):
    await _add(db, ATK)
    await _add(db, DEF)
    v = await make_view(db, in_pvp=True)
    labels = list(buttons(v))
    assert "🤝 邀请组队" in labels and "⚔️ 发起攻击" in labels and "💕 邀请双修" not in labels
    assert not buttons(v)["⚔️ 发起攻击"].disabled
    assert buttons(await make_view(db, in_pvp=False))["⚔️ 发起攻击"].disabled


@pytest.mark.parametrize("techs,has", [([], False), (["双修功法"], True), ([{"name": "双修功法"}], True),
                                       ([{"name": "别的"}], False)])
async def test_面板_有双修功法才有双修按钮(db, techs, has):
    await _add(db, ATK, techniques=json.dumps(techs, ensure_ascii=False))
    await _add(db, DEF)
    assert ("💕 邀请双修" in buttons(await make_view(db))) is has


async def test_面板_只有本人能点(db):
    await _add(db, ATK)
    await _add(db, DEF)
    v = await make_view(db)
    assert await v.interaction_check(inter("9999")) is False


# --- 攻击 ---------------------------------------------------------------------

async def attack(v, uid=ATK):
    i = inter(uid)
    await buttons(v)["⚔️ 发起攻击"].callback(i)
    return i


async def test_攻击_胜利给出胜者面板_战力写在战报里(db, monkeypatch):
    await _add(db, ATK)
    await _add(db, DEF)
    fix_fight(monkeypatch, True)
    v = await make_view(db)
    i = await attack(v)
    e = i.last.embed
    assert "战力：100.0" in e.description and "道友1001** 胜" in e.description and i.last.ephemeral
    v2 = i.last.view
    assert isinstance(v2, VictoryActionView) and v2.winner["discord_id"] == ATK and v2.loser["discord_id"] == DEF
    assert v.is_finished() and all(c.disabled for c in v.children)


async def test_攻击_败北且防守方逃脱_只有战报(db, monkeypatch):
    await _add(db, ATK)
    await _add(db, DEF)
    fix_fight(monkeypatch, False, escaped=True)
    i = await attack(await make_view(db))
    assert "败北" in i.last.embed.description and "趁乱逃脱" in i.last.embed.description and i.last.view is None


async def test_B63_攻击者败北且对方没逃脱_攻击者拿不到处置权(db, monkeypatch):
    await _add(db, ATK, stones=1000)
    await _add(db, DEF, stones=1000)
    fix_fight(monkeypatch, False, escaped=False)
    i = await attack(await make_view(db))
    assert "未能逃脱" in i.last.embed.description and i.last.embed.color == discord.Color.dark_red()
    assert i.last.view is None                                          # 输家不能对自己『打劫 / 击杀』
    assert (await row(db, ATK)).spirit_stones == 1000 and not (await row(db, ATK)).is_dead


async def test_B63_败北的一方照旧触发战斗回血(db, monkeypatch):
    from utils.buffs import apply_buff
    buffs = apply_buff("{}", "combat_lifespan_restore", 10)
    await _add(db, ATK, lifespan=10, active_buffs=buffs)                # 10/100 = 10% ≤ 20%
    await _add(db, DEF)
    fix_fight(monkeypatch, False, escaped=False)
    await attack(await make_view(db))
    await asyncio.sleep(0.1)
    p = await row(db, ATK)
    assert p.lifespan == 20 and "combat_lifespan_restore" not in json.loads(p.active_buffs or "{}")


async def test_攻击_胜利时输家触发战斗回血(db, monkeypatch):
    from utils.buffs import apply_buff
    await _add(db, ATK)
    await _add(db, DEF, lifespan=15, active_buffs=apply_buff("{}", "combat_lifespan_restore", 5))
    fix_fight(monkeypatch, True)
    await attack(await make_view(db))
    await asyncio.sleep(0.1)
    assert (await row(db, DEF)).lifespan == 20


async def test_攻击_战斗加成消耗一次(db, monkeypatch):
    from utils.buffs import apply_buff
    await _add(db, ATK, active_buffs=apply_buff("{}", "combat_power_bonus", 30, charges=2))
    await _add(db, DEF)
    fix_fight(monkeypatch, True)
    await attack(await make_view(db))
    assert json.loads((await row(db, ATK)).active_buffs)["combat_power_bonus"]["charges"] == 1


async def test_攻击_逃脱成功消耗逃跑buff(db, monkeypatch):
    from utils.buffs import apply_buff
    await _add(db, ATK)
    await _add(db, DEF, active_buffs=apply_buff("{}", "escape_bonus_once", 50))
    fix_fight(monkeypatch, False, escaped=True)
    await attack(await make_view(db))
    assert "escape_bonus_once" not in json.loads((await row(db, DEF)).active_buffs or "{}")


async def test_攻击_对方已坐化_或已离开(db, monkeypatch):
    await _add(db, ATK)
    await _add(db, DEF, is_dead=1)
    fix_fight(monkeypatch, True)
    v = await make_view(db)
    i = await attack(v)
    assert "已坐化" in i.last and not v.is_finished()
    await _add(db, "1003", city="漠北荒漠")
    v = await make_view(db, target="1003")
    i = await attack(v)
    assert "已离开此地" in i.last and not v.is_finished()                # 被拒不算用掉机会


async def test_B64_此刻已不在可交战区域_不能开打(db, monkeypatch):
    await _add(db, ATK, city=SAFE)                                      # 面板是在秘地打开的，后来两人走到了城里
    await _add(db, DEF, city=SAFE)
    fix_fight(monkeypatch, True)
    v = await make_view(db, in_pvp=True)
    i = await attack(v)
    assert "安全区域" in i.last and not v.is_finished()
    assert (await row(db, DEF)).spirit_stones == 1000


async def test_B64_不能攻击自己(db, monkeypatch):
    await _add(db, ATK)
    fix_fight(monkeypatch, True)
    v = PlayerActionView(inter().user, await as_dict(db, ATK), await as_dict(db, ATK), True)
    i = await attack(v)
    assert "自己" in i.last and not v.is_finished()


async def test_B62_连点攻击只打一场(db, monkeypatch):
    await _add(db, ATK)
    await _add(db, DEF)
    calls = []

    async def rc(atk, dfn):
        calls.append(1)
        await asyncio.sleep(0.01)
        return True, 100.0, 50.0
    monkeypatch.setattr(combat_mod, "roll_combat", rc)
    v = await make_view(db)
    a, b = await asyncio.gather(attack(v), attack(v))
    assert len(calls) == 1
    outcomes = [i.last for i in (a, b)]
    assert len([m for m in outcomes if m.view is not None and isinstance(m.view, VictoryActionView)]) == 1
    assert len([m for m in outcomes if "已经" in (m.content or "")]) == 1


# --- 胜者面板（补充） ---------------------------------------------------------

async def victory(db, winner=ATK, loser=DEF):
    return VictoryActionView(inter(winner).user, await as_dict(db, winner), await as_dict(db, loser))


async def test_B65_对已坐化的人_废修为和击杀不当成功(db):
    await _add(db, ATK)
    await _add(db, DEF, is_dead=1, cultivation=500)
    v = await victory(db)
    i = inter()
    await v.kill.callback(i)
    assert "已坐化" in i.last and "取了" not in i.last.content
    v = await victory(db)
    i = inter()
    await v.cripple.callback(i)
    assert "已坐化" in i.last and (await row(db, DEF)).cultivation == 500


async def test_击杀与废修为_对活人生效(db):
    await _add(db, ATK)
    await _add(db, DEF, cultivation=500)
    v = await victory(db)
    i = inter()
    await v.cripple.callback(i)
    assert (await row(db, DEF)).cultivation == 0 and "修为归零" in i.last
    v = await victory(db)
    i = inter()
    await v.kill.callback(i)
    p = await row(db, DEF)
    assert p.is_dead and p.lifespan == 0 and "魂归天道" in i.last


async def test_打劫_对已坐化的人落空_不用掉机会(db):
    await _add(db, ATK, stones=0)
    await _add(db, DEF, is_dead=1, stones=1000)
    v = await victory(db)
    i = inter()
    await v.rob.callback(i)
    assert "已坐化" in i.last and (await row(db, ATK)).spirit_stones == 0 and not v.is_finished()


# --- 战斗回血：边界 -----------------------------------------------------------

async def restore(db, uid, **fields):
    from utils.buffs import apply_buff
    await _add(db, uid, active_buffs=apply_buff("{}", "combat_lifespan_restore", 10), **fields)
    v = VictoryActionView(inter(uid).user, {}, await as_dict(db, uid))
    await v._check_lifespan_restore(await as_dict(db, uid))
    return await row(db, uid)


async def test_回血_寿元不超过20pct才触发(db):
    assert (await restore(db, "2001", lifespan=21)).lifespan == 21         # 21% 不触发
    assert (await restore(db, "2002", lifespan=20)).lifespan == 30         # 恰好 20% 触发


async def test_回血_不超过上限(db):
    assert (await restore(db, "2003", lifespan=18, lifespan_max=100)).lifespan == 28
    p = await restore(db, "2004", lifespan=1, lifespan_max=8)              # 8 * 10% = 0 → 不回；只验证不会超过上限
    assert p.lifespan <= 8
    from utils.buffs import apply_buff
    await _add(db, "2008", lifespan=15, lifespan_max=100, active_buffs=apply_buff("{}", "combat_lifespan_restore", 90))
    v = VictoryActionView(inter().user, {}, await as_dict(db, "2008"))
    await v._check_lifespan_restore(await as_dict(db, "2008"))
    assert (await row(db, "2008")).lifespan == 100                         # 15 + 90 夹到上限 100


async def test_回血_没有buff_或比例为0_不动(db):
    await _add(db, "2005", lifespan=5)
    v = VictoryActionView(inter().user, {}, await as_dict(db, "2005"))
    await v._check_lifespan_restore(await as_dict(db, "2005"))
    assert (await row(db, "2005")).lifespan == 5
    from utils.buffs import apply_buff
    await _add(db, "2006", lifespan=5, active_buffs=apply_buff("{}", "combat_lifespan_restore", 0))
    await v._check_lifespan_restore(await as_dict(db, "2006"))
    assert (await row(db, "2006")).lifespan == 5


async def test_回血_上限为0或回复量不足1_不动_也不消耗buff(db):
    from utils.buffs import apply_buff
    buff = apply_buff("{}", "combat_lifespan_restore", 10)
    await _add(db, "2009", lifespan=1, lifespan_max=5, active_buffs=buff)                  # 5 * 10% = 0
    v = VictoryActionView(inter().user, {}, await as_dict(db, "2009"))
    await v._check_lifespan_restore(await as_dict(db, "2009"))
    p = await row(db, "2009")
    assert p.lifespan == 1 and json.loads(p.active_buffs) == json.loads(buff)               # buff 还在，没白白用掉
    await v._check_lifespan_restore({"discord_id": "x", "lifespan": 1, "lifespan_max": 0})   # 上限为 0：直接返回，不抛


async def test_回血_buff表被别处改过_不重复回血(db):
    from utils.buffs import apply_buff
    stale = apply_buff("{}", "combat_lifespan_restore", 10)
    await _add(db, "2007", lifespan=10, active_buffs=apply_buff("{}", "other", 1))                 # 库里已经不是读到的那份
    v = VictoryActionView(inter().user, {}, await as_dict(db, "2007"))
    snapshot = await as_dict(db, "2007")
    snapshot["active_buffs"] = stale
    await v._check_lifespan_restore(snapshot)
    assert (await row(db, "2007")).lifespan == 10


async def test_没有事件循环时跳过回血不抛(db):
    v = VictoryActionView.__new__(VictoryActionView)
    called = []

    def no_loop(coro, **kw):
        called.append(1)
        raise RuntimeError("no running event loop")
    import utils.views.combat as m
    orig = m.spawn
    m.spawn = no_loop
    try:
        v._schedule_lifespan_restore({"discord_id": "x"})
    finally:
        m.spawn = orig
    assert called


# --- 邀请双修 -----------------------------------------------------------------

class Cog:
    pass


def dual_inter(uid=ATK, target_user=None, with_cog=True, fetch_fails=False):
    i = FakeInteraction(uid)

    async def fetch_user(n):
        if fetch_fails:
            raise RuntimeError("找不到")
        return target_user or SimpleNamespace(mention=f"<@{n}>", id=n)
    i.client = SimpleNamespace(cogs={"Cultivation": Cog()} if with_cog else {}, fetch_user=fetch_user)
    return i


async def invite(v, i):
    await buttons(v)["💕 邀请双修"].callback(i)


async def dual_view(db, **inviter_kw):
    await _add(db, ATK, techniques=json.dumps(["双修功法"]), **inviter_kw)
    return None


async def test_双修_邀请发出_清白倍数(db):
    await _add(db, ATK, techniques=json.dumps(["双修功法"]), is_virgin=True)
    await _add(db, DEF, is_virgin=True)
    v = await make_view(db)
    i = dual_inter()
    await invite(v, i)
    msg = i.last
    assert "双修邀请" in msg.embed.title and "皆为清白之身" in msg.embed.description
    from utils.views.dual import DualCultivateInviteView
    assert isinstance(msg.view, DualCultivateInviteView) and msg.view.both_virgin is True and 10 <= msg.view.multiplier <= 20


@pytest.mark.parametrize("inv_virgin,tgt_virgin,mult,words", [(True, False, 5.0, "一方清白"), (False, True, 5.0, "一方清白"),
                                                              (False, False, 1.2, "略有提升")])
async def test_双修_倍数分档(db, inv_virgin, tgt_virgin, mult, words):
    await _add(db, ATK, techniques=json.dumps(["双修功法"]), is_virgin=inv_virgin)
    await _add(db, DEF, is_virgin=tgt_virgin)
    i = dual_inter()
    await invite(await make_view(db), i)
    assert i.last.view.multiplier == mult and words in i.last.embed.description


@pytest.mark.parametrize("fields,words", [
    (dict(is_dead=1), "已坐化"),
    (dict(current_city="漠北荒漠"), "同一城市"),
    (dict(last_dual_cultivate=time.time() - 60), "对方双修冷却中"),
    (dict(cultivating_until=time.time() + 3600), "对方正在闭关"),
    (dict(lifespan=0), "对方寿元不足"),
])
async def test_双修_对方不满足条件(db, fields, words):
    await _add(db, ATK, techniques=json.dumps(["双修功法"]))
    await _add(db, DEF, **fields)
    i = dual_inter()
    await invite(await make_view(db), i)
    assert words in i.last and i.last.ephemeral


@pytest.mark.parametrize("fields,words", [
    (dict(last_dual_cultivate=time.time() - 60), "你的双修冷却中"),
    (dict(cultivating_until=time.time() + 3600), "你正在闭关"),
    (dict(lifespan=0), "你的寿元不足"),
])
async def test_双修_自己不满足条件(db, fields, words):
    await _add(db, ATK, techniques=json.dumps(["双修功法"]), **fields)
    await _add(db, DEF)
    i = dual_inter()
    await invite(await make_view(db), i)
    assert words in i.last


async def test_双修_冷却已过可以邀请(db):
    await _add(db, ATK, techniques=json.dumps(["双修功法"]), last_dual_cultivate=time.time() - 3 * 7200 - 1)
    await _add(db, DEF)
    i = dual_inter()
    await invite(await make_view(db), i)
    assert "双修邀请" in i.last.embed.title


async def test_双修_数据异常_找不到用户_系统异常(db):
    await _add(db, ATK, techniques=json.dumps(["双修功法"]))
    await _add(db, DEF)
    v = await make_view(db)
    v.target = {"discord_id": "9999"}
    i = dual_inter()
    await invite(v, i)
    assert "数据异常" in i.last
    v = await make_view(db)
    i = dual_inter(fetch_fails=True)
    await invite(v, i)
    assert "无法找到对方用户" in i.last
    i = dual_inter(with_cog=False)
    await invite(v, i)
    assert "系统异常" in i.last


async def test_B66_取用户时的取消不被吞掉(db):
    await _add(db, ATK, techniques=json.dumps(["双修功法"]))
    await _add(db, DEF)
    v = await make_view(db)
    i = FakeInteraction(ATK)

    async def cancelled(n):
        raise asyncio.CancelledError()
    i.client = SimpleNamespace(cogs={"Cultivation": Cog()}, fetch_user=cancelled)
    with pytest.raises(asyncio.CancelledError):
        await invite(v, i)


async def test_B66_不能邀请自己双修(db):
    await _add(db, ATK, techniques=json.dumps(["双修功法"]))
    v = PlayerActionView(inter().user, await as_dict(db, ATK), await as_dict(db, ATK), True)
    i = dual_inter()
    await invite(v, i)
    assert "自己" in i.last


async def test_攻击_对方数据不存在(db, monkeypatch):
    await _add(db, ATK)
    await _add(db, DEF)
    fix_fight(monkeypatch, True)
    v = await make_view(db)
    v.target = {"discord_id": "9999"}
    i = await attack(v)
    assert "数据异常" in i.last and not v.is_finished()


async def test_攻击_防守方的战斗加成也消耗一次(db, monkeypatch):
    from utils.buffs import apply_buff
    await _add(db, ATK)
    await _add(db, DEF, active_buffs=apply_buff("{}", "combat_power_bonus", 30, charges=2))
    fix_fight(monkeypatch, True)
    await attack(await make_view(db))
    assert json.loads((await row(db, DEF)).active_buffs)["combat_power_bonus"]["charges"] == 1
