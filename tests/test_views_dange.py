"""丹阁面板测试。

两处缴费原先是「读余额 → 比较 → -=」，连点会扣两次。

按钮回调是独立的交互事件，每个都得自己校验身份，只在发面板时查一次挡不住人。
调用方式：`await view.pay_btn.callback(interaction)`，callback 已经绑好 view 和 button。
"""

import asyncio

import pytest

from tests.conftest import make_player
from tests.discord_fakes import FakeInteraction, FakeUser
from utils.views import dange as dange_mod
from utils.views.dange import EXAM_COST, MATERIAL_COST, DangeView


@pytest.fixture
def view():
    """面板归 id=1 的玩家所有。"""
    return DangeView(author=FakeUser(id=1), cog=None, player={"discord_id": "1"})


@pytest.fixture
async def alchemist(db):
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        s.add(make_player(D, "1", stones=10_000))
        await s.commit()
    return "1"


async def _stones(db, uid="1"):
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        return (await s.get(D.Player, uid)).spirit_stones


async def _inv(db, uid="1"):
    return await db["inventory"].get_inventory(uid)


# --- 权限 --------------------------------------------------------------------

async def test_别人点不动这个面板(db, view, alchemist):
    """安全性质：按钮回调是独立事件，必须逐个校验身份。"""
    intruder = FakeInteraction(user_id=999)

    allowed = await view.interaction_check(intruder)

    assert allowed is False
    assert intruder.said("这不是你的面板")


async def test_面板主人可以操作(db, view, alchemist):
    owner = FakeInteraction(user_id=1)
    assert await view.interaction_check(owner) is True


# --- 考核缴费 ----------------------------------------------------------------

async def test_缴费成功扣灵石并发材料(db, view, alchemist):
    it = FakeInteraction(user_id=1)

    await view.pay_btn.callback(it)

    assert await _stones(db) == 10_000 - EXAM_COST
    inventory = await _inv(db)
    assert inventory.get("灵芝草") == 6 and inventory.get("茯苓灵块") == 3


async def test_缴费后记录考核次数(db, view, alchemist):
    it = FakeInteraction(user_id=1)
    await view.pay_btn.callback(it)

    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        assert (await s.get(D.Player, "1")).exam_attempts_left == 1


async def test_灵石不足时不发材料(db):
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        s.add(make_player(D, "2", stones=EXAM_COST - 1))
        await s.commit()
    v = DangeView(author=FakeUser(id=2), cog=None, player={"discord_id": "2"})
    it = FakeInteraction(user_id=2)

    await v.pay_btn.callback(it)

    assert it.said("灵石不够")
    assert await _stones(db, "2") == EXAM_COST - 1
    assert await _inv(db, "2") == {}


async def test_已是炼丹师不能重复考核(db):
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        p = make_player(D, "3", stones=10_000)
        p.alchemy_level = 2
        s.add(p)
        await s.commit()
    v = DangeView(author=FakeUser(id=3), cog=None, player={"discord_id": "3"})
    it = FakeInteraction(user_id=3)

    await v.pay_btn.callback(it)

    assert it.said("已经是炼丹师")
    assert await _stones(db, "3") == 10_000


async def test_重复缴费只收一次(db, view, alchemist):
    """考核费是一次性的：第二次点击应当被告知"已经交过钱了"，而不是再扣 500。

    幂等靠 `exam_attempts_left` 从 0 翻到 1 的原子占用实现，不是靠 UI 禁用按钮
    —— 旧消息里的按钮永远可点。
    """
    first = FakeInteraction(user_id=1)
    await view.pay_btn.callback(first)
    second = FakeInteraction(user_id=1)
    await view.pay_btn.callback(second)

    assert second.said("已经交过钱")
    assert await _stones(db) == 10_000 - EXAM_COST, "只应扣一次考核费"


async def test_连点缴费只扣一次(db, view, alchemist):
    """并发版本：四次同时点击，账面只能扣一次。"""
    await asyncio.gather(*[
        view.pay_btn.callback(FakeInteraction(user_id=1))
        for _ in range(4)
    ])

    assert await _stones(db) == 10_000 - EXAM_COST, "只应扣一次考核费"
    assert (await _inv(db)).get("灵芝草") == 6, "材料也只应发一份"


async def test_扣款失败时不发材料(db, view, alchemist, monkeypatch):
    """确定性地覆盖"扣不到钱就不发东西"这条路径。"""
    async def _fail(session, uid, amount):
        return False
    monkeypatch.setattr(dange_mod, "spend_stones", _fail)
    it = FakeInteraction(user_id=1)

    await view.pay_btn.callback(it)

    assert await _inv(db) == {}, "扣款失败绝不能发材料"
    assert await _stones(db) == 10_000


# --- 补充材料 ----------------------------------------------------------------

async def test_买材料扣灵石并入包(db, view, alchemist):
    it = FakeInteraction(user_id=1)

    await view.buy_btn.callback(it)

    assert await _stones(db) == 10_000 - MATERIAL_COST
    assert (await _inv(db)).get("灵芝草") == 6


async def test_买材料灵石不足时被拒(db):
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        s.add(make_player(D, "4", stones=MATERIAL_COST - 1))
        await s.commit()
    v = DangeView(author=FakeUser(id=4), cog=None, player={"discord_id": "4"})
    it = FakeInteraction(user_id=4)

    await v.buy_btn.callback(it)

    assert it.said("拿不出来")
    assert await _inv(db, "4") == {}


async def test_买材料是可重复购买的(db, view, alchemist):
    """与考核费不同，补充材料本来就允许多次购买 —— 每次各扣一份钱、发一份货。

    这条用来把两者的语义区分开，避免以后有人误把它也做成幂等的。
    """
    for _ in range(3):
        await view.buy_btn.callback(FakeInteraction(user_id=1))

    assert await _stones(db) == 10_000 - MATERIAL_COST * 3
    assert (await _inv(db)).get("灵芝草") == 18


# --- 按钮状态 ----------------------------------------------------------------

def test_缴费前后按钮可用状态互换(view):
    view.set_paid(False)
    assert view.pay_btn.disabled is False
    assert view.alchemy_btn.disabled is True

    view.set_paid(True)
    assert view.pay_btn.disabled is True
    assert view.pay_btn.label == "已缴费"
    assert view.alchemy_btn.disabled is False
    assert view.buy_btn.disabled is False
