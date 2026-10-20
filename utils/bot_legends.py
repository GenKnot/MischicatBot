"""天骄的称号与背景（U1「江湖百态」·天骄的一生）。

只有天骄有称号（epithet，如「寒江雪」）和一句话背景（backstory），按性格原型从 data/bot_legends.json 取：
称号随机、背景里的 `{home}` 换成常驻城市。同一批生成里称号尽量不重复。
传闻、资料页都用它们：天骄是『有名有姓、有来历』的人物，不是一串数字。
"""

import json
import random
import string
from functools import lru_cache
from pathlib import Path

from utils import settings_hub

_DATA = Path(__file__).resolve().parent.parent / "data" / "bot_legends.json"
MAX_EPITHET_LEN = 8
MAX_BACKSTORY_LEN = 80
MIN_PER_ARCHETYPE = 3
ALLOWED = {"home"}


@lru_cache(maxsize=1)
def _load() -> dict:
    return settings_hub.read(_DATA)


def load() -> dict:
    return json.loads(json.dumps(_load()))


def validate(data: dict) -> list[str]:
    from utils.bot_social import load_archetypes
    errors = []
    names = set(load_archetypes())
    for key in ("epithets", "backstories"):
        if set(data.get(key, {})) != names:
            errors.append(f"{key} 的性格原型应与 bot_archetypes.json 一致")
    for arche, items in data.get("epithets", {}).items():
        if len(items) < MIN_PER_ARCHETYPE or len(set(items)) != len(items):
            errors.append(f"epithets.{arche}: 至少 {MIN_PER_ARCHETYPE} 个且不重复")
        for t in items:
            if not t.strip() or len(t) > MAX_EPITHET_LEN or "{" in t:
                errors.append(f"epithets.{arche}: 称号不合法：{t!r}")
    for arche, items in data.get("backstories", {}).items():
        if len(items) < MIN_PER_ARCHETYPE:
            errors.append(f"backstories.{arche}: 至少 {MIN_PER_ARCHETYPE} 条")
        for t in items:
            if len(t) > MAX_BACKSTORY_LEN:
                errors.append(f"backstories.{arche}: 超过 {MAX_BACKSTORY_LEN} 字：{t[:12]}…")
            try:
                used = {f for _, f, _, _ in string.Formatter().parse(t) if f is not None}
            except ValueError:
                errors.append(f"backstories.{arche}: 花括号不成对：{t}")
                continue
            if used - ALLOWED:
                errors.append(f"backstories.{arche}: 不允许的占位符 {sorted(used - ALLOWED)}：{t}")
    return errors


def make_legend(archetype: str, home: str, rng: random.Random | None = None, taken: set | None = None) -> tuple[str, str]:
    """(称号, 背景)。`taken`：已被用掉的称号，尽量避开（用完了就允许重复）。"""
    rng, data = rng or random.Random(), _load()
    pool = [e for e in data["epithets"][archetype] if not taken or e not in taken] or data["epithets"][archetype]
    epithet = rng.choice(pool)
    if taken is not None:
        taken.add(epithet)
    backstory = rng.choice(data["backstories"][archetype]).format(home=home or "某处")
    return epithet, backstory
