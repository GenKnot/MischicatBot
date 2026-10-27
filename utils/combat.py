import random
import json
from utils import rules
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


async def calc_power(player: dict, equipped: list[dict] | None = None) -> float:
    """玩家战力。`equipped` 是该玩家已穿装备的列表；不传就自己去查库（单个玩家的场合）。

    批量算很多人（战力榜）时请一次性查出所有人的装备再逐个传进来，否则每人一次查询 = N+1。
    """
    from utils.buffs import get_combat_power_bonus, get_stat_temp, get_fortune_permanent_bonus
    base = (
        player.get("comprehension", 5) +
        player.get("physique", 5) +
        player.get("bone", 5) +
        player.get("soul", 5) +
        player.get("fortune", 5) +
        get_fortune_permanent_bonus(player)
    )
    stat_temp = get_stat_temp(player)
    base += sum(stat_temp.values())

    realm_idx = get_realm_index(player.get("realm", "炼气期1层"))
    realm_mult = 1.0 + realm_idx * rules.section("combat")["realm_step"]

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

    from utils.equipment import equip_stat_bonus
    if equipped is None:
        from utils.equipment_db import get_equipped
        equipped = await get_equipped(player.get("discord_id", ""))
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


calc_combat_power = calc_power


async def calc_escape_rate(player: dict) -> float:
    from utils.buffs import get_escape_bonus
    from utils.equipment_db import get_equipped
    from utils.equipment import equip_stat_bonus
    equipped = await get_equipped(player.get("discord_id", ""))
    equip_bonus = equip_stat_bonus(equipped)
    soul = player.get("soul", 5) + equip_bonus.get("soul", 0)
    realm_idx = get_realm_index(player.get("realm", "炼气期1层"))
    extra = player.get("escape_rate", 0)
    escape_buff = get_escape_bonus(player)
    e = rules.section("combat")["escape"]
    rate = e["base"] + soul * e["per_soul"] + realm_idx * e["per_realm"] + extra / 100 + escape_buff
    return min(e["max"], max(e["min"], rate))


async def roll_combat(attacker: dict, defender: dict) -> tuple[bool, float, float]:
    from utils.bot_combat import power_multiplier              # 机器人按档位有虚拟功法装备加成；真人是 1
    noise = rules.section("combat")["noise"]
    atk = (await calc_power(attacker)) * (await power_multiplier(attacker)) * random.uniform(*noise)
    dfn = (await calc_power(defender)) * (await power_multiplier(defender)) * random.uniform(*noise)
    won = atk > dfn
    return won, round(atk, 1), round(dfn, 1)


async def roll_escape(defender: dict) -> tuple[bool, float]:
    rate = await calc_escape_rate(defender)
    success = random.random() < rate
    return success, round(rate * 100, 1)


async def consume_combat_buffs(discord_id: str, player: dict):
    from utils.buffs import consume_charge_buff, get_combat_power_bonus
    from sqlalchemy import text
    from utils.db_async import AsyncSessionLocal
    raw = player.get("active_buffs") or "{}"
    changed = False
    if get_combat_power_bonus(player) > 0:
        _, raw = consume_charge_buff(raw, "combat_power_bonus")
        changed = True
    if changed:
        async with AsyncSessionLocal() as session:
            await session.execute(
                text("UPDATE players SET active_buffs = :raw WHERE discord_id = :uid"),
                {"raw": raw, "uid": discord_id}
            )
            await session.commit()


async def consume_escape_buff(discord_id: str, player: dict):
    from utils.buffs import consume_once_buff, get_escape_bonus
    from sqlalchemy import text
    from utils.db_async import AsyncSessionLocal
    raw = player.get("active_buffs") or "{}"
    if get_escape_bonus(player) > 0:
        _, raw = consume_once_buff(raw, "escape_bonus_once")
        async with AsyncSessionLocal() as session:
            await session.execute(
                text("UPDATE players SET active_buffs = :raw WHERE discord_id = :uid"),
                {"raw": raw, "uid": discord_id}
            )
            await session.commit()
