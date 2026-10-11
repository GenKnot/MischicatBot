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
)
TIERS = ("仇视", "陌生", "熟识", "至交")          # 同 utils/bot_social 的好感档位，从低到高
PLACEHOLDERS = {"player", "bot", "item"}         # 台词里允许出现的 {占位符}
MAX_LINE_LEN = 80
MIN_LINES_PER_CELL = 1


@lru_cache(maxsize=None)
def _load(archetype: str) -> dict:
    path = DIR / f"{archetype}.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8")).get("lines", {})


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


def get_line(archetype: str | None, scene: str, tier: str, rng: random.Random | None = None, **fmt) -> str:
    """取一句台词并代入 {player} / {bot} / {item}。找不到原型文件也不报错，用通用台词。"""
    lines = _candidates(archetype or DEFAULT, scene, tier)
    return string.Formatter().vformat(random.choice(lines) if rng is None else rng.choice(lines), (), _Safe(fmt))


def validate_file(path: Path, require_complete: bool = False) -> list[str]:
    """校验一份台词文件，返回错误列表（空 = 合法）。"""
    errors = []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:                                          # JSON 不合法
        return [f"{path.name}: 不是合法 JSON（{e}）"]
    if data.get("archetype") != path.stem:
        errors.append(f"{path.name}: archetype 字段应为 {path.stem!r}，实际是 {data.get('archetype')!r}")
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
                if used - PLACEHOLDERS:
                    errors.append(f"{path.name}: {scene}/{tier} 有不允许的占位符 {sorted(used - PLACEHOLDERS)}：{t}")
    return errors


def validate_all() -> list[str]:
    """校验目录下所有台词文件；`_default.json` 要求格子齐全。"""
    errors = []
    for path in sorted(DIR.glob("*.json")):
        errors += validate_file(path, require_complete=path.stem == DEFAULT)
    return errors
