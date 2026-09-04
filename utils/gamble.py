import json
import os
import random

from utils.atomic import claim_daily_quota, grant_stones, spend_stones
from utils.db_async import AsyncSessionLocal, Player

_config_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "gamble_config.json")
with open(_config_path, encoding="utf-8") as _f:
    CONFIG = json.load(_f)

DAILY_LIMIT = CONFIG["daily_limit"]
BET_OPTIONS = CONFIG["bet_options"]

_total_weight = sum(o["weight"] for o in CONFIG["outcomes"])
OUTCOME_PROBS = [(o["label"], round(100 * o["weight"] / _total_weight, 1)) for o in CONFIG["outcomes"]]


async def do_gamble(uid: str, bet: int) -> dict:
    async with AsyncSessionLocal() as session:
        player = await session.get(Player, uid)
        if not player:
            return {"ok": False, "reason": "角色不存在。"}

        if bet <= 0:
            return {"ok": False, "reason": "押注金额必须大于 0。"}

        # 先原子占掉今日一次配额，再原子扣灵石；任一步不满足都不会留下副作用
        daily_count = await claim_daily_quota(
            session, uid, Player.gamble_daily_count, Player.gamble_daily_reset, DAILY_LIMIT
        )
        if daily_count is None:
            return {"ok": False, "reason": f"今日赌注已达上限（{DAILY_LIMIT}次），明日再来。"}

        if not await spend_stones(session, uid, bet):
            await session.rollback()          # 连带退回刚占用的配额
            return {"ok": False, "reason": "灵石不足，无法押注。"}

        outcomes = CONFIG["outcomes"]
        weights = [o["weight"] for o in outcomes]
        outcome = random.choices(outcomes, weights=weights, k=1)[0]

        payout = int(bet * outcome["multiplier"])
        net = payout - bet
        message = random.choice(outcome["messages"])

        await grant_stones(session, uid, payout)
        await session.commit()

    return {
        "ok": True,
        "label": outcome["label"],
        "bet": bet,
        "payout": payout,
        "net": net,
        "message": message,
        "daily_count": daily_count,
        "daily_limit": DAILY_LIMIT,
    }
