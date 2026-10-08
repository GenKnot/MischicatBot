"""死亡与轮回逻辑测试（utils/death_rebirth_logic.py）。

轮回是"死亡不等于清零"的承诺：属性按公式继承，其余状态重置。
U1「江湖百态」要让机器人也走死亡/补员，改它之前先把现状钉住。
"""

import random

import pytest

from tests.conftest import make_player
from utils import death_rebirth_logic as dr
from utils.character import REALM_LIFESPAN
from utils.world import CITIES

UID = "u"


async def _add_player(db, **fields):
    D = db["db_async"]
    p = make_player(D, UID, stones=0)
    for k, v in fields.items():
        setattr(p, k, v)
    async with D.AsyncSessionLocal() as s:
        s.add(p)
        await s.commit()


async def _row(db):
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        return await s.get(D.Player, UID)


# --- calculate_rebirth_bonus --------------------------------------------------

def test_继承按超出5点的部分打三成():
    stats = {k: 15 for k in ("comprehension", "physique", "fortune", "bone", "soul")}
    bonus = dr.calculate_rebirth_bonus({**stats, "rebirth_count": 0})
    assert bonus == {k: 3 for k in stats}                # (15-5) * 0.3 = 3


def test_轮回次数越多继承越多():
    stats = {k: 15 for k in ("comprehension", "physique", "fortune", "bone", "soul")}
    assert dr.calculate_rebirth_bonus({**stats, "rebirth_count": 2})["bone"] == 6    # mult = 2
    assert dr.calculate_rebirth_bonus({**stats, "rebirth_count": 4})["bone"] == 9    # mult = 3


def test_属性不高于5不继承_也不会是负数():
    bonus = dr.calculate_rebirth_bonus({"comprehension": 1, "physique": 5, "fortune": 6})
    assert bonus["comprehension"] == 0
    assert bonus["physique"] == 0
    assert bonus["fortune"] == 0                         # int(0.3) = 0
    assert all(v >= 0 for v in bonus.values())


def test_缺字段按5处理():
    assert dr.calculate_rebirth_bonus({}) == {k: 0 for k in
                                            ("comprehension", "physique", "fortune", "bone", "soul")}


# --- check_death / handle_death -----------------------------------------------

async def test_寿元耗尽算死亡(db):
    await _add_player(db, lifespan=0)
    dead, d = await dr.check_death(UID)
    assert dead is True and d["discord_id"] == UID


async def test_标记已死也算死亡_哪怕寿元还有(db):
    await _add_player(db, lifespan=50, is_dead=True)
    assert (await dr.check_death(UID))[0] is True


async def test_活着的人不算死亡(db):
    await _add_player(db, lifespan=50)
    dead, d = await dr.check_death(UID)
    assert dead is False and d is not None


async def test_检查不存在的角色(db):
    assert await dr.check_death("nobody") == (False, None)


async def test_handle_death_标记死亡(db):
    await _add_player(db, name="紫霞")
    res = await dr.handle_death(UID)
    assert res == {"success": True, "name": "紫霞"}
    assert (await _row(db)).is_dead is True


async def test_handle_death_角色不存在(db):
    assert (await dr.handle_death("nobody"))["success"] is False


# --- handle_rebirth -----------------------------------------------------------

async def _dying_player(db, **extra):
    """一个什么状态都带着的老修士，用来验证轮回重置得干不干净。"""
    await _add_player(
        db, name="老怪", realm="元婴期后期", cultivation=777, lifespan=0, lifespan_max=1000,
        spirit_stones=99_999, is_dead=True, is_virgin=False, sect="仙葬谷", sect_rank="长老",
        cultivating_until=9e9, cultivating_years=10, active_quest="某任务", quest_due=9e9,
        gathering_until=9e9, gathering_type="采药", explore_count=7, explore_reset_year=3.5,
        current_city="某远方城",
        comprehension=15, physique=15, fortune=15, bone=15, soul=15, rebirth_count=0,
        **extra,
    )
    return (await dr.check_death(UID))[1]


async def test_轮回_重置成炼气期一层的新人(db):
    d = await _dying_player(db)

    res = await dr.handle_rebirth(UID, d)

    assert res["success"] and res["rebirth_count"] == 1 and res["name"] == "老怪"
    p = await _row(db)
    assert p.realm == "炼气期1层" and p.cultivation == 0
    assert p.lifespan == p.lifespan_max == REALM_LIFESPAN["炼气期"]
    assert p.is_dead is False and p.is_virgin is True
    assert p.spirit_stones == 500                        # 家底清掉，只给启动资金
    assert p.rebirth_count == 1


async def test_轮回_清掉宗门_任务_闭关_采集_探险状态(db):
    d = await _dying_player(db)

    await dr.handle_rebirth(UID, d)

    p = await _row(db)
    assert p.sect is None and p.sect_rank is None
    assert p.cultivating_until is None and p.cultivating_years is None
    assert p.active_quest is None and p.quest_due is None
    assert p.gathering_until is None and p.gathering_type is None
    assert p.explore_count == 0 and p.explore_reset_year == 0


async def test_轮回_属性按公式叠加继承(db):
    d = await _dying_player(db)

    res = await dr.handle_rebirth(UID, d)

    assert res["bonus"] == {k: 3 for k in ("comprehension", "physique", "fortune", "bone", "soul")}
    p = await _row(db)
    assert (p.comprehension, p.physique, p.fortune, p.bone, p.soul) == (18, 18, 18, 18, 18)


async def test_轮回_落在某个真实城市(db, monkeypatch):
    d = await _dying_player(db)
    monkeypatch.setattr(random, "choice", lambda seq: seq[-1])

    await dr.handle_rebirth(UID, d)

    assert (await _row(db)).current_city == CITIES[-1]["name"]


async def test_轮回次数累计(db):
    d = await _dying_player(db)
    d["rebirth_count"] = 2

    res = await dr.handle_rebirth(UID, d)

    assert res["rebirth_count"] == 3
    assert (await _row(db)).rebirth_count == 3


async def test_轮回原因_仙葬谷弟子与阴阳奇遇(db):
    d = await _dying_player(db)
    assert (await dr.handle_rebirth(UID, d))["reason"] == "仙葬谷轮回传承"

    d["sect"] = None
    assert (await dr.handle_rebirth(UID, d))["reason"] == "阴阳奇遇感应"


async def test_轮回_角色不存在(db):
    res = await dr.handle_rebirth("nobody", {"name": "x"})
    assert res == {"success": False, "message": "角色不存在"}


# --- can_rebirth --------------------------------------------------------------

@pytest.mark.parametrize("fields,expected", [
    ({"sect": "仙葬谷"}, True),
    ({"has_bahongchen": True}, True),
    ({"sect": "仙葬谷", "has_bahongchen": True}, True),
    ({"sect": "别的宗门"}, False),
    ({}, False),
])
async def test_谁有资格轮回(db, fields, expected):
    await _add_player(db, **fields)
    can, d = await dr.can_rebirth(UID)
    assert can is expected
    assert d["discord_id"] == UID


async def test_不存在的角色没有轮回资格(db):
    assert await dr.can_rebirth("nobody") == (False, None)


# --- 阴阳奇遇 -----------------------------------------------------------------

def test_已有八红尘或轮回过的人_不再触发阴阳奇遇(monkeypatch):
    monkeypatch.setattr(random, "random", lambda: 0.0)            # 骰子必中，排除运气
    assert dr.should_trigger_yinyang({"has_bahongchen": True}) is False
    assert dr.should_trigger_yinyang({"rebirth_count": 1}) is False


def test_阴阳奇遇概率是万分之三(monkeypatch):
    monkeypatch.setattr(random, "random", lambda: 0.0003)
    assert dr.should_trigger_yinyang({}) is True                  # <= 0.0003
    monkeypatch.setattr(random, "random", lambda: 0.0004)
    assert dr.should_trigger_yinyang({}) is False


async def test_标记阴阳奇遇已触发(db):
    await _add_player(db)
    await dr.mark_yinyang_triggered(UID)
    assert (await _row(db)).has_bahongchen is True


async def test_标记不存在的角色不报错(db):
    await dr.mark_yinyang_triggered("nobody")
