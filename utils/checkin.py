import json
import random
import time
from functools import lru_cache
from pathlib import Path

from sqlalchemy import or_, update

from utils import settings_hub
from utils.atomic import DEAD_REASON, grant_item, grant_stones
from utils.db_async import AsyncSessionLocal, Player

_PATH = Path(__file__).resolve().parent.parent / "data" / "checkin_config.json"
CATEGORIES = ("spirit_stones", "material", "technique", "equipment")


@lru_cache(maxsize=1)
def _load() -> dict:
    return settings_hub.read(_PATH)


def cfg() -> dict:
    """签到奖励配置（data/checkin_config.json，管理员可以 `cat!调参` 修改数字，只读）。"""
    return _load()


def validate(c: dict) -> list[str]:
    errors = []
    cw = c.get("category_weights", {})
    if set(cw) != set(CATEGORIES) or any(v < 0 for v in cw.values()) or sum(cw.values()) <= 0:
        errors.append(f"category_weights 需要 {CATEGORIES}，权重非负且总和 > 0")
    for cat in CATEGORIES:
        tiers = c.get(cat, {}).get("tiers", [])
        if not tiers or any(t.get("weight", -1) < 0 for t in tiers) or sum(t.get("weight", 0) for t in tiers) <= 0:
            errors.append(f"{cat}.tiers 至少一档，权重非负且总和 > 0")
    for t in c.get("spirit_stones", {}).get("tiers", []):
        if not 0 <= t.get("min", -1) <= t.get("max", -2):
            errors.append(f"spirit_stones.tiers {t.get('label')}: 0 ≤ min ≤ max")
    return errors


def _weighted_choice(tiers: list[dict]) -> dict:
    weights = [t["weight"] for t in tiers]
    return random.choices(tiers, weights=weights, k=1)[0]


async def do_checkin(uid: str) -> dict:
    from utils.equipment_db import new_equipment_row
    from utils.equipment import generate_equipment
    from utils.sects import TECHNIQUES

    today = time.strftime("%Y-%m-%d", time.gmtime())

    async with AsyncSessionLocal() as session:
        player = await session.get(Player, uid)
        if not player:
            return {"ok": False, "reason": "角色不存在。"}
        if player.is_dead:
            return {"ok": False, "reason": DEAD_REASON}

        # 原子占用今日签到名额：连点时只有一次能把日期改成今天，
        # 后续点击 rowcount 为 0，不会重复发奖。
        claimed = await session.execute(
            update(Player)
            .where(
                Player.discord_id == uid,
                or_(Player.checkin_last_date.is_(None),
                    Player.checkin_last_date != today),
            )
            .values(checkin_last_date=today)
        )
        if claimed.rowcount != 1:
            return {"ok": False, "reason": "今日已签到，明日再来。"}

        cats = cfg()["category_weights"]
        category = random.choices(list(cats.keys()), weights=list(cats.values()), k=1)[0]
        result = {"ok": True, "category": category}

        if category == "spirit_stones":
            tier = _weighted_choice(cfg()["spirit_stones"]["tiers"])
            amount = random.randint(tier["min"], tier["max"])
            result["spirit_stones"] = amount
            result["tier_label"] = tier["label"]
            await grant_stones(session, uid, amount)

        elif category == "material":
            tier = _weighted_choice(cfg()["material"]["tiers"])
            item_name = random.choice(tier["pool"])
            result["item_name"] = item_name
            result["tier_label"] = tier["label"]
            await grant_item(session, uid, item_name, 1)

        elif category == "technique":
            tier = _weighted_choice(cfg()["technique"]["tiers"])
            candidates = [name for name, info in TECHNIQUES.items() if info.get("grade") in tier["grades"]]
            if not candidates:
                candidates = list(TECHNIQUES.keys())
            learned = json.loads(player.techniques or "[]")
            unlocked = [t for t in candidates if t not in learned]
            tech_name = random.choice(unlocked) if unlocked else random.choice(candidates)
            already_known = tech_name in learned
            result["technique"] = tech_name
            result["tier_label"] = tier["label"]
            result["already_known"] = already_known
            if not already_known:
                player.techniques = json.dumps(learned + [tech_name], ensure_ascii=False)

        elif category == "equipment":
            tier = _weighted_choice(cfg()["equipment"]["tiers"])
            eq = generate_equipment(quality=tier["quality"])
            session.add(new_equipment_row(uid, eq))
            result["equipment"] = eq
            result["tier_label"] = tier["label"]

        await session.commit()

    return result
