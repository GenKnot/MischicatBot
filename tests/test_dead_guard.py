"""逻辑层的『已坐化』校验（U1 前置）。

此前赌坊 / 轮转 / 打工 / 签到 / 炼丹 / 锻造 / 钱庄 / 交易坊 / 万宝楼出价的逻辑层都不查 `is_dead`，全靠面板入口挡
（B69、B77 补的都是入口）。机器人接入后会直接调逻辑层，绕过所有入口 —— 所以每个会花资源、拿奖励的逻辑函数
自己拒绝已坐化的玩家，并且**什么都不改**（灵石、物品、每日次数、冷却都原样）。

最后一个测试是静态棘轮：下面名单里的函数源码里必须出现 `is_dead` 的校验，新加的同类函数请登记进来。
"""

import ast
from pathlib import Path

import pytest

from tests.conftest import make_player
from utils import alchemy as al
from utils import bank, checkin, forging, gamble, jobs, market, roulette
from utils.events.public import wanbao as wb

ROOT = Path(__file__).resolve().parent.parent
DEAD, ALIVE = "1001", "1002"
RECIPE = {"recipe_id": "t", "pill": "测试丹", "pill_tier": 1, "name": "测试丹方", "alchemy_level_req": 0,
          "base_success_rate": 80, "max_quality": 5, "main_ingredients": [{"item": "灵芝草", "qty": 1}], "aux_groups": []}


async def _add(db, uid, dead=False, stones=100_000, **kw):
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        p = make_player(D, uid, stones=stones)
        p.name = f"道友{uid}"
        p.is_dead, p.lifespan, p.alchemy_level, p.forging_level = dead, 80, 1, 1
        for k, v in kw.items():
            setattr(p, k, v)
        s.add(p)
        await s.commit()


async def snapshot(db, uid):
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        p = await s.get(D.Player, uid)
        row = {c.key: getattr(p, c.key) for c in p.__table__.columns}
    row["_inv"] = await db["inventory"].get_inventory(uid)
    row["_eq"] = [e["equip_id"] for e in await db["equipment_db"].get_equipment_list(uid)]
    return row


async def setup(db):
    await _add(db, DEAD, dead=True, forging_exam_paid=False, forging_level=0)
    await _add(db, ALIVE)
    for uid in (DEAD, ALIVE):
        D = db["db_async"]
        async with D.AsyncSessionLocal() as s:
            for item, qty in (("灵芝草", 20), ("铜矿石", 30), ("铁矿石", 5)):
                s.add(D.Inventory(discord_id=uid, item_id=item, quantity=qty))
            await s.commit()
    # 坐化者名下有一件装备、一笔活期存款、一件在售商品，用来验证『什么都不改』
    await db["equipment_db"].give_equipment(DEAD, {"equip_id": "eq1", "name": "剑", "slot": "武器", "quality": "普通", "tier": 0,
                                                   "tier_req": 0, "stats": {"physique": 1}, "flavor": ""})


def is_refused(result):
    if isinstance(result, tuple):
        ok, msg = result
        return ok is False and "坐化" in msg
    return result["ok"] is False and "坐化" in result["reason"]


CASES = {
    "赌坊": lambda: gamble.do_gamble(DEAD, 100),
    "轮转": lambda: roulette.do_roulette(DEAD),
    "签到": lambda: checkin.do_checkin(DEAD),
    "打工": lambda: jobs.do_job({"discord_id": DEAD}, next(j for j in jobs.JOBS if j["id"] == "sweep")),
    "炼丹": lambda: al.attempt_alchemy(DEAD, RECIPE, 5, 1, [], {"灵芝草": 20}),
    "锻造": lambda: forging.attempt_forge(DEAD, "饰品", "铜矿石", "普通", None, None, {"铜矿石": 30}, 10, 1),
    "淬炼": lambda: forging.attempt_reforge(DEAD, "eq1", "铜矿石", {"铜矿石": 30}, 10_000),
    "炼器考核": lambda: forging.start_forging_exam(DEAD),
    "活期存入": lambda: bank.deposit_demand(DEAD, 100),
    "活期取出": lambda: bank.withdraw_demand(DEAD, 100),
    "定期存入": lambda: bank.deposit_term(DEAD, bank.MIN_DEPOSIT, 10),
    "定期取出": lambda: bank.withdraw_term(DEAD, "不存在"),
    "转账（付款人已坐化）": lambda: bank.transfer(DEAD, ALIVE, 100),
    "转账（收款人已坐化）": lambda: bank.transfer(ALIVE, DEAD, 100),
    "上架物品": lambda: market.list_item(DEAD, "灵芝草", 1, 100),
    "上架装备": lambda: market.list_equipment(DEAD, "eq1", 100),
}


@pytest.mark.parametrize("name", list(CASES))
async def test_已坐化的玩家被逻辑层拒绝_且什么都不改(db, name):
    await setup(db)
    before = {u: await snapshot(db, u) for u in (DEAD, ALIVE)}
    result = await CASES[name]()
    assert is_refused(result), (name, result)
    after = {u: await snapshot(db, u) for u in (DEAD, ALIVE)}
    assert after == before, name


async def test_购买_已坐化的买家被拒(db):
    await setup(db)
    lid = (await market.list_item(ALIVE, "灵芝草", 2, 1000))["listing_id"]
    before = {u: await snapshot(db, u) for u in (DEAD, ALIVE)}
    result = await market.buy_listing(DEAD, lid)
    assert is_refused(result)
    assert {u: await snapshot(db, u) for u in (DEAD, ALIVE)} == before


async def test_万宝楼出价_已坐化的玩家被拒(db):
    await setup(db)
    a = await wb.get_or_create_auction("2026-10-09")
    await wb.start_auction(a["auction_id"])
    before = {u: await snapshot(db, u) for u in (DEAD, ALIVE)}
    result = await wb.place_bid(a["auction_id"], DEAD, 10**9)
    assert is_refused(result)
    assert {u: await snapshot(db, u) for u in (DEAD, ALIVE)} == before


async def test_活着的玩家不受影响(db):
    """防止校验写反：活人照常能做。"""
    await setup(db)
    assert (await gamble.do_gamble(ALIVE, 100))["ok"]
    assert (await roulette.do_roulette(ALIVE))["ok"]
    assert (await checkin.do_checkin(ALIVE))["ok"]
    assert (await bank.deposit_demand(ALIVE, 100))["ok"]
    assert (await market.list_item(ALIVE, "灵芝草", 1, 100))["ok"]


async def test_轮回重生后恢复可用(db):
    await setup(db)
    assert is_refused(await gamble.do_gamble(DEAD, 100))
    D = db["db_async"]
    from sqlalchemy import update
    async with D.AsyncSessionLocal() as s:
        await s.execute(update(D.Player).where(D.Player.discord_id == DEAD).values(is_dead=False))
        await s.commit()
    assert (await gamble.do_gamble(DEAD, 100))["ok"]


async def test_打工_用的是库里的状态而不是调用方传来的旧快照(db):
    """`do_job` 收的是调用方给的 player 字典，可能是旧的：坐化与否以数据库为准。"""
    await setup(db)
    job = next(j for j in jobs.JOBS if j["id"] == "sweep")
    result = await jobs.do_job({"discord_id": DEAD, "is_dead": 0}, job)
    assert is_refused(result)


# --- 静态棘轮 -----------------------------------------------------------------

MUST_CHECK = {
    "utils/gamble.py": ["do_gamble"],
    "utils/roulette.py": ["do_roulette"],
    "utils/checkin.py": ["do_checkin"],
    "utils/jobs.py": ["do_job"],
    "utils/alchemy.py": ["attempt_alchemy"],
    "utils/forging.py": ["attempt_forge", "attempt_reforge", "start_forging_exam"],
    "utils/bank.py": ["deposit_demand", "withdraw_demand", "deposit_term", "withdraw_term", "transfer"],
    "utils/market.py": ["list_item", "list_equipment", "buy_listing"],
    "utils/events/public/wanbao.py": ["place_bid"],
}


def _mentions_dead(path: str, func: str) -> bool:
    """函数体（含它直接调用的本文件私有校验函数）里是否出现了坐化校验。"""
    tree = ast.parse((ROOT / path).read_text(encoding="utf-8"))
    funcs = {n.name: n for n in ast.walk(tree) if isinstance(n, (ast.AsyncFunctionDef, ast.FunctionDef))}

    def mentions(node, seen):
        src = ast.unparse(node)
        if "is_dead" in src or "refuse_if_dead" in src:
            return True
        for sub in ast.walk(node):
            if isinstance(sub, ast.Call):
                name = getattr(sub.func, "id", None) or getattr(sub.func, "attr", None)
                if name in funcs and name not in seen and name.startswith("_"):
                    if mentions(funcs[name], seen | {name}):
                        return True
        return False
    return func in funcs and mentions(funcs[func], {func})


@pytest.mark.parametrize("path,func", [(p, f) for p, fs in MUST_CHECK.items() for f in fs])
def test_静态检查_这些函数里必须有坐化校验(path, func):
    assert _mentions_dead(path, func), f"{path}::{func} 没有 is_dead 校验"
