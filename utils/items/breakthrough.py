from utils import rules

# 各灵根的基础突破率、三道大关的公式系数、免丹门槛在 data/game_rules.json 的 gates（管理员可以调），用的时候读。


def _base(player: dict) -> int:
    g = rules.section("gates")
    return g["root_base"].get(player.get("spirit_root_type", "五灵根"), g["default_root_base"])


def calc_zhuji_breakthrough_rate(player: dict, use_pill: bool = False) -> int:
    g = rules.section("gates")
    z = g["zhuji"]
    bonus = player.get("comprehension", 5) * z["comprehension"] + player.get("fortune", 5) * z["fortune"]
    rate = _base(player) + bonus
    if use_pill:
        rate += z["pill"]
    return min(g["cap"], rate)


def can_skip_pill(player: dict) -> bool:
    return player.get("comprehension", 0) + player.get("fortune", 0) >= rules.section("gates")["skip_pill_min"]


def calc_ningdan_breakthrough_rate(player: dict, use_pill: bool = False) -> int:
    g = rules.section("gates")
    n = g["ningdan"]
    bonus = player.get("comprehension", 5) * n["comprehension"] + player.get("bone", 5) * n["bone"]
    rate = int(_base(player) * n["base_factor"]) + bonus
    if use_pill:
        rate += n["pill"]
    return min(g["cap"], rate)


def calc_huaying_breakthrough_rate(player: dict, use_pill: bool = False) -> int:
    g = rules.section("gates")
    h = g["huaying"]
    bonus = player.get("comprehension", 5) * h["comprehension"] + player.get("soul", 5) * h["soul"]
    rate = int(_base(player) * h["base_factor"]) + bonus
    if use_pill:
        rate += h["pill"]
    return min(g["cap"], rate)
