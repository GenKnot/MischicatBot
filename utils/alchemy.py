import json
import os
import random
import time

from sqlalchemy import select, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from utils.db_async import AsyncSessionLocal, AlchemyMastery, Player, KnownRecipe

_DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")

QUALITY_NAMES = ["常规", "一纹", "二纹", "三纹", "四纹", "五纹", "六纹", "七纹", "八纹", "九纹", "十纹", "无暇"]
DAILY_LIMIT = 6
NO_YANHUO_CAP = 8

MASTERY_STAGES = [
    (0, 0),
    (10, 1),
    (30, 2),
    (100, 3),
]

ALCHEMY_EXP_PER_CRAFT = 10
ALCHEMY_EXP_THRESHOLDS = [0, 100, 250, 500, 900, 1400, 2100, 3000, 4200, 6000]


def _load_pills() -> dict:
    with open(os.path.join(_DATA_DIR, "pills.json"), encoding="utf-8") as f:
        return json.load(f)


def _load_recipes() -> list:
    with open(os.path.join(_DATA_DIR, "recipes.json"), encoding="utf-8") as f:
        return json.load(f)


PILLS = _load_pills()
RECIPES = _load_recipes()


def get_recipes_for_pill(pill_name: str) -> list[dict]:
    return [r for r in RECIPES if r["pill"] == pill_name]


def get_recipe_by_id(recipe_id: str) -> dict | None:
    for r in RECIPES:
        if r["recipe_id"] == recipe_id:
            return r
    return None


def list_available_recipes(alchemy_level: int) -> list[dict]:
    return [r for r in RECIPES if r["alchemy_level_req"] <= alchemy_level]


def get_mastery_bonus(count: int) -> tuple[int, bool]:
    bonus = 0
    master = False
    for threshold, b in reversed(MASTERY_STAGES):
        if count >= threshold:
            bonus = b
            master = (threshold == 100)
            break
    return bonus, master


def get_mastery_label(count: int) -> str:
    if count >= 100:
        return "炉火纯青"
    if count >= 30:
        return "精通"
    if count >= 10:
        return "熟悉"
    return "生疏"


def calc_quality(recipe: dict, player_soul: int, alchemy_level: int, aux_quality_bonus: int, mastery_count: int, has_yanhuo: bool = False) -> int:
    mastery_bonus, _ = get_mastery_bonus(mastery_count)
    level_bonus = max(0, alchemy_level - recipe["pill_tier"])
    soul_bonus = int(player_soul * 0.5)
    quality_score = level_bonus + soul_bonus + aux_quality_bonus + mastery_bonus
    base = random.randint(0, 6)
    result = base + quality_score
    cap = recipe["max_quality"]
    if not has_yanhuo:
        cap = min(cap, NO_YANHUO_CAP)
    result = max(0, min(result, cap))
    return result


def calc_success_rate(recipe: dict, alchemy_level: int, mastery_count: int) -> int:
    _, is_master = get_mastery_bonus(mastery_count)
    rate = recipe["base_success_rate"]
    if is_master:
        rate += 10
    rate = min(95, max(5, rate))
    return rate


def roll_failure_consequence() -> tuple[str, int]:
    roll = random.random()
    if roll < 0.70:
        return "普通失败", 0
    elif roll < 0.90:
        return "炉毁", random.randint(1, 5)
    else:
        return "丹毒反噬", random.randint(5, 15)


def is_daily_reset_needed(reset_ts: float) -> bool:
    now = time.time()
    reset_date = time.gmtime(reset_ts)
    now_date = time.gmtime(now)
    return (now_date.tm_year, now_date.tm_yday) != (reset_date.tm_year, reset_date.tm_yday)


async def get_mastery_count(discord_id: str, pill_name: str) -> int:
    async with AsyncSessionLocal() as session:
        row = await session.get(AlchemyMastery, (discord_id, pill_name))
        return row.count if row else 0


async def get_known_recipes(discord_id: str) -> set[str]:
    async with AsyncSessionLocal() as session:
        from sqlalchemy import select
        rows = await session.execute(
            select(KnownRecipe).where(KnownRecipe.discord_id == discord_id)
        )
        return {row.recipe_id for row in rows.scalars()}


async def unlock_recipe(discord_id: str, recipe_id: str):
    from sqlalchemy.dialects.sqlite import insert as sqlite_insert
    async with AsyncSessionLocal() as session:
        stmt = sqlite_insert(KnownRecipe).values(
            discord_id=discord_id, recipe_id=recipe_id
        ).on_conflict_do_nothing()
        await session.execute(stmt)
        await session.commit()


async def increment_mastery(discord_id: str, pill_name: str) -> int:
    async with AsyncSessionLocal() as session:
        stmt = sqlite_insert(AlchemyMastery).values(
            discord_id=discord_id, pill_name=pill_name, count=1
        ).on_conflict_do_update(
            index_elements=["discord_id", "pill_name"],
            set_={"count": AlchemyMastery.count + 1}
        )
        await session.execute(stmt)
        await session.commit()
        row = await session.get(AlchemyMastery, (discord_id, pill_name))
        return row.count if row else 1


async def check_and_consume_daily(discord_id: str) -> tuple[bool, int]:
    async with AsyncSessionLocal() as session:
        player = await session.get(Player, discord_id)
        if not player:
            return False, 0
        if is_daily_reset_needed(player.alchemy_daily_reset):
            player.alchemy_daily_count = 0
            player.alchemy_daily_reset = time.time()
        if player.alchemy_daily_count >= DAILY_LIMIT:
            return False, player.alchemy_daily_count
        player.alchemy_daily_count += 1
        await session.commit()
        return True, player.alchemy_daily_count


async def add_alchemy_exp(discord_id: str, exp: int) -> tuple[int, int, bool]:
    async with AsyncSessionLocal() as session:
        player = await session.get(Player, discord_id)
        if not player:
            return 0, 0, False
        player.alchemy_exp += exp
        leveled_up = False
        if player.alchemy_level < 9:
            next_threshold = ALCHEMY_EXP_THRESHOLDS[player.alchemy_level + 1] if player.alchemy_level + 1 < len(ALCHEMY_EXP_THRESHOLDS) else 999999
            if player.alchemy_exp >= next_threshold:
                player.alchemy_level += 1
                leveled_up = True
        await session.commit()
        return player.alchemy_level, player.alchemy_exp, leveled_up


async def attempt_alchemy(
    discord_id: str,
    recipe: dict,
    player_soul: int,
    alchemy_level: int,
    aux_choices: list[int],
    inventory: dict,
    has_yanhuo: bool = False,
) -> dict:
    allowed, count = await check_and_consume_daily(discord_id)
    if not allowed:
        return {"ok": False, "reason": f"今日炼丹次数已达上限（{DAILY_LIMIT}次），明日再来。", "daily_count": DAILY_LIMIT}

    for ing in recipe["main_ingredients"]:
        have = inventory.get(ing["item"], 0)
        if have < ing["qty"]:
            return {"ok": False, "reason": f"主药不足：「{ing['item']}」需要 {ing['qty']} 个，当前只有 {have} 个。"}

    aux_quality_bonus = 0
    consumed = dict(recipe["main_ingredients"])
    for i, group in enumerate(recipe["aux_groups"]):
        choice_idx = aux_choices[i] if i < len(aux_choices) else 0
        choice_idx = max(0, min(choice_idx, len(group["options"]) - 1))
        opt = group["options"][choice_idx]
        have = inventory.get(opt["item"], 0)
        if have < opt["qty"]:
            return {"ok": False, "reason": f"辅药不足：「{opt['item']}」需要 {opt['qty']} 个，当前只有 {have} 个。"}
        aux_quality_bonus += opt.get("quality_bonus", 0)
        consumed[opt["item"]] = consumed.get(opt["item"], 0) + opt["qty"]

    mastery_count = await get_mastery_count(discord_id, recipe["pill"])
    success_rate = calc_success_rate(recipe, alchemy_level, mastery_count)
    success = random.randint(1, 100) <= success_rate

    if not success:
        consequence, lifespan_loss = roll_failure_consequence()
        return {
            "ok": False,
            "success": False,
            "consequence": consequence,
            "lifespan_loss": lifespan_loss,
            "consumed": consumed,
            "success_rate": success_rate,
            "daily_count": count,
        }

    quality_idx = calc_quality(recipe, player_soul, alchemy_level, aux_quality_bonus, mastery_count, has_yanhuo)
    quality_name = QUALITY_NAMES[quality_idx]
    new_count = await increment_mastery(discord_id, recipe["pill"])
    new_level, new_exp, leveled_up = await add_alchemy_exp(discord_id, ALCHEMY_EXP_PER_CRAFT)
    known_before = await get_known_recipes(discord_id)
    first_unlock = recipe["recipe_id"] not in known_before
    await unlock_recipe(discord_id, recipe["recipe_id"])

    return {
        "ok": True,
        "success": True,
        "pill": recipe["pill"],
        "quality_idx": quality_idx,
        "quality_name": quality_name,
        "consumed": consumed,
        "success_rate": success_rate,
        "mastery_count": new_count,
        "mastery_label": get_mastery_label(new_count),
        "alchemy_level": new_level,
        "alchemy_exp": new_exp,
        "leveled_up": leveled_up,
        "first_unlock": first_unlock,
        "daily_count": count,
    }
