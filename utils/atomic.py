"""并发安全的资源变更原语。

按钮能连点，「读出来判断够不够再写回」会丢更新 —— 两次点击读到同一份余额，
各扣一次，物品和灵石就复制了。这里的做法是把判断条件写进 UPDATE，
靠 rowcount 判断有没有生效。

这些函数都接收调用方的 session，不自己 commit。返回 False / None 表示
条件不满足且什么都没改，调用方直接提示玩家即可。
"""

import time

from sqlalchemy import case, func, or_, select, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from utils.db_async import Inventory, Player


async def increment_player(session, discord_id: str, **deltas: int | float) -> bool:
    """原子增减玩家的数值字段，可正可负。

    用于"无条件发放"的场景（任务奖励、活动结算等）。需要"够不够"语义时
    请用 `spend_stones`，它带余额校验。

    >>> await increment_player(session, uid, spirit_stones=100, reputation=5)
    """
    values = {}
    for name, delta in deltas.items():
        col = getattr(Player, name, None)
        if col is None or not hasattr(col, "expression"):
            raise AttributeError(f"Player 上没有名为 {name!r} 的列")
        if delta:
            values[col] = col + delta
    if not values:
        return True
    result = await session.execute(
        update(Player).where(Player.discord_id == discord_id).values(values)
    )
    return result.rowcount == 1


async def spend_stones(session, discord_id: str, amount: int) -> bool:
    """原子扣减灵石。余额不足时返回 False 且不修改任何数据。"""
    if amount < 0:
        raise ValueError(f"spend_stones 的 amount 不能为负：{amount}")
    if amount == 0:
        return True
    result = await session.execute(
        update(Player)
        .where(Player.discord_id == discord_id, Player.spirit_stones >= amount)
        .values(spirit_stones=Player.spirit_stones - amount)
    )
    return result.rowcount == 1


async def grant_stones(session, discord_id: str, amount: int) -> bool:
    """原子增加灵石。玩家不存在时返回 False。"""
    if amount < 0:
        raise ValueError(f"grant_stones 的 amount 不能为负：{amount}")
    return await increment_player(session, discord_id, spirit_stones=amount)


async def consume_item(session, discord_id: str, item_id: str, quantity: int = 1) -> bool:
    """原子扣减背包物品。数量不足时返回 False 且不修改任何数据。"""
    if quantity <= 0:
        raise ValueError(f"consume_item 的 quantity 必须为正：{quantity}")
    result = await session.execute(
        update(Inventory)
        .where(
            Inventory.discord_id == discord_id,
            Inventory.item_id == item_id,
            Inventory.quantity >= quantity,
        )
        .values(quantity=Inventory.quantity - quantity)
    )
    if result.rowcount != 1:
        return False
    # 扣到 0 就清掉这一行，保持与旧行为一致（背包里不留 0 数量的条目）
    await session.execute(
        Inventory.__table__.delete().where(
            Inventory.discord_id == discord_id,
            Inventory.item_id == item_id,
            Inventory.quantity <= 0,
        )
    )
    return True


async def grant_item(session, discord_id: str, item_id: str, quantity: int = 1) -> None:
    """原子增加背包物品（UPSERT，不存在则新建）。"""
    if quantity <= 0:
        raise ValueError(f"grant_item 的 quantity 必须为正：{quantity}")
    await session.execute(
        sqlite_insert(Inventory)
        .values(discord_id=discord_id, item_id=item_id, quantity=quantity)
        .on_conflict_do_update(
            index_elements=["discord_id", "item_id"],
            set_={"quantity": Inventory.quantity + quantity},
        )
    )


async def cas_player_field(session, discord_id: str, column, expected, new_value) -> bool:
    """比较并设置玩家的某个字段（CAS）。字段值与 `expected` 不符时不改动，返回 False。

    用于那些**没法用增量表达**的字段 —— 功法列表、buff 表这类 JSON 文本：
    调用方读出来、改完、再写回，中间若被别处改过，这次写入就该作废，
    否则会覆盖掉别人的修改（学两本功法只留下一本）。

    能用增量表达的（灵石、物品数量）请用 `spend_stones` / `consume_item`，
    那些更省事也更不容易写错。
    """
    result = await session.execute(
        update(Player)
        .where(Player.discord_id == discord_id, column == expected)
        .values({column: new_value})
    )
    return result.rowcount == 1


async def claim_daily_quota(
    session,
    discord_id: str,
    count_col,
    reset_col,
    limit: int,
    now: float | None = None,
) -> int | None:
    """占用一次每日配额。一条 UPDATE 同时做「跨日归零」和「未超限则 +1」。

    日界是 UTC 自然日，沿用原来的语义。超限或玩家不存在返回 None。
    """
    now = time.time() if now is None else now
    used = func.coalesce(count_col, 0)
    same_day = func.date(func.coalesce(reset_col, 0), "unixepoch") == func.date(now, "unixepoch")

    result = await session.execute(
        update(Player)
        .where(
            Player.discord_id == discord_id,
            or_(~same_day, used < limit),   # 新的一天，或今日还有余量
        )
        .values({
            count_col: case((same_day, used + 1), else_=1),
            reset_col: now,
        })
        .execution_options(synchronize_session="fetch")
    )
    if result.rowcount != 1:
        return None
    return await session.scalar(select(count_col).where(Player.discord_id == discord_id))


async def claim_cooldown(session, discord_id: str, cooldown_col, seconds: float,
                         now: float | None = None) -> bool:
    """原子占用一次冷却：仅当冷却已过时把冷却推到 ``now + seconds``。

    校验与推进在同一条 UPDATE 里完成，所以连点不会两次都通过。
    冷却未到返回 False，且不修改任何数据。
    """
    now = time.time() if now is None else now
    result = await session.execute(
        update(Player)
        .where(
            Player.discord_id == discord_id,
            func.coalesce(cooldown_col, 0) <= now,
        )
        .values({cooldown_col: now + seconds})
    )
    return result.rowcount == 1


async def peek_daily_used(session, discord_id: str, count_col, reset_col,
                          now: float | None = None) -> int:
    """只读查询今日已用次数（跨日按 0 计），用于展示，不做任何修改。"""
    now = time.time() if now is None else now
    row = (await session.execute(
        select(count_col, reset_col).where(Player.discord_id == discord_id)
    )).first()
    if not row:
        return 0
    used, reset_ts = row[0] or 0, row[1] or 0
    if time.gmtime(reset_ts)[:3] != time.gmtime(now)[:3]:
        return 0
    return used
