"""机器人经济的共用部分（U1「江湖百态」）：参数与纯函数。

每日结算（utils/bot_settle.py）和离线模拟（scripts/sim_bots.py）都从这里取参数和公式 ——
以前这类「两处各抄一份」的逻辑迟早漂移（B31）。参数在 `data/bot_economy.json`，来源见 .gk/ISSUES.md「经济参数」。
这里**不碰数据库**（天花板的取数在 bot_settle 里）。
"""

import json
import random
from functools import lru_cache
from pathlib import Path

from utils.character import calc_cultivation_gain
from utils.items import ITEMS
from utils.items import calc_zhuji_breakthrough_rate
from utils.items.breakthrough import calc_huaying_breakthrough_rate, calc_ningdan_breakthrough_rate
from utils.jobs import JOBS
from utils.realms import REALM_GROUPS, REALMS, get_realm_index
from utils.world import SPECIAL_REGIONS
from utils import settings_hub

_CONFIG = Path(__file__).resolve().parent.parent / "data" / "bot_economy.json"

# 三道大关：从哪层突破、要吃什么丹、成功率函数（机器人用游戏里的同一套）
GATES = {
    "炼气期10层": ("筑基丹", calc_zhuji_breakthrough_rate),
    "筑基期10层": ("凝丹丹", calc_ningdan_breakthrough_rate),
    "结丹期后期": ("化婴丹", calc_huaying_breakthrough_rate),
}
MAJORS = [m for m, _ in REALM_GROUPS]


@lru_cache(maxsize=1)
def _load() -> dict:
    return settings_hub.read(_CONFIG)


def load_config() -> dict:
    """配置的一份拷贝（调用方可以改自己的，不影响别人）。"""
    return json.loads(json.dumps(_load()))


def validate_config(cfg: dict) -> list[str]:
    """校验配置，返回错误列表（空 = 合法）。"""
    from utils.bot_social import load_archetypes
    from utils.bot_world import TIER_WEIGHTS
    errors = []
    tiers = set(TIER_WEIGHTS)
    for key in ("income", "speed"):
        if set(cfg.get(key, {})) != tiers:
            errors.append(f"{key} 的档位应为 {sorted(tiers)}")
        elif any(not isinstance(v, (int, float)) or v < 0 for v in cfg[key].values()):
            errors.append(f"{key} 的数值要是非负数")
    if any(not 0 <= v <= 1 for v in cfg.get("speed", {}).values()):
        errors.append("speed 应在 0~1 之间（相对勤奋真人的速度）")
    lo, hi = cfg.get("income_noise", [None, None])
    if not (isinstance(lo, (int, float)) and isinstance(hi, (int, float)) and 0 < lo <= hi):
        errors.append("income_noise 应为 [下限, 上限]，且 0 < 下限 ≤ 上限")
    if set(cfg.get("money", {})) != set(load_archetypes()):
        errors.append("money 的性格原型应与 bot_archetypes.json 一致")
    for name, m in cfg.get("money", {}).items():
        if not (0 <= m.get("carry", -1) <= 1 and 0 <= m.get("spend", -1) <= 1):
            errors.append(f"money.{name} 的 carry / spend 应在 0~1 之间")
    if set(cfg.get("pill_price", {})) != {pill for pill, _ in GATES.values()}:
        errors.append("pill_price 应覆盖三道大关的丹药")
    if not 0 < cfg.get("refill_rate", 0) <= 1:
        errors.append("refill_rate 应在 (0, 1] 之间")
    if not isinstance(cfg.get("refill_min_per_day"), int) or cfg["refill_min_per_day"] < 1:
        errors.append("refill_min_per_day 应为正整数")
    if cfg.get("daily_cap_per_bot", 0) <= 0 or cfg.get("day_years", 0) <= 0:
        errors.append("daily_cap_per_bot / day_years 应为正数")
    mat = cfg.get("materials", {})
    if not (0 <= mat.get("discount", -1) <= 1 and mat.get("jobs_per_day", 0) >= 0 and mat.get("keep_per_item", 0) > 0
            and mat.get("daily_cap_value_per_bot", -1) >= 0):
        errors.append("materials 参数不合法")
    combat = cfg.get("combat", {})
    for key in ("rob", "kill"):
        c = combat.get(key, {})
        if not (0 < c.get("share", 0) <= 1 and c.get("cap", 0) > 0 and c.get("per_human_per_day", 0) > 0):
            errors.append(f"combat.{key} 参数不合法")
    if combat.get("kill", {}).get("global_per_day", 0) < 1:
        errors.append("combat.kill.global_per_day 应为正整数（全服每天最多被击杀几个机器人）")
    cr = combat.get("captive_rob", {})
    if not (0 < cr.get("share", 0) <= 1 and cr.get("cap", 0) > 0):
        errors.append("combat.captive_rob 参数不合法")
    if set(combat.get("power_bonus", {})) != tiers or any(v < 0 for v in combat.get("power_bonus", {}).values()):
        errors.append("combat.power_bonus 的档位应为 " + str(sorted(tiers)) + "，且不能为负")
    cost = combat.get("cost", {})
    if set(cost) != {"rob", "cripple", "kill"} or any(v < 0 for c in cost.values() for k, v in c.items() if k.startswith("reputation")):
        errors.append("combat.cost 应有 rob / cripple / kill，声望代价不能为负")
    if any(c.get("favor", 0) > 0 for c in cost.values()):
        errors.append("combat.cost 的好感变化应为负数或 0")
    reaction = combat.get("reaction", {})
    if set(reaction) != set(load_archetypes()):
        errors.append("combat.reaction 的性格原型应与 bot_archetypes.json 一致")
    for name, w in reaction.items():
        if not w or set(w) - {"release", "rob", "kill"} or any(v < 0 for v in w.values()) or sum(w.values()) <= 0:
            errors.append(f"combat.reaction.{name} 应是 release / rob / kill 的非负权重，且不全为 0")
    if not isinstance(combat.get("can_kill_humans"), bool):
        errors.append("combat.can_kill_humans 应为布尔值")
    if combat.get("kill_protect_below") not in REALMS:
        errors.append("combat.kill_protect_below 应是一个境界名")
    pe = cfg.get("public_events", {})
    for key in ("migrate_share", "join_chance", "defense_chance"):
        if not 0 <= pe.get(key, -1) <= 1:
            errors.append(f"public_events.{key} 应在 0~1 之间")
    if not isinstance(pe.get("bots_compete_for_defense_rewards"), bool):
        errors.append("public_events.bots_compete_for_defense_rewards 应为布尔值")
    if not isinstance(pe.get("stat_cap_over_tier"), int) or pe["stat_cap_over_tier"] < 0:
        errors.append("public_events.stat_cap_over_tier 应为非负整数")
    if pe.get("activity_reward_budget_per_event", -1) < 0:
        errors.append("public_events.activity_reward_budget_per_event 不能为负")
    au = pe.get("auction", {})
    lo, hi = (au.get("bid_window") or [None, None])
    if not (au.get("bidders_per_lot", -1) >= 0 and au.get("max_bids_per_lot", 0) >= 1 and au.get("max_multiple", 0) >= 1
            and 0 < au.get("carry_share", 0) <= 1 and au.get("min_carry", -1) >= 0 and au.get("increment_pct", 0) > 0
            and isinstance(lo, (int, float)) and isinstance(hi, (int, float)) and 0 <= lo < hi <= 1):
        errors.append("public_events.auction 参数不合法")
    interest = au.get("interest", {})
    if set(interest) != {"equipment", "technique"} or any(set(v) - set(load_archetypes()) for v in interest.values()):
        errors.append("public_events.auction.interest 应有 equipment / technique，且是已有的性格原型")
    if mat.get("keep_equipment", 0) < 1:
        errors.append("materials.keep_equipment 应 ≥ 1")
    tj = cfg.get("tianjiao", {})
    if not (isinstance(tj.get("ascend_after_days"), int) and tj["ascend_after_days"] >= 1 and 0 < tj.get("ascend_chance", 0) <= 1):
        errors.append("tianjiao.ascend_after_days 应为正整数，ascend_chance 应在 (0, 1] 之间")
    wild = cfg.get("wild", {})
    if not 0 <= wild.get("trip_chance", -1) <= 1:
        errors.append("wild.trip_chance 应在 0~1 之间")
    ceiling = cfg.get("ceiling", {})
    for key in ("override", "floor"):
        if ceiling.get(key) is not None and ceiling[key] not in MAJORS:
            errors.append(f"ceiling.{key} 应为 null 或大境名（{MAJORS[:4]}…）")
    if ceiling.get("floor") is None:
        errors.append("ceiling.floor 不能为空")
    return errors


# ---- 公式 -------------------------------------------------------------------

def stochastic_round(x: float, rng=random) -> int:
    """随机取整，期望不变：2.4 → 2（60%）或 3（40%）。库里的列是整数，但日均值带小数。"""
    base = int(x // 1)
    return base + (1 if rng.random() < x - base else 0)


def daily_income(tier: str, cfg: dict, rng=random) -> float:
    lo, hi = cfg["income_noise"]
    return cfg["income"][tier] * rng.uniform(lo, hi)


def income_scale(tiers: list[str], cfg: dict) -> float:
    """全服上限的缩放系数：按「期望总收入」算（不依赖当天的随机噪声），超过上限就按比例缩。"""
    expected = sum(cfg["income"][t] for t in tiers)
    cap = cfg["daily_cap_per_bot"] * len(tiers)
    return min(1.0, cap / expected) if expected else 1.0


def refill_cap(target: int, cfg: dict) -> int:
    """每天最多补几个：目标的 refill_rate，但至少 refill_min_per_day。
    小世界里创始那批机器人寿元相近、集中老死，只按比例补会塌陷（100 个时最低掉到 52%）；500 个时 2% = 10 个，下限不起作用。"""
    return max(int(target * cfg["refill_rate"]), cfg["refill_min_per_day"])


def active_years(tier: str, cfg: dict, rng=random) -> int:
    """今天『活跃』的游戏年数 = 一天的游戏年 × 速度系数；寿元只在这些年里消耗。"""
    return stochastic_round(cfg["day_years"] * cfg["speed"][tier], rng)


def cultivation_gain(years: int, stats: dict) -> int:
    return calc_cultivation_gain(years, stats["comprehension"], stats["spirit_root_type"])


def split_income(paid: int, archetype: str, cfg: dict, rng=random) -> tuple[int, int]:
    """收入分成 (随身, 钱庄)：随身比例由性格定。"""
    carry = stochastic_round(paid * cfg["money"][archetype]["carry"], rng)
    return carry, paid - carry


def spend_amount(carry: int, archetype: str, cfg: dict) -> int:
    return int(carry * cfg["money"][archetype]["spend"])


def gate_price(realm: str, cfg: dict) -> tuple[str, int] | None:
    """(丹药名, 价格)；这一层不是大关返回 None。"""
    gate = GATES.get(realm)
    return (gate[0], cfg["pill_price"][gate[0]]) if gate else None


def eligible_jobs(realm: str) -> list:
    """机器人能做的工种：限定城市的不算，其余看境界门槛。"""
    idx = get_realm_index(realm)
    out = []
    for job in JOBS:
        req = job["req"]
        if "city_in" in req:
            continue
        if "realm_min" in req and idx < get_realm_index(req["realm_min"]):
            continue
        out.append(job)
    return out


def material_roll(realm: str, cfg: dict, rng=random) -> list[str]:
    """一天里这个机器人打工掉落的材料（名字列表，可重复），概率已按折扣打折。"""
    mat, jobs, drops = cfg["materials"], eligible_jobs(realm), []
    for _ in range(mat["jobs_per_day"]):
        job = rng.choice(jobs)
        for name, prob in job["reward"].get("items", []):
            if rng.random() < prob * mat["discount"]:
                drops.append(name)
    return drops


def pick_wild_trip(realm: str, cfg: dict, rng=random) -> str | None:
    """今天要不要去秘地历练：按 wild.trip_chance 掷骰，去的话从境界够得着的秘地里随机选一个；否则 None。"""
    if rng.random() >= cfg["wild"]["trip_chance"]:
        return None
    idx = get_realm_index(realm)
    regions = [r["name"] for r in SPECIAL_REGIONS if get_realm_index(r["min_realm"]) <= idx]
    return rng.choice(regions) if regions else None


WILD_NAMES = frozenset(r["name"] for r in SPECIAL_REGIONS)        # 能被攻击的地方（秘地），城市是安全区


def captive_outcome(archetype: str, cfg: dict, *, can_kill: bool, rng=random, shift: dict | None = None) -> str:
    """打输了的真人被擒获之后，这个机器人怎么处置：release（放走）/ rob（劫一点灵石）/ kill（杀）。
    杀不被允许（总开关关着，或对方受保护）时，杀的权重并入 rob。"""
    weights = dict(cfg["combat"]["reaction"][archetype])
    for name, factor in (shift or {}).items():                  # 行为画像的修正（善恶 / 守序混乱，见 bot_profile.captive_shift）
        if name in weights:
            weights[name] = weights[name] * factor
    if not can_kill and "kill" in weights:
        weights["rob"] = weights.get("rob", 0) + weights.pop("kill")
    names = list(weights)
    return rng.choices(names, weights=[weights[n] for n in names])[0]


def item_value(name: str) -> int:
    return ITEMS.get(name, {}).get("sell_price") or 0


# ---- 天花板 -----------------------------------------------------------------

def ceiling_index(top_realm: str | None, cfg: dict) -> int:
    """机器人最高能到的境界下标（含）：最高真人所在大境的最后一个小境。

    `ceiling.override` 设了就用它（例如现网有个调试账号境界很高，会让天花板形同虚设）；
    没有真人时取 `ceiling.floor`；真人低于 floor 时也取 floor。
    """
    ceiling = cfg["ceiling"]
    if ceiling.get("override"):
        major = ceiling["override"]
    else:
        floor_idx = MAJORS.index(ceiling["floor"])
        top_major = _major(top_realm) if top_realm else None
        major = MAJORS[max(floor_idx, MAJORS.index(top_major))] if top_major else ceiling["floor"]
    last = [r for m, subs in REALM_GROUPS if m == major for r in subs][-1]
    return get_realm_index(last)


def _major(realm: str) -> str | None:
    from utils.realms import major_realm
    return major_realm(realm)


def realm_at_most(realms: list[str], idx: int) -> list[str]:
    """不超过下标 idx 的境界；全都超过时退而取 idx 本身那一层。"""
    return [r for r in realms if get_realm_index(r) <= idx] or [REALMS[idx]]
