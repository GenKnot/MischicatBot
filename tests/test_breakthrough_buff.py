"""破障丹（B52）：『突破时服用，提升所有境界突破成功率 20%』。

以前它在突破逻辑里根本没有接入，哪里都用不上（`使用` 会扣药并回复「+20%」却什么也不记录；后来改成拒绝）。
按你的决定接入：`使用 破障丹` 写入一次性 buff `breakthrough_bonus_once`（+20%），**下一次任意境界的突破**
（普通突破、筑基 / 凝丹 / 化婴三道大关）都会把它加进成功率，并在那次结算里一并消耗（成败都消耗，
与落库同一个条件写，连点 / 陈旧快照不会白吞也不会用两遍）。
"""

import json
import random

import pytest

from tests.conftest import make_player
from utils import breakthrough_logic as bt
from utils import realms
from utils.buffs import apply_buff
from utils.realms import cultivation_needed

UID = "u"
BUFF = apply_buff("{}", "breakthrough_bonus_once", 20)


async def _add(db, **fields):
    D = db["db_async"]
    p = make_player(D, UID, stones=0)
    for k, v in fields.items():
        setattr(p, k, v)
    async with D.AsyncSessionLocal() as s:
        s.add(p)
        await s.commit()


async def row(db):
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        return await s.get(D.Player, UID)


async def pdict():
    _, d = await bt.load_breakthrough_state(UID)
    return d


def has_buff(p):
    return "breakthrough_bonus_once" in json.loads(p.active_buffs or "{}")


# --- roll_breakthrough 的加成 -------------------------------------------------

def test_roll_breakthrough_加成加到成功率上_封顶95(monkeypatch):
    realm = "元婴期初期"                                                       # 原成功率 0.35，离封顶足够远
    base = realms.breakthrough_success_rate(realm, 5, 5, 0)
    seen = {}

    def fake_random():
        return seen["r"]
    monkeypatch.setattr(random, "random", fake_random)
    seen["r"] = base + 0.10                                                  # 略高于原成功率、低于 +20 之后
    assert realms.roll_breakthrough(realm, 5, 5, 0)[0] is False
    assert realms.roll_breakthrough(realm, 5, 5, 0, bonus=0.20)[0] is True
    seen["r"] = 0.94
    assert realms.roll_breakthrough(realm, 5, 5, 0, bonus=0.99)[0] is True      # 封顶 0.95
    seen["r"] = 0.96
    assert realms.roll_breakthrough(realm, 5, 5, 0, bonus=0.99)[0] is False


# --- 普通突破 -----------------------------------------------------------------

async def test_普通突破_带上加成_成功后buff被消耗(db, monkeypatch):
    await _add(db, realm="炼气期1层", cultivation=100, active_buffs=BUFF)
    seen = {}

    def fake(realm, physique, bone, cultivation, bonus=0.0):
        seen["bonus"] = bonus
        return True, None
    monkeypatch.setattr(bt, "roll_breakthrough", fake)
    res = await bt.do_single_breakthrough(UID, await pdict())
    assert res["breakthrough"] and seen["bonus"] == pytest.approx(0.20)
    assert not has_buff(await row(db))


async def test_普通突破_失败也消耗buff(db, monkeypatch):
    await _add(db, realm="炼气期1层", cultivation=100, lifespan=100, active_buffs=BUFF)
    monkeypatch.setattr(bt, "roll_breakthrough", lambda *a, **k: (False, realms.FAIL_LIGHT))
    res = await bt.do_single_breakthrough(UID, await pdict())
    assert res["success"] and res["breakthrough"] is False
    assert not has_buff(await row(db))


async def test_普通突破_没有buff时加成为0_不动buff表(db, monkeypatch):
    other = apply_buff("{}", "combat_power_bonus", 10, charges=1)
    await _add(db, realm="炼气期1层", cultivation=100, active_buffs=other)
    seen = {}

    def fake(realm, physique, bone, cultivation, bonus=0.0):
        seen["bonus"] = bonus
        return True, None
    monkeypatch.setattr(bt, "roll_breakthrough", fake)
    await bt.do_single_breakthrough(UID, await pdict())
    assert seen["bonus"] == 0.0 and json.loads((await row(db)).active_buffs) == json.loads(other)


async def test_普通突破_只消耗破障丹的buff_别的buff保留(db, monkeypatch):
    mixed = apply_buff(BUFF, "combat_power_bonus", 10, charges=2)
    await _add(db, realm="炼气期1层", cultivation=100, active_buffs=mixed)
    monkeypatch.setattr(bt, "roll_breakthrough", lambda *a, **k: (True, None))
    await bt.do_single_breakthrough(UID, await pdict())
    left = json.loads((await row(db)).active_buffs)
    assert "breakthrough_bonus_once" not in left and "combat_power_bonus" in left


async def test_普通突破_陈旧快照被拒_buff一并保留(db, monkeypatch):
    await _add(db, realm="炼气期1层", cultivation=100, active_buffs=BUFF)
    d = await pdict()
    D = db["db_async"]
    from sqlalchemy import update
    async with D.AsyncSessionLocal() as s:                              # 另一次点击先把修为改了
        await s.execute(update(D.Player).values(cultivation=50))
        await s.commit()
    monkeypatch.setattr(bt, "roll_breakthrough", lambda *a, **k: (True, None))
    res = await bt.do_single_breakthrough(UID, d)
    assert res["message"] == bt.STALE_MESSAGE and has_buff(await row(db))


async def test_连续突破_buff只用在第一次(db, monkeypatch):
    needed = cultivation_needed("炼气期1层")
    await _add(db, realm="炼气期1层", cultivation=needed * 3, active_buffs=BUFF)
    bonuses = []

    def fake(realm, physique, bone, cultivation, bonus=0.0):
        bonuses.append(bonus)
        return True, None
    monkeypatch.setattr(bt, "roll_breakthrough", fake)
    await bt.do_breakthrough_chain(UID)
    assert bonuses[0] == pytest.approx(0.20) and all(b == 0.0 for b in bonuses[1:]) and len(bonuses) >= 2


# --- 三道大关 -----------------------------------------------------------------

PILLS = [
    pytest.param(bt.handle_zhuji_breakthrough, "筑基期1层", "炼气期10层", id="筑基"),
    pytest.param(bt.handle_ningdan_breakthrough, "结丹期初期", "筑基期10层", id="凝丹"),
    pytest.param(bt.handle_huaying_breakthrough, "元婴期初期", "结丹期后期", id="化婴"),
]


@pytest.mark.parametrize("handler,target,start", PILLS)
async def test_大关_破障丹加成抬高成功率_不吃丹也生效_成败都消耗(db, monkeypatch, handler, target, start):
    await _add(db, realm=start, cultivation=cultivation_needed(start), spirit_root_type="五灵根",
               comprehension=1, fortune=1, bone=1, soul=1, active_buffs=BUFF)
    # 不加成时成功率很低；0.5 的掷骰值只有在 +20 个百分点后才可能成功，这里把它定在刚好能被加成救起来的位置
    seen = {}

    def fake_random():
        return seen["r"]
    monkeypatch.setattr(random, "random", fake_random)
    from utils.items import calc_zhuji_breakthrough_rate
    from utils.items.breakthrough import calc_ningdan_breakthrough_rate, calc_huaying_breakthrough_rate
    rate_fn = {"筑基期1层": calc_zhuji_breakthrough_rate, "结丹期初期": calc_ningdan_breakthrough_rate,
               "元婴期初期": calc_huaying_breakthrough_rate}[target]
    base = rate_fn(await pdict(), use_pill=False)
    seen["r"] = (base + 10) / 100                                         # 高于原成功率、低于 +20 后的成功率
    res = await handler(UID, False)
    assert res["breakthrough"] is True and not has_buff(await row(db))


@pytest.mark.parametrize("handler,target,start", PILLS)
async def test_大关_没有buff时不加成(db, monkeypatch, handler, target, start):
    await _add(db, realm=start, cultivation=cultivation_needed(start), spirit_root_type="五灵根",
               comprehension=1, fortune=1, bone=1, soul=1)
    from utils.items import calc_zhuji_breakthrough_rate
    from utils.items.breakthrough import calc_ningdan_breakthrough_rate, calc_huaying_breakthrough_rate
    rate_fn = {"筑基期1层": calc_zhuji_breakthrough_rate, "结丹期初期": calc_ningdan_breakthrough_rate,
               "元婴期初期": calc_huaying_breakthrough_rate}[target]
    base = rate_fn(await pdict(), use_pill=False)
    monkeypatch.setattr(random, "random", lambda: (base + 10) / 100)
    res = await handler(UID, False)
    assert res["breakthrough"] is False


@pytest.mark.parametrize("handler,target,start", PILLS)
async def test_大关_吃丹加破障丹_叠加但封顶95(db, monkeypatch, handler, target, start):
    await _add(db, realm=start, cultivation=cultivation_needed(start), spirit_root_type="单灵根",
               comprehension=30, fortune=30, bone=30, soul=30, active_buffs=BUFF)
    pill = {"筑基期1层": "筑基丹", "结丹期初期": "凝丹丹", "元婴期初期": "化婴丹"}[target]
    await db["inventory"].add_item(UID, pill, 1)
    monkeypatch.setattr(random, "random", lambda: 0.96)                    # 即便加成再高，也过不了 95% 的封顶
    res = await handler(UID, True)
    assert res["breakthrough"] is False


@pytest.mark.parametrize("handler,target,start", PILLS)
async def test_大关_失败也消耗破障丹buff(db, monkeypatch, handler, target, start):
    await _add(db, realm=start, cultivation=cultivation_needed(start), lifespan=100, lifespan_max=100, active_buffs=BUFF)
    monkeypatch.setattr(random, "random", lambda: 0.999)                   # 一定失败
    monkeypatch.setattr(bt, "roll_failure_outcome", lambda realm: realms.FAIL_LIGHT)
    res = await handler(UID, False)
    assert res["breakthrough"] is False and not has_buff(await row(db))
