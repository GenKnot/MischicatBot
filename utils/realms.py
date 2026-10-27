import random

from utils import rules

# 13 个大境，REALMS 由这里派生，免得两份列表对不上。
REALM_GROUPS = [
    ("炼气期", [f"炼气期{i}层" for i in range(1, 11)]),
    ("筑基期", [f"筑基期{i}层" for i in range(1, 11)]),
    ("结丹期", ["结丹期初期", "结丹期中期", "结丹期后期"]),
    ("元婴期", ["元婴期初期", "元婴期中期", "元婴期后期"]),
    ("化神期", ["化神期初期", "化神期中期", "化神期后期"]),
    ("炼虚期", ["炼虚期初期", "炼虚期中期", "炼虚期后期"]),
    ("合体期", ["合体期初期", "合体期中期", "合体期后期"]),
    ("大乘期", ["大乘期初期", "大乘期中期", "大乘期后期"]),
    ("真仙", ["真仙初期", "真仙中期", "真仙后期"]),
    ("金仙", ["金仙初期", "金仙中期", "金仙后期"]),
    ("太乙", ["太乙初期", "太乙中期", "太乙后期"]),
    ("大罗", ["大罗初期", "大罗中期", "大罗后期"]),
    ("道祖", ["道祖"]),
]

REALMS = [realm for _major, subs in REALM_GROUPS for realm in subs]

# 小境 → 大境。用查表而不是靠字符串切割：「真仙初期」这类没有"期"字后缀的
# 大境名，切割规则会算错。
MAJOR_OF_REALM = {
    realm: major for major, subs in REALM_GROUPS for realm in subs
}


def major_realm(realm: str) -> str | None:
    """返回该小境所属的大境；境界名不在体系内时返回 None。"""
    return MAJOR_OF_REALM.get(realm)

# 每个小境的突破所需修为、寿元上限、突破成功率、失败后果、功法栏位：节奏参数在 data/game_rules.json 的 realms（管理员可以调），用的时候读。
_INDEX = {realm: i for i, realm in enumerate(REALMS)}


def _cfg() -> dict:
    return rules.section("realms")


def _breakthrough_base(realm: str) -> float:
    c = _cfg()["breakthrough"]
    i = _INDEX.get(realm)
    if i is None:
        return c["unknown"]
    if i < 10:
        return c["tier1_base"] - i * c["tier1_step"]
    if i < 20:
        return c["tier2_base"] - (i - 10) * c["tier2_step"]
    late = c["late_rates"]
    return late[i - 20] if i - 20 < len(late) else c["late_default"]


def get_realm_index(realm: str) -> int:
    try:
        return REALMS.index(realm)
    except ValueError:
        return 0


def cultivation_needed(realm: str) -> int:
    c = _cfg()["cultivation_needed"]
    i = _INDEX.get(realm)
    if i is None:
        return c["unknown"]
    return c["tier1"] if i < 10 else c["tier2"] if i < 20 else c["late_base"] + (i - 20) * c["late_step"]


def lifespan_max_for_realm(realm: str) -> int:
    c = _cfg()["lifespan_max"]
    i = _INDEX.get(realm)
    if i is None:
        return c["unknown"]
    if i < 10:
        return c["tier1_base"] + i * c["tier1_step"]
    if i < 20:
        return c["tier2_base"] + (i - 10) * c["tier2_step"]
    return c["table"][realm]


def next_realm(realm: str) -> str | None:
    idx = get_realm_index(realm)
    if idx + 1 < len(REALMS):
        return REALMS[idx + 1]
    return None


def breakthrough_success_rate(realm: str, physique: int, bone: int, cultivation: int) -> float:
    c = _cfg()["breakthrough"]
    base = _breakthrough_base(realm)
    stat_bonus = ((physique - 5) + (bone - 5)) * c["stat_bonus"]
    needed = cultivation_needed(realm)
    overflow_bonus = max(0, (cultivation - needed) / needed) * c["overflow_bonus"]
    return min(c["cap"], max(c["floor"], base + stat_bonus + overflow_bonus))


FAIL_LIGHT = "light"
FAIL_HEAVY = "heavy"
FAIL_DEVIATE = "deviate"


def roll_failure_outcome(realm: str) -> str:
    """突破**已经失败**之后，掷出失败的严重程度。

    只管「怎么败」，不管「成不成」。需要失败类型时用这个，**不要**再调一次
    `roll_breakthrough` 然后丢掉第一个返回值：那次掷骰自己也可能掷出成功，
    outcome 就是 None，而 `apply_failure` 对未知类型一律按走火入魔处理 ——
    修为高、成功率大的人反而最容易走火入魔（按钮突破曾因此踩坑，见 .gk/ISSUES.md B4）。
    """
    f = _cfg()["failure"]
    w = f["early_weights"] if get_realm_index(realm) < f["split_index"] else f["late_weights"]
    return random.choices([FAIL_LIGHT, FAIL_HEAVY, FAIL_DEVIATE], weights=[w["light"], w["heavy"], w["deviate"]])[0]


def roll_breakthrough(realm: str, physique: int, bone: int, cultivation: int,
                      bonus: float = 0.0) -> tuple[bool, str | None]:
    """`bonus` 是额外的成功率（0.2 = +20 个百分点，例如破障丹），加完仍封顶 95%。"""
    rate = min(_cfg()["breakthrough"]["cap"], breakthrough_success_rate(realm, physique, bone, cultivation) + bonus)
    if random.random() < rate:
        return True, None

    return False, roll_failure_outcome(realm)


def get_technique_slot_limit(realm: str) -> int:
    idx = get_realm_index(realm)
    slots = _cfg()["technique_slots"]
    best = max((r for r in slots if get_realm_index(r) <= idx), key=get_realm_index, default=None)
    return slots[best] if best else slots["炼气期1层"]


def apply_failure(cultivation: int, lifespan: int, outcome: str) -> tuple[int, int, str]:
    if outcome == FAIL_LIGHT:
        new_cultivation = int(cultivation * _cfg()["failure"]["cultivation_keep"])
        new_lifespan = lifespan
        msg = "差之毫厘，突破失败，修为受损。"
    elif outcome == FAIL_HEAVY:
        new_cultivation = int(cultivation * _cfg()["failure"]["cultivation_keep"])
        loss = max(1, lifespan // _cfg()["failure"]["heavy_loss_div"])
        new_lifespan = max(0, lifespan - loss)
        msg = f"突破失败，经脉受损，损耗寿元 {loss} 年。"
    elif outcome == FAIL_DEVIATE:
        new_cultivation = 0
        loss = max(1, lifespan // _cfg()["failure"]["deviate_loss_div"])
        new_lifespan = max(0, lifespan - loss)
        msg = f"走火入魔！修为尽散，寿元大损 {loss} 年，九死一生。"
    else:
        # 曾经这里是裸 else，None 之类的非法值会悄悄按最重的走火入魔处理。
        raise ValueError(f"未知的突破失败类型：{outcome!r}")
    return new_cultivation, new_lifespan, msg
