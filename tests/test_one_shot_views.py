"""一次性按钮（B11 存量核对后修复的那批）的行为测试。

共同的问题：回调先 `await interaction.response.defer()`（走网络）、后 `stop()`，
两次几乎同时的点击会一起越过入口。这里统一用会让出事件循环的 defer 模拟真实延迟。
修法见 CONVENTIONS #11：`TimedView.try_claim()`；可能被拒绝的操作用 `try_hold()/finish()/release_hold()`。

结构：A 新原语  B 战斗胜利面板  C 炼丹确认  D 阴阳奇遇  E 双修接受  F 酒馆接任务
"""

import asyncio
import json

import pytest

from tests.conftest import make_player
from tests.discord_fakes import FakeInteraction, FakeUser
from utils.views.base import TimedView


def _slow(interaction):
    """让 defer 会让出事件循环 —— 连点能钻进来的窗口。"""
    real = interaction.response.defer

    async def _defer(**kw):
        await asyncio.sleep(0.01)
        await real(**kw)
    interaction.response.defer = _defer
    return interaction


def _click(user_id=1):
    return _slow(FakeInteraction(user_id=user_id))


async def _add_player(db, uid, **fields):
    D = db["db_async"]
    p = make_player(D, uid, stones=1000)
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


# =============================================================================
# A. TimedView 的占位原语
# =============================================================================

class _Panel(TimedView):
    pass


async def test_try_claim_只有第一个拿到(db):
    view = _Panel(author=FakeUser(id=1))
    assert view.try_claim() is True
    assert view.try_claim() is False
    assert view.is_finished()


async def test_try_claim_禁用全部按钮(db):
    import discord
    view = _Panel(author=FakeUser(id=1))
    view.add_item(discord.ui.Button(label="a"))
    view.add_item(discord.ui.Button(label="b"))
    view.try_claim()
    assert all(b.disabled for b in view.children)


async def test_hold_期间别人进不来_放回后又可以进(db):
    view = _Panel(author=FakeUser(id=1))
    assert view.try_hold() is True
    assert view.try_hold() is False and view.try_claim() is False      # 占着的期间谁也进不来
    assert not view.is_finished()

    view.release_hold()

    assert view.try_claim() is True                                     # 放回后可以重新占


async def test_finish_之后不能再占也不能再hold(db):
    view = _Panel(author=FakeUser(id=1))
    view.try_hold()
    view.finish()
    assert view.is_finished()
    assert view.try_hold() is False and view.try_claim() is False
    view.release_hold()                                                 # 对已作废的面板是空操作
    assert view.try_hold() is False


# =============================================================================
# B. 战斗胜利面板（打劫 / 废修为 / 击杀）
# =============================================================================

WINNER, LOSER = "10", "20"


@pytest.fixture
async def duel(db):
    from utils.views.combat import VictoryActionView
    await _add_player(db, WINNER, spirit_stones=100)
    await _add_player(db, LOSER, spirit_stones=1000, cultivation=500, lifespan=80)
    winner = {"discord_id": WINNER, "name": f"道友{WINNER}", "lifespan": 80, "lifespan_max": 100}
    loser = {"discord_id": LOSER, "name": f"道友{LOSER}", "lifespan": 80, "lifespan_max": 100}
    return VictoryActionView(FakeUser(id=int(WINNER)), winner, loser)


async def test_打劫_按比例转移灵石并作废面板(db, duel, monkeypatch):
    import random
    monkeypatch.setattr(random, "uniform", lambda a, b: 0.5)
    it = FakeInteraction(user_id=10)

    await duel.rob.callback(it)

    assert it.said("搜刮了 **500 灵石**")
    assert (await _row(db, WINNER)).spirit_stones == 600
    assert (await _row(db, LOSER)).spirit_stones == 500
    assert duel.is_finished()


async def test_打劫落空_不用掉机会_可以改选别的(db, duel):
    """对方身上没钱：打劫落空，面板必须还能用 —— 否则赢了却什么都拿不到，也不能击杀。"""
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        (await s.get(D.Player, LOSER)).spirit_stones = 0
        await s.commit()
    it = FakeInteraction(user_id=10)

    await duel.rob.callback(it)

    assert it.said("没什么油水")
    assert not duel.is_finished()
    kill_it = FakeInteraction(user_id=10)
    await duel.kill.callback(kill_it)                                   # 改选击杀仍然可以
    assert (await _row(db, LOSER)).is_dead is True


async def test_打劫出错_占位会放回_不会把面板卡死(db, duel, monkeypatch):
    import utils.atomic as atomic

    async def _boom(*a, **k):
        raise RuntimeError("数据库挂了")
    monkeypatch.setattr(atomic, "spend_stones", _boom)

    with pytest.raises(RuntimeError):
        await duel.rob.callback(FakeInteraction(user_id=10))

    assert not duel.is_finished()
    assert duel.try_hold() is True                                      # 没有一直占着


async def test_连点打劫_只劫一次(db, duel, monkeypatch):
    """B11：曾经两次点击各算一次战利品（loot 按各自读到的余额算，扣得动就都成功）。"""
    import random
    monkeypatch.setattr(random, "uniform", lambda a, b: 0.5)
    its = [_click(10), _click(10)]

    await asyncio.gather(*(duel.rob.callback(it) for it in its))

    assert (await _row(db, LOSER)).spirit_stones == 500                 # 只被劫了一次
    assert (await _row(db, WINNER)).spirit_stones == 600
    assert len([m for it in its for m in it.messages if "搜刮了" in m]) == 1


async def test_同时点打劫和击杀_只会发生一个(db, duel, monkeypatch):
    """三个按钮互斥：胜者只能选一样。曾经没有互斥，可以又劫财又取命。"""
    import random
    monkeypatch.setattr(random, "uniform", lambda a, b: 0.5)
    rob, kill = _click(10), _click(10)

    await asyncio.gather(duel.rob.callback(rob), duel.kill.callback(kill))

    loser = await _row(db, LOSER)
    robbed = loser.spirit_stones == 500
    dead = loser.is_dead is True
    assert robbed != dead, f"应当只发生一个：被劫={robbed} 被杀={dead}"


async def test_废去修为_修为归零(db, duel):
    it = FakeInteraction(user_id=10)
    await duel.cripple.callback(it)
    assert (await _row(db, LOSER)).cultivation == 0 and it.said("修为归零") and duel.is_finished()


async def test_击杀_标记死亡寿元归零(db, duel):
    it = FakeInteraction(user_id=10)
    await duel.kill.callback(it)
    loser = await _row(db, LOSER)
    assert loser.is_dead is True and loser.lifespan == 0 and it.said("魂归天道")


@pytest.mark.parametrize("which", ["cripple", "kill"])
async def test_连点_只执行一次(db, duel, which):
    its = [_click(10), _click(10)]
    btn = getattr(duel, which)

    await asyncio.gather(*(btn.callback(it) for it in its))

    done = [m for it in its for m in it.messages if "已经做出了选择" not in m and m.content]
    refused = [m for it in its for m in it.messages if "已经做出了选择" in m]
    assert len(done) == 1 and len(refused) == 1


async def test_做出选择后再点任何按钮都得到提示(db, duel):
    await duel.cripple.callback(FakeInteraction(user_id=10))
    for name in ("rob", "cripple", "kill"):
        it = FakeInteraction(user_id=10)
        await getattr(duel, name).callback(it)
        assert it.said("已经做出了选择")


# =============================================================================
# C. 炼丹确认
# =============================================================================

@pytest.fixture
async def alchemist(db):
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        p = make_player(D, "u", stones=10_000)
        p.alchemy_level = 3
        s.add(p)
        for item in ("灵芝草", "茯苓灵块", "朱果"):
            s.add(D.Inventory(discord_id="u", item_id=item, quantity=50))
        await s.commit()
    return "u"


async def test_炼丹确认连点_只开一炉(db, alchemist, monkeypatch):
    """一次点击 = 一次开炉。连点曾经各付全价各开一炉，结果消息还互相覆盖，玩家只看到一炉。"""
    from tests.test_alchemy import RECIPE
    from utils import alchemy as alchemy_mod
    from utils.views.alchemy import _ConfirmView

    monkeypatch.setattr(alchemy_mod.random, "randint", lambda a, b: 1)       # 必定成功
    view = _ConfirmView(
        author=FakeUser(id=1), player={"discord_id": "u", "soul": 10, "alchemy_level": 3},
        has_yanhuo=False, recipe=RECIPE, inventory={"灵芝草": 50, "茯苓灵块": 50}, choices=[0],
    )
    its = [_click(1), _click(1)]
    for it in its:
        it.user.id = "u"

    await asyncio.gather(*(view.confirm.callback(it) for it in its))

    inv = await db["inventory"].get_inventory("u")
    assert inv["灵芝草"] == 50 - 2 and inv["茯苓灵块"] == 50 - 1              # 只扣了一炉的材料
    assert len([m for it in its for m in it.messages if "这一炉已经开了" in m]) == 1


# =============================================================================
# D. 阴阳奇遇
# =============================================================================

def _yy_player(**extra):
    return {"discord_id": "1", "name": "紫霞", "realm": "炼气期1层", "rebirth_count": 0,
            "soul": 99, "comprehension": 99, "fortune": 99, **extra}


async def _yy_open(db, **fields):
    from utils.events.adventure import YINYANG_EVENT, YINYANG_FINALE
    from utils.views.yinyang import YinYangView
    await _add_player(db, "1", comprehension=5, soul=5, fortune=5, bone=5, physique=5, cultivation=0, **fields)
    row = await _row(db, "1")
    player = {c.key: getattr(row, c.key) for c in row.__table__.columns}
    return YinYangView(FakeUser(id=1), YINYANG_EVENT, YINYANG_FINALE, player, None, "1")


def _by_label(view, label):
    return next(b for b in view.children if b.label == label)


async def test_阴阳奇遇_结局奖励真的发到了玩家手上(db):
    """B13：四处 `_apply_rewards(...)` 少了 await —— 协程只被创建、从不执行，
    所以整条阴阳奇遇（一生一次的稀有事件）所有结局的奖励都从来没发过。"""
    view = await _yy_open(db)
    it1 = FakeInteraction(user_id=1)
    await _by_label(view, "接过令牌，问他是什么冤案").callback(it1)
    nxt = it1.last.view
    it2 = FakeInteraction(user_id=1)
    await _by_label(nxt, "问他：你认识秋叶青吗").callback(it2)
    leaf_view = it2.last.view
    it3 = FakeInteraction(user_id=1)

    await _by_label(leaf_view, "告诉她：不是，我是来带你走的").callback(it3)       # 奖励 修为 +200 根骨 +1

    p = await _row(db, "1")
    assert p.cultivation == 200, "结局奖励没有发放"
    assert p.bone == 6
    assert it3.last.view is not None                                           # 随后进入终章


async def test_阴阳奇遇_一层结局的奖励(db):
    """另一条路径：第一层选项直接带奖励的分支（拒绝 → 叫住他）也要发。"""
    view = await _yy_open(db)
    it1 = FakeInteraction(user_id=1)
    await _by_label(view, "拒绝，你不想卷入这些事").callback(it1)
    it2 = FakeInteraction(user_id=1)

    await _by_label(it1.last.view, "叫住他，答应帮忙").callback(it2)           # 机缘 +2 根骨 +1

    p = await _row(db, "1")
    assert (p.fortune, p.bone) == (7, 6)


async def test_阴阳奇遇_终章奖励发放_且完成轮回(db):
    from utils.events.adventure import YINYANG_FINALE
    from utils.views.yinyang import YinYangFinaleView
    await _add_player(db, "1", comprehension=5, soul=5, physique=5, cultivation=300, rebirth_count=0)
    row = await _row(db, "1")
    player = {c.key: getattr(row, c.key) for c in row.__table__.columns}
    view = YinYangFinaleView(FakeUser(id=1), YINYANG_FINALE, player, None, "1")
    it1 = FakeInteraction(user_id=1)
    await _by_label(view, "让她现身，见最后一面").callback(it1)
    it2 = FakeInteraction(user_id=1)

    await _by_label(it1.last.view, "什么都不说，看着沈渡离开").callback(it2)     # 悟性 +2 体魄 +1 神识 +1

    p = await _row(db, "1")
    assert (p.comprehension, p.physique, p.soul) == (7, 6, 6)                  # 奖励在轮回后仍保留
    assert p.rebirth_count == 1 and p.cultivation == 0 and p.has_bahongchen is True
    assert it2.said("大梦初醒")


async def test_阴阳奇遇_连点结局_奖励和轮回只算一次(db):
    from utils.events.adventure import YINYANG_FINALE
    from utils.views.yinyang import YinYangFinaleSubView
    await _add_player(db, "1", comprehension=5, soul=5, physique=5, rebirth_count=0)
    row = await _row(db, "1")
    player = {c.key: getattr(row, c.key) for c in row.__table__.columns}
    sub = YINYANG_FINALE["choices"][0]["next"]
    view = YinYangFinaleSubView(FakeUser(id=1), YINYANG_FINALE, sub, player, None, "1")
    btn = _by_label(view, "什么都不说，看着沈渡离开")
    its = [_click(1), _click(1)]

    await asyncio.gather(*(btn.callback(it) for it in its))

    p = await _row(db, "1")
    assert (p.comprehension, p.physique, p.soul) == (7, 6, 6)                  # 奖励只发一次
    assert p.rebirth_count == 1
    assert len([m for it in its for m in it.messages if "大梦初醒" in m]) == 1


async def test_阴阳奇遇_连点选项_只推进一次(db):
    view = await _yy_open(db)
    btn = _by_label(view, "接过令牌，问他是什么冤案")
    its = [_click(1), _click(1)]

    await asyncio.gather(*(btn.callback(it) for it in its))

    assert len([m for it in its for m in it.messages if m.view is not None]) == 1
    assert len([m for it in its for m in it.messages if "已处理" in m]) == 1


# =============================================================================
# E. 双修接受
# =============================================================================

async def test_双修邀请连点接受_只开始一次(db):
    from cogs.cultivation import CultivationCog
    from tests.test_dual_cultivation import _invite
    cog = CultivationCog(bot=None)
    msg, view, target = await _invite(db, cog, False, False)
    its = [_click(1002), _click(1002)]
    for it in its:
        it.user = target

    await asyncio.gather(*(view.accept.callback(it) for it in its))

    started = [m for it in its for m in it.messages if m.embed is not None and "双修" in (m.embed.title or "")]
    assert len(started) == 1
    assert len([m for it in its for m in it.messages if "已处理" in m]) == 1


# =============================================================================
# F. 酒馆接任务
# =============================================================================

QUEST = {"id": "q1", "title": "护送商队", "type": "escort", "rewards": {}}


async def test_接任务连点_只接一次(db):
    from cogs.tavern import QuestConfirmView
    await _add_player(db, "1")
    view = QuestConfirmView(FakeUser(id=1), QUEST, "普通", None)
    its = [_click(1), _click(1)]

    await asyncio.gather(*(view.accept.callback(it) for it in its))

    done = [m for it in its for m in it.messages if "已接取任务" in m]
    refused = [m for it in its for m in it.messages if "已经接取过了" in m]
    assert len(done) == 1 and len(refused) == 1
    assert json.loads((await _row(db, "1")).active_quest)["id"] == "q1"


async def test_接任务_成功与失败的提示(db):
    from cogs.tavern import QuestConfirmView
    await _add_player(db, "1")
    ok = FakeInteraction(user_id=1)
    await QuestConfirmView(FakeUser(id=1), QUEST, "普通", None).accept.callback(ok)
    assert ok.said("已接取任务「**护送商队**」")

    again = FakeInteraction(user_id=1)                                          # 已经有任务了，再开一个面板去接
    await QuestConfirmView(FakeUser(id=1), QUEST, "普通", None).accept.callback(again)
    assert again.said("已有进行中的任务")


async def test_酒馆任务确认面板_别人点不动(db):
    from cogs.tavern import QuestConfirmView
    view = QuestConfirmView(FakeUser(id=1), QUEST, "普通", None)
    intruder = FakeInteraction(user_id=999)
    assert await view.interaction_check(intruder) is False
    assert intruder.said("这不是你的任务")


# --- 真实数据里走不到、但代码里存在的分支（第一层直接出结果）---------------------
# 现有阴阳奇遇的第一层选项都带 next，所以这两个分支只能用合成事件覆盖；
# 否则以后有人加一个直接出结果的选项，B13 同样的 bug（少 await）会无声复发。

def _leaf_event(label="直接领悟"):
    return {"title": "合成事件", "desc": "d", "choices": [
        {"label": label, "condition": None, "flavor": "你有所得。", "rewards": {"fortune": 3}}]}


async def test_阴阳奇遇_第一层直接出结果的选项_奖励也发放(db):
    from utils.events.adventure import YINYANG_FINALE
    from utils.views.yinyang import YinYangView
    await _add_player(db, "1", fortune=5)
    row = await _row(db, "1")
    player = {c.key: getattr(row, c.key) for c in row.__table__.columns}
    view = YinYangView(FakeUser(id=1), _leaf_event(), YINYANG_FINALE, player, None, "1")
    it = FakeInteraction(user_id=1)

    await _by_label(view, "直接领悟").callback(it)

    assert (await _row(db, "1")).fortune == 8
    assert it.last.view is not None                                           # 随后进入终章


async def test_阴阳奇遇_终章第一层直接出结果的选项_奖励发放并轮回(db):
    from utils.views.yinyang import YinYangFinaleView
    await _add_player(db, "1", fortune=5, rebirth_count=0)
    row = await _row(db, "1")
    player = {c.key: getattr(row, c.key) for c in row.__table__.columns}
    view = YinYangFinaleView(FakeUser(id=1), _leaf_event("直接醒来"), player, None, "1")
    it = FakeInteraction(user_id=1)

    await _by_label(view, "直接醒来").callback(it)

    p = await _row(db, "1")
    assert p.fortune == 8 and p.rebirth_count == 1
    assert it.said("大梦初醒")
