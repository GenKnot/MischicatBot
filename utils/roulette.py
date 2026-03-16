import random
import time

from utils.db_async import AsyncSessionLocal, Player

BET = 500
DAILY_LIMIT = 5

SLOTS = [
    {"label": "× 0",   "multiplier": 0.0,  "emoji": "💀", "count": 4},
    {"label": "× 0.5", "multiplier": 0.5,  "emoji": "🌑", "count": 1},
    {"label": "× 1",   "multiplier": 1.0,  "emoji": "⚪", "count": 3},
    {"label": "× 2",   "multiplier": 2.0,  "emoji": "🟡", "count": 2},
    {"label": "× 5",   "multiplier": 5.0,  "emoji": "🔥", "count": 1},
    {"label": "× 10",  "multiplier": 10.0, "emoji": "💎", "count": 1},
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

        now = time.time()
        daily_count = player.roulette_daily_count or 0
        daily_reset = player.roulette_daily_reset or 0

        reset_date = time.gmtime(daily_reset)
        now_date = time.gmtime(now)
        if (now_date.tm_year, now_date.tm_yday) != (reset_date.tm_year, reset_date.tm_yday):
            daily_count = 0

        if daily_count >= DAILY_LIMIT:
            return {"ok": False, "reason": f"今日轮转次数已达上限（{DAILY_LIMIT}次），明日再来。"}

        if player.spirit_stones < BET:
            return {"ok": False, "reason": f"灵石不足，轮转需要 **{BET}** 灵石。"}

        result_slot = spin_wheel()
        payout = int(BET * result_slot["multiplier"])
        net = payout - BET

        player.spirit_stones += net
        player.roulette_daily_count = daily_count + 1
        player.roulette_daily_reset = now
        await session.commit()

    return {
        "ok": True,
        "slot": result_slot,
        "bet": BET,
        "payout": payout,
        "net": net,
        "daily_count": daily_count + 1,
        "daily_limit": DAILY_LIMIT,
    }
