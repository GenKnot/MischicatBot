import json
import random
from functools import lru_cache
from pathlib import Path

from utils import settings_hub
from utils.atomic import DEAD_REASON, claim_daily_quota, grant_stones, spend_stones
from utils.db_async import AsyncSessionLocal, Player

_PATH = Path(__file__).resolve().parent.parent / "data" / "gamble_config.json"


@lru_cache(maxsize=1)
def _load() -> dict:
    return settings_hub.read(_PATH)


def cfg() -> dict:
    """赌坊配置（data/gamble_config.json，管理员可以 `cat!调参` 修改数字，只读）。"""
    return _load()


def validate(c: dict) -> list[str]:
    errors = []
    outs = c.get("outcomes", [])
    total = sum(o.get("weight", 0) for o in outs)
    if not outs or total <= 0 or any(o.get("weight", -1) < 0 or o.get("multiplier", -1) < 0 for o in outs):
        errors.append("outcomes 至少一项，权重 / 倍率非负，权重总和 > 0")
    elif sum(o["weight"] * o["multiplier"] for o in outs) / total > 1:
        errors.append("outcomes 的期望倍率不能超过 1（否则庄家亏本，玩家可以无限刷灵石）")
    bets = c.get("bet_options", [])
    if not bets or bets != sorted(set(bets)) or bets[0] < 1:
        errors.append("bet_options 至少一项，从小到大，不重复，≥ 1")
    if c.get("daily_limit", -1) < 0:
        errors.append("daily_limit 不能为负")
    return errors


def daily_limit() -> int:
    return cfg()["daily_limit"]


def bet_options() -> list[int]:
    return cfg()["bet_options"]


def outcome_probs() -> list[tuple[str, float]]:
    """[(结局名, 百分比)]，面板上展示用。"""
    outs = cfg()["outcomes"]
    total = sum(o["weight"] for o in outs)
    return [(o["label"], round(100 * o["weight"] / total, 1)) for o in outs]


async def do_gamble(uid: str, bet: int) -> dict:
    async with AsyncSessionLocal() as session:
        player = await session.get(Player, uid)
        if not player:
            return {"ok": False, "reason": "角色不存在。"}

        if player.is_dead:
            return {"ok": False, "reason": DEAD_REASON}

        if bet <= 0:
            return {"ok": False, "reason": "押注金额必须大于 0。"}

        # 先原子占掉今日一次配额，再原子扣灵石；任一步不满足都不会留下副作用
        daily_count = await claim_daily_quota(
            session, uid, Player.gamble_daily_count, Player.gamble_daily_reset, daily_limit()
        )
        if daily_count is None:
            return {"ok": False, "reason": f"今日赌注已达上限（{daily_limit()}次），明日再来。"}

        if not await spend_stones(session, uid, bet):
            await session.rollback()          # 连带退回刚占用的配额
            return {"ok": False, "reason": "灵石不足，无法押注。"}

        outcomes = cfg()["outcomes"]
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
        "daily_limit": daily_limit(),
    }
