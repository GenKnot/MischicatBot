ITEMS = {
    "筑基丹": {
        "name": "筑基丹",
        "desc": "炼气期修士突破筑基的必备丹药，服用后大幅提升突破成功率。",
        "type": "pill",
        "effect": {"breakthrough_bonus": 40},
    },
    "聚灵丹": {
        "name": "聚灵丹",
        "desc": "服用后修炼速度提升50%，持续效果在下次修炼时生效。",
        "type": "pill",
        "effect": {"cultivation_speed_bonus": 50},
    },
    "续命丹": {
        "name": "续命丹",
        "desc": "珍贵丹药，服用后恢复30年寿元。",
        "type": "pill",
        "effect": {"lifespan": 30},
    },
    "破障丹": {
        "name": "破障丹",
        "desc": "突破瓶颈时服用，提升所有境界突破成功率20%。",
        "type": "pill",
        "effect": {"breakthrough_bonus": 20},
    },
}

SPIRIT_ROOT_BASE_RATE = {
    "单灵根": 90,
    "双灵根": 75,
    "三灵根": 60,
    "变异灵根": 70,
    "四灵根": 45,
    "五灵根": 30,
}

def calc_zhuji_breakthrough_rate(player: dict, use_pill: bool = False) -> int:
    base = SPIRIT_ROOT_BASE_RATE.get(player.get("spirit_root_type", "五灵根"), 30)
    bonus = player.get("comprehension", 5) * 3 + player.get("fortune", 5) * 2
    rate = base + bonus
    if use_pill:
        rate += 40
    return min(95, rate)

def can_skip_pill(player: dict) -> bool:
    return player.get("comprehension", 0) + player.get("fortune", 0) >= 20
