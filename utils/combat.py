import random
import json
from utils.realms import get_realm_index
from utils.sects import calc_technique_stat_bonus


def _parse_techniques(raw) -> list:
    data = json.loads(raw or "[]")
    result = []
    for item in data:
        if isinstance(item, str):
            result.append({"name": item, "stage": "入门", "equipped": True})
        elif isinstance(item, dict):
            result.append(item)
    return result


def calc_power(player: dict) -> float:
    from utils.buffs import get_combat_power_bonus, get_stat_temp
    base = (
        player.get("comprehension", 5) +
        player.get("physique", 5) +
        player.get("bone", 5) +
        player.get("soul", 5) +
        player.get("fortune", 5)
    )
    stat_temp = get_stat_temp(player)
    base += sum(stat_temp.values())

    realm_idx = get_realm_index(player.get("realm", "炼气期1层"))
    realm_mult = 1.0 + realm_idx * 0.15

    techs = _parse_techniques(player.get("techniques", "[]"))
    bonus = calc_technique_stat_bonus(techs)
    stat_bonus = (
        bonus.get("comprehension", 0) +
        bonus.get("physique", 0) +
        bonus.get("bone", 0) +
        bonus.get("soul", 0) +
        bonus.get("fortune", 0)
    )
    speed_bonus = bonus.get("cultivation_speed", 0)

    from utils.db import get_equipped
    from utils.equipment import equip_stat_bonus
    equipped = get_equipped(player.get("discord_id", ""))
    equip_bonus = equip_stat_bonus(equipped)
    equip_stat = (
        equip_bonus.get("comprehension", 0) +
        equip_bonus.get("physique", 0) +
        equip_bonus.get("bone", 0) +
        equip_bonus.get("soul", 0) +
        equip_bonus.get("fortune", 0)
    )

    combat_buff = get_combat_power_bonus(player)
    total = (base + stat_bonus + equip_stat) * realm_mult * (1 + speed_bonus) * (1 + combat_buff)
    return total


def calc_escape_rate(player: dict) -> float:
    from utils.buffs import get_escape_bonus
    from utils.db import get_equipped
    from utils.equipment import equip_stat_bonus
    equipped = get_equipped(player.get("discord_id", ""))
    equip_bonus = equip_stat_bonus(equipped)
    soul = player.get("soul", 5) + equip_bonus.get("soul", 0)
    realm_idx = get_realm_index(player.get("realm", "炼气期1层"))
    extra = player.get("escape_rate", 0)
    escape_buff = get_escape_bonus(player)
    rate = 0.30 + soul * 0.01 + realm_idx * 0.005 + extra / 100 + escape_buff
    return min(0.90, max(0.05, rate))


def roll_combat(attacker: dict, defender: dict) -> tuple[bool, float, float]:
    atk = calc_power(attacker) * random.uniform(0.85, 1.15)
    dfn = calc_power(defender) * random.uniform(0.85, 1.15)
    won = atk > dfn
    return won, round(atk, 1), round(dfn, 1)


def roll_escape(defender: dict) -> tuple[bool, float]:
    rate = calc_escape_rate(defender)
    success = random.random() < rate
    return success, round(rate * 100, 1)


def consume_combat_buffs(discord_id: str, player: dict):
    from utils.buffs import consume_charge_buff, get_combat_power_bonus
    from utils.db import get_conn
    raw = player.get("active_buffs") or "{}"
    changed = False
    if get_combat_power_bonus(player) > 0:
        _, raw = consume_charge_buff(raw, "combat_power_bonus")
        changed = True
    if changed:
        with get_conn() as conn:
            conn.execute(
                "UPDATE players SET active_buffs = ? WHERE discord_id = ?",
                (raw, discord_id)
            )
            conn.commit()


def consume_escape_buff(discord_id: str, player: dict):
    from utils.buffs import consume_once_buff, get_escape_bonus
    from utils.db import get_conn
    raw = player.get("active_buffs") or "{}"
    if get_escape_bonus(player) > 0:
        _, raw = consume_once_buff(raw, "escape_bonus_once")
        with get_conn() as conn:
            conn.execute(
                "UPDATE players SET active_buffs = ? WHERE discord_id = ?",
                (raw, discord_id)
            )
            conn.commit()
