"""机器人的台词（U1「江湖百态」）。运行时只查表，不调用模型。

台词放在 `data/bot_dialogues/<原型>.json`，格式见该目录的 README.md。查找顺序：
  原型文件 [场景][当前档位] → 原型文件 [场景] 里最接近的档位 → `_default.json` [场景][当前档位]
所以原型文件可以只写一部分，没写的自动回退到通用台词；`_default.json` 必须是完整的格子（测试保证）。
**台词只负责说，给不给、涨多少好感一律由代码判定**（utils/bot_social.py）。
"""

import json
import random
import string
from functools import lru_cache
from pathlib import Path

DIR = Path(__file__).resolve().parent.parent / "data" / "bot_dialogues"
DEFAULT = "_default"

# 场景清单（改动要同步 README.md 和 _default.json）
SCENES = (
    "greet",          # 搭话
    "chat_again",     # 今天已经聊过
    "gift_love", "gift_like", "gift_neutral", "gift_dislike", "gift_hate",   # 收到礼物的五种反应
    "gift_limit",     # 今天收礼已达上限
    "party_accept", "party_refuse",     # 邀请组队
    "dual_accept", "dual_refuse",       # 邀请双修
    "captive_release", "captive_rob", "captive_kill",       # 真人攻击它打输了、被擒获：放走 / 劫财 / 杀
    "bot_robbed", "bot_crippled", "bot_killed",             # 它被真人打劫 / 废修为 / 击杀时说的话
    "recall_gift", "recall_absence", "recall_chat",         # 关系记忆：追加在上面某些台词后面的一句回忆
    "recall_grudge", "recall_together", "recall_defeat",    # （utils/bot_memory，偶尔出现）
    "ambush_appear", "ambush_demand", "ambush_cripple",     # 拦路（utils/bot_ambush）：放话 / 打赢后先要个交代 / 废掉修为时说的话
)
RECALL_VARS = {                                  # 回忆场景各自能用的变量（其余场景只有 player/bot/item）
    "recall_gift": {"item", "count"}, "recall_absence": {"days", "city"}, "recall_chat": {"count"},
    "recall_grudge": {"count"}, "recall_together": {"count"}, "recall_defeat": {"count"},
}
SCENE_VARS = {**RECALL_VARS, "ambush_appear": {"victim"}, "ambush_demand": {"victim"}, "ambush_cripple": {"victim"}}      # 校验用：每个场景额外允许的变量
TIERS = ("仇视", "陌生", "熟识", "至交")          # 同 utils/bot_social 的好感档位，从低到高
PLACEHOLDERS = {"player", "bot", "item"}         # 台词里允许出现的 {占位符}（回忆场景另有 RECALL_VARS）
MAX_LINE_LEN = 80
MIN_LINES_PER_CELL = 1


def files_for(archetype: str) -> list[Path]:
    """某个原型的所有台词文件：主文件 `<原型>.json`，加上任意个『批次文件』`<原型>.<批次名>.json`。
    不同的 AI / 不同的时间写的台词放在各自的批次文件里，互不覆盖，查找时自动合并。"""
    main = DIR / f"{archetype}.json"
    return ([main] if main.exists() else []) + sorted(DIR.glob(f"{archetype}.*.json"))


def archetype_of(path: Path) -> str:
    """台词文件属于哪个原型：文件名第一个『.』之前的部分（`豪爽.json` / `豪爽.批次二.json` 都是『豪爽』）。"""
    return path.name.split(".")[0]


@lru_cache(maxsize=None)
def _load(archetype: str) -> dict:
    """合并主文件和所有批次文件：同一个格子的台词拼在一起，去掉完全相同的句子。"""
    merged: dict = {}
    for path in files_for(archetype):
        for scene, cells in json.loads(path.read_text(encoding="utf-8")).get("lines", {}).items():
            for tier, texts in cells.items():
                bucket = merged.setdefault(scene, {}).setdefault(tier, [])
                bucket.extend(t for t in texts if t not in bucket)
    return merged


def reload() -> None:
    """改了台词文件之后清缓存（工具脚本、测试用）。"""
    _load.cache_clear()


def _candidates(archetype: str, scene: str, tier: str) -> list[str]:
    cells = _load(archetype).get(scene, {})
    if cells.get(tier):
        return cells[tier]
    # 原型自己没写这一档：用它写过的最接近的档位
    order = sorted((t for t in TIERS if cells.get(t)), key=lambda t: abs(TIERS.index(t) - TIERS.index(tier)))
    if order:
        return cells[order[0]]
    return _load(DEFAULT)[scene][tier]


class _Safe(dict):
    def __missing__(self, key):
        return "{" + key + "}"


def pick_template(archetype: str | None, scene: str, tier: str, rng: random.Random | None = None) -> str:
    """挑一条骨架台词（还没代入占位符）。"""
    lines = _candidates(archetype or DEFAULT, scene, tier)
    return random.choice(lines) if rng is None else rng.choice(lines)


def fill(template: str, **fmt) -> str:
    return string.Formatter().vformat(template, (), _Safe(fmt))


def get_line(archetype: str | None, scene: str, tier: str, rng: random.Random | None = None, *,
             traits: dict | None = None, **fmt) -> str:
    """取一句台词并代入 {player} / {bot} / {item}。找不到原型文件也不报错，用通用台词。
    给了 `traits`（机器人的特质，见 utils/bot_traits）就先按它的口吻改写骨架台词（utils/bot_voice）。"""
    template = pick_template(archetype, scene, tier, rng)
    if traits:
        from utils.bot_voice import style
        template = style(template, traits, scene, tier, rng)
    return fill(template, **fmt)


def coverage(archetype: str) -> dict[str, dict[str, int]]:
    """{场景: {档位: 句数}}，包含主文件和所有批次文件（没写的格子是 0）。"""
    lines = _load(archetype)
    return {s: {t: len(lines.get(s, {}).get(t, [])) for t in TIERS} for s in SCENES}


def validate_file(path: Path, require_complete: bool = False) -> list[str]:
    """校验一份台词文件，返回错误列表（空 = 合法）。"""
    errors = []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:                                          # JSON 不合法
        return [f"{path.name}: 不是合法 JSON（{e}）"]
    if data.get("archetype") != archetype_of(path):
        errors.append(f"{path.name}: archetype 字段应为 {archetype_of(path)!r}，实际是 {data.get('archetype')!r}")
    lines = data.get("lines")
    if not isinstance(lines, dict):
        return errors + [f"{path.name}: 缺少 lines"]
    for scene in lines:
        if scene not in SCENES:
            errors.append(f"{path.name}: 未知场景 {scene!r}")
    for scene in SCENES:
        cells = lines.get(scene)
        if cells is None:
            if require_complete:
                errors.append(f"{path.name}: 缺场景 {scene}")
            continue
        for tier in cells:
            if tier not in TIERS:
                errors.append(f"{path.name}: {scene} 里有未知档位 {tier!r}")
        for tier in TIERS:
            if tier not in cells:
                if require_complete:
                    errors.append(f"{path.name}: {scene}/{tier} 为空")
                continue
            texts = cells[tier]
            if not isinstance(texts, list) or len(texts) < MIN_LINES_PER_CELL:
                errors.append(f"{path.name}: {scene}/{tier} 至少要有 {MIN_LINES_PER_CELL} 句")
                continue
            for t in texts:
                if not isinstance(t, str) or not t.strip():
                    errors.append(f"{path.name}: {scene}/{tier} 有空台词")
                    continue
                if len(t) > MAX_LINE_LEN:
                    errors.append(f"{path.name}: {scene}/{tier} 台词超过 {MAX_LINE_LEN} 字：{t[:20]}…")
                try:
                    used = {f for _, f, _, _ in string.Formatter().parse(t) if f is not None}
                except ValueError:
                    errors.append(f"{path.name}: {scene}/{tier} 花括号不成对：{t}")
                    continue
                allowed = PLACEHOLDERS | SCENE_VARS.get(scene, set())
                if used - allowed:
                    errors.append(f"{path.name}: {scene}/{tier} 有不允许的占位符 {sorted(used - allowed)}：{t}")
    return errors


def validate_all() -> list[str]:
    """校验目录下所有台词文件；`_default.json` 要求格子齐全。"""
    errors = []
    for path in sorted(DIR.glob("*.json")):
        errors += validate_file(path, require_complete=path.name == f"{DEFAULT}.json")
    return errors
