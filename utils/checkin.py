import json
import os
import random
import time

_config_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "checkin_config.json")
with open(_config_path, encoding="utf-8") as _f:
    CONFIG = json.load(_f)


def _weighted_choice(tiers: list[dict]) -> dict:
    weights = [t["weight"] for t in tiers]
    return random.choices(tiers, weights=weights, k=1)[0]


def do_checkin(player: dict) -> dict:
    from utils.db import get_conn, add_item, give_equipment
    from utils.equipment import generate_equipment
    from utils.sects import TECHNIQUES

    uid = player["discord_id"]
    now = time.time()

    today = time.strftime("%Y-%m-%d", time.gmtime(now))
    last = player.get("checkin_last_date") or ""
    if last == today:
        return {"ok": False, "reason": "今日已签到，明日再来。"}

    cats = CONFIG["category_weights"]
    category = random.choices(list(cats.keys()), weights=list(cats.values()), k=1)[0]

    result = {"ok": True, "category": category}

    if category == "spirit_stones":
        tier = _weighted_choice(CONFIG["spirit_stones"]["tiers"])
        amount = random.randint(tier["min"], tier["max"])
        result["spirit_stones"] = amount
        result["tier_label"] = tier["label"]
        with get_conn() as conn:
            conn.execute(
                "UPDATE players SET spirit_stones = spirit_stones + ?, checkin_last_date = ? WHERE discord_id = ?",
                (amount, today, uid)
            )
            conn.commit()

    elif category == "material":
        tier = _weighted_choice(CONFIG["material"]["tiers"])
        item_name = random.choice(tier["pool"])
        result["item_name"] = item_name
        result["tier_label"] = tier["label"]
        add_item(uid, item_name, 1)
        with get_conn() as conn:
            conn.execute("UPDATE players SET checkin_last_date = ? WHERE discord_id = ?", (today, uid))
            conn.commit()

    elif category == "technique":
        tier = _weighted_choice(CONFIG["technique"]["tiers"])
        candidates = [name for name, info in TECHNIQUES.items() if info.get("grade") in tier["grades"]]
        if not candidates:
            candidates = list(TECHNIQUES.keys())
        learned = json.loads(player.get("techniques") or "[]")
        unlocked = [t for t in candidates if t not in learned]
        tech_name = random.choice(unlocked) if unlocked else random.choice(candidates)
        already_known = tech_name in learned
        result["technique"] = tech_name
        result["tier_label"] = tier["label"]
        result["already_known"] = already_known
        if not already_known:
            new_techs = json.dumps(learned + [tech_name], ensure_ascii=False)
            with get_conn() as conn:
                conn.execute(
                    "UPDATE players SET techniques = ?, checkin_last_date = ? WHERE discord_id = ?",
                    (new_techs, today, uid)
                )
                conn.commit()
        else:
            with get_conn() as conn:
                conn.execute("UPDATE players SET checkin_last_date = ? WHERE discord_id = ?", (today, uid))
                conn.commit()

    elif category == "equipment":
        tier = _weighted_choice(CONFIG["equipment"]["tiers"])
        eq = generate_equipment(quality=tier["quality"])
        give_equipment(uid, eq)
        result["equipment"] = eq
        result["tier_label"] = tier["label"]
        with get_conn() as conn:
            conn.execute("UPDATE players SET checkin_last_date = ? WHERE discord_id = ?", (today, uid))
            conn.commit()

    return result
