import random

from utils import rules
from utils.atomic import DEAD_REASON, claim_daily_quota, grant_stones, spend_stones
from utils.db_async import AsyncSessionLocal, Player

# 下注额、每日次数、每格的倍率和格数在 data/game_rules.json 的 roulette（管理员可以调；校验保证期望倍率 ≤ 1，庄家不亏）。
# 以前是 4/1/3/2/1/1，期望 1.875，每转平均净赚 437 灵石（B39）；默认 12 格，期望 = (0.5×3 + 1 + 2 + 5) / 12 ≈ 0.79。
# count 为 0 的档位保留定义，但不上转盘、面板里也不展示。


def bet() -> int:
    return rules.section("roulette")["bet"]


def daily_limit() -> int:
    return rules.section("roulette")["daily_limit"]


def slots() -> list[dict]:
    """每一格的定义 [{label, multiplier, emoji, count}]（label 由倍率生成）。"""
    return [{"label": f"× {s['multiplier']:g}", **s} for s in rules.section("roulette")["slots"]]


def wheel() -> list[dict]:
    """转盘（每格一项，按定义顺序展开）。"""
    out: list[dict] = []
    for s in slots():
        out.extend([s] * s["count"])
    return out


def spin_wheel() -> dict:
    return random.choice(wheel())


def build_wheel_display(landed: dict) -> str:
    cells = wheel()
    emojis = [s["emoji"] for s in cells]
    landed_idx = next(i for i, s in enumerate(cells) if s["label"] == landed["label"] and s["emoji"] == landed["emoji"])
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
            session, uid, Player.roulette_daily_count, Player.roulette_daily_reset, daily_limit()
        )
        if daily_count is None:
            return {"ok": False, "reason": f"今日轮转次数已达上限（{daily_limit()}次），明日再来。"}

        if not await spend_stones(session, uid, bet()):
            await session.rollback()          # 连带退回刚占用的配额
            return {"ok": False, "reason": f"灵石不足，轮转需要 **{bet()}** 灵石。"}

        result_slot = spin_wheel()
        stake = bet()
        payout = int(stake * result_slot["multiplier"])
        net = payout - stake

        await grant_stones(session, uid, payout)
        await session.commit()

    return {
        "ok": True,
        "slot": result_slot,
        "bet": stake,
        "payout": payout,
        "net": net,
        "daily_count": daily_count,
        "daily_limit": daily_limit(),
    }
