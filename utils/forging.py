import random
import time

from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy import select

from utils.db_async import AsyncSessionLocal, Player
from utils.equipment import generate_equipment, QUALITY_ORDER

FORGING_CITIES = ["铸剑城", "玄铁城", "北冥港", "落云城", "天工城"]

FORGING_EXP_THRESHOLDS = [0, 0, 80, 200, 400, 700, 1100, 1600, 2300, 3200]
FORGING_EXP_PER_CRAFT = 12
DAILY_LIMIT = 5

ORE_TIERS = [
    "铜矿石",
    "铁矿石",
    "精铁矿",
    "灵铁矿",
    "秘银矿",
    "玄铁矿",
    "陨铁矿",
]

ORE_TO_EQUIP_TIER = {
    "铜矿石": 0,
    "铁矿石": 1,
    "精铁矿": 2,
    "灵铁矿": 3,
    "秘银矿": 4,
    "玄铁矿": 5,
    "陨铁矿": 6,
}

FORGING_LEVEL_MAX_QUALITY = {
    1: "普通",
    2: "普通",
    3: "精良",
    4: "精良",
    5: "稀有",
    6: "稀有",
    7: "史诗",
    8: "史诗",
    9: "传说",
}

SLOT_MAIN_ORE_QTY = {
    "武器": 3,
    "防具": 3,
    "饰品": 2,
}

AUX_WOOD_STAT_BIAS = {
    "铁桦木": ["physique", "bone"],
    "紫檀灵木": ["soul", "comprehension"],
    "雷击木": ["physique", "soul"],
    "寒霜柏": ["soul", "bone"],
    "火凤梧桐": ["physique", "fortune"],
    "龙血木": ["physique", "bone"],
    "星辰木": ["soul", "fortune"],
    "风吟木": ["fortune", "comprehension"],
    "月华桂": ["soul", "comprehension"],
}

AUX_HERB_STAT_BIAS = {
    "灵芝草": ["comprehension", "soul"],
    "碧灵花": ["soul", "fortune"],
    "九节菖蒲": ["bone", "physique"],
    "天山雪莲": ["comprehension", "fortune"],
    "血灵芝": ["physique", "bone"],
    "玄冥草": ["soul", "comprehension"],
    "紫云英": ["fortune", "soul"],
    "金丝草": ["comprehension", "bone"],
}

FORGING_MASTERY_STAGES = [
    (0, "生疏", 0),
    (10, "熟悉", 5),
    (30, "精通", 12),
    (100, "炉火纯青", 20),
]

RELIQUARY_COST_MULTIPLIER = {
    "普通": 1,
    "精良": 2,
    "稀有": 4,
    "史诗": 8,
    "传说": 15,
}


def get_forging_mastery(count: int) -> tuple[str, int]:
    label, bonus = "生疏", 0
    for threshold, lbl, b in FORGING_MASTERY_STAGES:
        if count >= threshold:
            label, bonus = lbl, b
    return label, bonus


def get_forging_level_label(level: int) -> str:
    return f"{level}品炼器师" if level > 0 else "未入门"


def calc_forge_success_rate(forging_level: int, target_quality: str, bone: int, mastery_count: int) -> int:
    quality_idx = QUALITY_ORDER.index(target_quality)
    base = 85 - quality_idx * 15
    level_bonus = (forging_level - 1) * 5
    bone_bonus = min(bone // 3, 10)
    _, mastery_bonus = get_forging_mastery(mastery_count)
    rate = base + level_bonus + bone_bonus + mastery_bonus
    return max(5, min(95, rate))


def get_max_quality_for_level(forging_level: int) -> str:
    return FORGING_LEVEL_MAX_QUALITY.get(forging_level, "普通")


def get_available_qualities(forging_level: int) -> list[str]:
    effective_level = max(forging_level, 1)
    max_q = get_max_quality_for_level(effective_level)
    max_idx = QUALITY_ORDER.index(max_q)
    return QUALITY_ORDER[: max_idx + 1]


def roll_forge_failure() -> tuple[str, int]:
    roll = random.random()
    if roll < 0.80:
        return "普通失败", 0
    else:
        return "走火", random.randint(1, 5)


def is_daily_reset_needed(reset_ts: float) -> bool:
    now = time.time()
    reset_date = time.gmtime(reset_ts)
    now_date = time.gmtime(now)
    return (now_date.tm_year, now_date.tm_yday) != (reset_date.tm_year, reset_date.tm_yday)


async def get_forging_mastery_count(discord_id: str) -> int:
    async with AsyncSessionLocal() as session:
        player = await session.get(Player, discord_id)
        return player.forging_mastery_count if player else 0


async def add_forging_exp(discord_id: str, exp: int) -> tuple[int, int, bool]:
    async with AsyncSessionLocal() as session:
        player = await session.get(Player, discord_id)
        if not player:
            return 0, 0, False
        player.forging_exp += exp
        leveled_up = False
        if player.forging_level < 9:
            next_threshold = FORGING_EXP_THRESHOLDS[player.forging_level + 1] if player.forging_level + 1 < len(FORGING_EXP_THRESHOLDS) else 999999
            if player.forging_exp >= next_threshold:
                player.forging_level += 1
                leveled_up = True
        await session.commit()
        return player.forging_level, player.forging_exp, leveled_up


async def increment_forging_mastery(discord_id: str) -> int:
    async with AsyncSessionLocal() as session:
        player = await session.get(Player, discord_id)
        if not player:
            return 0
        player.forging_mastery_count = (player.forging_mastery_count or 0) + 1
        await session.commit()
        return player.forging_mastery_count


async def check_and_consume_daily(discord_id: str) -> tuple[bool, int]:
    async with AsyncSessionLocal() as session:
        player = await session.get(Player, discord_id)
        if not player:
            return False, 0
        if is_daily_reset_needed(player.forging_daily_reset or 0):
            player.forging_daily_count = 0
            player.forging_daily_reset = time.time()
        if (player.forging_daily_count or 0) >= DAILY_LIMIT:
            return False, player.forging_daily_count
        player.forging_daily_count = (player.forging_daily_count or 0) + 1
        await session.commit()
        return True, player.forging_daily_count


async def attempt_forge(
    discord_id: str,
    slot: str,
    ore_name: str,
    target_quality: str,
    aux_wood: str | None,
    aux_herb: str | None,
    inventory: dict,
    player_bone: int,
    forging_level: int,
) -> dict:
    allowed, daily_count = await check_and_consume_daily(discord_id)
    if not allowed:
        return {"ok": False, "reason": f"今日锻造次数已达上限（{DAILY_LIMIT}次），明日再来。"}

    ore_qty_needed = SLOT_MAIN_ORE_QTY[slot]
    if inventory.get(ore_name, 0) < ore_qty_needed:
        return {"ok": False, "reason": f"主材不足：「{ore_name}」需要 {ore_qty_needed} 个，当前只有 {inventory.get(ore_name, 0)} 个。"}

    if aux_wood and inventory.get(aux_wood, 0) < 1:
        return {"ok": False, "reason": f"辅材不足：「{aux_wood}」需要 1 个。"}

    if aux_herb and inventory.get(aux_herb, 0) < 1:
        return {"ok": False, "reason": f"辅材不足：「{aux_herb}」需要 1 个。"}

    max_quality = get_max_quality_for_level(forging_level)
    if forging_level > 0 and QUALITY_ORDER.index(target_quality) > QUALITY_ORDER.index(max_quality):
        return {"ok": False, "reason": f"炼器品级不足，当前最高可锻造「{max_quality}」品质。"}

    mastery_count = await get_forging_mastery_count(discord_id)
    success_rate = calc_forge_success_rate(forging_level, target_quality, player_bone, mastery_count)
    success = random.randint(1, 100) <= success_rate

    consumed = {ore_name: ore_qty_needed}
    if aux_wood:
        consumed[aux_wood] = 1
    if aux_herb:
        consumed[aux_herb] = 1

    from utils.inventory import remove_item
    for item_name, qty in consumed.items():
        await remove_item(discord_id, item_name, qty)

    if not success:
        consequence, lifespan_loss = roll_forge_failure()
        if lifespan_loss > 0:
            async with AsyncSessionLocal() as session:
                player = await session.get(Player, discord_id)
                if player:
                    player.lifespan = max(1, player.lifespan - lifespan_loss)
                    await session.commit()
        return {
            "ok": False,
            "success": False,
            "consequence": consequence,
            "lifespan_loss": lifespan_loss,
            "consumed": consumed,
            "success_rate": success_rate,
            "daily_count": daily_count,
        }

    equip_tier = ORE_TO_EQUIP_TIER.get(ore_name, 0)

    stat_bias = []
    if aux_wood and aux_wood in AUX_WOOD_STAT_BIAS:
        stat_bias.extend(AUX_WOOD_STAT_BIAS[aux_wood])
    if aux_herb and aux_herb in AUX_HERB_STAT_BIAS:
        stat_bias.extend(AUX_HERB_STAT_BIAS[aux_herb])

    equipment = generate_equipment(tier=equip_tier, quality=target_quality, slot=slot, stat_bias=stat_bias if stat_bias else None)

    from utils.equipment_db import give_equipment
    await give_equipment(discord_id, equipment)

    new_count = await increment_forging_mastery(discord_id)
    new_level, new_exp, leveled_up = await add_forging_exp(discord_id, FORGING_EXP_PER_CRAFT)

    exam_passed = False
    async with AsyncSessionLocal() as session:
        player = await session.get(Player, discord_id)
        if player and player.forging_level == 0:
            player.forging_level = 1
            player.forging_exp = 0
            await session.commit()
            new_level = 1
            leveled_up = True
            exam_passed = True

    return {
        "ok": True,
        "success": True,
        "equipment": equipment,
        "consumed": consumed,
        "success_rate": success_rate,
        "mastery_count": new_count,
        "mastery_label": get_forging_mastery(new_count)[0],
        "forging_level": new_level,
        "forging_exp": new_exp,
        "leveled_up": leveled_up,
        "exam_passed": exam_passed,
        "daily_count": daily_count,
    }


async def attempt_reforge(
    discord_id: str,
    equip_id: str,
    ore_name: str,
    inventory: dict,
    spirit_stones: int,
) -> dict:
    from utils.equipment_db import get_equipment_by_id
    from utils.equipment import generate_equipment, QUALITY_ORDER
    from utils.inventory import remove_item
    import json

    eq = await get_equipment_by_id(equip_id, discord_id)
    if not eq:
        return {"ok": False, "reason": "装备不存在或不属于你。"}

    quality = eq["quality"]
    ore_tier_needed = QUALITY_ORDER.index(quality)
    ore_needed = ORE_TIERS[min(ore_tier_needed, len(ORE_TIERS) - 1)]

    if ore_name != ore_needed:
        return {"ok": False, "reason": f"淬炼「{quality}」品质装备需要「{ore_needed}」。"}

    ore_qty = 2
    if inventory.get(ore_name, 0) < ore_qty:
        return {"ok": False, "reason": f"「{ore_name}」不足，需要 {ore_qty} 个。"}

    stone_cost = 200 * RELIQUARY_COST_MULTIPLIER[quality]
    if spirit_stones < stone_cost:
        return {"ok": False, "reason": f"灵石不足，淬炼需要 {stone_cost} 灵石。"}

    await remove_item(discord_id, ore_name, ore_qty)
    async with AsyncSessionLocal() as session:
        player = await session.get(Player, discord_id)
        if player:
            player.spirit_stones -= stone_cost
            await session.commit()

    new_eq = generate_equipment(tier=eq["tier"], quality=quality, slot=eq["slot"])

    from utils.equipment_db import update_equipment_stats
    await update_equipment_stats(equip_id, new_eq["name"], new_eq["stats"], new_eq["flavor"])

    return {
        "ok": True,
        "old_name": eq["name"],
        "new_name": new_eq["name"],
        "new_stats": new_eq["stats"],
        "ore_used": ore_name,
        "ore_qty": ore_qty,
        "stone_cost": stone_cost,
    }


EXAM_COST = 500
EXAM_MATERIALS = {"铜矿石": 6, "铁矿石": 3}


async def start_forging_exam(discord_id: str) -> dict:
    from utils.inventory import add_item
    async with AsyncSessionLocal() as session:
        player = await session.get(Player, discord_id)
        if not player:
            return {"ok": False, "reason": "角色不存在。"}
        if player.forging_level > 0:
            return {"ok": False, "reason": "你已经是炼器师了。"}
        if player.spirit_stones < EXAM_COST:
            return {"ok": False, "reason": f"灵石不足，考核需缴纳 {EXAM_COST} 灵石。"}
        player.spirit_stones -= EXAM_COST
        await session.commit()
    for item, qty in EXAM_MATERIALS.items():
        await add_item(discord_id, item, qty)
    return {"ok": True}


async def pass_forging_exam(discord_id: str) -> bool:
    async with AsyncSessionLocal() as session:
        player = await session.get(Player, discord_id)
        if not player or player.forging_level > 0:
            return False
        player.forging_level = 1
        player.forging_exp = 0
        await session.commit()
    return True
