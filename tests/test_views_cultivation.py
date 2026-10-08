"""筑基 / 凝丹 / 化婴 按钮突破的端到端测试（utils/views/cultivation.py）。

这三道大关的结算原先在 views 里各写了一份裸 SQL，和 breakthrough_logic 是不同的实现，
结果两边各有缺口（见 .gk/ISSUES.md B3、B4）：
- 按钮路径不认狐符，寿元归零照样死；
- 成功时修为直接清零，丢掉溢出部分；
- 失败类型靠「第二次 roll_breakthrough 并丢掉成败」取，成功率越高越容易走火入魔。
现在按钮只负责措辞，结算全部交给 breakthrough_logic。这里验证整条链路，而不是逻辑层本身
（那在 test_breakthrough.py）。
"""

import json
import random

import pytest

from tests.conftest import make_player
from tests.discord_fakes import FakeInteraction, FakeUser
from utils import breakthrough_logic as bt
from utils.realms import FAIL_DEVIATE, FAIL_LIGHT, cultivation_needed
from utils.views.cultivation import (
    HuayingBreakthroughView, NingdanBreakthroughView, ZhujiBreakthroughView,
)

UID = "1"

# (面板类, 丹药, 起始境界, 目标境界, 成功时的措辞片段)
STAGES = [
    pytest.param(ZhujiBreakthroughView, "筑基丹", "炼气期10层", "筑基期1层", "成功筑基", id="筑基"),
    pytest.param(NingdanBreakthroughView, "凝丹丹", "筑基期10层", "结丹期初期", "凝结金丹", id="凝丹"),
    pytest.param(HuayingBreakthroughView, "化婴丹", "结丹期后期", "元婴期初期", "元婴化形", id="化婴"),
]


async def _add_player(db, **fields):
    D = db["db_async"]
    p = make_player(D, UID, stones=0)
    p.name = "紫霞"
    for k, v in fields.items():
        setattr(p, k, v)
    async with D.AsyncSessionLocal() as s:
        s.add(p)
        await s.commit()


async def _row(db):
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        return await s.get(D.Player, UID)


async def _pills(db, pill):
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        row = await s.get(D.Inventory, (UID, pill))
        return row.quantity if row else 0


async def _open(db, view_cls, has_pill=False):
    row = await _row(db)
    player = {c.key: getattr(row, c.key) for c in row.__table__.columns}
    return view_cls(author=FakeUser(id=1), cog=None, player=player, has_pill=has_pill, uid=UID)


def _button(view, label):
    return next(b for b in view.children if b.label == label)


def _force_random(monkeypatch, value):
    monkeypatch.setattr(random, "random", lambda: value)


@pytest.mark.parametrize("view_cls,pill,start,target,phrase", STAGES)
async def test_面板按成色给出按钮(db, view_cls, pill, start, target, phrase):
    await _add_player(db, realm=start, cultivation=cultivation_needed(start))
    assert [b.label for b in (await _open(db, view_cls, has_pill=False)).children] == ["直接冲关"]
    labels = [b.label for b in (await _open(db, view_cls, has_pill=True)).children]
    assert labels == [f"服用{pill}冲关", "直接冲关"]


@pytest.mark.parametrize("view_cls,pill,start,target,phrase", STAGES)
async def test_别人点不动这个面板(db, view_cls, pill, start, target, phrase):
    await _add_player(db, realm=start, cultivation=cultivation_needed(start))
    view = await _open(db, view_cls)
    intruder = FakeInteraction(user_id=999)

    assert await view.interaction_check(intruder) is False


@pytest.mark.parametrize("view_cls,pill,start,target,phrase", STAGES)
async def test_直接冲关成功_晋级并结转溢出修为(db, monkeypatch, view_cls, pill, start, target, phrase):
    """B3：按钮路径成功时曾把修为直接清零，丢掉溢出部分。"""
    await _add_player(db, realm=start, cultivation=cultivation_needed(start) + 30)
    view = await _open(db, view_cls)
    _force_random(monkeypatch, 0.0)
    it = FakeInteraction(user_id=1)

    await _button(view, "直接冲关").callback(it)

    assert it.said(phrase) and it.said(f"**{start}** ➜ **{target}**") and it.said("紫霞")
    p = await _row(db)
    assert p.realm == target
    assert p.cultivation == 30
    assert view.is_finished()


@pytest.mark.parametrize("view_cls,pill,start,target,phrase", STAGES)
async def test_吃丹冲关成功_扣丹并在消息里注明(db, monkeypatch, view_cls, pill, start, target, phrase):
    await _add_player(db, realm=start, cultivation=cultivation_needed(start))
    await db["inventory"].add_item(UID, pill, 1)
    view = await _open(db, view_cls, has_pill=True)
    _force_random(monkeypatch, 0.0)
    it = FakeInteraction(user_id=1)

    await _button(view, f"服用{pill}冲关").callback(it)

    assert it.said(f"（服用{pill}）")
    assert await _pills(db, pill) == 0
    assert (await _row(db)).realm == target


@pytest.mark.parametrize("view_cls,pill,start,target,phrase", STAGES)
async def test_冲关失败_消息带修为寿元_丹药已消耗(db, monkeypatch, view_cls, pill, start, target, phrase):
    await _add_player(db, realm=start, cultivation=cultivation_needed(start) + 20, lifespan=120)
    await db["inventory"].add_item(UID, pill, 1)
    view = await _open(db, view_cls, has_pill=True)
    _force_random(monkeypatch, 0.999)
    monkeypatch.setattr(bt, "roll_failure_outcome", lambda realm: FAIL_LIGHT)
    it = FakeInteraction(user_id=1)

    await _button(view, f"服用{pill}冲关").callback(it)

    assert it.said("💔") and it.said(f"（{pill}已消耗）") and it.said("差之毫厘")
    assert it.said(f"修为：{(cultivation_needed(start) + 20) // 2}") and it.said("寿元：120年")
    assert await _pills(db, pill) == 0
    assert (await _row(db)).realm == start


@pytest.mark.parametrize("view_cls,pill,start,target,phrase", STAGES)
async def test_失败不再强行走火入魔(db, monkeypatch, view_cls, pill, start, target, phrase):
    """B4：失败类型曾靠第二次 roll_breakthrough 取，成功率高的人 95% 走火入魔。
    属性拉满（成功率最高）且不打桩失败类型，连着败 40 次，走火入魔应当是少数。"""
    n_deviate = 0
    for _ in range(40):
        await _add_player(db, realm=start, cultivation=cultivation_needed(start), lifespan=1000,
                          physique=15, bone=15)
        view = await _open(db, view_cls)
        _force_random(monkeypatch, 0.999)
        it = FakeInteraction(user_id=1)
        await _button(view, "直接冲关").callback(it)
        n_deviate += it.said("走火入魔")
        D = db["db_async"]
        async with D.AsyncSessionLocal() as s:                  # 清场，下一轮重来
            await s.delete(await s.get(D.Player, UID))
            await s.commit()

    assert n_deviate <= 12                                       # 期望 ≈5%~20%；旧写法约 95%


@pytest.mark.parametrize("view_cls,pill,start,target,phrase", STAGES)
async def test_狐符在按钮路径上也生效(db, monkeypatch, view_cls, pill, start, target, phrase):
    """B3：按钮路径曾完全没有狐符逻辑 —— 带着狐符照样死，狐符也不消耗。"""
    buffs = json.dumps({"fox_charm": {"value": 1}})
    await _add_player(db, realm=start, cultivation=cultivation_needed(start), lifespan=1, active_buffs=buffs)
    view = await _open(db, view_cls)
    _force_random(monkeypatch, 0.999)
    monkeypatch.setattr(bt, "roll_failure_outcome", lambda realm: FAIL_DEVIATE)
    it = FakeInteraction(user_id=1)

    await _button(view, "直接冲关").callback(it)

    assert it.said("狐符替你挡下一劫") and not it.said("魂归天道")
    p = await _row(db)
    assert p.is_dead is False and p.lifespan == 1
    assert "fox_charm" not in json.loads(p.active_buffs)


@pytest.mark.parametrize("view_cls,pill,start,target,phrase", STAGES)
async def test_没有狐符寿尽就是死(db, monkeypatch, view_cls, pill, start, target, phrase):
    await _add_player(db, realm=start, cultivation=cultivation_needed(start), lifespan=1)
    view = await _open(db, view_cls)
    _force_random(monkeypatch, 0.999)
    monkeypatch.setattr(bt, "roll_failure_outcome", lambda realm: FAIL_DEVIATE)
    it = FakeInteraction(user_id=1)

    await _button(view, "直接冲关").callback(it)

    assert it.said("魂归天道")
    assert (await _row(db)).is_dead is True


@pytest.mark.parametrize("view_cls,pill,start,target,phrase", STAGES)
async def test_丹药已不在背包_提示并作废面板(db, view_cls, pill, start, target, phrase):
    await _add_player(db, realm=start, cultivation=cultivation_needed(start))
    view = await _open(db, view_cls, has_pill=True)          # 开面板时有，点的时候没了
    it = FakeInteraction(user_id=1)

    await _button(view, f"服用{pill}冲关").callback(it)

    assert it.said(f"背包中无{pill}")
    assert (await _row(db)).realm == start
    assert view.is_finished()


@pytest.mark.parametrize("view_cls,pill,start,target,phrase", STAGES)
async def test_连点_只结算一次_且后到的那次不吞丹(db, monkeypatch, view_cls, pill, start, target, phrase):
    """同一面板被点两次：第二次的状态条件已不成立，提示重试，丹药退回，面板仍可再点。"""
    await _add_player(db, realm=start, cultivation=cultivation_needed(start))
    await db["inventory"].add_item(UID, pill, 2)
    view = await _open(db, view_cls, has_pill=True)
    D = db["db_async"]
    real_consume = bt.consume_item

    async def _race_then_consume(session, *a, **k):
        async with D.AsyncSessionLocal() as other:               # 另一次点击抢先落了库
            (await other.get(D.Player, UID)).cultivation += 5
            await other.commit()
        return await real_consume(session, *a, **k)

    monkeypatch.setattr(bt, "consume_item", _race_then_consume)
    _force_random(monkeypatch, 0.0)
    it = FakeInteraction(user_id=1)

    await _button(view, f"服用{pill}冲关").callback(it)

    assert it.said(bt.STALE_MESSAGE)
    assert await _pills(db, pill) == 2                           # 没白吞
    assert (await _row(db)).realm == start
    assert not view.is_finished()                                # 玩家可以再点
