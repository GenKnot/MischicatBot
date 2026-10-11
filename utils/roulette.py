import random

from utils.atomic import DEAD_REASON, claim_daily_quota, grant_stones, spend_stones
from utils.db_async import AsyncSessionLocal, Player

BET = 500
DAILY_LIMIT = 5

# 12 格，期望 = (0.5×3 + 1 + 2 + 5) / 12 ≈ 0.79：庄家占优，与赌坊（0.78）同量级。
# 以前是 4/1/3/2/1/1，期望 1.875，每转平均净赚 437 灵石（B39）。改格数时同步改 tests/test_gamble_roulette.py 里的期望断言。
# count 为 0 的档位保留定义（结算与展示的映射还在），但不上转盘、面板里也不展示。
SLOTS = [
    {"label": "× 0",   "multiplier": 0.0,  "emoji": "💀", "count": 6},
    {"label": "× 0.5", "multiplier": 0.5,  "emoji": "🌑", "count": 3},
    {"label": "× 1",   "multiplier": 1.0,  "emoji": "⚪", "count": 1},
    {"label": "× 2",   "multiplier": 2.0,  "emoji": "🟡", "count": 1},
    {"label": "× 5",   "multiplier": 5.0,  "emoji": "🔥", "count": 1},
    {"label": "× 10",  "multiplier": 10.0, "emoji": "💎", "count": 0},
]

WHEEL: list[dict] = []
for _s in SLOTS:
    WHEEL.extend([_s] * _s["count"])


def spin_wheel() -> dict:
    return random.choice(WHEEL)


def build_wheel_display(landed: dict) -> str:
    emojis = [s["emoji"] for s in WHEEL]
    landed_idx = next(i for i, s in enumerate(WHEEL) if s["label"] == landed["label"] and s["emoji"] == landed["emoji"])
    display = []
    for i, e in enumerate(emojis):
        if i == landed_idx:
            display.append(f"[{e}]")
        else:
            display.append(e)
    return " ".join(display)


async def do_roulette(uid: str) -> dict:
    async with AsyncSessionLocal() as session:
        player = await session.get(Player, uid)
        if not player:
            return {"ok": False, "reason": "角色不存在。"}

        if player.is_dead:
            return {"ok": False, "reason": DEAD_REASON}

        daily_count = await claim_daily_quota(
            session, uid, Player.roulette_daily_count, Player.roulette_daily_reset, DAILY_LIMIT
        )
        if daily_count is None:
            return {"ok": False, "reason": f"今日轮转次数已达上限（{DAILY_LIMIT}次），明日再来。"}

        if not await spend_stones(session, uid, BET):
            await session.rollback()          # 连带退回刚占用的配额
            return {"ok": False, "reason": f"灵石不足，轮转需要 **{BET}** 灵石。"}

        result_slot = spin_wheel()
        payout = int(BET * result_slot["multiplier"])
        net = payout - BET

        await grant_stones(session, uid, payout)
        await session.commit()

    return {
        "ok": True,
        "slot": result_slot,
        "bet": BET,
        "payout": payout,
        "net": net,
        "daily_count": daily_count,
        "daily_limit": DAILY_LIMIT,
    }
