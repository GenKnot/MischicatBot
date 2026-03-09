import random
from utils.quests.common import COMMON_QUESTS
from utils.quests.elite import ELITE_QUESTS
from utils.quests.legendary import LEGENDARY_QUESTS
from utils.realms import get_realm_index

ALL_QUESTS = {q["id"]: q for q in COMMON_QUESTS + ELITE_QUESTS + LEGENDARY_QUESTS}


def _meets_req(player: dict, req: dict) -> bool:
    if req.get("min_realm"):
        if get_realm_index(player["realm"]) < get_realm_index(req["min_realm"]):
            return False
    if req.get("min_stat"):
        for stat, val in req["min_stat"].items():
            if player.get(stat, 0) < val:
                return False
    if req.get("min_reputation"):
        if player.get("reputation", 0) < req["min_reputation"]:
            return False
    return True


def get_tavern_quests(player: dict) -> dict:
    available_common = [q for q in COMMON_QUESTS if _meets_req(player, q["req"])]
    available_elite = [q for q in ELITE_QUESTS if _meets_req(player, q["req"])]
    available_legendary = [q for q in LEGENDARY_QUESTS if _meets_req(player, q["req"])]

    rep = player.get("reputation", 0)
    locked = []
    if rep < 50 and any(get_realm_index(player["realm"]) >= get_realm_index(q["req"].get("min_realm", "炼气期1层")) for q in ELITE_QUESTS):
        locked.append(f"精英任务需声望 ≥ 50（当前 {rep}）")
    if rep < 150 and any(get_realm_index(player["realm"]) >= get_realm_index(q["req"].get("min_realm", "炼气期1层")) for q in LEGENDARY_QUESTS):
        locked.append(f"传说任务需声望 ≥ 150（当前 {rep}）")

    result = {}
    if available_common:
        result["普通"] = random.sample(available_common, min(3, len(available_common)))
    if available_elite:
        result["精英"] = random.sample(available_elite, min(2, len(available_elite)))
    if available_legendary:
        result["传说"] = random.sample(available_legendary, min(1, len(available_legendary)))
    if locked:
        result["_locked"] = locked
    return result


def get_quest(quest_id: str) -> dict | None:
    return ALL_QUESTS.get(quest_id)
