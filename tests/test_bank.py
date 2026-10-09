"""钱庄逻辑（utils/bank.py）。

B34 —— 钱庄只在 `BANK_CITIES` 里营业（城市菜单进不了别处的钱庄），但存取转账的逻辑层不检查所在城市：
  钱庄面板留在聊天里，人走到别的城市后照样能存、取、转账。
"""

import asyncio
import time

import pytest

from tests.conftest import make_player
from utils import bank
from utils.bank import (BANK_CITIES, MIN_DEPOSIT, TRANSFER_MAX, deposit_demand, deposit_term, get_bank_account,
                        get_term_deposits, transfer, withdraw_demand, withdraw_term)

U = "1001"
YEAR = 7200                      # 一游戏年 = 2 小时 = 7200 秒


async def _add(db, uid=U, stones=100_000, city="灵虚城", **kw):
    D = db["db_async"]
    p = make_player(D, uid, stones=stones)
    p.name = f"道友{uid}"
    p.current_city = city
    for k, v in kw.items():
        setattr(p, k, v)
    async with D.AsyncSessionLocal() as s:
        s.add(p)
        await s.commit()


async def stones(db, uid=U):
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        return (await s.get(D.Player, uid)).spirit_stones


async def _age_account(db, years, uid=U):
    """把活期存入时间拨回 `years` 个游戏年前。"""
    D = db["db_async"]
    from sqlalchemy import update
    async with D.AsyncSessionLocal() as s:
        await s.execute(update(D.BankAccount).where(D.BankAccount.discord_id == uid)
                        .values(demand_deposited_at=time.time() - years * YEAR))
        await s.commit()


async def _age_deposit(db, dep_id, due_in):
    D = db["db_async"]
    from sqlalchemy import update
    async with D.AsyncSessionLocal() as s:
        await s.execute(update(D.BankDeposit).where(D.BankDeposit.deposit_id == dep_id)
                        .values(due_at=time.time() + due_in))
        await s.commit()


# --- 利息公式 -----------------------------------------------------------------

def test_活期利息按游戏年计():
    assert bank.calc_demand_interest(10_000, time.time() - 100 * YEAR) == 1000      # 0.1% × 100 年
    assert bank.calc_demand_interest(10_000, time.time()) == 0


def test_定期利息是单利():
    assert bank.calc_term_interest(20_000, 10, 0.01) == 2000
    assert bank.calc_term_interest(20_000, 100, 0.04) == 80_000


# --- 活期存入 -----------------------------------------------------------------

async def test_活期存入_没有角色(db):
    assert (await deposit_demand(U, 10))["reason"] == "角色不存在。"


@pytest.mark.parametrize("amount", [0, -5])
async def test_活期存入_金额必须为正(db, amount):
    await _add(db)
    r = await deposit_demand(U, amount)
    assert not r["ok"] and await stones(db) == 100_000


async def test_活期存入_灵石不足_账不动(db):
    await _add(db, stones=50)
    r = await deposit_demand(U, 51)
    assert r["reason"] == "灵石不足。" and await stones(db) == 50
    assert (await get_bank_account(U))["demand_balance"] == 0


async def test_活期存入_首次开户(db):
    await _add(db)
    r = await deposit_demand(U, 30_000)
    assert r == {"ok": True, "demand_balance": 30_000}
    assert await stones(db) == 70_000 and (await get_bank_account(U))["demand_balance"] == 30_000


async def test_活期存入_再存时先结息(db):
    await _add(db)
    await deposit_demand(U, 10_000)
    await _age_account(db, 100)
    r = await deposit_demand(U, 5_000)
    assert r["demand_balance"] == 10_000 + 1000 + 5_000
    assert await stones(db) == 100_000 - 15_000                                      # 利息是钱庄给的，不从玩家扣


async def test_活期存入_并发不丢钱(db):
    await _add(db)
    await deposit_demand(U, 1_000)
    results = await asyncio.gather(*[deposit_demand(U, 1_000) for _ in range(6)])
    ok = [r for r in results if r["ok"]]
    acc = await get_bank_account(U)
    assert acc["demand_balance"] == 1_000 + 1_000 * len(ok)                          # 存成功几笔就进几笔
    assert await stones(db) == 100_000 - 1_000 - 1_000 * len(ok)                     # 被拒的没有白扣


async def test_活期存入_账户被改动_回滚且不白扣(db, monkeypatch):
    await _add(db)
    await deposit_demand(U, 1_000)

    async def stale(*a, **k):
        return False
    monkeypatch.setattr(bank, "_cas_account", stale)
    r = await deposit_demand(U, 500)
    assert "请重试" in r["reason"] and await stones(db) == 99_000


# --- 活期取出 -----------------------------------------------------------------

async def test_活期取出_没有账户(db):
    await _add(db)
    assert (await withdraw_demand(U, 10))["reason"] == "账户不存在。"


@pytest.mark.parametrize("amount", [0, -1, 10_001])
async def test_活期取出_金额不合法(db, amount):
    await _add(db)
    await deposit_demand(U, 10_000)
    r = await withdraw_demand(U, amount)
    assert not r["ok"] and "可取金额为" in r["reason"]


async def test_活期取出_含利息(db):
    await _add(db, stones=10_000)
    await deposit_demand(U, 10_000)
    await _age_account(db, 100)                                                       # 利息 1000
    r = await withdraw_demand(U, 10_500)
    assert r["ok"] and r["withdrawn"] == 10_500 and r["interest"] == 1000 and r["remaining"] == 500
    assert await stones(db) == 10_500 and (await get_bank_account(U))["demand_balance"] == 500


async def test_活期取出_可以把本息全部取空(db):
    await _add(db, stones=10_000)
    await deposit_demand(U, 10_000)
    await _age_account(db, 100)
    r = await withdraw_demand(U, 11_000)
    assert r["ok"] and r["remaining"] == 0 and (await get_bank_account(U))["demand_balance"] == 0


async def test_活期取出_并发不超取(db):
    await _add(db, stones=0)
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        s.add(D.BankAccount(discord_id=U, demand_balance=10_000, demand_deposited_at=time.time()))
        await s.commit()
    results = await asyncio.gather(*[withdraw_demand(U, 6_000) for _ in range(4)])
    assert len([r for r in results if r["ok"]]) == 1
    assert await stones(db) == 6_000 and (await get_bank_account(U))["demand_balance"] == 4_000


async def test_活期取出_账户被改动_不发钱(db, monkeypatch):
    await _add(db, stones=0)
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        s.add(D.BankAccount(discord_id=U, demand_balance=1_000, demand_deposited_at=time.time()))
        await s.commit()

    async def stale(*a, **k):
        return False
    monkeypatch.setattr(bank, "_cas_account", stale)
    r = await withdraw_demand(U, 500)
    assert "请重试" in r["reason"] and await stones(db) == 0


# --- 定期存款 -----------------------------------------------------------------

async def test_定期存入_校验(db):
    assert (await deposit_term(U, MIN_DEPOSIT, 10))["reason"] == "角色不存在。"
    await _add(db)
    assert "最低" in (await deposit_term(U, MIN_DEPOSIT - 1, 10))["reason"]
    assert "无效的存款期限" in (await deposit_term(U, MIN_DEPOSIT, 7))["reason"]
    await _add(db, "1002", stones=MIN_DEPOSIT - 1)
    assert (await deposit_term("1002", MIN_DEPOSIT, 10))["reason"] == "灵石不足。"
    assert await stones(db) == 100_000


async def test_定期存入_成功_记录与扣款(db):
    await _add(db)
    r = await deposit_term(U, 20_000, 20)
    assert r["ok"] and r["interest"] == 20_000 * 0.015 * 20 and r["term_years"] == 20
    assert r["due_at"] == pytest.approx(time.time() + 20 * YEAR, abs=5)
    assert await stones(db) == 80_000
    [d] = await get_term_deposits(U)
    assert d["principal"] == 20_000 and d["status"] == "active" and d["rate"] == 0.015


# --- 定期取出 -----------------------------------------------------------------

async def _deposit(db, uid=U, amount=20_000, years=10):
    return (await deposit_term(uid, amount, years))["deposit_id"]


async def test_定期取出_不存在或别人的存款(db):
    await _add(db)
    await _add(db, "1002")
    assert (await withdraw_term(U, "nope"))["reason"] == "存款记录不存在。"
    dep = await _deposit(db, "1002")
    assert (await withdraw_term(U, dep))["reason"] == "存款记录不存在。"
    assert len(await get_term_deposits("1002")) == 1


async def test_定期取出_到期拿本息(db):
    await _add(db)
    dep = await _deposit(db)
    await _age_deposit(db, dep, -1)
    r = await withdraw_term(U, dep)
    assert r["matured"] and r["payout"] == 22_000 and r["interest_earned"] == 2000 and r["principal"] == 20_000
    assert await stones(db) == 100_000 + 2000 and await get_term_deposits(U) == []


async def test_定期取出_提前只退本金(db):
    await _add(db)
    dep = await _deposit(db)
    r = await withdraw_term(U, dep)
    assert not r["matured"] and r["payout"] == 20_000 and r["interest_earned"] == 0
    assert await stones(db) == 100_000


async def test_定期取出_只能取一次(db):
    await _add(db)
    dep = await _deposit(db)
    await _age_deposit(db, dep, -1)
    assert (await withdraw_term(U, dep))["ok"]
    assert (await withdraw_term(U, dep))["reason"] == "该存款已结算。"
    assert await stones(db) == 100_000 + 2000


async def test_定期取出_并发只发一次(db):
    await _add(db)
    dep = await _deposit(db)
    await _age_deposit(db, dep, -1)
    results = await asyncio.gather(*[withdraw_term(U, dep) for _ in range(5)])
    assert len([r for r in results if r["ok"]]) == 1 and await stones(db) == 102_000


# --- 转账 ---------------------------------------------------------------------

async def test_转账_成功_含手续费(db):
    await _add(db)
    await _add(db, "1002", stones=0)
    r = await transfer(U, "1002", 10_000)
    assert r == {"ok": True, "amount": 10_000, "fee": 200, "receiver_name": "道友1002"}
    assert await stones(db) == 100_000 - 10_200 and await stones(db, "1002") == 10_000


async def test_转账_手续费至少1(db):
    await _add(db)
    await _add(db, "1002", stones=0)
    r = await transfer(U, "1002", 10)
    assert r["fee"] == 1


async def test_转账_上限边界(db):
    await _add(db, stones=1_000_000)
    await _add(db, "1002", stones=0)
    assert (await transfer(U, "1002", TRANSFER_MAX))["ok"]
    r = await transfer(U, "1002", TRANSFER_MAX + 1)
    assert not r["ok"] and "上限" in r["reason"]
    assert (await transfer(U, "1002", 0))["ok"] is False and (await transfer(U, "1002", -5))["ok"] is False


async def test_转账_各种失败不动账(db):
    assert (await transfer(U, "1002", 10))["reason"] == "角色不存在。"
    await _add(db, stones=100)
    assert (await transfer(U, "1002", 10))["reason"] == "对方角色不存在。"
    await _add(db, "1002", stones=0)
    r = await transfer(U, "1002", 100)                                               # 需要 102
    assert "灵石不足" in r["reason"] and "102" in r["reason"]
    assert await stones(db) == 100 and await stones(db, "1002") == 0


async def test_转账_灵石总量守恒_手续费被钱庄收走(db):
    await _add(db)
    await _add(db, "1002", stones=500)
    before = await stones(db) + await stones(db, "1002")
    r = await transfer(U, "1002", 7_777)
    assert before - (await stones(db) + await stones(db, "1002")) == r["fee"]


# --- 只在钱庄所在城市营业（B34） ----------------------------------------------

def test_钱庄城市包含灵虚城():
    assert "灵虚城" in BANK_CITIES


async def test_不在钱庄城市_五种操作都被拒_账不动(db):
    await _add(db, city="昆仑秘境")
    await _add(db, "1002", stones=0)
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        s.add(D.BankAccount(discord_id=U, demand_balance=1_000, demand_deposited_at=time.time()))
        await s.commit()
    dep = await _deposit_in(db)
    results = [
        await deposit_demand(U, 100), await withdraw_demand(U, 100), await deposit_term(U, MIN_DEPOSIT, 10),
        await withdraw_term(U, dep), await transfer(U, "1002", 100),
    ]
    for r in results:
        assert not r["ok"] and "钱庄" in r["reason"], r
    assert await stones(db) == 100_000 - MIN_DEPOSIT and await stones(db, "1002") == 0
    assert (await get_bank_account(U))["demand_balance"] == 1_000


async def _deposit_in(db):
    """先在城里存一笔，再把人移到城外。"""
    from sqlalchemy import update
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        await s.execute(update(D.Player).where(D.Player.discord_id == U).values(current_city="灵虚城"))
        await s.commit()
    dep = await _deposit(db)
    async with D.AsyncSessionLocal() as s:
        await s.execute(update(D.Player).where(D.Player.discord_id == U).values(current_city="昆仑秘境"))
        await s.commit()
    return dep


@pytest.mark.parametrize("city", BANK_CITIES)
async def test_每个钱庄城市都能用(db, city):
    await _add(db, city=city)
    assert (await deposit_demand(U, 100))["ok"]


async def test_收款人不必在钱庄城市(db):
    await _add(db)
    await _add(db, "1002", stones=0, city="昆仑秘境")
    assert (await transfer(U, "1002", 100))["ok"]
