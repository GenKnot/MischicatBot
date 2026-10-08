"""闭关修炼逻辑测试（utils/cultivation_logic.py）。

时间模型（容易看岔）：
- 寿元不在这里按时间扣，而是 utils/player.py::settle_time 每次交互时按
  `last_active` 以来的真实时间结算。所以 start 不碰寿元是设计。
- 闭关**自然结束**时的入账不在这个文件里：由 cogs/cultivation.py::_cultivation_notifier 定时结算
  （见 tests/test_notifiers.py）。以前这里有个 claim_cultivation，对应的「领取」按钮从未上线，已删除。
- stop_cultivation 把 `last_active` 当闭关起点，据此算已修炼多少年并扣寿元。
  测试里直接把 last_active 往回拨，模拟"已经闭了 N 年"。
"""

import json
import time

import pytest

from tests.conftest import make_player
from utils import cultivation_logic as cl
from utils.character import (
    CAVE_BONUS, calc_cultivation_gain, years_to_seconds,
)
from utils.realms import cultivation_needed

UID = "u"
PARTNER = "p"


async def _add_player(db, uid=UID, **fields):
    D = db["db_async"]
    p = make_player(D, uid, stones=0)
    for k, v in fields.items():
        setattr(p, k, v)
    async with D.AsyncSessionLocal() as s:
        s.add(p)
        await s.commit()


async def _row(db, uid=UID):
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        return await s.get(D.Player, uid)


def _gain(years, comprehension=5, root="单灵根", bonus=0.0):
    return int(calc_cultivation_gain(years, comprehension, root) * (1 + bonus))


# --- get_player_data / check_cultivation_status -------------------------------

async def test_读不存在的玩家(db):
    assert await cl.get_player_data("nobody") is None
    assert await cl.check_cultivation_status("nobody") == {"exists": False}


async def test_空闲状态(db):
    await _add_player(db)
    st = await cl.check_cultivation_status(UID)
    assert st["exists"] and st["status"] == "空闲"
    assert not st["is_cultivating"] and not st["is_gathering"]
    assert st["player_dict"]["discord_id"] == UID


async def test_闭关中状态带剩余年数(db):
    await _add_player(db, cultivating_until=time.time() + years_to_seconds(3))
    st = await cl.check_cultivation_status(UID)
    assert st["is_cultivating"] is True
    assert st["status"].startswith("闭关中") and "3.0" in st["status"]


async def test_采集中状态用采集类型命名(db):
    await _add_player(db, gathering_until=time.time() + years_to_seconds(2), gathering_type="采药")
    st = await cl.check_cultivation_status(UID)
    assert st["is_gathering"] is True
    assert st["status"].startswith("采药中")


async def test_闭关已结束不再算闭关中(db):
    await _add_player(db, cultivating_until=time.time() - 10)
    assert (await cl.check_cultivation_status(UID))["is_cultivating"] is False


# --- start_cultivation --------------------------------------------------------

async def test_开始闭关_记下结束时间和年数(db):
    await _add_player(db, lifespan=50)
    before = time.time()

    res = await cl.start_cultivation(UID, 10)

    assert res["success"] and res["years"] == 10
    p = await _row(db)
    assert p.cultivating_years == 10
    assert before + years_to_seconds(10) <= p.cultivating_until <= time.time() + years_to_seconds(10)
    assert p.lifespan == 50                      # 开始时不扣寿元，见模块说明
    assert p.cultivation == 0                    # 收益到出关才结算


async def test_开始闭关_预估收益按悟性与灵根算(db):
    await _add_player(db, comprehension=9, spirit_root_type="双灵根")
    res = await cl.start_cultivation(UID, 10)
    assert res["gain"] == _gain(10, 9, "双灵根")
    assert res["needed"] == cultivation_needed("炼气期1层")


async def test_洞府加成计入预估收益(db):
    await _add_player(db, cave="青云洞府")
    res = await cl.start_cultivation(UID, 10)
    assert res["gain"] == _gain(10, bonus=CAVE_BONUS)


async def test_丹药修炼速度buff计入预估收益(db):
    buffs = json.dumps({"cultivation_speed_bonus": {"value": 50}})
    await _add_player(db, active_buffs=buffs)
    res = await cl.start_cultivation(UID, 10)
    assert res["speed_bonus"] == 0.5
    assert res["gain"] == _gain(10, bonus=0.5)


async def test_寿元不够不能闭关(db):
    await _add_player(db, lifespan=5)
    res = await cl.start_cultivation(UID, 10)
    assert res["success"] is False and "寿元不足" in res["message"]
    assert (await _row(db)).cultivating_until is None


async def test_已在闭关不能重复开始(db):
    until = time.time() + years_to_seconds(5)
    await _add_player(db, cultivating_until=until, cultivating_years=5)

    res = await cl.start_cultivation(UID, 10)

    assert res["success"] is False and "正在闭关" in res["message"]
    p = await _row(db)
    assert p.cultivating_until == pytest.approx(until) and p.cultivating_years == 5


async def test_正在采集不能闭关(db):
    await _add_player(db, gathering_until=time.time() + 100)
    res = await cl.start_cultivation(UID, 10)
    assert res["success"] is False and "采集" in res["message"]


async def test_上次闭关已结束_可以再开(db):
    await _add_player(db, cultivating_until=time.time() - 1, cultivating_years=5)
    assert (await cl.start_cultivation(UID, 10))["success"] is True


async def test_开始闭关_角色不存在(db):
    assert (await cl.start_cultivation("nobody", 10))["message"] == "角色不存在"


# --- stop_cultivation：单人 ---------------------------------------------------

def _mid_cultivation(elapsed_years, total_years=10, **extra):
    """闭关到一半：总共 total_years，已经过去 elapsed_years。"""
    now = time.time()
    return dict(
        cultivating_until=now + years_to_seconds(total_years - elapsed_years),
        cultivating_years=total_years,
        last_active=now - years_to_seconds(elapsed_years),
        **extra,
    )


async def test_提前出关_按实际年数结算修为并扣寿元(db):
    await _add_player(db, lifespan=50, cultivation=5, **_mid_cultivation(4))

    res = await cl.stop_cultivation(UID)

    assert res["success"] and not res["is_dual"]
    assert res["actual_years"] == 4
    assert res["gain"] == _gain(4)
    p = await _row(db)
    assert p.cultivation == 5 + _gain(4)
    assert p.lifespan == 50 - 4
    assert p.cultivating_until is None and p.cultivating_years is None


async def test_提前出关_实际年数不超过计划年数(db):
    """last_active 拨得比计划还早（比如挂了很久没交互），收益仍封顶在计划年数。"""
    await _add_player(db, lifespan=50, **_mid_cultivation(elapsed_years=15, total_years=10))
    # 把 until 改到未来，保证仍处于"闭关中"
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        (await s.get(D.Player, UID)).cultivating_until = time.time() + 100
        await s.commit()

    res = await cl.stop_cultivation(UID)

    assert res["actual_years"] == 10
    assert res["gain"] == _gain(10)


async def test_有溢出修为时按比例发放_不再重算(db):
    """cultivation_overflow > 0 是别处（如双修）预先算好的总收益，按已过比例兑现。"""
    await _add_player(db, cultivation_overflow=1000, **_mid_cultivation(4, total_years=10))

    res = await cl.stop_cultivation(UID)

    assert res["gain"] == 1000 * 4 // 10
    assert (await _row(db)).cultivation_overflow == 0


async def test_没在闭关不能停(db):
    await _add_player(db)
    assert (await cl.stop_cultivation(UID))["message"] == "当前并未在闭关"


async def test_闭关已自然结束不能停_该走领取(db):
    await _add_player(db, cultivating_until=time.time() - 1, cultivating_years=10)
    assert (await cl.stop_cultivation(UID))["message"] == "当前并未在闭关"


async def test_停止_角色不存在(db):
    assert (await cl.stop_cultivation("nobody"))["message"] == "角色不存在"


# --- stop_cultivation：双修 ---------------------------------------------------

async def _dual_pair(db, **a_extra):
    await _add_player(db, UID, lifespan=50, dual_partner_id=PARTNER, **_mid_cultivation(4), **a_extra)
    await _add_player(db, PARTNER, lifespan=60, dual_partner_id=UID, **_mid_cultivation(4))


async def test_双修提前出关_双方按实际年数结算_且寿元退回未修的部分(db):
    await _dual_pair(db)

    res = await cl.stop_cultivation(UID)

    assert res["success"] and res["is_dual"] and res["partner_id"] == PARTNER
    assert res["actual_years"] == res["partner_years"] == 4
    a, b = await _row(db, UID), await _row(db, PARTNER)
    # 双修闭关时不消耗寿元，没修满的 6 年退回（与单人"扣实际年数"相反）
    assert a.lifespan == 50 + (10 - 4)
    assert b.lifespan == 60 + (10 - 4)
    for p in (a, b):
        assert p.cultivating_until is None and p.cultivating_years is None
        assert p.dual_partner_id is None and p.cultivation_overflow == 0
    assert a.cultivation == _gain(4) and b.cultivation == _gain(4)


async def test_双修退回的寿元不会超过上限(db):
    await _add_player(db, UID, lifespan=98, lifespan_max=100, dual_partner_id=PARTNER, **_mid_cultivation(4))
    await _add_player(db, PARTNER, lifespan=50, dual_partner_id=UID, **_mid_cultivation(4))

    await cl.stop_cultivation(UID)

    assert (await _row(db, UID)).lifespan == 100


async def test_搭档已出关_退化成单人结算(db):
    """搭档那边已经不在闭关了（或者搭档指向的不是我），不能把我也当双修结算。"""
    await _add_player(db, UID, lifespan=50, dual_partner_id=PARTNER, **_mid_cultivation(4))
    await _add_player(db, PARTNER, lifespan=60)                       # 没在闭关

    res = await cl.stop_cultivation(UID)

    assert res["is_dual"] is False
    assert (await _row(db, UID)).lifespan == 50 - 4
    assert (await _row(db, PARTNER)).lifespan == 60                   # 搭档不受影响


async def test_搭档的搭档不是我_也按单人结算(db):
    await _add_player(db, UID, lifespan=50, dual_partner_id=PARTNER, **_mid_cultivation(4))
    await _add_player(db, PARTNER, lifespan=60, dual_partner_id="someone-else", **_mid_cultivation(4))

    res = await cl.stop_cultivation(UID)

    assert res["is_dual"] is False
    assert (await _row(db, PARTNER)).cultivating_until is not None    # 对方的闭关没被动
