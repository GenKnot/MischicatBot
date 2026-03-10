import time
from utils.db import get_conn
from utils.character import (
    seconds_to_years, calc_cultivation_gain,
    AUTO_CULTIVATE_THRESHOLD_YEARS, get_cultivation_bonus,
)
from utils.realms import cultivation_needed


def get_player(discord_id: str):
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM players WHERE discord_id = ?", (discord_id,)).fetchone()
        return dict(row) if row else None


def is_defending(uid: str) -> bool:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT 1 FROM public_event_participants ep "
            "JOIN public_events e ON ep.event_id = e.event_id "
            "WHERE ep.discord_id = ? AND ep.activity = 'defense' AND e.status = 'active'",
            (uid,)
        ).fetchone()
    return row is not None


def settle_time(player: dict):
    now = time.time()
    elapsed_years = seconds_to_years(now - player["last_active"])
    new_lifespan = max(0, player["lifespan"] - int(elapsed_years))
    updates = {"lifespan": new_lifespan, "last_active": now, "cultivation": player["cultivation"]}
    cultivating = player["cultivating_until"] and now < player["cultivating_until"]
    if not cultivating and elapsed_years >= AUTO_CULTIVATE_THRESHOLD_YEARS:
        bonus = get_cultivation_bonus(player["discord_id"], player["current_city"], player.get("cave"))
        gain = calc_cultivation_gain(int(elapsed_years), player["comprehension"], player["spirit_root_type"])
        from utils.buffs import get_cultivation_speed_bonus
        speed_bonus = get_cultivation_speed_bonus(player)
        if speed_bonus > 0:
            bonus += speed_bonus
        gain = int(gain * (1 + bonus))
        updates["cultivation"] = player["cultivation"] + gain
    return updates, elapsed_years


def apply_updates(discord_id: str, updates: dict):
    fields = ", ".join(f"{k} = ?" for k in updates)
    values = list(updates.values()) + [discord_id]
    with get_conn() as conn:
        conn.execute(f"UPDATE players SET {fields} WHERE discord_id = ?", values)
        conn.commit()


def can_breakthrough(player: dict) -> bool:
    return player["cultivation"] >= cultivation_needed(player["realm"])
