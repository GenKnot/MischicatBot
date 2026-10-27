"""游戏规则的数值（U1·调参）：钱庄利率、坊市手续费、每日次数、冷却……原先写死在各模块里的平衡数字，统一放 `data/game_rules.json`。

· 文件里的值是默认值；管理员可以用 `cat!调参` 在游戏里改（`utils/settings_hub.py` 叠加覆盖值），立即生效、重启不丢；
· 用法：`rules.section("bank")["min_deposit"]` 或 `rules.get("bank.min_deposit")`。**每次用的时候读，不要在模块顶层存成常量**（存了就不会跟着调参变）；
· 校验在 `validate`：每个数字都必须在 `SPECS` 里登记范围（棘轮：新增数字没登记范围会报错），再加几条跨字段的检查（比如轮转的期望不能让庄家亏本）。
"""

import json
import re
from functools import lru_cache
from pathlib import Path

from utils import settings_hub

_PATH = Path(__file__).resolve().parent.parent / "data" / "game_rules.json"
INF = 10 ** 9

# 路径模式（列表序号写 *）→ (最小, 最大)。整数项另外要求是整数（见 INTEGER）。
SPECS: dict[str, tuple[float, float]] = {
    # 钱庄
    "bank.demand_rate": (0, 1), "bank.min_deposit": (1, INF), "bank.transfer_fee_rate": (0, 1), "bank.transfer_max": (1, INF),
    "bank.terms.*.years": (1, 100000), "bank.terms.*.rate": (0, 1),
    # 坊市
    "market.max_listings": (1, 1000), "market.fee_rate": (0, 1), "market.listing_ttl_hours": (1, 24 * 365),
    # 轮转赌坊
    "roulette.bet": (1, INF), "roulette.daily_limit": (0, 1000),
    "roulette.slots.*.multiplier": (0, 1000), "roulette.slots.*.count": (0, 100),
    # 打工 / 探险 / 组队 / 茶馆
    "jobs.cooldown_seconds": (0, 86400 * 30), "jobs.daily_limit": (0, 1000),
    "explore.limit": (1, 1000), "explore.reset_years": (0.01, 100000),
    "party.max_size": (2, 50),
    # 炼丹
    "alchemy.daily_limit": (0, 1000), "alchemy.no_yanhuo_cap": (0, 11), "alchemy.exp_per_craft": (0, INF),
    "alchemy.quality_multipliers.*": (0, 1000), "alchemy.exp_thresholds.*": (0, INF),
    "alchemy.mastery_stages.*.crafts": (0, INF), "alchemy.mastery_stages.*.bonus": (0, 100),
    "alchemy.quality.roll_max": (0, 100), "alchemy.quality.soul_factor": (0, 10),
    "alchemy.success.master_bonus": (0, 100), "alchemy.success.free_mix_factor": (0, 1), "alchemy.success.min": (0, 100), "alchemy.success.max": (0, 100),
    "alchemy.exam_cost": (0, INF), "alchemy.exam_refill_cost": (0, INF),
    # 炼器
    "forging.daily_limit": (0, 1000), "forging.exp_per_craft": (0, INF), "forging.exp_thresholds.*": (0, INF), "forging.slot_ore_qty.*": (1, 1000),
    "forging.mastery_stages.*.crafts": (0, INF), "forging.mastery_stages.*.bonus": (0, 100),
    "forging.success.base": (0, 200), "forging.success.per_quality": (0, 100), "forging.success.per_level": (0, 100),
    "forging.success.bone_div": (1, 1000), "forging.success.bone_cap": (0, 100), "forging.success.min": (0, 100), "forging.success.max": (0, 100),
    "forging.failure.plain_p": (0, 1), "forging.failure.fire_loss.*": (0, 1000),
    "forging.reforge.base_cost": (0, INF), "forging.reforge.ore_qty": (1, 1000), "forging.reforge.cost_multiplier.*": (0, 1000),
    "forging.exam_cost": (0, INF), "forging.exam_materials.*": (0, 1000),
    # 采集
    "gathering.options.*": (0.01, 1000), "gathering.rarity_base.*": (0, 10000), "gathering.rarity_time.per_year": (0, 1000), "gathering.rarity_time.cap": (0, 10000),
    "gathering.rarity_realm.per_realm": (0, 1000), "gathering.rarity_realm.cap": (0, 10000), "gathering.rarity_scale.*": (0, 100),
    "gathering.rolls.per_year": (0, 1000), "gathering.rolls.realm_div": (1, 1000), "gathering.element_bias_p": (0, 1),
    "gathering.max_cooldown_reduction": (0, 1), "gathering.min_actual_years": (0.01, 1000),
    # 角色 / 修炼 / 置业
    "character.base_stats.*": (0, 1000000), "character.spirit_root_speed.*": (0, 100), "character.spirit_root_odds.*": (0, 100),
    "character.realm_lifespan.*": (1, 10000000), "character.cultivation.base_per_year": (0, 1000000), "character.cultivation.comprehension_base": (0, 100),
    "character.cultivation.comprehension_step": (0, 10), "character.cultivation.auto_threshold_years": (0, 100000),
    "character.residence.bonus": (0, 100), "character.residence.explore_bonus": (0, 1000), "character.residence.price_normal": (0, INF),
    "character.residence.price_central": (0, INF), "character.residence.reputation": (0, INF),
    "character.cave.bonus": (0, 100), "character.cave.explore_bonus": (0, 1000), "character.cave.price": (0, INF), "character.cave.reputation": (0, INF),
    # 境界体系
    "realms.cultivation_needed.*": (1, INF), "realms.lifespan_max.tier1_base": (1, INF), "realms.lifespan_max.tier1_step": (0, INF),
    "realms.lifespan_max.tier2_base": (1, INF), "realms.lifespan_max.tier2_step": (0, INF), "realms.lifespan_max.unknown": (1, INF),
    "realms.lifespan_max.table.*": (1, INF),
    "realms.breakthrough.tier1_base": (0, 1), "realms.breakthrough.tier1_step": (0, 1), "realms.breakthrough.tier2_base": (0, 1),
    "realms.breakthrough.tier2_step": (0, 1), "realms.breakthrough.late_rates.*": (0, 1), "realms.breakthrough.late_default": (0, 1),
    "realms.breakthrough.unknown": (0, 1), "realms.breakthrough.stat_bonus": (0, 1), "realms.breakthrough.overflow_bonus": (0, 1),
    "realms.breakthrough.cap": (0, 1), "realms.breakthrough.floor": (0, 1),
    "realms.failure.split_index": (0, 100), "realms.failure.early_weights.*": (0, 1000), "realms.failure.late_weights.*": (0, 1000),
    "realms.failure.cultivation_keep": (0, 1), "realms.failure.heavy_loss_div": (1, 1000), "realms.failure.deviate_loss_div": (1, 1000),
    "realms.technique_slots.*": (1, 1000),
    # 战斗 / 任务 / 转世
    "combat.realm_step": (0, 100), "combat.noise.*": (0.01, 100), "combat.escape.base": (0, 1), "combat.escape.per_soul": (0, 1),
    "combat.escape.per_realm": (0, 1), "combat.escape.min": (0, 1), "combat.escape.max": (0, 1),
    "quests.noise.*": (0.01, 100), "quests.normal_drop_chance": (0, 1), "quests.drops.*.*": (0, 10000), "quests.escape_loss.*": (0, 100000),
    "quests.death.base": (0, 1), "quests.death.cap": (0, 1), "quests.death.gap_div": (0.01, 1000), "quests.fail_loss.*": (0, 100000),
    "rebirth.mult_step": (0, 100), "rebirth.stat_keep": (0, 10), "rebirth.start_stones": (0, INF), "rebirth.yinyang_chance": (0, 1),
    # 三道大关
    "gates.root_base.*": (0, 100), "gates.default_root_base": (0, 100), "gates.cap": (1, 100), "gates.skip_pill_min": (0, 1000),
    "gates.zhuji.*": (0, 1000), "gates.ningdan.base_factor": (0, 10), "gates.ningdan.comprehension": (0, 1000), "gates.ningdan.bone": (0, 1000),
    "gates.ningdan.pill": (0, 1000), "gates.huaying.base_factor": (0, 10), "gates.huaying.comprehension": (0, 1000), "gates.huaying.soul": (0, 1000),
    "gates.huaying.pill": (0, 1000),
    # 装备
    "equipment.quality_mult.*": (0, 1000), "equipment.affix_count.*.*": (0, 3), "equipment.random_quality_weights.*": (0, 10000),
    "equipment.tier_div": (1, 100), "equipment.affix_scale": (0, 100), "equipment.noise.*": (0.01, 100), "equipment.second_prefix_p": (0, 1),
    # 功法修炼
    "techniques.stage_cost.*": (0, INF), "techniques.stage_years.*": (0, 100000), "techniques.grade_cost.*": (0, 100000),
    "techniques.stat_mult.*": (0, 1000), "techniques.pct_mult.*": (0, 1000),
    # 公共事件：灵雨 / 万宝楼
    "spirit_rain.beast_tide_chance": (0, 1), "spirit_rain.max_activities": (1, 100), "spirit_rain.activity_cooldown_seconds": (0, 86400),
    "spirit_rain.temper_min_physique": (0, 1000),
    "spirit_rain.defense.base.stones.*": (0, INF), "spirit_rain.defense.base.rep": (0, INF),
    "spirit_rain.defense.rank1.stones.*": (0, INF), "spirit_rain.defense.rank1.rep": (0, INF), "spirit_rain.defense.rank1.equipment": (0, 10),
    "spirit_rain.defense.rank23.stones.*": (0, INF), "spirit_rain.defense.rank23.rep": (0, INF), "spirit_rain.defense.rank23.equipment": (0, 10),
    "spirit_rain.defense.rest.stones.*": (0, INF), "spirit_rain.defense.rest.rep": (0, INF),
    "spirit_rain.defense.list_max": (1, 1000), "spirit_rain.defense.power_noise.*": (0.01, 100),
    "spirit_rain.slacker.chance": (0, 1), "spirit_rain.slacker.loss.*": (0, 100000),
    "spirit_rain.crystal.stones.*": (0, INF), "spirit_rain.crystal.herb_chance": (0, 1), "spirit_rain.crystal.herb_weights.*": (0, 10000),
    "spirit_rain.crystal.herb_count.*": (1, 100), "spirit_rain.crystal.qty.*": (1, 100),
    "spirit_rain.enlighten.stat_chance": (0, 1), "spirit_rain.enlighten.cultivation.*": (0, INF),
    "spirit_rain.temper.physique_chance": (0, 1), "spirit_rain.temper.bone_chance": (0, 1), "spirit_rain.temper.cultivation.*": (0, INF),
    "wanbao.commission": (0, 1), "wanbao.listing_fee": (0, INF), "wanbao.max_lots": (1, 1000), "wanbao.max_player_lots": (1, 1000),
    "wanbao.lot_seconds": (10, 86400), "wanbao.preview_before_seconds": (0, 86400 * 3), "wanbao.official.*": (0, 50),
    "wanbao.grade_weights.*": (0, 100000), "wanbao.rarity_weights.*": (0, 100000), "wanbao.start_price.*.*": (0, INF),
    "wanbao.pill_qty.*": (1, 100), "wanbao.material_qty.*": (1, 100), "wanbao.equipment_quality_weights.*": (0, 100000), "wanbao.equipment_tier.*": (0, 12),
    "alchemy.failure.plain_p": (0, 1), "alchemy.failure.ruin_p": (0, 1), "alchemy.failure.ruin_loss.*": (0, 1000), "alchemy.failure.poison_loss.*": (0, 1000),
    "tavern.quest_years.*": (0, 1000), "tavern.gather_years.*": (0, 1000),
}
INTEGER = {"bank.min_deposit", "bank.transfer_max", "bank.terms.*.years", "market.max_listings", "roulette.bet", "roulette.daily_limit",
           "roulette.slots.*.count", "jobs.daily_limit", "explore.limit", "party.max_size", "jobs.cooldown_seconds",
           "alchemy.daily_limit", "alchemy.no_yanhuo_cap", "alchemy.exp_per_craft", "alchemy.exp_thresholds.*", "alchemy.mastery_stages.*.crafts",
           "alchemy.mastery_stages.*.bonus", "alchemy.quality.roll_max", "alchemy.success.master_bonus", "alchemy.success.min", "alchemy.success.max",
           "alchemy.failure.ruin_loss.*", "alchemy.failure.poison_loss.*", "alchemy.exam_cost", "alchemy.exam_refill_cost",
           "forging.daily_limit", "forging.exp_per_craft", "forging.exp_thresholds.*", "forging.slot_ore_qty.*", "forging.mastery_stages.*.crafts",
           "forging.mastery_stages.*.bonus", "forging.success.base", "forging.success.per_quality", "forging.success.per_level", "forging.success.bone_div",
           "forging.success.bone_cap", "forging.success.min", "forging.success.max", "forging.failure.fire_loss.*", "forging.reforge.base_cost",
           "forging.reforge.ore_qty", "forging.reforge.cost_multiplier.*", "forging.exam_cost", "forging.exam_materials.*",
           "character.base_stats.*", "character.realm_lifespan.*", "character.residence.explore_bonus", "character.residence.price_normal",
           "character.residence.price_central", "character.residence.reputation", "character.cave.explore_bonus", "character.cave.price",
           "character.cave.reputation", "realms.cultivation_needed.*", "realms.lifespan_max.tier1_base", "realms.lifespan_max.tier1_step",
           "realms.lifespan_max.tier2_base", "realms.lifespan_max.tier2_step", "realms.lifespan_max.unknown", "realms.lifespan_max.table.*",
           "realms.failure.split_index", "realms.failure.heavy_loss_div", "realms.failure.deviate_loss_div", "realms.technique_slots.*", "quests.escape_loss.*", "quests.fail_loss.*", "rebirth.start_stones", "gates.skip_pill_min", "equipment.affix_count.*.*", "equipment.tier_div", "techniques.stage_cost.*",
           "spirit_rain.max_activities", "spirit_rain.activity_cooldown_seconds", "spirit_rain.temper_min_physique", "spirit_rain.defense.base.stones.*",
           "spirit_rain.defense.base.rep", "spirit_rain.defense.rank1.stones.*", "spirit_rain.defense.rank1.rep", "spirit_rain.defense.rank1.equipment",
           "spirit_rain.defense.rank23.stones.*", "spirit_rain.defense.rank23.rep", "spirit_rain.defense.rank23.equipment",
           "spirit_rain.defense.rest.stones.*", "spirit_rain.defense.rest.rep", "spirit_rain.defense.list_max", "spirit_rain.slacker.loss.*",
           "spirit_rain.crystal.stones.*", "spirit_rain.crystal.herb_count.*", "spirit_rain.crystal.qty.*", "spirit_rain.enlighten.cultivation.*",
           "spirit_rain.temper.cultivation.*", "wanbao.listing_fee", "wanbao.max_lots", "wanbao.max_player_lots", "wanbao.lot_seconds",
           "wanbao.preview_before_seconds", "wanbao.official.*", "wanbao.start_price.*.*", "wanbao.pill_qty.*", "wanbao.material_qty.*",
           "wanbao.equipment_tier.*"}


@lru_cache(maxsize=1)
def _load() -> dict:
    return settings_hub.read(_PATH)


def load() -> dict:
    """整份规则（只读，别改它）。"""
    return _load()


def reload() -> None:
    _load.cache_clear()


def section(name: str) -> dict:
    return _load()[name]


def get(path: str):
    """按点号路径取一项，例如 `bank.terms.0.rate`。"""
    node = _load()
    for part in path.split("."):
        node = node[int(part)] if isinstance(node, list) else node[part]
    return node


def pattern(path: str) -> str | None:
    """路径对应的 SPECS 键（`*` 匹配列表序号和字典里的任意一个键）；没登记返回 None。"""
    parts = path.split(".")
    for pat in SPECS:
        segs = pat.split(".")
        if len(segs) == len(parts) and all(a == "*" or a == b for a, b in zip(segs, parts)):
            return pat
    return None


def validate(cfg: dict) -> list[str]:
    errors = []
    for path, value in settings_hub.leaves(cfg):
        pat = pattern(path)
        spec = SPECS.get(pat) if pat else None
        if spec is None:
            errors.append(f"{path} 没有登记取值范围（rules.SPECS）")
            continue
        lo, hi = spec
        if not lo <= value <= hi or isinstance(value, bool):
            errors.append(f"{path} 应在 {lo:g}~{hi:g} 之间")
        elif pat in INTEGER and value != int(value):
            errors.append(f"{path} 应是整数")
    errors += _cross_checks(cfg)
    return errors


def _cross_checks(cfg: dict) -> list[str]:
    errors = []
    terms = cfg.get("bank", {}).get("terms", [])
    years = [t.get("years", 0) for t in terms]
    if not terms or len(set(years)) != len(years):
        errors.append("bank.terms 至少一档，各档年限不能重复")
    slots = cfg.get("roulette", {}).get("slots", [])
    total = sum(s.get("count", 0) for s in slots)
    if total < 1:
        errors.append("roulette.slots 至少要有一格（count 总和 ≥ 1）")
    elif sum(s.get("multiplier", 0) * s.get("count", 0) for s in slots) / total > 1.0:
        errors.append("roulette.slots 的期望倍率不能超过 1（否则庄家亏本，玩家可以无限刷灵石）")
    errors += _alchemy_checks(cfg.get("alchemy", {}))
    errors += _forging_checks(cfg.get("forging", {}))
    errors += _realm_checks(cfg.get("realms", {}))
    errors += _event_checks(cfg.get("spirit_rain", {}), cfg.get("wanbao", {}))
    t = cfg.get("techniques", {})
    stages = ("入门", "熟练", "精通", "小成", "大成", "圆满", "破限")
    if set(t.get("stage_cost", {})) != set(stages[:-1]) or set(t.get("stage_years", {})) != set(stages[:-1]):
        errors.append(f"techniques.stage_cost / stage_years 需要 {stages[:-1]}（破限不用升级）")
    if set(t.get("stat_mult", {})) != set(stages) or set(t.get("pct_mult", {})) != set(stages):
        errors.append(f"techniques.stat_mult / pct_mult 需要 {stages}")
    if len(t.get("grade_cost", {})) < 12:
        errors.append("techniques.grade_cost 需要 12 个品阶")
    e = cfg.get("equipment", {})
    qs = {"普通", "精良", "稀有", "史诗", "传说"}
    if set(e.get("quality_mult", {})) != qs or set(e.get("affix_count", {})) != qs or set(e.get("random_quality_weights", {})) != qs:
        errors.append("equipment.quality_mult / affix_count / random_quality_weights 都需要五个品质")
    elif sum(e["random_quality_weights"].values()) <= 0:
        errors.append("equipment.random_quality_weights 权重总和 > 0")
    if any(len(v) != 2 or v[0] > v[1] for v in e.get("affix_count", {}).values()):
        errors.append("equipment.affix_count 每项应是 [最少, 最多]")
    if len(e.get("noise", [])) != 2 or e["noise"][0] > e["noise"][1]:
        errors.append("equipment.noise 应是 [最小, 最大]")
    if set(cfg.get("gates", {}).get("root_base", {})) != set(cfg.get("character", {}).get("spirit_root_speed", {})):
        errors.append("gates.root_base 要覆盖所有灵根（和 character.spirit_root_speed 同一组）")
    for name, rng_ in (("combat.noise", cfg.get("combat", {}).get("noise", [])), ("quests.noise", cfg.get("quests", {}).get("noise", [])),
                       ("quests.fail_loss", cfg.get("quests", {}).get("fail_loss", []))):
        if len(rng_) != 2 or rng_[0] > rng_[1]:
            errors.append(f"{name} 应是 [最小, 最大]")
    e = cfg.get("combat", {}).get("escape", {})
    if e.get("min", 0) > e.get("max", 1):
        errors.append("combat.escape: min 不能大于 max")
    q = cfg.get("quests", {})
    if set(q.get("drops", {})) != {"普通", "精英", "传说"} or any(sum(w.values()) <= 0 for w in q.get("drops", {}).values()):
        errors.append("quests.drops 需要 普通 / 精英 / 传说，每档权重总和 > 0")
    elif any(k not in ("普通", "精良", "稀有", "史诗", "传说") for w in q["drops"].values() for k in w):
        errors.append("quests.drops 里的装备品质只能是 普通 / 精良 / 稀有 / 史诗 / 传说")
    if set(q.get("escape_loss", {})) != {"普通", "精英", "传说"}:
        errors.append("quests.escape_loss 需要 普通 / 精英 / 传说")
    c = cfg.get("character", {})
    if set(c.get("spirit_root_odds", {})) != set(c.get("spirit_root_speed", {})) or sum(c.get("spirit_root_odds", {}).values()) <= 0:
        errors.append("character.spirit_root_odds 要和 spirit_root_speed 是同一组灵根，权重总和 > 0")
    if set(c.get("realm_lifespan", {})) != {"炼气期", "筑基期", "结丹期", "元婴期", "化神期", "炼虚期", "合体期", "大乘期"}:
        errors.append("character.realm_lifespan 需要炼气期到大乘期八个大境界")
    elif list(c["realm_lifespan"].values()) != sorted(c["realm_lifespan"].values()):
        errors.append("character.realm_lifespan 应随境界递增")
    if set(c.get("base_stats", {})) != {"comprehension", "physique", "fortune", "bone", "soul", "spirit_stones"}:
        errors.append("character.base_stats 需要五项属性和 spirit_stones")
    g = cfg.get("gathering", {})
    opts = g.get("options", [])
    if not opts or opts != sorted(set(opts)):
        errors.append("gathering.options 至少一项，从短到长，不能重复")
    if set(g.get("rarity_base", {})) != {"普通", "稀有", "珍贵", "绝世"} or sum(g.get("rarity_base", {}).values()) <= 0:
        errors.append("gathering.rarity_base 需要 普通 / 稀有 / 珍贵 / 绝世，权重总和 > 0")
    if set(g.get("rarity_scale", {})) != {"珍贵_time", "珍贵_realm", "绝世_time", "绝世_realm"}:
        errors.append("gathering.rarity_scale 需要 珍贵_time / 珍贵_realm / 绝世_time / 绝世_realm")
    for name in ("quest_years", "gather_years"):
        if set(cfg.get("tavern", {}).get(name, {})) != {"普通", "精英", "传说"}:
            errors.append(f"tavern.{name} 需要 普通 / 精英 / 传说")
    return errors


def _alchemy_checks(a: dict) -> list[str]:
    errors = []
    if len(a.get("quality_multipliers", [])) != 12:
        errors.append("alchemy.quality_multipliers 必须正好 12 档（和品质名一一对应）")
    th = a.get("exp_thresholds", [])
    if len(th) != 10 or th != sorted(th):
        errors.append("alchemy.exp_thresholds 必须正好 10 项（品级 0~9），且从小到大")
    stages = a.get("mastery_stages", [])
    crafts = [s.get("crafts", -1) for s in stages]
    if not stages or crafts[0] != 0 or crafts != sorted(set(crafts)):
        errors.append("alchemy.mastery_stages 第一档从 0 次开始，次数严格递增")
    f = a.get("failure", {})
    if f.get("plain_p", 0) + f.get("ruin_p", 0) > 1:
        errors.append("alchemy.failure: plain_p + ruin_p 不能超过 1（其余是丹毒反噬）")
    for key in ("ruin_loss", "poison_loss"):
        r = f.get(key, [1, 0])
        if len(r) != 2 or r[0] > r[1]:
            errors.append(f"alchemy.failure.{key} 应是 [最小, 最大]")
    s = a.get("success", {})
    if s.get("min", 0) > s.get("max", 0):
        errors.append("alchemy.success: min 不能大于 max")
    if a.get("no_yanhuo_cap", 0) > 11:
        errors.append("alchemy.no_yanhuo_cap 最高 11")
    return errors


def _forging_checks(f: dict) -> list[str]:
    errors = []
    th = f.get("exp_thresholds", [])
    if len(th) != 10 or th != sorted(th):
        errors.append("forging.exp_thresholds 必须正好 10 项（品级 0~9），且从小到大")
    if set(f.get("slot_ore_qty", {})) != {"武器", "防具", "饰品"}:
        errors.append("forging.slot_ore_qty 需要 武器 / 防具 / 饰品")
    stages = f.get("mastery_stages", [])
    crafts = [s.get("crafts", -1) for s in stages]
    if not stages or crafts[0] != 0 or crafts != sorted(set(crafts)):
        errors.append("forging.mastery_stages 第一档从 0 次开始，次数严格递增")
    if f.get("success", {}).get("min", 0) > f.get("success", {}).get("max", 0):
        errors.append("forging.success: min 不能大于 max")
    r = f.get("failure", {}).get("fire_loss", [1, 0])
    if len(r) != 2 or r[0] > r[1]:
        errors.append("forging.failure.fire_loss 应是 [最小, 最大]")
    if set(f.get("reforge", {}).get("cost_multiplier", {})) != {"普通", "精良", "稀有", "史诗", "传说"}:
        errors.append("forging.reforge.cost_multiplier 需要五个品质")
    if not f.get("exam_materials"):
        errors.append("forging.exam_materials 不能为空")
    return errors


def _realm_checks(r: dict) -> list[str]:
    from utils.realms import REALMS
    errors = []
    late = REALMS[20:]
    if set(r.get("lifespan_max", {}).get("table", {})) != set(late):
        errors.append("realms.lifespan_max.table 需要第 21 个小境起的每一个境界（含道祖）")
    if len(r.get("breakthrough", {}).get("late_rates", [])) < 1:
        errors.append("realms.breakthrough.late_rates 至少一项")
    for key in ("early_weights", "late_weights"):
        w = r.get("failure", {}).get(key, {})
        if set(w) != {"light", "heavy", "deviate"} or sum(w.values()) <= 0:
            errors.append(f"realms.failure.{key} 需要 light / heavy / deviate，权重总和 > 0")
    slots = r.get("technique_slots", {})
    if not slots or any(k not in REALMS for k in slots) or "炼气期1层" not in slots:
        errors.append("realms.technique_slots 的键必须是境界名，且要有炼气期1层")
    else:
        ordered = sorted(slots, key=REALMS.index)
        if [slots[k] for k in ordered] != sorted(slots.values()):
            errors.append("realms.technique_slots 应随境界递增")
    if r.get("breakthrough", {}).get("floor", 0) > r.get("breakthrough", {}).get("cap", 1):
        errors.append("realms.breakthrough: floor 不能大于 cap")
    return errors


def _event_checks(rain: dict, wb: dict) -> list[str]:
    errors = []
    ranges = [("spirit_rain.defense.base.stones", rain.get("defense", {}).get("base", {}).get("stones", [])),
              ("spirit_rain.defense.rank1.stones", rain.get("defense", {}).get("rank1", {}).get("stones", [])),
              ("spirit_rain.defense.rank23.stones", rain.get("defense", {}).get("rank23", {}).get("stones", [])),
              ("spirit_rain.defense.rest.stones", rain.get("defense", {}).get("rest", {}).get("stones", [])),
              ("spirit_rain.defense.power_noise", rain.get("defense", {}).get("power_noise", [])),
              ("spirit_rain.slacker.loss", rain.get("slacker", {}).get("loss", [])),
              ("spirit_rain.crystal.stones", rain.get("crystal", {}).get("stones", [])),
              ("spirit_rain.crystal.herb_count", rain.get("crystal", {}).get("herb_count", [])),
              ("spirit_rain.crystal.qty", rain.get("crystal", {}).get("qty", [])),
              ("spirit_rain.enlighten.cultivation", rain.get("enlighten", {}).get("cultivation", [])),
              ("spirit_rain.temper.cultivation", rain.get("temper", {}).get("cultivation", [])),
              ("wanbao.pill_qty", wb.get("pill_qty", [])), ("wanbao.material_qty", wb.get("material_qty", [])),
              ("wanbao.equipment_tier", wb.get("equipment_tier", []))]
    for name, r in ranges:
        if len(r) != 2 or r[0] > r[1]:
            errors.append(f"{name} 应是 [最小, 最大]")
    if set(rain.get("crystal", {}).get("herb_weights", {})) != {"普通", "稀有", "珍贵", "绝世"} or sum(rain.get("crystal", {}).get("herb_weights", {}).values()) <= 0:
        errors.append("spirit_rain.crystal.herb_weights 需要 普通 / 稀有 / 珍贵 / 绝世，权重总和 > 0")
    if set(wb.get("official", {})) != {"techniques", "pills", "materials", "equipment"}:
        errors.append("wanbao.official 需要 techniques / pills / materials / equipment")
    if len(wb.get("grade_weights", {})) != 12 or sum(wb.get("grade_weights", {}).values()) <= 0:
        errors.append("wanbao.grade_weights 需要 12 个品阶，权重总和 > 0")
    if set(wb.get("rarity_weights", {})) != {"普通", "稀有", "珍贵", "绝世"} or sum(wb.get("rarity_weights", {}).values()) <= 0:
        errors.append("wanbao.rarity_weights 需要四种稀有度，权重总和 > 0")
    sp = wb.get("start_price", {})
    if set(sp) != {"technique", "pill", "material", "equipment"} or len(sp.get("technique", {})) != 12:
        errors.append("wanbao.start_price 需要 technique（12 个品阶）/ pill / material / equipment")
    if set(wb.get("equipment_quality_weights", {})) != {"普通", "精良", "稀有", "史诗", "传说"} or sum(wb.get("equipment_quality_weights", {}).values()) <= 0:
        errors.append("wanbao.equipment_quality_weights 需要五个品质，权重总和 > 0")
    if wb.get("max_player_lots", 0) > wb.get("max_lots", 0):
        errors.append("wanbao.max_player_lots 不能超过 max_lots")
    return errors
