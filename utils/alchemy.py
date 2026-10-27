import json
import os
import random

from sqlalchemy import select, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from utils import rules, rumors
from utils.atomic import claim_daily_quota, consume_item, peek_daily_used, refuse_if_dead
from utils.db_async import AsyncSessionLocal, AlchemyMastery, Player, KnownRecipe

import logging

log = logging.getLogger(__name__)


_DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")

QUALITY_NAMES = ["常规", "一纹", "二纹", "三纹", "四纹", "五纹", "六纹", "七纹", "八纹", "九纹", "十纹", "无暇"]

# 每日次数、品质倍率、经验门槛、熟练度阶段、成功率 / 失败后果等数值在 data/game_rules.json 的 alchemy（管理员可以调），用的时候读


def cfg() -> dict:
    return rules.section("alchemy")


def daily_limit() -> int:
    return cfg()["daily_limit"]


def no_yanhuo_cap() -> int:
    return cfg()["no_yanhuo_cap"]


def quality_multipliers() -> list[float]:
    return cfg()["quality_multipliers"]


def exp_thresholds() -> list[int]:
    return cfg()["exp_thresholds"]


def _load_pills() -> dict:
    with open(os.path.join(_DATA_DIR, "pills.json"), encoding="utf-8") as f:
        data = json.load(f)
    # `_schema_notes` 之类下划线开头的键是给人看的说明，不是丹药；
    # 以前被当成一件物品并进了 ITEMS（网页物品页搜索会因此 KeyError）（B75）
    return {k: v for k, v in data.items() if not k.startswith("_")}


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
    stages = cfg()["mastery_stages"]
    bonus, master = 0, False
    for i in range(len(stages) - 1, -1, -1):
        if count >= stages[i]["crafts"]:
            bonus, master = stages[i]["bonus"], i == len(stages) - 1          # 最后一档是『炉火纯青』
            break
    return bonus, master


def get_mastery_label(count: int) -> str:
    stages = cfg()["mastery_stages"]
    return next(s["label"] for s in reversed(stages) if count >= s["crafts"])


def calc_quality(recipe: dict, player_soul: int, alchemy_level: int, aux_quality_bonus: int, mastery_count: int, has_yanhuo: bool = False) -> int:
    mastery_bonus, _ = get_mastery_bonus(mastery_count)
    level_bonus = max(0, alchemy_level - recipe["pill_tier"])
    q = cfg()["quality"]
    soul_bonus = int(player_soul * q["soul_factor"])
    quality_score = level_bonus + soul_bonus + aux_quality_bonus + mastery_bonus
    base = random.randint(0, q["roll_max"])
    result = base + quality_score
    cap = recipe["max_quality"]
    if not has_yanhuo:
        cap = min(cap, no_yanhuo_cap())
    result = max(0, min(result, cap))
    return result


def calc_success_rate(recipe: dict, alchemy_level: int, mastery_count: int, free_mix: bool = False) -> int:
    _, is_master = get_mastery_bonus(mastery_count)
    s = cfg()["success"]
    rate = recipe["base_success_rate"]
    if is_master:
        rate += s["master_bonus"]
    if free_mix:
        rate = int(rate * s["free_mix_factor"])
    rate = min(s["max"], max(s["min"], rate))
    return rate


def roll_failure_consequence() -> tuple[str, int]:
    f = cfg()["failure"]
    roll = random.random()
    if roll < f["plain_p"]:
        return "普通失败", 0
    elif roll < f["plain_p"] + f["ruin_p"]:
        return "炉毁", random.randint(*f["ruin_loss"])
    else:
        return "丹毒反噬", random.randint(*f["poison_loss"])


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


async def get_known_recipes_with_choices(discord_id: str) -> dict[str, list[int]]:
    async with AsyncSessionLocal() as session:
        rows = await session.execute(
            select(KnownRecipe).where(KnownRecipe.discord_id == discord_id)
        )
        result = {}
        for row in rows.scalars():
            try:
                import json as _json
                result[row.recipe_id] = _json.loads(row.aux_choices or "[]")
            except Exception:
                result[row.recipe_id] = []
        return result


async def unlock_recipe(discord_id: str, recipe_id: str, aux_choices: list[int] = None):
    import json as _json
    choices_str = _json.dumps(aux_choices or [])
    async with AsyncSessionLocal() as session:
        stmt = sqlite_insert(KnownRecipe).values(
            discord_id=discord_id, recipe_id=recipe_id, aux_choices=choices_str
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
    """占用今日一次炼丹次数。返回 (是否成功, 占用后的今日次数)。"""
    async with AsyncSessionLocal() as session:
        used = await claim_daily_quota(
            session, discord_id, Player.alchemy_daily_count, Player.alchemy_daily_reset, daily_limit()
        )
        if used is None:
            return False, await peek_daily_used(
                session, discord_id, Player.alchemy_daily_count, Player.alchemy_daily_reset
            )
        await session.commit()
        return True, used


async def add_alchemy_exp(discord_id: str, exp: int) -> tuple[int, int, bool]:
    """原子加炼丹经验，够门槛则升一级。经验用 `exp = exp + n`（并发炼丹不丢更新），
    升级用 `WHERE alchemy_level = 旧等级` 做 CAS（B48）。"""
    async with AsyncSessionLocal() as session:
        res = await session.execute(
            update(Player).where(Player.discord_id == discord_id)
            .values(alchemy_exp=Player.alchemy_exp + exp)
            .returning(Player.alchemy_level, Player.alchemy_exp)
        )
        got = res.first()
        if got is None:
            return 0, 0, False
        level, total = got
        leveled_up = False
        if level < 9:
            nxt = level + 1
            threshold = exp_thresholds()[nxt] if nxt < len(exp_thresholds()) else 999999
            if total >= threshold:
                up = await session.execute(
                    update(Player).where(Player.discord_id == discord_id, Player.alchemy_level == level)
                    .values(alchemy_level=nxt)
                )
                if up.rowcount == 1:
                    level, leveled_up = nxt, True
        await session.commit()
        return level, total, leveled_up


async def attempt_alchemy(
    discord_id: str,
    recipe: dict,
    player_soul: int,
    alchemy_level: int,
    aux_choices: list[int],
    inventory: dict,
    has_yanhuo: bool = False,
    free_mix: bool = False,
) -> dict:
    # 顺序：校验 → 扣料 → 占次数 → 掷骰。原先先占次数再掷骰，材料不足会白丢一次。
    # 这一段只校验，为的是给准确提示；真正的扣减在下面。
    for ing in recipe["main_ingredients"]:
        have = inventory.get(ing["item"], 0)
        if have < ing["qty"]:
            return {"ok": False, "reason": f"主药不足：「{ing['item']}」需要 {ing['qty']} 个，当前只有 {have} 个。"}

    aux_quality_bonus = 0
    consumed: dict[str, int] = {}
    for ing in recipe["main_ingredients"]:
        consumed[ing["item"]] = consumed.get(ing["item"], 0) + ing["qty"]
    for i, group in enumerate(recipe["aux_groups"]):
        choice_idx = aux_choices[i] if i < len(aux_choices) else 0
        choice_idx = max(0, min(choice_idx, len(group["options"]) - 1))
        opt = group["options"][choice_idx]
        have = inventory.get(opt["item"], 0)
        if have < opt["qty"]:
            return {"ok": False, "reason": f"辅药不足：「{opt['item']}」需要 {opt['qty']} 个，当前只有 {have} 个。"}
        aux_quality_bonus += opt.get("quality_bonus", 0)
        consumed[opt["item"]] = consumed.get(opt["item"], 0) + opt["qty"]

    async with AsyncSessionLocal() as session:
        if (refused := await refuse_if_dead(session, discord_id)):
            return refused
        for item_id, qty in consumed.items():
            if not await consume_item(session, discord_id, item_id, qty):
                await session.rollback()
                return {"ok": False, "reason": f"药材不足：「{item_id}」需要 {qty} 个。"}
        count = await claim_daily_quota(
            session, discord_id,
            Player.alchemy_daily_count, Player.alchemy_daily_reset, daily_limit(),
        )
        if count is None:
            await session.rollback()          # 连带退回刚扣的药材
            return {"ok": False,
                    "reason": f"今日炼丹次数已达上限（{daily_limit()}次），明日再来。",
                    "daily_count": daily_limit()}
        await session.commit()

    mastery_count = await get_mastery_count(discord_id, recipe["pill"])
    success_rate = calc_success_rate(recipe, alchemy_level, mastery_count, free_mix=free_mix)
    success = random.randint(1, 100) <= success_rate
    log.debug("炼丹 %s recipe=%s rate=%s%% free_mix=%s success=%s",
              discord_id, recipe["recipe_id"], success_rate, free_mix, success)

    if not success:
        consequence, lifespan_loss = roll_failure_consequence()
        result = {
            "ok": False,
            "success": False,
            "consequence": consequence,
            "lifespan_loss": lifespan_loss,
            "consumed": consumed,
            "success_rate": success_rate,
            "daily_count": count,
        }
        await rumors.on_alchemy(discord_id, result)
        return result

    quality_idx = calc_quality(recipe, player_soul, alchemy_level, aux_quality_bonus, mastery_count, has_yanhuo)
    quality_name = QUALITY_NAMES[quality_idx]
    new_count = await increment_mastery(discord_id, recipe["pill"])
    new_level, new_exp, leveled_up = await add_alchemy_exp(discord_id, cfg()["exp_per_craft"])
    known_before = await get_known_recipes(discord_id)
    first_unlock = recipe["recipe_id"] not in known_before
    await unlock_recipe(discord_id, recipe["recipe_id"], aux_choices)

    exam_passed = False
    if recipe["recipe_id"] == "juqiwan_exam" and alchemy_level == 0:
        async with AsyncSessionLocal() as session:
            p = await session.get(Player, discord_id)
            if p and p.alchemy_level == 0:
                p.alchemy_level = 1
                p.alchemy_exp = 0
                p.exam_attempts_left = 0
                await session.commit()
        exam_passed = True
        new_level = 1

    result = {
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
        "exam_passed": exam_passed,
    }
    await rumors.on_alchemy(discord_id, result)
    return result
