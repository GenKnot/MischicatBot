"""机器人的行为画像（U1·江湖百态 P1）：把『性格』从说话方式扩展到做事方式。

用户 2026-10-12 的要求：行为由『基础性格 + 道德 / 行为倾向 + 出身 + 境界 + 经历 + 关系 + 处境 + 随机性』共同决定；
善良守序的人也可能偶尔反常（比如 13% 概率）；数值要可计算、可配置。

· 轴（0~100，`data/bot_profiles.json`）：善意 kindness（已有）· 守序 lawful · 冲动 impulse · 义气 loyalty · 记仇 vengeful · 关系容量 capacity；
  还有偏离概率 deviance。按原型给范围随机，出身再加减一点。生成机器人时抽，老机器人每日结算时按 `bot_id` 种子补上（可复现）。
· 阵营标签（`alignment`）：善意 × 守序 → 守序善良 / 中立善良 / 混乱善良 / … / 混乱邪恶，给资料页和台词条件用（P5）。
· 决策接口（给仇恨 / 拦路 / 处置用）：`effective`（这一次有没有『反常』）、`revenge_style`（直接 / 隐忍 / 等待时机）、`captive_shift`（赢了之后处置的倾向）。
"""

import random
from functools import lru_cache
from pathlib import Path

from utils import settings_hub

_PATH = Path(__file__).resolve().parent.parent / "data" / "bot_profiles.json"
AXES = ("lawful", "impulse", "loyalty", "vengeful", "capacity")
PERCENT_AXES = ("lawful", "impulse", "loyalty", "vengeful")
KIND_LABEL = {"high": "善良", "mid": "中立", "low": "邪恶"}
ORDER_LABEL = {"high": "守序", "mid": "中立", "low": "混乱"}
STYLES = ("直接", "隐忍", "等待时机")


@lru_cache(maxsize=1)
def _load() -> dict:
    return settings_hub.read(_PATH)


def load() -> dict:
    return _load()


def reload() -> None:
    _load.cache_clear()


def validate(cfg: dict, archetypes: list[str] | None = None, origins: list[str] | None = None) -> list[str]:
    errors = []
    arch = cfg.get("archetypes", {})
    if archetypes is not None and set(arch) != set(archetypes):
        errors.append(f"archetypes 应与 bot_archetypes.json 一致，差异：{sorted(set(arch) ^ set(archetypes))}")
    for name, spec in arch.items():
        for axis in AXES:
            r = spec.get(axis)
            hi = 50 if axis == "capacity" else 100
            if not (isinstance(r, list) and len(r) == 2 and 0 <= r[0] <= r[1] <= hi):
                errors.append(f"{name}.{axis} 应是 [最小, 最大]，范围 0~{hi}")
        d = spec.get("deviance")
        if not (isinstance(d, list) and len(d) == 2 and 0 <= d[0] <= d[1] <= 0.5):
            errors.append(f"{name}.deviance 应是 [最小, 最大]，范围 0~0.5")
    for origin, mods in cfg.get("origin_mods", {}).items():
        if origins is not None and origin not in origins:
            errors.append(f"origin_mods 里有未知出身 {origin!r}")
        for axis, v in mods.items():
            if axis not in PERCENT_AXES or not isinstance(v, int) or abs(v) > 30:
                errors.append(f"origin_mods.{origin}.{axis}：只能调 {PERCENT_AXES}，幅度 ≤30")
    t = cfg.get("thresholds", {})
    if not (0 <= t.get("low", -1) < t.get("high", -1) <= 100):
        errors.append("thresholds 应满足 0 ≤ low < high ≤ 100")
    return errors


def _clamp(v, lo=0, hi=100):
    return max(lo, min(hi, v))


def roll_profile(archetype: str, origin: str | None = None, rng: random.Random | None = None) -> dict:
    """抽一份行为画像（传同样的 rng 种子得到同样的结果）。"""
    rng = rng or random.Random()
    cfg = _load()
    spec = cfg["archetypes"][archetype]
    mods = cfg.get("origin_mods", {}).get(origin or "", {})
    out = {a: _clamp(rng.randint(*spec[a]) + mods.get(a, 0)) for a in PERCENT_AXES}
    out["capacity"] = rng.randint(*spec["capacity"])
    out["deviance"] = round(rng.uniform(*spec["deviance"]), 3)
    return out


def level(value: int) -> str:
    t = _load()["thresholds"]
    return "high" if value >= t["high"] else "low" if value <= t["low"] else "mid"


def alignment(kindness: int, lawful: int) -> str:
    """阵营标签：守序善良 / 中立善良 / … / 绝对中立 / … / 混乱邪恶。"""
    k, o = KIND_LABEL[level(kindness)], ORDER_LABEL[level(lawful)]
    return "绝对中立" if (k, o) == ("中立", "中立") else f"{o}{k}"


def tags(kindness: int, profile: dict | None) -> list[str]:
    """给台词 / 事件挑选用的标签（P5 的条件化文案库用它做条件）。"""
    if not profile:
        return []
    out = [alignment(kindness, profile["lawful"])]
    out.append("冲动" if level(profile["impulse"]) == "high" else "谨慎" if level(profile["impulse"]) == "low" else "")
    if level(profile["loyalty"]) == "high":
        out.append("重义气")
    if level(profile["vengeful"]) == "high":
        out.append("记仇")
    if is_righteous(kindness, profile):
        out.append("好打抱不平")
    return [t for t in out if t]


def is_righteous(kindness: int, profile: dict | None) -> bool:
    """爱打抱不平：心地不坏（善意不低）、而且义气重或性子急。路过看见不平事会插一手（拦路组团、劝架都用它）。"""
    if not profile:
        return False
    return kindness >= 55 and (level(profile["loyalty"]) == "high" or level(profile["impulse"]) == "high")


def effective(kindness: int, profile: dict | None, rng=random) -> tuple[int, int, int, bool]:
    """这一次决定用的 (善意, 守序, 冲动, 是否反常)。以 `deviance` 的概率『反常』：善恶、守序混乱倒过来，冲动也倒过来。"""
    if not profile:
        return kindness, 50, 50, False
    if rng.random() < profile.get("deviance", 0):
        return 100 - kindness, 100 - profile["lawful"], 100 - profile["impulse"], True
    return kindness, profile["lawful"], profile["impulse"], False


def revenge_style(profile: dict | None, rng=random) -> str:
    """要报仇时怎么报：直接（冲动，打不过也上）/ 隐忍（谨慎，先打听、修炼）/ 等待时机（折中）。"""
    _k, _o, impulse, _flipped = effective(50, profile, rng)
    p_direct = impulse / 100
    r = rng.random()
    if impulse >= 65:
        return "直接" if r < 0.8 else "等待时机"
    if impulse <= 35:
        return "隐忍" if r < 0.8 else "等待时机"
    return "直接" if r < p_direct * 0.5 else "隐忍" if r > 1 - (1 - p_direct) * 0.5 else "等待时机"


def captive_shift(kindness: int, profile: dict | None, rng=random) -> dict[str, float]:
    """赢了玩家之后处置倾向的修正倍数 {release, rob, kill}：善良的更愿意放，邪恶的更狠，混乱的更容易下杀手；缺画像则不修正。"""
    if not profile:
        return {}
    k, lawful, _impulse, _ = effective(kindness, profile, rng)
    shift = {"release": 1.0, "rob": 1.0, "kill": 1.0}
    if level(k) == "high":
        shift.update(release=1.5, kill=0.3)
    elif level(k) == "low":
        shift.update(release=0.6, rob=1.2, kill=1.8)
    if level(lawful) == "low":
        shift["kill"] *= 1.2
    elif level(lawful) == "high":
        shift["kill"] *= 0.8
    return shift
