import random

REALMS = (
    [f"炼气期{i}层" for i in range(1, 11)] +
    [f"筑基期{i}层" for i in range(1, 11)] +
    ["结丹期初期", "结丹期中期", "结丹期后期"] +
    ["元婴期初期", "元婴期中期", "元婴期后期"] +
    ["化神期初期", "化神期中期", "化神期后期"] +
    ["炼虚期初期", "炼虚期中期", "炼虚期后期"] +
    ["合体期初期", "合体期中期", "合体期后期"] +
    ["大乘期初期", "大乘期中期", "大乘期后期"] +
    ["真仙初期", "真仙中期", "真仙后期"] +
    ["金仙初期", "金仙中期", "金仙后期"] +
    ["太乙初期", "太乙中期", "太乙后期"] +
    ["大罗初期", "大罗中期", "大罗后期"] +
    ["道祖"]
)

_CULTIVATION_NEEDED = {}
for r in REALMS[:10]:
    _CULTIVATION_NEEDED[r] = 100
for r in REALMS[10:20]:
    _CULTIVATION_NEEDED[r] = 200
for i, r in enumerate(REALMS[20:]):
    _CULTIVATION_NEEDED[r] = 400 + i * 100

_LIFESPAN_MAX = {}
for r in REALMS[:10]:
    _LIFESPAN_MAX[r] = 100
for r in REALMS[10:20]:
    _LIFESPAN_MAX[r] = 200
_LIFESPAN_MAX.update({
    "结丹期初期": 400, "结丹期中期": 450, "结丹期后期": 500,
    "元婴期初期": 800, "元婴期中期": 900, "元婴期后期": 1000,
    "化神期初期": 1500, "化神期中期": 1800, "化神期后期": 2000,
    "炼虚期初期": 2500, "炼虚期中期": 2800, "炼虚期后期": 3000,
    "合体期初期": 4000, "合体期中期": 4500, "合体期后期": 5000,
    "大乘期初期": 8000, "大乘期中期": 9000, "大乘期后期": 10000,
    "真仙初期": 20000, "真仙中期": 25000, "真仙后期": 30000,
    "金仙初期": 50000, "金仙中期": 60000, "金仙后期": 80000,
    "太乙初期": 100000, "太乙中期": 120000, "太乙后期": 150000,
    "大罗初期": 200000, "大罗中期": 250000, "大罗后期": 300000,
    "道祖": 999999,
})

_BREAKTHROUGH_RATE = {}
for i, r in enumerate(REALMS[:10]):
    _BREAKTHROUGH_RATE[r] = 0.90 - i * 0.01
for i, r in enumerate(REALMS[10:20]):
    _BREAKTHROUGH_RATE[r] = 0.80 - i * 0.02
rates = [0.60, 0.50, 0.40, 0.35, 0.28, 0.22, 0.18, 0.14, 0.11,
         0.09, 0.07, 0.06, 0.05, 0.04, 0.03, 0.025, 0.02, 0.015,
         0.012, 0.010, 0.008, 0.006, 0.005, 0.004, 0.003]
for i, r in enumerate(REALMS[20:]):
    _BREAKTHROUGH_RATE[r] = rates[i] if i < len(rates) else 0.002


def get_realm_index(realm: str) -> int:
    try:
        return REALMS.index(realm)
    except ValueError:
        return 0


def cultivation_needed(realm: str) -> int:
    return _CULTIVATION_NEEDED.get(realm, 100)


def lifespan_max_for_realm(realm: str) -> int:
    return _LIFESPAN_MAX.get(realm, 100)


def next_realm(realm: str) -> str | None:
    idx = get_realm_index(realm)
    if idx + 1 < len(REALMS):
        return REALMS[idx + 1]
    return None


def breakthrough_success_rate(realm: str, physique: int, bone: int, cultivation: int) -> float:
    base = _BREAKTHROUGH_RATE.get(realm, 0.5)
    stat_bonus = ((physique - 5) + (bone - 5)) * 0.02
    needed = cultivation_needed(realm)
    overflow_bonus = max(0, (cultivation - needed) / needed) * 0.05
    return min(0.95, max(0.01, base + stat_bonus + overflow_bonus))


FAIL_LIGHT = "light"
FAIL_HEAVY = "heavy"
FAIL_DEVIATE = "deviate"


def roll_breakthrough(realm: str, physique: int, bone: int, cultivation: int) -> tuple[bool, str | None]:
    rate = breakthrough_success_rate(realm, physique, bone, cultivation)
    if random.random() < rate:
        return True, None

    idx = get_realm_index(realm)
    if idx < 20:
        weights = [0.70, 0.25, 0.05]
    else:
        weights = [0.30, 0.50, 0.20]

    outcome = random.choices([FAIL_LIGHT, FAIL_HEAVY, FAIL_DEVIATE], weights=weights)[0]
    return False, outcome


def apply_failure(cultivation: int, lifespan: int, outcome: str) -> tuple[int, int, str]:
    if outcome == FAIL_LIGHT:
        new_cultivation = cultivation // 2
        new_lifespan = lifespan
        msg = "差之毫厘，突破失败，修为受损。"
    elif outcome == FAIL_HEAVY:
        new_cultivation = cultivation // 2
        loss = max(1, lifespan // 10)
        new_lifespan = max(0, lifespan - loss)
        msg = f"突破失败，经脉受损，损耗寿元 {loss} 年。"
    else:
        new_cultivation = 0
        loss = max(1, lifespan // 4)
        new_lifespan = max(0, lifespan - loss)
        msg = f"走火入魔！修为尽散，寿元大损 {loss} 年，九死一生。"
    return new_cultivation, new_lifespan, msg
