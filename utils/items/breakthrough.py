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


def calc_ningdan_breakthrough_rate(player: dict, use_pill: bool = False) -> int:
    base = SPIRIT_ROOT_BASE_RATE.get(player.get("spirit_root_type", "五灵根"), 30)
    bonus = player.get("comprehension", 5) * 2 + player.get("bone", 5) * 2
    rate = int(base * 0.8) + bonus
    if use_pill:
        rate += 35
    return min(95, rate)


def calc_huaying_breakthrough_rate(player: dict, use_pill: bool = False) -> int:
    base = SPIRIT_ROOT_BASE_RATE.get(player.get("spirit_root_type", "五灵根"), 30)
    bonus = player.get("comprehension", 5) * 2 + player.get("soul", 5) * 2
    rate = int(base * 0.6) + bonus
    if use_pill:
        rate += 30
    return min(95, rate)
