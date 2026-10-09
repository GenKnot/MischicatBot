"""锻造（utils/forging.py、utils/views/forging.py）：公式、经验升级、淬炼、面板。基础扣料与考核见 test_forging.py。

B41 —— `attempt_forge` 先占今日次数再校验材料 / 品级：主材不足、辅材不足、品级超限这些被拒的尝试也会白白烧掉一次
  （一天 5 次），而 `test_主材不足直接被拒且不消耗次数` 的名字写的正是相反的意图。现在材料和次数在同一个事务里一起占，
  任一不满足整组回滚。
B42 —— 熟练度 / 经验 / 走火扣寿元都是「读出来 → 改 → 写回」：同时开多炉会丢更新（经验少算、寿元少扣）。改成原子 UPDATE。
B43 —— 炼器入门考核的『通过』永远不会触发：第一炉成功后先走 `add_forging_exp`，它发现 0 级 + 12 经验已够 1 级门槛直接升级，
  随后 `forging_level == 0` 的判断就不成立了；结果玩家看到的是『晋升至 1 品』而不是『通过入门考核』，经验也不归零。
"""

import asyncio

import pytest

from tests.conftest import make_player
from tests.discord_fakes import FakeInteraction
from utils import forging as fm
from utils.equipment import QUALITY_ORDER
from utils.forging import (DAILY_LIMIT, FORGING_EXP_PER_CRAFT, FORGING_EXP_THRESHOLDS, ORE_TIERS, SLOT_MAIN_ORE_QTY,
                           add_forging_exp, attempt_forge, attempt_reforge, calc_forge_success_rate,
                           get_available_qualities, get_forging_level_label, get_forging_mastery,
                           get_max_quality_for_level, increment_forging_mastery, pass_forging_exam, roll_forge_failure)
from utils.views import forging as fv

U = "1001"
ORE, SLOT = "铜矿石", "饰品"
QTY = SLOT_MAIN_ORE_QTY[SLOT]


async def _add(db, uid=U, stones=100_000, ore=99, **kw):
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        p = make_player(D, uid, stones=stones)
        p.name = f"道友{uid}"
        for k, v in kw.items():
            setattr(p, k, v)
        s.add(p)
        if ore:
            s.add(D.Inventory(discord_id=uid, item_id=ORE, quantity=ore))
        await s.commit()


async def row(db, uid=U):
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        return await s.get(D.Player, uid)


async def inv(db, uid=U):
    return await db["inventory"].get_inventory(uid)


def win(monkeypatch):
    monkeypatch.setattr(fm.random, "randint", lambda a, b: 1)


def lose(monkeypatch, failure=("走火", 3)):
    monkeypatch.setattr(fm.random, "randint", lambda a, b: 100)
    monkeypatch.setattr(fm, "roll_forge_failure", lambda: failure)


async def forge(db, level=1, quality="普通", wood=None, herb=None, ore=ORE, slot=SLOT, bone=10):
    return await attempt_forge(U, slot, ore, quality, wood, herb, await inv(db), bone, level)


# --- 纯公式 -------------------------------------------------------------------

def test_熟练度阶段():
    assert get_forging_mastery(0) == ("生疏", 0) and get_forging_mastery(9) == ("生疏", 0)
    assert get_forging_mastery(10) == ("熟悉", 5) and get_forging_mastery(29) == ("熟悉", 5)
    assert get_forging_mastery(30) == ("精通", 12) and get_forging_mastery(99) == ("精通", 12)
    assert get_forging_mastery(100) == ("炉火纯青", 20) and get_forging_mastery(10**6) == ("炉火纯青", 20)


def test_品级标签():
    assert get_forging_level_label(0) == "未入门" and get_forging_level_label(3) == "3品炼器师"


def test_成功率公式与夹取():
    # 基础 85 - 15*品质序号，+5*(等级-1)，+min(根骨//3, 10)，+熟练度
    assert calc_forge_success_rate(1, "普通", 0, 0) == 85
    assert calc_forge_success_rate(3, "普通", 0, 0) == 95                       # 夹到 95
    assert calc_forge_success_rate(1, "精良", 0, 0) == 70
    assert calc_forge_success_rate(1, "普通", 9, 0) == 88 and calc_forge_success_rate(1, "普通", 30, 0) == 95
    assert calc_forge_success_rate(1, "稀有", 0, 0) == 55 and calc_forge_success_rate(1, "稀有", 0, 100) == 75
    assert calc_forge_success_rate(1, "传说", 0, 0) == 25
    assert calc_forge_success_rate(0, "传说", 0, 0) == 20 and calc_forge_success_rate(-50, "传说", 0, 0) == 5


def test_可锻造品质随等级():
    assert get_max_quality_for_level(1) == "普通" and get_max_quality_for_level(9) == "传说"
    assert get_max_quality_for_level(99) == "普通"
    assert get_available_qualities(0) == ["普通"] and get_available_qualities(1) == ["普通"]
    assert get_available_qualities(5) == QUALITY_ORDER[:3] and get_available_qualities(9) == QUALITY_ORDER


def test_走火概率与寿元(monkeypatch):
    monkeypatch.setattr(fm.random, "random", lambda: 0.79)
    assert roll_forge_failure() == ("普通失败", 0)
    monkeypatch.setattr(fm.random, "random", lambda: 0.8)
    monkeypatch.setattr(fm.random, "randint", lambda a, b: b)
    assert roll_forge_failure() == ("走火", 5)


def test_经验门槛表_长度足够_单调():
    assert len(FORGING_EXP_THRESHOLDS) >= 10 and FORGING_EXP_THRESHOLDS == sorted(FORGING_EXP_THRESHOLDS)


# --- 经验与熟练度 -------------------------------------------------------------

async def test_经验_没有玩家(db):
    assert await add_forging_exp("nope", 10) == (0, 0, False)
    assert await increment_forging_mastery("nope") == 0


async def test_经验_达到门槛才升级(db):
    await _add(db, forging_level=1, forging_exp=0)
    lvl, exp, up = await add_forging_exp(U, FORGING_EXP_THRESHOLDS[2] - 1)
    assert (lvl, up) == (1, False)
    lvl, exp, up = await add_forging_exp(U, 1)
    assert (lvl, exp, up) == (2, FORGING_EXP_THRESHOLDS[2], True)


async def test_经验_9级封顶(db):
    await _add(db, forging_level=9, forging_exp=3200)
    lvl, exp, up = await add_forging_exp(U, 10_000)
    assert (lvl, up) == (9, False) and exp == 13_200


async def test_经验_一次只升一级(db):
    await _add(db, forging_level=1, forging_exp=0)
    lvl, _, up = await add_forging_exp(U, 10_000)
    assert lvl == 2 and up


async def test_B42_并发加经验不丢更新(db):
    await _add(db, forging_level=1, forging_exp=0)
    await asyncio.gather(*[add_forging_exp(U, 5) for _ in range(12)])
    assert (await row(db)).forging_exp == 60


async def test_B42_并发加熟练度不丢更新(db):
    await _add(db)
    await asyncio.gather(*[increment_forging_mastery(U) for _ in range(15)])
    assert (await row(db)).forging_mastery_count == 15


async def test_B42_并发走火扣寿元不丢更新(db, monkeypatch):
    await _add(db, lifespan=100, ore=999)
    lose(monkeypatch, ("走火", 2))
    inventory = await inv(db)
    D = db["db_async"]
    from sqlalchemy import update
    async with D.AsyncSessionLocal() as s:
        await s.execute(update(D.Player).values(forging_level=1))
        await s.commit()
    # 绕开每日 5 次：直接并发调内部失败结算路径需要真实锻造，这里把上限抬高
    monkeypatch.setattr(fm, "DAILY_LIMIT", 50)
    await asyncio.gather(*[attempt_forge(U, SLOT, ORE, "普通", None, None, inventory, 10, 1) for _ in range(8)])
    assert (await row(db)).lifespan == 100 - 2 * 8


async def test_考核通过函数(db):
    await _add(db, forging_level=0, forging_exp=77)
    assert await pass_forging_exam(U) is True
    p = await row(db)
    assert p.forging_level == 1 and p.forging_exp == 0
    assert await pass_forging_exam(U) is False and await pass_forging_exam("nope") is False


# --- 锻造：被拒的尝试不烧次数（B41） ------------------------------------------

async def daily_used(db):
    return (await row(db)).forging_daily_count or 0


async def test_B41_主材不足_不烧次数(db):
    await _add(db, ore=1)
    r = await forge(db)
    assert "主材不足" in r["reason"] and await daily_used(db) == 0


async def test_B41_辅材不足_不烧次数_不扣主材(db):
    await _add(db)
    inventory = await inv(db)
    inventory["松木"] = 1                                                        # 谎报库存
    r = await attempt_forge(U, SLOT, ORE, "普通", "松木", None, inventory, 10, 1)
    assert not r["ok"] and await daily_used(db) == 0 and (await inv(db))[ORE] == 99


async def test_B41_品级超限_不烧次数(db):
    await _add(db)
    r = await forge(db, level=1, quality="精良")
    assert "炼器品级不足" in r["reason"] and await daily_used(db) == 0 and (await inv(db))[ORE] == 99


async def test_B41_背包实际不足时整笔回滚_次数也退回(db):
    """调用方给的库存快照过期（实际已被别处用掉），事务里扣料失败 → 次数一并退回。"""
    await _add(db, ore=1)
    r = await attempt_forge(U, SLOT, ORE, "普通", None, None, {ORE: 99}, 10, 1)
    assert not r["ok"] and "不足" in r["reason"] and await daily_used(db) == 0 and (await inv(db))[ORE] == 1


async def test_正常开炉才烧次数(db, monkeypatch):
    await _add(db)
    win(monkeypatch)
    r = await forge(db)
    assert r["ok"] and r["daily_count"] == 1 and await daily_used(db) == 1


async def test_次数用尽后再开炉被拒_材料不动(db, monkeypatch):
    await _add(db)
    win(monkeypatch)
    for _ in range(DAILY_LIMIT):
        assert (await forge(db))["ok"]
    left = (await inv(db))[ORE]
    r = await forge(db)
    assert "上限" in r["reason"] and (await inv(db))[ORE] == left


async def test_并发开炉不超次数不超扣(db, monkeypatch):
    await _add(db)
    win(monkeypatch)
    inventory = await inv(db)
    rs = await asyncio.gather(*[attempt_forge(U, SLOT, ORE, "普通", None, None, inventory, 10, 1)
                                for _ in range(DAILY_LIMIT + 4)])
    ok = [r for r in rs if r["ok"]]
    assert len(ok) == DAILY_LIMIT and (await inv(db))[ORE] == 99 - QTY * DAILY_LIMIT
    assert len(await db["equipment_db"].get_equipment_list(U)) == DAILY_LIMIT


# --- 锻造：结果 ---------------------------------------------------------------

async def test_成功_熟练度经验升级字段(db, monkeypatch):
    await _add(db, forging_level=1, forging_exp=FORGING_EXP_THRESHOLDS[2] - 5, forging_mastery_count=9)
    win(monkeypatch)
    r = await forge(db)
    assert r["success"] and r["mastery_count"] == 10 and r["mastery_label"] == "熟悉"
    assert r["leveled_up"] and r["forging_level"] == 2 and r["forging_exp"] == FORGING_EXP_THRESHOLDS[2] - 5 + FORGING_EXP_PER_CRAFT
    assert r["consumed"] == {ORE: QTY} and r["exam_passed"] is False


async def test_B43_考核第一炉成功_通过入门考核(db, monkeypatch):
    await _add(db, forging_level=0, forging_exp=0)
    win(monkeypatch)
    r = await forge(db, level=0)
    assert r["success"] and r["exam_passed"] is True and r["forging_level"] == 1 and r["leveled_up"]
    p = await row(db)
    assert p.forging_level == 1 and p.forging_exp == 0                          # 考核通过：经验归零重新计


async def test_考核期间失败_不通过(db, monkeypatch):
    await _add(db, forging_level=0)
    lose(monkeypatch, ("普通失败", 0))
    r = await forge(db, level=0)
    assert r["success"] is False and (await row(db)).forging_level == 0


async def test_失败_不产出_走火扣寿元_不低于1(db, monkeypatch):
    await _add(db, lifespan=2)
    lose(monkeypatch, ("走火", 5))
    r = await forge(db)
    assert r["success"] is False and r["consequence"] == "走火" and r["lifespan_loss"] == 5
    assert (await row(db)).lifespan == 1 and await db["equipment_db"].get_equipment_list(U) == []


async def test_失败_普通失败不扣寿元(db, monkeypatch):
    await _add(db, lifespan=50)
    lose(monkeypatch, ("普通失败", 0))
    await forge(db)
    assert (await row(db)).lifespan == 50


async def test_辅材偏向传给装备生成(db, monkeypatch):
    await _add(db)
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        s.add(D.Inventory(discord_id=U, item_id="铁桦木", quantity=1))
        s.add(D.Inventory(discord_id=U, item_id="灵芝草", quantity=1))
        await s.commit()
    win(monkeypatch)
    seen = {}
    real = fm.generate_equipment

    def spy(**kw):
        seen.update(kw)
        return real(**kw)
    monkeypatch.setattr(fm, "generate_equipment", spy)
    r = await forge(db, wood="铁桦木", herb="灵芝草", ore="铜矿石")
    assert r["success"] and seen["stat_bias"] == ["physique", "bone", "comprehension", "soul"]
    assert seen["tier"] == 0 and seen["quality"] == "普通" and seen["slot"] == SLOT
    assert r["consumed"] == {ORE: QTY, "铁桦木": 1, "灵芝草": 1}


async def test_没有辅材时不传偏向(db, monkeypatch):
    await _add(db)
    win(monkeypatch)
    seen = {}
    real = fm.generate_equipment
    monkeypatch.setattr(fm, "generate_equipment", lambda **kw: (seen.update(kw), real(**kw))[1])
    await forge(db)
    assert seen["stat_bias"] is None


@pytest.mark.parametrize("slot,qty", [("武器", 3), ("防具", 3), ("饰品", 2)])
async def test_各部位主材用量(db, monkeypatch, slot, qty):
    await _add(db)
    win(monkeypatch)
    await forge(db, slot=slot)
    assert (await inv(db))[ORE] == 99 - qty


async def test_矿石品级决定装备境界(db, monkeypatch):
    await _add(db, ore=0)
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        s.add(D.Inventory(discord_id=U, item_id="灵铁矿", quantity=9))
        await s.commit()
    win(monkeypatch)
    r = await forge(db, ore="灵铁矿")
    assert r["equipment"]["tier"] == 3


# --- 淬炼 ---------------------------------------------------------------------

async def give_eq(db, quality="普通", equip_id="eq000001", uid=U):
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        s.add(D.Equipment(equip_id=equip_id, discord_id=uid, name="旧剑", slot="武器", quality=quality, tier=1,
                          tier_req=0, stats='{"attack": 1}', flavor="旧", equipped=False))
        await s.commit()


async def reforge(db, quality="普通", ore=None, stones=0):
    ore = ore or ORE_TIERS[QUALITY_ORDER.index(quality)]
    return await attempt_reforge(U, "eq000001", ore, await inv(db), stones)


async def test_淬炼_成功_扣矿石和灵石_换词缀(db):
    await _add(db, ore=0, stones=1000)
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        s.add(D.Inventory(discord_id=U, item_id="铜矿石", quantity=5))
        await s.commit()
    await give_eq(db)
    r = await reforge(db)
    assert r["ok"] and r["ore_qty"] == 2 and r["stone_cost"] == 200 and r["old_name"] == "旧剑"
    assert (await inv(db))["铜矿石"] == 3 and (await row(db)).spirit_stones == 800
    [e] = await db["equipment_db"].get_equipment_list(U)
    assert e["name"] == r["new_name"] and e["stats"] == r["new_stats"] and e["quality"] == "普通" and e["tier"] == 1


@pytest.mark.parametrize("quality,mult", [("普通", 1), ("精良", 2), ("稀有", 4), ("史诗", 8), ("传说", 15)])
async def test_淬炼_灵石费用与矿石随品质(db, quality, mult):
    await _add(db, ore=0, stones=100_000)
    ore = ORE_TIERS[QUALITY_ORDER.index(quality)]
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        s.add(D.Inventory(discord_id=U, item_id=ore, quantity=2))
        await s.commit()
    await give_eq(db, quality)
    r = await reforge(db, quality)
    assert r["ok"] and r["stone_cost"] == 200 * mult and r["ore_used"] == ore
    assert (await row(db)).spirit_stones == 100_000 - 200 * mult


async def test_淬炼_拒绝各种情况(db):
    await _add(db, stones=1000)
    assert (await attempt_reforge(U, "nope", ORE, {}, 0))["reason"] == "装备不存在或不属于你。"
    await give_eq(db, "稀有")
    r = await attempt_reforge(U, "eq000001", ORE, {ORE: 9}, 1000)
    assert "需要「精铁矿」" in r["reason"]
    r = await attempt_reforge(U, "eq000001", "精铁矿", {"精铁矿": 1}, 1000)
    assert "不足" in r["reason"]


async def test_淬炼_灵石不足_矿石也不扣(db):
    await _add(db, ore=0, stones=10)
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        s.add(D.Inventory(discord_id=U, item_id="铜矿石", quantity=5))
        await s.commit()
    await give_eq(db)
    r = await reforge(db)
    assert "灵石不足" in r["reason"] and (await inv(db))["铜矿石"] == 5 and (await row(db)).spirit_stones == 10


async def test_淬炼_背包实际矿石不足_回滚(db):
    await _add(db, ore=0, stones=1000)
    await give_eq(db)
    r = await attempt_reforge(U, "eq000001", "铜矿石", {"铜矿石": 9}, 1000)
    assert not r["ok"] and (await row(db)).spirit_stones == 1000


async def test_淬炼_不能淬别人的装备(db):
    await _add(db, stones=1000)
    await _add(db, "1002", ore=0)
    await give_eq(db, uid="1002")
    r = await reforge(db)
    assert "装备不存在" in r["reason"]


# --- 面板 ---------------------------------------------------------------------

def inter(uid=U):
    i = FakeInteraction(uid)
    i.message = __import__("types").SimpleNamespace(id=1)           # followup.edit_message 要用到原消息 id
    return i


async def pdict(uid=U):
    return await fv._get_player(uid)


def test_主界面文案_未入门与满级():
    e = fv._forging_main_embed({"forging_level": 0, "forging_mastery_count": 3, "forging_daily_count": 2,
                                "forging_daily_reset": __import__("time").time()})
    f = {x.name: x.value for x in e.fields}
    assert "未入门" in f["炼器师品级"] and "炼器经验" not in f and "可锻造上限" not in f and f["今日锻造"] == f"2 / {DAILY_LIMIT}"
    import time
    e = fv._forging_main_embed({"forging_level": 9, "forging_exp": 4000, "forging_daily_reset": time.time()})
    f = {x.name: x.value for x in e.fields}
    assert f["炼器经验"] == "4000" and "传说" in f["可锻造上限"]
    e = fv._forging_main_embed({"forging_level": 2, "forging_exp": 100, "forging_daily_count": 5, "forging_daily_reset": 0})
    f = {x.name: x.value for x in e.fields}
    assert f["炼器经验"] == f"100 / {FORGING_EXP_THRESHOLDS[3]}" and f["今日锻造"] == f"0 / {DAILY_LIMIT}"


async def test_主界面_按钮随等级禁用(db):
    await _add(db, forging_level=0)
    v = fv.ForgingMainView(inter().user, await pdict(), None)
    assert v.reforge_btn.disabled and not v.exam_btn.disabled
    v = fv.ForgingMainView(inter().user, {"forging_level": 2}, None)
    assert v.exam_btn.disabled and not v.reforge_btn.disabled


async def test_考核按钮_各分支(db):
    await _add(db, forging_level=0, current_city="铸剑城")
    v = fv.ForgingMainView(inter().user, await pdict(), None)
    i = inter()
    await v.exam_btn.callback(i)
    assert "炼器入门考核" in i.last.embed.title and (await row(db)).spirit_stones == 100_000 - fm.EXAM_COST
    i = inter()
    await v.exam_btn.callback(i)
    assert "已缴过考核费" in i.last and i.last.ephemeral

    await _add(db, "1002", forging_level=0, current_city="灵虚城")
    i = inter("1002")
    await v.exam_btn.callback(i)
    assert "铸造坊城市" in i.last and (await row(db, "1002")).spirit_stones == 100_000

    await _add(db, "1003", forging_level=2, current_city="铸剑城")
    i = inter("1003")
    await v.exam_btn.callback(i)
    assert "已经是炼器师" in i.last

    await _add(db, "1004", forging_level=0, current_city="铸剑城", stones=10)
    i = inter("1004")
    await v.exam_btn.callback(i)
    assert "灵石不足" in i.last and i.last.ephemeral


async def test_锻造流程_逐级导航到开炉(db, monkeypatch):
    await _add(db, forging_level=1)
    win(monkeypatch)
    main = fv.ForgingMainView(inter().user, await pdict(), None)
    i = inter()
    await main.forge_btn.callback(i)
    slot_view = i.last.view
    assert isinstance(slot_view, fv.ForgeSlotSelectView)

    i = inter()
    await slot_view.accessory_btn.callback(i)
    ore_view = i.last.view
    assert isinstance(ore_view, fv.ForgeOreSelectView) and "铜矿石" in i.last.embed.fields[0].value
    btn = next(b for b in ore_view.children if getattr(b, "ore", None) == ORE)
    assert not btn.disabled and next(b for b in ore_view.children if getattr(b, "ore", None) == "陨铁矿").disabled

    i = inter()
    await btn.callback(i)
    q_view = i.last.view
    assert isinstance(q_view, fv.ForgeQualitySelectView) and "普通" in i.last.embed.fields[0].value
    assert len([c for c in q_view.children if isinstance(c, fv.QualityButton)]) == 1

    i = inter()
    await next(c for c in q_view.children if isinstance(c, fv.QualityButton)).callback(i)
    aux_view = i.last.view
    assert isinstance(aux_view, fv.ForgeAuxSelectView) and "铜矿石" in i.last.embed.description

    i = inter()
    await next(c for c in aux_view.children if isinstance(c, fv.ForgeConfirmButton)).callback(i)
    msg = i.edited[-1]
    assert "锻造成功" in msg.embed.title and isinstance(msg.view, fv.ForgingMainView)
    assert (await inv(db))[ORE] == 99 - QTY


async def test_锻造流程_各部位按钮与返回(db):
    await _add(db, forging_level=1)
    v = fv.ForgeSlotSelectView(inter().user, await pdict(), await inv(db), None)
    for btn, slot in ((v.weapon_btn, "武器"), (v.armor_btn, "防具"), (v.accessory_btn, "饰品")):
        i = inter()
        await btn.callback(i)
        assert i.last.view.slot == slot
    i = inter()
    await v.back_btn.callback(i)
    assert isinstance(i.last.view, fv.ForgingMainView)

    ov = fv.ForgeOreSelectView(inter().user, await pdict(), await inv(db), "武器", None)
    i = inter()
    await next(c for c in ov.children if isinstance(c, fv.BackToSlotButton)).callback(i)
    assert isinstance(i.last.view, fv.ForgeSlotSelectView)

    qv = fv.ForgeQualitySelectView(inter().user, await pdict(), await inv(db), "武器", ORE, None)
    i = inter()
    await next(c for c in qv.children if isinstance(c, fv.BackToOreButton)).callback(i)
    assert isinstance(i.last.view, fv.ForgeOreSelectView)

    av = fv.ForgeAuxSelectView(inter().user, await pdict(), await inv(db), "武器", ORE, "普通", cog=None)
    i = inter()
    await next(c for c in av.children if isinstance(c, fv.BackToQualityButton)).callback(i)
    assert isinstance(i.last.view, fv.ForgeQualitySelectView)


async def test_辅材下拉_只列持有的_选择与取消(db):
    await _add(db, forging_level=1)
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        s.add(D.Inventory(discord_id=U, item_id="铁桦木", quantity=1))
        await s.commit()
    av = fv.ForgeAuxSelectView(inter().user, await pdict(), await inv(db), "武器", ORE, "普通", cog=None)
    selects = [c for c in av.children if isinstance(c, fv.AuxSelect)]
    assert [s.aux_type for s in selects] == ["wood"]
    assert [o.value for o in selects[0].options] == ["none_wood", "铁桦木"]
    sel = selects[0]
    sel._values = ["铁桦木"]
    i = inter()
    await sel.callback(i)
    assert av.aux_wood == "铁桦木" and i.response.deferred
    sel._values = ["none_wood"]
    await sel.callback(inter())
    assert av.aux_wood is None
    herb = fv.AuxSelect("herb", "x", [])
    herb._view = av
    herb._values = ["灵芝草"]
    await herb.callback(inter())
    assert av.aux_herb == "灵芝草"
    herb._values = ["none_herb"]
    await herb.callback(inter())
    assert av.aux_herb is None


async def test_开炉按钮_被拒时转述原因(db):
    await _add(db, forging_level=1, ore=1)
    av = fv.ForgeAuxSelectView(inter().user, await pdict(), {ORE: 99}, "饰品", ORE, "普通", cog=None)
    i = inter()
    await next(c for c in av.children if isinstance(c, fv.ForgeConfirmButton)).callback(i)
    assert i.last.ephemeral and "不足" in i.last


def test_锻造结果卡片():
    ok = fv._forge_result_embed({"success": True, "equipment": {"name": "剑", "slot": "武器", "quality": "普通", "tier": 0,
                                                                "tier_req": 0, "stats": {"attack": 1}, "flavor": "x"},
                                 "consumed": {ORE: 2}, "success_rate": 85, "mastery_label": "生疏", "mastery_count": 1,
                                 "leveled_up": True, "forging_level": 2}, SLOT, ORE, "普通")
    assert "锻造成功" in ok.title and any("晋升至 **2品**" in f.value for f in ok.fields)
    exam = fv._forge_result_embed({"success": True, "equipment": {"name": "剑", "slot": "武器", "quality": "普通", "tier": 0,
                                                                  "tier_req": 0, "stats": {}, "flavor": ""},
                                   "consumed": {ORE: 2}, "success_rate": 85, "mastery_label": "生疏", "mastery_count": 1,
                                   "leveled_up": True, "exam_passed": True, "forging_level": 1}, SLOT, ORE, "普通")
    assert any("通过炼器入门考核" in f.value for f in exam.fields)
    bad = fv._forge_result_embed({"success": False, "consequence": "走火", "consumed": {ORE: 2}, "success_rate": 85,
                                  "lifespan_loss": 3}, SLOT, ORE, "普通")
    assert "锻造失败 · 走火" in bad.title and any("损失 **3 年**" in f.value for f in bad.fields)
    plain = fv._forge_result_embed({"success": False, "consumed": {ORE: 2}, "success_rate": 85}, SLOT, ORE, "普通")
    assert "普通失败" in plain.title and not any(f.name == "⚠️ 走火" for f in plain.fields)


async def test_淬炼面板(db):
    await _add(db, forging_level=2, ore=0, stones=5000)
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        s.add(D.Inventory(discord_id=U, item_id="铜矿石", quantity=4))
        await s.commit()
    main = fv.ForgingMainView(inter().user, await pdict(), None)
    i = inter()
    await main.reforge_btn.callback(i)
    assert "没有任何装备" in i.last and i.last.ephemeral

    await give_eq(db)
    i = inter()
    await main.reforge_btn.callback(i)
    view = i.last.view
    assert isinstance(view, fv.ReforgeSelectView) and "eq000001" in i.last.embed.fields[0].value

    sel = next(c for c in view.children if isinstance(c, fv.ReforgeEquipSelect))
    sel._values = ["eq000001"]
    i = inter()
    await sel.callback(i)
    assert "淬炼完成" in i.edited[-1].embed.title and isinstance(i.edited[-1].view, fv.ForgingMainView)
    assert (await row(db)).spirit_stones == 4800

    sel._values = ["nope"]
    i = inter()
    await sel.callback(i)
    assert "装备不存在" in i.last

    await db["inventory"].remove_item(U, "铜矿石", 2)
    sel._values = ["eq000001"]
    i = inter()
    await sel.callback(i)
    assert "不足" in i.last and i.last.ephemeral

    i = inter()
    await next(c for c in view.children if isinstance(c, fv.BackFromReforgeButton)).callback(i)
    assert isinstance(i.last.view, fv.ForgingMainView)


async def test_主界面返回技艺(db):
    await _add(db)
    v = fv.ForgingMainView(inter().user, await pdict(), None)
    i = inter()
    await v.back_btn.callback(i)
    assert i.last.view is not None


def test_成功率_根骨加成封顶10():
    assert calc_forge_success_rate(1, "稀有", 30, 0) == 55 + 10
    assert calc_forge_success_rate(1, "稀有", 60, 0) == 55 + 10          # 超过 30 根骨不再加


async def test_B42_同时跨过升级门槛只升一级(db):
    await _add(db, forging_level=1, forging_exp=FORGING_EXP_THRESHOLDS[2] - 1)
    results = await asyncio.gather(*[add_forging_exp(U, 12) for _ in range(6)])
    p = await row(db)
    assert p.forging_level == 2 and p.forging_exp == FORGING_EXP_THRESHOLDS[2] - 1 + 72
    assert len([r for r in results if r[2]]) == 1


async def test_B41_调用方库存里就没有辅材_直接拒_不烧次数(db):
    await _add(db)
    r = await attempt_forge(U, SLOT, ORE, "普通", "松木", None, {ORE: 99}, 10, 1)
    assert "辅材不足" in r["reason"] and await daily_used(db) == 0
    r = await attempt_forge(U, SLOT, ORE, "普通", None, "灵芝草", {ORE: 99}, 10, 1)
    assert "辅材不足" in r["reason"] and await daily_used(db) == 0


async def test_淬炼面板_装备列表上限(db):
    await _add(db, forging_level=2)
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        for n in range(30):
            s.add(D.Equipment(equip_id=f"eq{n:06d}", discord_id=U, name=f"剑{n}", slot="武器", quality="普通", tier=1,
                              tier_req=0, stats="{}", flavor="", equipped=False))
        await s.commit()
    equips = await db["equipment_db"].get_equipment_list(U)
    assert len(fv._reforge_select_embed(equips).fields[0].value.splitlines()) == 10
    view = fv.ReforgeSelectView(inter().user, await pdict(), {}, equips, None)
    assert len(next(c for c in view.children if isinstance(c, fv.ReforgeEquipSelect)).options) == 25
