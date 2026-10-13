"""机器人的『特质』（U1·让每个机器人说话都不一样）。

骨架台词（场景 × 档位 × 性格原型）之外，每个机器人出生时再各抽一份特质，**只影响说话方式，不影响任何数值**：
· 内向外向（由健谈数值决定）· 星座 · 出身 · 1~2 个说话习惯 · 1~2 个口头禅 · 嗜好 · 一件往事。
说话时由 `utils/bot_voice.py` 按这些特质改写骨架台词，所以『同一性格的两个人』也不会说出同一句话。

特质池是数据（data/bot_traits/*.json），支持『批次文件』`<池>.<批次名>.json` 自动合并，方便不同的 AI 各写各的；
改写规则的格式见 data/CONTENT_GUIDE.md，校验见 `validate_pools`。
"""

import json
import random
import string
from functools import lru_cache
from pathlib import Path

from utils import bot_dialogue as bd

DIR = Path(__file__).resolve().parent.parent / "data" / "bot_traits"
POOLS = {  # 池名 -> 文件里存放条目的键
    "zodiac": "signs", "origins": "origins", "habits": "habits", "hobbies": "hobbies", "pasts": "pasts",
}
LEVELS_ORDER = ["内向", "偏内向", "中性", "偏外向", "外向"]
RULE_KEYS = {"swap", "swap_p", "end_particles", "end_p", "prefix", "prefix_p", "suffix", "suffix_p", "punct", "punct_p",
             "max_clauses", "ellipsis_p", "tiers", "scenes"}
PROB_KEYS = {"swap_p", "end_p", "prefix_p", "suffix_p", "punct_p", "ellipsis_p"}
MAX_REMARK_LEN = 40
MAX_PHRASE_LEN = 14          # 前缀 / 后缀 / 口头禅的单条长度
HABITS_PER_BOT = (1, 2)
CATCHPHRASES_PER_BOT = (1, 2)


def _files(pool: str) -> list[Path]:
    main = DIR / f"{pool}.json"
    return ([main] if main.exists() else []) + sorted(DIR.glob(f"{pool}.*.json"))


@lru_cache(maxsize=None)
def _load_pool(pool: str) -> dict:
    """合并主文件和所有批次文件。字典池：新条目加进来，已有条目的 remarks / rules 追加；口头禅池：按原型拼接去重。"""
    merged: dict = {}
    for path in _files(pool):
        data = json.loads(path.read_text(encoding="utf-8"))
        if pool == "catchphrases":
            for arche, items in data.items():
                if arche.startswith("_"):
                    continue
                bucket = merged.setdefault(arche, [])
                bucket.extend(t for t in items if t not in bucket)
        elif pool == "introversion":
            merged.update(data.get("levels", {}))
        else:
            for name, entry in data.get(POOLS[pool], {}).items():
                if name not in merged:
                    merged[name] = json.loads(json.dumps(entry))
                    continue
                cur = merged[name]
                for key in ("remarks", "rules"):
                    cur[key] = cur.get(key, []) + [x for x in entry.get(key, []) if x not in cur.get(key, [])]
                cur["weights"] = {**entry.get("weights", {}), **cur.get("weights", {})}
    return merged


def reload() -> None:
    _load_pool.cache_clear()


def pool(name: str) -> dict:
    return _load_pool(name)


# ---- 校验 -------------------------------------------------------------------

def _placeholders(text: str) -> bool:
    try:
        return any(f is not None for _, f, _, _ in string.Formatter().parse(text))
    except ValueError:
        return True


def validate_rule(rule: dict, where: str) -> list[str]:
    errors = []
    if not isinstance(rule, dict):
        return [f"{where}: 规则应是对象"]
    for k in rule:
        if k not in RULE_KEYS:
            errors.append(f"{where}: 未知规则键 {k!r}（可用：{sorted(RULE_KEYS)}）")
    for k in PROB_KEYS & set(rule):
        if not isinstance(rule[k], (int, float)) or not 0 <= rule[k] <= 1:
            errors.append(f"{where}: {k} 应在 0~1 之间")
    if "max_clauses" in rule and (not isinstance(rule["max_clauses"], int) or rule["max_clauses"] < 1):
        errors.append(f"{where}: max_clauses 应为正整数")
    for k in ("swap", "punct"):
        if k in rule:
            if not isinstance(rule[k], dict) or not rule[k]:
                errors.append(f"{where}: {k} 应是非空对象")
                continue
            for a, b in rule[k].items():
                if not a or not isinstance(b, str) or _placeholders(a) or _placeholders(b):
                    errors.append(f"{where}: {k} 里的 {a!r}→{b!r} 不合法（不能为空，不能含花括号）")
    for k, endings, hint in (("prefix", ("，", "、", "——", "…", "：", "！", "？"), "句首补话要以逗号或感叹类标点结尾（如『说起来，』『来！』）"),
                             ("suffix", ("。", "！", "？", "…"), "句尾补话要以句号类标点结尾（如『你说是不是？』）")):
        for t in rule.get(k, []) if isinstance(rule.get(k), list) else []:
            if isinstance(t, str) and t.strip() and not t.endswith(endings):
                errors.append(f"{where}: {k} 里的 {t!r} 不合法：{hint}")
    for k in ("end_particles", "prefix", "suffix"):
        if k in rule:
            items = rule[k]
            if not isinstance(items, list) or not items:
                errors.append(f"{where}: {k} 应是非空列表")
                continue
            for t in items:
                if not isinstance(t, str) or not t.strip() or len(t) > MAX_PHRASE_LEN or _placeholders(t):
                    errors.append(f"{where}: {k} 里的 {t!r} 不合法（非空、≤{MAX_PHRASE_LEN} 字、不含花括号）")
    if "end_particles" in rule and any(len(t) != 1 for t in rule["end_particles"] if isinstance(t, str)):
        errors.append(f"{where}: end_particles 每个只能是一个字")
    for k, allowed in (("tiers", bd.TIERS), ("scenes", bd.SCENES)):
        if k in rule and (not isinstance(rule[k], list) or not rule[k] or set(rule[k]) - set(allowed)):
            errors.append(f"{where}: {k} 应是 {list(allowed)} 的非空子集")
    return errors


def validate_pools() -> list[str]:
    """校验所有特质池。"""
    from utils.bot_social import load_archetypes
    archetypes = set(load_archetypes())
    errors = []

    def weights_ok(entry, where):
        for a, w in entry.get("weights", {}).items():
            if a not in archetypes or not isinstance(w, (int, float)) or w < 0:
                errors.append(f"{where}: weights 里的 {a!r}:{w!r} 不合法（键必须是性格原型，值非负）")

    intro = pool("introversion")
    if list(intro) != LEVELS_ORDER:
        errors.append(f"introversion: 档位应依次为 {LEVELS_ORDER}")
    else:
        last = 0
        for lv, e in intro.items():
            if not (isinstance(e.get("talk_max"), int) and last < e["talk_max"] <= 100):
                errors.append(f"introversion.{lv}: talk_max 应递增且 ≤100")
            last = e.get("talk_max", last)
            for k in ("catch_p", "remark_p"):
                if not 0 <= e.get(k, -1) <= 1:
                    errors.append(f"introversion.{lv}: {k} 应在 0~1 之间")
            for i, r in enumerate(e.get("rules", [])):
                errors += validate_rule(r, f"introversion.{lv}.rules[{i}]")
        if intro["外向"].get("talk_max") != 100:
            errors.append("introversion.外向: talk_max 应为 100")
    for name, minimum in (("zodiac", 12), ("origins", 8), ("habits", 6), ("hobbies", 8), ("pasts", 6)):
        entries = pool(name)
        if len(entries) < minimum:
            errors.append(f"{name}: 至少 {minimum} 个条目，现在 {len(entries)}")
        for key, e in entries.items():
            where = f"{name}.{key}"
            if not e.get("desc"):
                errors.append(f"{where}: 缺 desc")
            weights_ok(e, where)
            for i, r in enumerate(e.get("rules", [])):
                errors += validate_rule(r, f"{where}.rules[{i}]")
            if name in ("hobbies", "pasts"):
                rem = e.get("remarks", [])
                if len(rem) < 2:
                    errors.append(f"{where}: remarks 至少 2 条")
                for t in rem:
                    if not isinstance(t, str) or not t.strip() or len(t) > MAX_REMARK_LEN or _placeholders(t):
                        errors.append(f"{where}: remarks 里的 {t!r} 不合法（非空、≤{MAX_REMARK_LEN} 字、不含花括号）")
            elif name != "zodiac" and not e.get("rules"):
                errors.append(f"{where}: 需要 rules")
    cp = pool("catchphrases")
    if "通用" not in cp or len(cp["通用"]) < 10:
        errors.append("catchphrases: 『通用』池至少 10 条")
    for arche, items in cp.items():
        if arche != "通用" and arche not in archetypes:
            errors.append(f"catchphrases: {arche!r} 不是性格原型")
        for t in items:
            if not isinstance(t, str) or not t.strip() or len(t) > MAX_PHRASE_LEN or _placeholders(t):
                errors.append(f"catchphrases.{arche}: {t!r} 不合法（非空、≤{MAX_PHRASE_LEN} 字、不含花括号）")
    return errors


# ---- 抽特质 -----------------------------------------------------------------

def introversion_of(talk: int, rng: random.Random | None = None) -> str:
    """由健谈数值定内向外向；邻近档位交界处加一点随机，免得同一数值的人完全一样。"""
    rng = rng or random.Random()
    talk = max(0, min(100, talk + rng.randint(-4, 4)))
    for lv, e in pool("introversion").items():
        if talk <= e["talk_max"]:
            return lv
    return "外向"


def _weighted(entries: dict, archetype: str, rng: random.Random, k: int = 1, exclude=()) -> list[str]:
    names = [n for n in entries if n not in exclude]
    weights = [entries[n].get("weights", {}).get(archetype, 1.0) for n in names]
    out = []
    for _ in range(min(k, len(names))):
        if sum(weights) <= 0:
            break
        pick = rng.choices(names, weights=weights)[0]
        out.append(pick)
        weights[names.index(pick)] = 0.0
    return out


def roll_traits(archetype: str, talk: int, rng: random.Random | None = None) -> dict:
    """给一个机器人抽一份特质（可复现：传同样的 rng 种子得到同样的结果）。"""
    rng = rng or random.Random()
    cp = pool("catchphrases")
    own, common = cp.get(archetype, []), cp.get("通用", [])
    phrases = []
    for _ in range(rng.randint(*CATCHPHRASES_PER_BOT)):
        src = own if own and rng.random() < 0.6 else common
        choices = [p for p in src if p not in phrases] or [p for p in common if p not in phrases]
        if choices:
            phrases.append(rng.choice(choices))
    return {
        "introversion": introversion_of(talk, rng),
        "zodiac": rng.choice(sorted(pool("zodiac"))),
        "origin": _weighted(pool("origins"), archetype, rng)[0],
        "habits": _weighted(pool("habits"), archetype, rng, rng.randint(*HABITS_PER_BOT)),
        "catchphrases": phrases,
        "hobby": _weighted(pool("hobbies"), archetype, rng)[0],
        "past": _weighted(pool("pasts"), archetype, rng)[0],
    }


def describe(traits: dict) -> str:
    """资料页上给玩家看的一行：出身 · 星座 · 内向外向（嗜好 / 往事让玩家自己从对话里发现）。"""
    if not traits:
        return ""
    return f"出身：{traits['origin']} · {traits['zodiac']}座 · {traits['introversion']}"
