import json
import os
import random
import time

from utils.db_async import AsyncSessionLocal, Player

_config_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "gamble_config.json")
with open(_config_path, encoding="utf-8") as _f:
    CONFIG = json.load(_f)

DAILY_LIMIT = CONFIG["daily_limit"]
BET_OPTIONS = CONFIG["bet_options"]


async def do_gamble(uid: str, bet: int) -> dict:
    async with AsyncSessionLocal() as session:
        player = await session.get(Player, uid)
        if not player:
            return {"ok": False, "reason": "角色不存在。"}

        now = time.time()
        daily_count = player.gamble_daily_count or 0
        daily_reset = player.gamble_daily_reset or 0

        reset_date = time.gmtime(daily_reset)
        now_date = time.gmtime(now)
        if (now_date.tm_year, now_date.tm_yday) != (reset_date.tm_year, reset_date.tm_yday):
            daily_count = 0

        if daily_count >= DAILY_LIMIT:
            return {"ok": False, "reason": f"今日赌注已达上限（{DAILY_LIMIT}次），明日再来。"}

        if player.spirit_stones < bet:
            return {"ok": False, "reason": "灵石不足，无法押注。"}

        outcomes = CONFIG["outcomes"]
        weights = [o["weight"] for o in outcomes]
        outcome = random.choices(outcomes, weights=weights, k=1)[0]

        payout = int(bet * outcome["multiplier"])
        net = payout - bet
        message = random.choice(outcome["messages"])

        player.spirit_stones += net
        player.gamble_daily_count = daily_count + 1
        player.gamble_daily_reset = now
        await session.commit()

    return {
        "ok": True,
        "label": outcome["label"],
        "bet": bet,
        "payout": payout,
        "net": net,
        "message": message,
        "daily_count": daily_count + 1,
        "daily_limit": DAILY_LIMIT,
    }
