import json
import os
import random
import time

from utils.db_async import AsyncSessionLocal, Player

_config_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "checkin_config.json")
with open(_config_path, encoding="utf-8") as _f:
    CONFIG = json.load(_f)


def _weighted_choice(tiers: list[dict]) -> dict:
    weights = [t["weight"] for t in tiers]
    return random.choices(tiers, weights=weights, k=1)[0]


async def do_checkin(uid: str) -> dict:
    from utils.db import add_item, give_equipment
    from utils.equipment import generate_equipment
    from utils.sects import TECHNIQUES

    today = time.strftime("%Y-%m-%d", time.gmtime())

    async with AsyncSessionLocal() as session:
        player = await session.get(Player, uid)
        if not player:
            return {"ok": False, "reason": "角色不存在。"}

        if (player.checkin_last_date or "") == today:
            return {"ok": False, "reason": "今日已签到，明日再来。"}

        cats = CONFIG["category_weights"]
        category = random.choices(list(cats.keys()), weights=list(cats.values()), k=1)[0]
        result = {"ok": True, "category": category}

        if category == "spirit_stones":
            tier = _weighted_choice(CONFIG["spirit_stones"]["tiers"])
            amount = random.randint(tier["min"], tier["max"])
            result["spirit_stones"] = amount
            result["tier_label"] = tier["label"]
            player.spirit_stones += amount

        elif category == "material":
            tier = _weighted_choice(CONFIG["material"]["tiers"])
            item_name = random.choice(tier["pool"])
            result["item_name"] = item_name
            result["tier_label"] = tier["label"]
            add_item(uid, item_name, 1)

        elif category == "technique":
            tier = _weighted_choice(CONFIG["technique"]["tiers"])
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
            tier = _weighted_choice(CONFIG["equipment"]["tiers"])
            eq = generate_equipment(quality=tier["quality"])
            give_equipment(uid, eq)
            result["equipment"] = eq
            result["tier_label"] = tier["label"]

        player.checkin_last_date = today
        await session.commit()

    return result
