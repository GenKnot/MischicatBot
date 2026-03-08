import random
import uuid

QUALITY_ORDER = ["普通", "精良", "稀有", "史诗", "传说"]

QUALITY_COLOR = {
    "普通": "⬜",
    "精良": "🟩",
    "稀有": "🟦",
    "史诗": "🟪",
    "传说": "🟨",
}

QUALITY_STAT_MULT = {
    "普通": 1.0,
    "精良": 1.5,
    "稀有": 2.2,
    "史诗": 3.5,
    "传说": 6.0,
}

SLOTS = ["武器", "防具", "饰品"]

REALM_TIER = {
    "炼气": 0,
    "筑基": 1,
    "结丹": 2,
    "元婴": 3,
    "化神": 4,
    "炼虚": 5,
    "合体": 6,
    "大乘": 7,
    "真仙": 8,
    "金仙": 9,
    "太乙": 10,
    "大罗": 11,
    "道祖": 12,
}

TIER_NAMES = ["炼气", "筑基", "结丹", "元婴", "化神", "炼虚", "合体", "大乘", "真仙", "金仙", "太乙", "大罗", "道祖"]

EQUIP_TEMPLATES = {
    "武器": [
        {"name": "飞剑", "stats": ["physique", "bone"], "flavor": "御剑飞行，攻伐利器"},
        {"name": "法杖", "stats": ["soul", "comprehension"], "flavor": "凝聚神识，催动法术"},
        {"name": "战刀", "stats": ["physique", "physique"], "flavor": "横扫千军，力劈山河"},
        {"name": "灵弓", "stats": ["fortune", "soul"], "flavor": "百步穿杨，机缘加持"},
        {"name": "玄鞭", "stats": ["bone", "physique"], "flavor": "柔中带刚，缠绕敌身"},
    ],
    "防具": [
        {"name": "护身符", "stats": ["soul", "fortune"], "flavor": "神识护体，逢凶化吉"},
        {"name": "玄铁甲", "stats": ["physique", "bone"], "flavor": "坚不可摧，铁壁铜墙"},
        {"name": "灵玉佩", "stats": ["comprehension", "soul"], "flavor": "玉石温润，滋养神识"},
        {"name": "云纹袍", "stats": ["fortune", "comprehension"], "flavor": "轻盈如云，机缘护身"},
        {"name": "龟甲盾", "stats": ["physique", "physique"], "flavor": "厚重如山，防御无双"},
    ],
    "饰品": [
        {"name": "聚灵戒", "stats": ["comprehension", "soul"], "flavor": "聚拢灵气，修炼加速"},
        {"name": "血煞环", "stats": ["physique", "bone"], "flavor": "煞气凛然，战力大增"},
        {"name": "机缘珠", "stats": ["fortune", "fortune"], "flavor": "机缘加身，好运连连"},
        {"name": "神识镯", "stats": ["soul", "soul"], "flavor": "神识通明，感知万物"},
        {"name": "根骨链", "stats": ["bone", "comprehension"], "flavor": "强化根骨，突破更易"},
    ],
}

STAT_NAMES = {
    "physique": "体魄",
    "bone": "根骨",
    "soul": "神识",
    "comprehension": "悟性",
    "fortune": "机缘",
}


def get_player_tier(realm: str) -> int:
    for prefix, tier in REALM_TIER.items():
        if realm.startswith(prefix):
            return tier
    return 0


def generate_equipment(tier: int = 0, quality: str = None, slot: str = None) -> dict:
    if slot is None:
        slot = random.choice(SLOTS)
    if quality is None:
        weights = [50, 30, 15, 4, 1]
        quality = random.choices(QUALITY_ORDER, weights=weights)[0]

    template = random.choice(EQUIP_TEMPLATES[slot])
    mult = QUALITY_STAT_MULT[quality]
    base = 1 + tier // 2

    stats = {}
    for stat in template["stats"]:
        val = max(1, int(base * mult * random.uniform(0.8, 1.2)))
        stats[stat] = stats.get(stat, 0) + val

    tier_name = TIER_NAMES[min(tier, len(TIER_NAMES) - 1)]
    name = f"{tier_name}·{quality}·{template['name']}"

    return {
        "equip_id": str(uuid.uuid4())[:8],
        "name": name,
        "slot": slot,
        "quality": quality,
        "tier": tier,
        "tier_req": tier,
        "stats": stats,
        "flavor": template["flavor"],
    }


def equip_stat_bonus(equipped: list[dict]) -> dict:
    total = {}
    for eq in equipped:
        for stat, val in eq.get("stats", {}).items():
            total[stat] = total.get(stat, 0) + val
    return total


def format_equipment(eq: dict) -> str:
    icon = QUALITY_COLOR.get(eq["quality"], "⬜")
    stats_str = "  ".join(f"{STAT_NAMES.get(k, k)} +{v}" for k, v in eq["stats"].items())
    tier_name = TIER_NAMES[min(eq["tier"], len(TIER_NAMES) - 1)]
    return (
        f"{icon} **{eq['name']}**（{eq['slot']}）\n"
        f"　{eq['flavor']}\n"
        f"　需求：{tier_name}期　属性：{stats_str}"
    )
