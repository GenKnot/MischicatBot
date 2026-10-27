import time
from sqlalchemy import text
from utils.db_async import AsyncSessionLocal, Player
from utils.character import (
    seconds_to_years, calc_cultivation_gain,
    auto_cultivate_threshold_years, get_cultivation_bonus,
)
from utils.realms import cultivation_needed


async def get_player(discord_id: str):
    async with AsyncSessionLocal() as session:
        row = await session.get(Player, discord_id)
        if not row:
            return None
        return {c.name: getattr(row, c.name) for c in row.__table__.columns}


async def is_defending(uid: str) -> bool:
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            text(
                "SELECT 1 FROM public_event_participants ep "
                "JOIN public_events e ON ep.event_id = e.event_id "
                "WHERE ep.discord_id = :uid AND ep.activity = 'defense' AND e.status = 'active'"
            ),
            {"uid": uid},
        )
        return result.fetchone() is not None


async def settle_time(player: dict):
    now = time.time()
    elapsed_years = seconds_to_years(now - player["last_active"])
    new_lifespan = max(0, player["lifespan"] - int(elapsed_years))
    updates = {"lifespan": new_lifespan, "last_active": now, "cultivation": player["cultivation"]}
    cultivating = player["cultivating_until"] and now < player["cultivating_until"]
    if not cultivating and elapsed_years >= auto_cultivate_threshold_years():
        bonus = await get_cultivation_bonus(player["discord_id"], player["current_city"], player.get("cave"))
        gain = calc_cultivation_gain(int(elapsed_years), player["comprehension"], player["spirit_root_type"])
        from utils.buffs import get_cultivation_speed_bonus
        speed_bonus = get_cultivation_speed_bonus(player)
        if speed_bonus > 0:
            bonus += speed_bonus
        gain = int(gain * (1 + bonus))
        updates["cultivation"] = player["cultivation"] + gain
    return updates, elapsed_years


async def apply_updates(discord_id: str, updates: dict):
    async with AsyncSessionLocal() as session:
        row = await session.get(Player, discord_id)
        if row:
            for k, v in updates.items():
                setattr(row, k, v)
            await session.commit()


def can_breakthrough(player: dict) -> bool:
    return player["cultivation"] >= cultivation_needed(player["realm"])
