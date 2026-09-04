import time
import uuid

from sqlalchemy import select, update

from utils.atomic import grant_stones, spend_stones
from utils.db_async import AsyncSessionLocal, Player, BankDeposit
from utils.character import years_to_seconds, seconds_to_years

BANK_CITIES = ["灵虚城", "丹阁", "落云城", "碧波城", "天工城"]

DEMAND_RATE = 0.001

TERM_OPTIONS = [
    {"years": 10,  "rate": 0.01},
    {"years": 15,  "rate": 0.0125},
    {"years": 20,  "rate": 0.015},
    {"years": 50,  "rate": 0.0175},
    {"years": 100, "rate": 0.04},
    {"years": 500, "rate": 0.05},
]

MIN_DEPOSIT = 20000
TRANSFER_FEE_RATE = 0.02
TRANSFER_MAX = 50000


def calc_demand_interest(principal: int, deposited_at: float) -> int:
    now = time.time()
    years = seconds_to_years(now - deposited_at)
    return int(principal * DEMAND_RATE * years)


def calc_term_interest(principal: int, term_years: int, rate: float) -> int:
    return int(principal * rate * term_years)


async def get_bank_account(discord_id: str) -> dict:
    async with AsyncSessionLocal() as session:
        from utils.db_async import BankAccount
        acc = await session.get(BankAccount, discord_id)
        if not acc:
            return {"discord_id": discord_id, "demand_balance": 0, "demand_deposited_at": 0.0}
        return {c.name: getattr(acc, c.name) for c in acc.__table__.columns}


async def _cas_account(session, discord_id: str, seen_balance: int, seen_at, 
                       new_balance: int, now: float) -> bool:
    """按「读到的值」做条件更新（CAS）。期间被别处改过则返回 False，不做修改。

    活期余额要先按存入时长结息再变动，利息算不进单条 SQL，因此用 CAS
    保证「读 → 算息 → 写回」这一串不会与另一次操作交错。
    """
    from utils.db_async import BankAccount
    at_col = BankAccount.demand_deposited_at
    result = await session.execute(
        update(BankAccount)
        .where(
            BankAccount.discord_id == discord_id,
            BankAccount.demand_balance == seen_balance,
            at_col.is_(None) if seen_at is None else at_col == seen_at,
        )
        .values(demand_balance=new_balance, demand_deposited_at=now)
    )
    return result.rowcount == 1


async def deposit_demand(discord_id: str, amount: int) -> dict:
    from utils.db_async import BankAccount
    async with AsyncSessionLocal() as session:
        player = await session.get(Player, discord_id)
        if not player:
            return {"ok": False, "reason": "角色不存在。"}
        if amount <= 0:
            return {"ok": False, "reason": "存入金额必须大于 0。"}
        if not await spend_stones(session, discord_id, amount):
            return {"ok": False, "reason": "灵石不足。"}

        acc = await session.get(BankAccount, discord_id)
        now = time.time()
        if acc:
            seen_balance, seen_at = acc.demand_balance, acc.demand_deposited_at
            interest = calc_demand_interest(seen_balance, seen_at or now)
            new_balance = seen_balance + interest + amount
            # 乐观并发控制：账户在我们读取之后若被改动过就放弃本次操作，
            # 否则两次并发存入会互相覆盖，玩家白扣一笔灵石。
            if not await _cas_account(session, discord_id, seen_balance, seen_at, new_balance, now):
                await session.rollback()
                return {"ok": False, "reason": "账户刚刚有变动，请重试。"}
        else:
            new_balance = amount
            session.add(BankAccount(discord_id=discord_id, demand_balance=amount,
                                    demand_deposited_at=now))

        await session.commit()
        return {"ok": True, "demand_balance": new_balance}


async def withdraw_demand(discord_id: str, amount: int) -> dict:
    from utils.db_async import BankAccount
    async with AsyncSessionLocal() as session:
        player = await session.get(Player, discord_id)
        acc = await session.get(BankAccount, discord_id)
        if not player or not acc:
            return {"ok": False, "reason": "账户不存在。"}

        now = time.time()
        seen_balance, seen_at = acc.demand_balance, acc.demand_deposited_at
        interest = calc_demand_interest(seen_balance, seen_at or now)
        total = seen_balance + interest

        if amount <= 0 or amount > total:
            return {"ok": False, "reason": f"可取金额为 {total:,} 灵石（含利息 {interest:,}）。"}

        remaining = total - amount
        if not await _cas_account(session, discord_id, seen_balance, seen_at, remaining, now):
            await session.rollback()
            return {"ok": False, "reason": "账户刚刚有变动，请重试。"}
        await grant_stones(session, discord_id, amount)
        await session.commit()
        return {"ok": True, "withdrawn": amount, "interest": interest, "remaining": remaining}


async def deposit_term(discord_id: str, amount: int, term_years: int) -> dict:
    async with AsyncSessionLocal() as session:
        player = await session.get(Player, discord_id)
        if not player:
            return {"ok": False, "reason": "角色不存在。"}
        if amount < MIN_DEPOSIT:
            return {"ok": False, "reason": f"定期存款每笔最低 {MIN_DEPOSIT:,} 灵石。"}

        term = next((t for t in TERM_OPTIONS if t["years"] == term_years), None)
        if not term:
            return {"ok": False, "reason": "无效的存款期限。"}

        if not await spend_stones(session, discord_id, amount):
            return {"ok": False, "reason": "灵石不足。"}

        now = time.time()
        due_at = now + years_to_seconds(term_years)
        deposit_id = str(uuid.uuid4())[:8]
        interest = calc_term_interest(amount, term_years, term["rate"])

        session.add(BankDeposit(
            deposit_id=deposit_id,
            discord_id=discord_id,
            principal=amount,
            term_years=term_years,
            rate=term["rate"],
            interest=interest,
            deposited_at=now,
            due_at=due_at,
            status="active",
        ))
        await session.commit()
        return {"ok": True, "deposit_id": deposit_id, "principal": amount, "interest": interest, "due_at": due_at, "term_years": term_years}


async def withdraw_term(discord_id: str, deposit_id: str) -> dict:
    async with AsyncSessionLocal() as session:
        player = await session.get(Player, discord_id)
        dep = await session.get(BankDeposit, deposit_id)
        if not player or not dep or dep.discord_id != discord_id:
            return {"ok": False, "reason": "存款记录不存在。"}
        if dep.status != "active":
            return {"ok": False, "reason": "该存款已结算。"}

        now = time.time()
        matured = now >= dep.due_at
        if matured:
            payout = dep.principal + dep.interest
            interest_earned = dep.interest
        else:
            payout = dep.principal
            interest_earned = 0

        # 原子结算：并发点击时只有一次能把 active 改成 withdrawn
        settled = await session.execute(
            update(BankDeposit)
            .where(BankDeposit.deposit_id == deposit_id, BankDeposit.status == "active")
            .values(status="withdrawn")
        )
        if settled.rowcount != 1:
            return {"ok": False, "reason": "该存款已结算。"}
        await grant_stones(session, discord_id, payout)
        await session.commit()
        return {"ok": True, "payout": payout, "principal": dep.principal, "interest_earned": interest_earned, "matured": matured}


async def get_term_deposits(discord_id: str) -> list[dict]:
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(BankDeposit).where(BankDeposit.discord_id == discord_id, BankDeposit.status == "active")
        )
        return [{c.name: getattr(r, c.name) for c in r.__table__.columns} for r in result.scalars()]


async def transfer(sender_id: str, receiver_id: str, amount: int) -> dict:
    async with AsyncSessionLocal() as session:
        sender = await session.get(Player, sender_id)
        receiver = await session.get(Player, receiver_id)
        if not sender:
            return {"ok": False, "reason": "角色不存在。"}
        if not receiver:
            return {"ok": False, "reason": "对方角色不存在。"}
        if amount <= 0 or amount > TRANSFER_MAX:
            return {"ok": False, "reason": f"单次转账上限 {TRANSFER_MAX:,} 灵石。"}
        fee = max(1, int(amount * TRANSFER_FEE_RATE))
        total_cost = amount + fee
        if not await spend_stones(session, sender_id, total_cost):
            return {"ok": False, "reason": f"灵石不足（需 {total_cost:,}，含手续费 {fee:,}）。"}
        await grant_stones(session, receiver_id, amount)
        await session.commit()
        return {"ok": True, "amount": amount, "fee": fee, "receiver_name": receiver.name}
