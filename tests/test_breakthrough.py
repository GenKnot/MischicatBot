"""突破逻辑功能测试（utils/breakthrough_logic.py）。

此前这个文件 0% 覆盖：把突破改坏了，没有一个测试会红。
这里钉的是**正常流程**——成功晋级、失败扣修为/寿元、寿尽死亡、狐符续命、
丹药扣除——而不是并发性质（并发见 test_concurrency.py）。

随机性的处理：
- 通用突破：替换 breakthrough_logic.roll_breakthrough（它在模块里是按名字导入的）
- 筑基/凝丹/化婴：函数内 `import random; random.random()`，直接 patch random.random
"""

import json
import random

import pytest

from tests.conftest import make_player
from utils import breakthrough_logic as bt
from utils.realms import (
    FAIL_DEVIATE, FAIL_HEAVY, FAIL_LIGHT,
    apply_failure, cultivation_needed, lifespan_max_for_realm, roll_failure_outcome,
)

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


async def _pill_qty(db, item_id):
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        row = await s.get(D.Inventory, (UID, item_id))
        return row.quantity if row else 0


def _force_roll(monkeypatch, success: bool, outcome=None):
    monkeypatch.setattr(bt, "roll_breakthrough", lambda *a, **k: (success, outcome))


def _force_random(monkeypatch, value: float):
    monkeypatch.setattr(random, "random", lambda: value)


async def _player_dict(db):
    can, d = await bt.can_breakthrough(UID)
    return d


# --- can_breakthrough ---------------------------------------------------------

async def test_修为圆满才能突破(db):
    await _add_player(db, realm="炼气期1层", cultivation=cultivation_needed("炼气期1层"))
    can, d = await bt.can_breakthrough(UID)
    assert can is True
    assert d["realm"] == "炼气期1层"


async def test_修为差一点不能突破(db):
    await _add_player(db, realm="炼气期1层", cultivation=cultivation_needed("炼气期1层") - 1)
    can, _ = await bt.can_breakthrough(UID)
    assert can is False


async def test_角色不存在_不能突破(db):
    assert await bt.can_breakthrough("nobody") == (False, None)


# --- do_single_breakthrough：成功 ---------------------------------------------

async def test_突破成功_晋级并结转溢出修为和寿元(db, monkeypatch):
    await _add_player(db, realm="炼气期1层", cultivation=130, lifespan=90, lifespan_max=100)
    _force_roll(monkeypatch, True)

    res = await bt.do_single_breakthrough(UID, await _player_dict(db))

    new_max = lifespan_max_for_realm("炼气期2层")
    assert res["success"] and res["breakthrough"]
    assert (res["old_realm"], res["new_realm"]) == ("炼气期1层", "炼气期2层")
    assert res["lifespan_gain"] == new_max - 100

    p = await _row(db)
    assert p.realm == "炼气期2层"
    assert p.cultivation == 30                       # 130 - 100 的溢出
    assert p.lifespan_max == new_max
    assert p.lifespan == 90 + (new_max - 100)        # 寿元上限涨多少，当前寿元就补多少


async def test_突破成功_寿元上限没涨时不补寿元(db, monkeypatch):
    """上限比现有的还低（比如被功法/事件抬高过）时，gain 取 0，不会扣寿元。"""
    await _add_player(db, realm="炼气期1层", cultivation=100, lifespan=50, lifespan_max=500)
    _force_roll(monkeypatch, True)

    res = await bt.do_single_breakthrough(UID, await _player_dict(db))

    assert res["lifespan_gain"] == 0
    p = await _row(db)
    assert p.lifespan == 50
    assert p.lifespan_max == lifespan_max_for_realm("炼气期2层")


async def test_已至大道巅峰_不能再突破(db, monkeypatch):
    await _add_player(db, realm="道祖", cultivation=10**6)
    _force_roll(monkeypatch, True)

    res = await bt.do_single_breakthrough(UID, await _player_dict(db))

    assert res == {"success": False, "message": "已至大道巅峰"}
    assert (await _row(db)).realm == "道祖"


async def test_突破时角色已不存在(db, monkeypatch):
    """玩家字典是先读出来的，写回前角色可能被删（重置命令）。成功/失败两条路径都要兜住。"""
    await _add_player(db, realm="炼气期1层", cultivation=100)
    d = await _player_dict(db)
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        await s.delete(await s.get(D.Player, UID))
        await s.commit()

    _force_roll(monkeypatch, True)
    assert (await bt.do_single_breakthrough(UID, d))["message"] == "角色不存在"
    _force_roll(monkeypatch, False, FAIL_LIGHT)
    assert (await bt.do_single_breakthrough(UID, d))["message"] == "角色不存在"


# --- do_single_breakthrough：失败 ---------------------------------------------

async def test_轻伤_修为减半_寿元不变_境界不变(db, monkeypatch):
    await _add_player(db, realm="炼气期1层", cultivation=101, lifespan=80)
    _force_roll(monkeypatch, False, FAIL_LIGHT)

    res = await bt.do_single_breakthrough(UID, await _player_dict(db))

    assert res["success"] and not res["breakthrough"] and not res["is_dead"]
    p = await _row(db)
    assert (p.realm, p.cultivation, p.lifespan) == ("炼气期1层", 50, 80)
    assert res["cultivation"] == 50 and res["needed"] == 100


async def test_重伤_修为减半_损耗十分之一寿元(db, monkeypatch):
    await _add_player(db, realm="炼气期1层", cultivation=100, lifespan=80)
    _force_roll(monkeypatch, False, FAIL_HEAVY)

    await bt.do_single_breakthrough(UID, await _player_dict(db))

    p = await _row(db)
    assert (p.cultivation, p.lifespan) == (50, 72)       # 80 // 10 = 8


async def test_走火入魔_修为清零_损耗四分之一寿元(db, monkeypatch):
    await _add_player(db, realm="炼气期1层", cultivation=100, lifespan=80)
    _force_roll(monkeypatch, False, FAIL_DEVIATE)

    await bt.do_single_breakthrough(UID, await _player_dict(db))

    p = await _row(db)
    assert (p.cultivation, p.lifespan) == (0, 60)        # 80 // 4 = 20


async def test_失败后寿元耗尽_角色死亡(db, monkeypatch):
    await _add_player(db, realm="炼气期1层", cultivation=100, lifespan=1)
    _force_roll(monkeypatch, False, FAIL_DEVIATE)

    res = await bt.do_single_breakthrough(UID, await _player_dict(db))

    assert res["is_dead"] is True
    p = await _row(db)
    assert p.lifespan == 0 and p.is_dead is True


async def test_狐符续命_寿元尽了也不死_且狐符被消耗(db, monkeypatch):
    buffs = json.dumps({"fox_charm": {"value": 1}})
    await _add_player(db, realm="炼气期1层", cultivation=100, lifespan=1, active_buffs=buffs)
    _force_roll(monkeypatch, False, FAIL_DEVIATE)

    await bt.do_single_breakthrough(UID, await _player_dict(db))

    p = await _row(db)
    assert p.is_dead is False
    assert p.lifespan == 1
    assert "fox_charm" not in json.loads(p.active_buffs)


async def test_没有狐符时寿元尽了就是死(db, monkeypatch):
    """反向对照：别的 buff 不能顶替狐符。"""
    buffs = json.dumps({"cultivation_speed_bonus": {"value": 20}})
    await _add_player(db, realm="炼气期1层", cultivation=100, lifespan=1, active_buffs=buffs)
    _force_roll(monkeypatch, False, FAIL_HEAVY)

    await bt.do_single_breakthrough(UID, await _player_dict(db))

    assert (await _row(db)).is_dead is True


# --- do_breakthrough_chain ----------------------------------------------------

async def test_修为未圆满_连续突破直接拒绝(db):
    await _add_player(db, realm="炼气期1层", cultivation=10)
    res = await bt.do_breakthrough_chain(UID)
    assert res == {"success": False, "message": "修为未圆满"}


async def test_修为够用几层就连破几层_然后停下(db, monkeypatch):
    """250 修为：1→2 溢出 150，2→3 溢出 50，不够再破，停在 3 层。"""
    await _add_player(db, realm="炼气期1层", cultivation=250)
    _force_roll(monkeypatch, True)

    res = await bt.do_breakthrough_chain(UID)

    assert res["success"]
    assert len(res["successes"]) == 2
    assert res["fail_line"] == ""
    assert "炼气期1层" in res["successes"][0] and "炼气期2层" in res["successes"][0]
    p = await _row(db)
    assert (p.realm, p.cultivation) == ("炼气期3层", 50)


async def test_连续突破中途失败就停(db, monkeypatch):
    await _add_player(db, realm="炼气期1层", cultivation=250, lifespan=100)
    results = iter([(True, None), (False, FAIL_LIGHT)])
    monkeypatch.setattr(bt, "roll_breakthrough", lambda *a, **k: next(results))

    res = await bt.do_breakthrough_chain(UID)

    assert len(res["successes"]) == 1
    assert "突破失败" in res["fail_line"]
    p = await _row(db)
    assert p.realm == "炼气期2层"
    assert p.cultivation == 75                    # 溢出 150，失败后减半


async def test_连续突破失败行包含修为与寿元进度(db, monkeypatch):
    await _add_player(db, realm="炼气期1层", cultivation=100, lifespan=80)
    _force_roll(monkeypatch, False, FAIL_LIGHT)

    res = await bt.do_breakthrough_chain(UID)

    assert res["successes"] == []
    assert "修为：50/100" in res["fail_line"]
    assert "寿元：80年" in res["fail_line"]


async def test_连续突破中寿尽身死_留下魂归天道的提示(db, monkeypatch):
    await _add_player(db, realm="炼气期1层", cultivation=100, lifespan=1)
    _force_roll(monkeypatch, False, FAIL_DEVIATE)

    res = await bt.do_breakthrough_chain(UID)

    assert "魂归天道" in res["fail_line"]
    assert (await _row(db)).is_dead is True


async def test_连续突破到顶会停在巅峰提示(db, monkeypatch):
    await _add_player(db, realm="道祖", cultivation=10**6)

    res = await bt.do_breakthrough_chain(UID)

    assert res["success"] is True
    assert res["chain"] == ["已至大道巅峰"]


async def test_狐符救下的玩家_提示里说狐符挡劫_而不是魂归天道(db, monkeypatch):
    """回归：狐符把寿元救回 1 年后，结果曾沿用救之前的 new_lifespan<=0 判死，
    连续突破会对一个活着的玩家说『魂归天道』。"""
    buffs = json.dumps({"fox_charm": {"value": 1}})
    await _add_player(db, realm="炼气期1层", cultivation=100, lifespan=1, active_buffs=buffs)
    _force_roll(monkeypatch, False, FAIL_DEVIATE)

    res = await bt.do_breakthrough_chain(UID)

    assert (await _row(db)).is_dead is False
    assert "魂归天道" not in res["fail_line"]
    assert "狐符" in res["fail_line"] and "寿元仅余1年" in res["fail_line"]


async def test_狐符救命时_结果里的状态是结算后的真实状态(db, monkeypatch):
    buffs = json.dumps({"fox_charm": {"value": 1}})
    await _add_player(db, realm="炼气期1层", cultivation=100, lifespan=1, active_buffs=buffs)
    _force_roll(monkeypatch, False, FAIL_DEVIATE)

    res = await bt.do_single_breakthrough(UID, await _player_dict(db))

    assert res["is_dead"] is False
    assert res["saved_by_charm"] is True
    assert res["lifespan"] == 1                  # 不是 apply_failure 算出来的 0


async def test_没有狐符时_结果标明死亡且没被救(db, monkeypatch):
    await _add_player(db, realm="炼气期1层", cultivation=100, lifespan=1)
    _force_roll(monkeypatch, False, FAIL_DEVIATE)

    res = await bt.do_single_breakthrough(UID, await _player_dict(db))

    assert res["is_dead"] is True and res["saved_by_charm"] is False
    assert res["lifespan"] == 0


async def test_寿元没尽时不动狐符(db, monkeypatch):
    buffs = json.dumps({"fox_charm": {"value": 1}})
    await _add_player(db, realm="炼气期1层", cultivation=100, lifespan=80, active_buffs=buffs)
    _force_roll(monkeypatch, False, FAIL_LIGHT)

    res = await bt.do_single_breakthrough(UID, await _player_dict(db))

    assert res["saved_by_charm"] is False
    assert "fox_charm" in json.loads((await _row(db)).active_buffs)       # 留着下次保命


# --- 防重复结算（CAS）---------------------------------------------------------

async def test_连点突破成功_同一份旧状态只能结算一次(db, monkeypatch):
    """两次点击读到同一份状态：第一次晋级，第二次的条件（旧境界+旧修为）已不成立，必须被挡下，
    否则同一份状态被判定两遍，可能连升两级。"""
    await _add_player(db, realm="炼气期1层", cultivation=100, lifespan=100, lifespan_max=100)
    d = await _player_dict(db)
    _force_roll(monkeypatch, True)

    first = await bt.do_single_breakthrough(UID, d)
    second = await bt.do_single_breakthrough(UID, d)

    assert first["breakthrough"] is True
    assert second == {"success": False, "message": bt.STALE_MESSAGE}
    p = await _row(db)
    assert p.realm == "炼气期2层"                      # 只升了一级
    assert p.lifespan == first["lifespan"]             # 寿元也只补了一次


async def test_连点突破失败_惩罚只扣一次(db, monkeypatch):
    await _add_player(db, realm="炼气期1层", cultivation=100, lifespan=80)
    d = await _player_dict(db)
    _force_roll(monkeypatch, False, FAIL_HEAVY)

    await bt.do_single_breakthrough(UID, d)
    second = await bt.do_single_breakthrough(UID, d)

    assert second["message"] == bt.STALE_MESSAGE
    p = await _row(db)
    assert (p.cultivation, p.lifespan) == (50, 72)     # 只罚了一次，不是 25 / 65


async def test_状态变了的陈旧快照_不会被写回(db, monkeypatch):
    """读完之后修为被别处改了（比如战斗、吃丹）：旧快照算出来的结果不能覆盖新状态。"""
    await _add_player(db, realm="炼气期1层", cultivation=100)
    d = await _player_dict(db)
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        (await s.get(D.Player, UID)).cultivation = 180
        await s.commit()
    _force_roll(monkeypatch, True)

    res = await bt.do_single_breakthrough(UID, d)

    assert res["message"] == bt.STALE_MESSAGE
    p = await _row(db)
    assert (p.realm, p.cultivation) == ("炼气期1层", 180)


async def test_境界变了而修为恰好没变_同样算陈旧快照(db, monkeypatch):
    """CAS 条件是「境界 + 修为」两个一起：只比修为，会被『别处刚好把境界改了、修为没动』放过。"""
    await _add_player(db, realm="炼气期1层", cultivation=100)
    d = await _player_dict(db)
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        (await s.get(D.Player, UID)).realm = "炼气期5层"
        await s.commit()
    _force_roll(monkeypatch, True)

    res = await bt.do_single_breakthrough(UID, d)

    assert res["message"] == bt.STALE_MESSAGE
    assert (await _row(db)).realm == "炼气期5层"


# --- 筑基 / 凝丹 / 化婴：吃丹突破 ----------------------------------------------

# (处理函数, 丹药, 目标境界, 起始境界)
PILL_BREAKTHROUGHS = [
    pytest.param(bt.handle_zhuji_breakthrough, "筑基丹", "筑基期1层", "炼气期10层", id="筑基"),
    pytest.param(bt.handle_ningdan_breakthrough, "凝丹丹", "结丹期初期", "筑基期10层", id="凝丹"),
    pytest.param(bt.handle_huaying_breakthrough, "化婴丹", "元婴期初期", "结丹期后期", id="化婴"),
]


def _force_fail_outcome(monkeypatch, outcome):
    monkeypatch.setattr(bt, "roll_failure_outcome", lambda realm: outcome)


@pytest.mark.parametrize("handler,pill,target,start", PILL_BREAKTHROUGHS)
async def test_要丹药却没有丹药_直接拒绝_什么都不变(db, handler, pill, target, start):
    await _add_player(db, realm=start, cultivation=cultivation_needed(start), lifespan=100)

    res = await handler(UID, True)

    assert res == {"success": False, "message": f"背包中无{pill}"}
    p = await _row(db)
    assert (p.realm, p.cultivation, p.lifespan) == (start, cultivation_needed(start), 100)


@pytest.mark.parametrize("handler,pill,target,start", PILL_BREAKTHROUGHS)
async def test_角色不存在(db, handler, pill, target, start):
    assert await handler("nobody", False) == {"success": False, "message": "角色不存在"}


@pytest.mark.parametrize("handler,pill,target,start", PILL_BREAKTHROUGHS)
async def test_境界不对_拒绝且不吞丹药(db, handler, pill, target, start):
    """过期的面板：已经突破过了还点旧按钮，不能在新境界上再来一次、更不能白吞一颗丹。"""
    await _add_player(db, realm="炼气期3层", cultivation=10_000)
    await db["inventory"].add_item(UID, pill, 1)

    res = await handler(UID, True)

    assert res["success"] is False and "无需此关" in res["message"]
    assert await _pill_qty(db, pill) == 1
    assert (await _row(db)).realm == "炼气期3层"


@pytest.mark.parametrize("handler,pill,target,start", PILL_BREAKTHROUGHS)
async def test_修为未圆满_拒绝且不吞丹药(db, handler, pill, target, start):
    """过期的面板：上次失败把修为减半了，再点按钮不能不够格就往下冲。"""
    await _add_player(db, realm=start, cultivation=cultivation_needed(start) - 1)
    await db["inventory"].add_item(UID, pill, 1)

    res = await handler(UID, True)

    assert res == {"success": False, "message": "修为未圆满"}
    assert await _pill_qty(db, pill) == 1


@pytest.mark.parametrize("handler,pill,target,start", PILL_BREAKTHROUGHS)
async def test_不吃丹成功_晋级且不动背包(db, monkeypatch, handler, pill, target, start):
    needed = cultivation_needed(start)
    await _add_player(db, realm=start, cultivation=needed + 7, lifespan=100, lifespan_max=100)
    await db["inventory"].add_item(UID, pill, 2)
    _force_random(monkeypatch, 0.0)

    res = await handler(UID, False)

    assert res["success"] and res["breakthrough"]
    assert (res["old_realm"], res["new_realm"]) == (start, target)
    p = await _row(db)
    assert p.realm == target
    assert p.cultivation == 7                                # 溢出结转
    assert p.lifespan_max == lifespan_max_for_realm(target)
    assert p.lifespan == 100 + max(0, p.lifespan_max - 100)
    assert await _pill_qty(db, pill) == 2                    # 没吃丹就不扣


@pytest.mark.parametrize("handler,pill,target,start", PILL_BREAKTHROUGHS)
async def test_吃丹成功_扣一颗丹药(db, monkeypatch, handler, pill, target, start):
    await _add_player(db, realm=start, cultivation=cultivation_needed(start))
    await db["inventory"].add_item(UID, pill, 2)
    _force_random(monkeypatch, 0.0)

    res = await handler(UID, True)

    assert res["breakthrough"] is True
    assert await _pill_qty(db, pill) == 1


@pytest.mark.parametrize("handler,pill,target,start", PILL_BREAKTHROUGHS)
@pytest.mark.parametrize("outcome", [FAIL_LIGHT, FAIL_HEAVY, FAIL_DEVIATE])
async def test_吃丹失败_丹药照样消耗_惩罚与普通突破一致(
        db, monkeypatch, handler, pill, target, start, outcome):
    needed = cultivation_needed(start)
    await _add_player(db, realm=start, cultivation=needed + 20, lifespan=120)
    await db["inventory"].add_item(UID, pill, 1)
    _force_random(monkeypatch, 0.999)          # 成功率封顶 95%，0.999*100 必然落空
    _force_fail_outcome(monkeypatch, outcome)

    res = await handler(UID, True)

    exp_cult, exp_life, exp_msg = apply_failure(needed + 20, 120, outcome)
    assert res["success"] and not res["breakthrough"] and not res["is_dead"]
    assert res["fail_msg"] == exp_msg
    p = await _row(db)
    assert p.realm == start
    assert (p.cultivation, p.lifespan) == (exp_cult, exp_life)
    assert await _pill_qty(db, pill) == 0                    # 吃了就是吃了


@pytest.mark.parametrize("handler,pill,target,start", PILL_BREAKTHROUGHS)
async def test_吃丹失败不再强行走火入魔(db, monkeypatch, handler, pill, target, start):
    """B4 回归：失败类型不能再靠『第二次 roll_breakthrough 并丢掉成败』来取。
    那样第二次掷出成功时 outcome=None，被当作最重的走火入魔 —— 成功率越高越容易走火。

    这里让 roll_breakthrough 一调用就炸，证明丹药失败路径根本不再碰它。"""
    def _boom(*a, **k):
        raise AssertionError("丹药失败路径不该再调用 roll_breakthrough")
    monkeypatch.setattr(bt, "roll_breakthrough", _boom)
    monkeypatch.setattr("utils.realms.roll_breakthrough", _boom)
    await _add_player(db, realm=start, cultivation=cultivation_needed(start) + 20, lifespan=120)
    _force_random(monkeypatch, 0.999)
    _force_fail_outcome(monkeypatch, FAIL_LIGHT)

    res = await handler(UID, False)

    assert "走火入魔" not in res["fail_msg"]
    assert (await _row(db)).lifespan == 120                  # 轻伤不损寿元


@pytest.mark.parametrize("handler,pill,target,start", PILL_BREAKTHROUGHS)
async def test_吃丹失败且寿尽_死亡(db, monkeypatch, handler, pill, target, start):
    await _add_player(db, realm=start, cultivation=cultivation_needed(start), lifespan=1)
    _force_random(monkeypatch, 0.999)
    _force_fail_outcome(monkeypatch, FAIL_DEVIATE)

    res = await handler(UID, False)

    assert res["is_dead"] is True and res["saved_by_charm"] is False
    p = await _row(db)
    assert p.lifespan == 0 and p.is_dead is True


@pytest.mark.parametrize("handler,pill,target,start", PILL_BREAKTHROUGHS)
async def test_吃丹失败且寿尽_狐符续命(db, monkeypatch, handler, pill, target, start):
    buffs = json.dumps({"fox_charm": {"value": 1}})
    await _add_player(db, realm=start, cultivation=cultivation_needed(start), lifespan=1, active_buffs=buffs)
    _force_random(monkeypatch, 0.999)
    _force_fail_outcome(monkeypatch, FAIL_DEVIATE)

    res = await handler(UID, False)

    assert res["is_dead"] is False and res["saved_by_charm"] is True and res["lifespan"] == 1
    p = await _row(db)
    assert p.is_dead is False and p.lifespan == 1
    assert "fox_charm" not in json.loads(p.active_buffs)


@pytest.mark.parametrize("handler,pill,target,start", PILL_BREAKTHROUGHS)
async def test_丹药被别的点击抢走后_直接拒绝_不享受丹药加成(
        db, monkeypatch, handler, pill, target, start):
    """B2 回归：曾经先 has_item 再另开事务 remove_item 且忽略返回值 ——
    两次点击都通过判断、背包只有一颗时，扣不掉的那次照样按『吃了丹』的成功率判。

    用打桩把竞态窗口固定住：即便 has_item 说"有"，背包里实际没有。
    骰子给 0.0（任何成功率都会成功）：若还会往下走，就会白白晋级 —— 必须在掷骰之前拒绝。
    """
    from utils import inventory
    await _add_player(db, realm=start, cultivation=cultivation_needed(start))

    async def _still_looks_available(*_a, **_k):
        return True
    monkeypatch.setattr(inventory, "has_item", _still_looks_available)
    _force_random(monkeypatch, 0.0)

    res = await handler(UID, True)

    assert await _pill_qty(db, pill) == 0
    assert res == {"success": False, "message": f"背包中无{pill}"}
    assert (await _row(db)).realm == start                 # 没有靠一颗不存在的丹晋级


@pytest.mark.parametrize("handler,pill,target,start", PILL_BREAKTHROUGHS)
async def test_丹药是掷骰之前扣的(db, monkeypatch, handler, pill, target, start):
    """CONVENTIONS #7：扣资源必须在产生随机结果之前。"""
    await _add_player(db, realm=start, cultivation=cultivation_needed(start))
    await db["inventory"].add_item(UID, pill, 1)
    order = []
    real_consume = bt.consume_item

    async def _spy(*a, **k):
        order.append("扣丹")
        return await real_consume(*a, **k)

    def _roll():
        order.append("掷骰")
        return 0.0

    monkeypatch.setattr(bt, "consume_item", _spy)
    monkeypatch.setattr(random, "random", _roll)

    await handler(UID, True)

    assert order == ["扣丹", "掷骰"]


@pytest.mark.parametrize("handler,pill,target,start", PILL_BREAKTHROUGHS)
async def test_落库时发现状态已变_丹药一并退回(db, monkeypatch, handler, pill, target, start):
    """扣丹和落库同一事务：连点时后到的那次落库被 CAS 挡下，丹药不能白吞。

    竞态窗口：本次读完玩家、扣丹之前，另一次点击已经把修为改了。"""
    await _add_player(db, realm=start, cultivation=cultivation_needed(start))
    await db["inventory"].add_item(UID, pill, 1)
    D = db["db_async"]
    real_consume = bt.consume_item

    async def _race_then_consume(session, *a, **k):
        async with D.AsyncSessionLocal() as other:               # 另一次点击抢先落了库
            (await other.get(D.Player, UID)).cultivation += 5
            await other.commit()
        return await real_consume(session, *a, **k)

    monkeypatch.setattr(bt, "consume_item", _race_then_consume)
    _force_random(monkeypatch, 0.0)

    res = await handler(UID, True)

    assert res == {"success": False, "message": bt.STALE_MESSAGE}
    assert await _pill_qty(db, pill) == 1                        # 丹药退回
    p = await _row(db)
    assert p.realm == start and p.cultivation == cultivation_needed(start) + 5


# --- 失败类型本身（utils/realms.py）--------------------------------------------

def test_失败类型的权重按境界分档(monkeypatch):
    seen = {}

    def _spy(population, weights):
        seen["weights"] = weights
        return [population[0]]
    monkeypatch.setattr(random, "choices", _spy)

    roll_failure_outcome("炼气期10层")
    assert seen["weights"] == [0.70, 0.25, 0.05]
    roll_failure_outcome("太乙初期")
    assert seen["weights"] == [0.30, 0.50, 0.20]


def test_失败类型的实际分布_走火入魔是少数():
    """B4 的数值依据：低境界走火入魔本该只有 5%，曾被扭曲到 87%~95%。"""
    random.seed(20261007)
    n = 6000
    hits = sum(roll_failure_outcome("炼气期10层") == FAIL_DEVIATE for _ in range(n))
    assert 0.03 < hits / n < 0.08


def test_apply_failure_不再把未知类型当成走火入魔():
    with pytest.raises(ValueError):
        apply_failure(100, 100, None)
    with pytest.raises(ValueError):
        apply_failure(100, 100, "nope")
