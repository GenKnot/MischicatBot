"""统一设置（U1·江湖百态 B）：所有『数字 / 开关』类的配置，管理员不改文件、不重启，在游戏里就能查和调。

做法：各系统的配置还是放在 `data/*.json`（文件里的值是**默认值**），这里在读文件的那一刻叠加管理员的**覆盖值**：
· 覆盖值存在 `bot_world_state`（键 `cfg.<文件名>`，值是 {路径: 新值} 的 json），重启还在；启动时 `refresh()` 读进内存，`read(path)` 读文件时叠加；
· 路径用点号：`kill.cap`、`outcomes.by_archetype.豪爽.击杀`；列表元素用序号：`reach_delay_years.none.0`；
· 只能改『叶子』上的数字 / 开关（整数、小数、真假），而且类型要和默认值一致；文字（台词、模板）、列表长度、字典结构都不在这里改（那是内容，改文件）；
· 每次设置先把『覆盖后的整份配置』交给该系统自己的校验函数，不通过就拒绝，所以调不坏；
· 恢复默认 = 删掉覆盖值。写在代码里、没搬进配置的系数（见 .gk/ISSUES.md）不在这里。
出错时：读覆盖值失败只记 warning，用默认值，不拖垮游戏。
"""

import copy
import importlib
import json
import logging
from pathlib import Path

from sqlalchemy import delete, select

from utils.db_async import AsyncSessionLocal, BotWorldState

log = logging.getLogger(__name__)

PREFIX = "cfg."
DATA = Path(__file__).resolve().parent.parent / "data"

# 文件名 → (模块, 校验函数名)。校验函数收整份配置，返回错误列表。
REGISTRY = {
    "bot_economy.json": ("utils.bot_economy", "validate_config"),
    "bot_profiles.json": ("utils.bot_profile", "validate"),
    "bot_ties.json": ("utils.bot_ties", "validate"),
    "bot_grudges.json": ("utils.bot_grudges", "validate"),
    "bot_ambush.json": ("utils.bot_ambush", "validate"),
    "bot_chatter_config.json": ("utils.bot_chatter", "validate"),
    "bot_requests.json": ("utils.bot_requests", "validate"),
    "bot_investigation.json": ("utils.bot_investigation", "validate"),
    "bot_feuds.json": ("utils.bot_feuds", "validate"),
    "rumors.json": ("utils.rumors", "validate_config"),
    "llm_polish.json": ("utils.llm_polish", "validate"),
}
MAX_VALUE = 10 ** 9

_overrides: dict[str, dict[str, object]] = {}


# ---- 路径与叶子 -------------------------------------------------------------

def is_tunable(v) -> bool:
    return isinstance(v, (bool, int, float))


def leaves(obj, prefix: str = ""):
    """所有能调的叶子 (路径, 值)：字典里以 _ 开头的键（说明）跳过。"""
    if isinstance(obj, dict):
        for k, v in obj.items():
            if not str(k).startswith("_"):
                yield from leaves(v, f"{prefix}{k}.")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from leaves(v, f"{prefix}{i}.")
    elif is_tunable(obj):
        yield prefix[:-1], obj


def _walk(obj, parts: list[str]):
    """按路径走到叶子的『父亲』，返回 (父亲, 最后一段的键)；走不通返回 None。"""
    for p in parts[:-1]:
        if isinstance(obj, dict) and p in obj:
            obj = obj[p]
        elif isinstance(obj, list) and p.isdigit() and int(p) < len(obj):
            obj = obj[int(p)]
        else:
            return None
    last = parts[-1]
    if isinstance(obj, dict) and last in obj:
        return obj, last
    if isinstance(obj, list) and last.isdigit() and int(last) < len(obj):
        return obj, int(last)
    return None


def apply(cfg: dict, overrides: dict) -> dict:
    """把覆盖值叠到配置上（原地改，返回它）。路径对不上（配置改过版）的覆盖值直接忽略。"""
    for path, value in overrides.items():
        hit = _walk(cfg, path.split("."))
        if hit is not None and is_tunable(hit[0][hit[1]]):
            hit[0][hit[1]] = value
    return cfg


def read(path: Path) -> dict:
    """各系统读配置文件的入口：文件里的默认值 + 管理员的覆盖值。"""
    return apply(json.loads(path.read_text(encoding="utf-8")), _overrides.get(path.name, {}))


def resolve(name: str) -> str | None:
    """管理员打的文件名 → 注册表里的文件名：精确 / 缺 .json / 唯一的子串匹配（`feuds` → bot_feuds.json）。"""
    name = name.strip()
    if name in REGISTRY:
        return name
    if name + ".json" in REGISTRY:
        return name + ".json"
    hits = [n for n in REGISTRY if name and name in n]
    return hits[0] if len(hits) == 1 else None


def defaults(name: str) -> dict:
    return json.loads((DATA / name).read_text(encoding="utf-8"))


def parse(raw: str, default):
    """把管理员输入的文字按默认值的类型转成值。返回 (值, 错误)。"""
    raw = raw.strip()
    if isinstance(default, bool):
        if raw in ("开", "true", "True", "是", "1"):
            return True, None
        if raw in ("关", "false", "False", "否", "0"):
            return False, None
        return None, "这是个开关，请填 开 / 关"
    try:
        v = float(raw)
    except ValueError:
        return None, "请填数字"
    if v != v or abs(v) > MAX_VALUE:
        return None, "数字太大或无效"
    return (int(v) if isinstance(default, int) and v == int(v) else v), None


# ---- 缓存与校验 -------------------------------------------------------------

def reload_module(name: str) -> None:
    module = importlib.import_module(REGISTRY[name][0])
    module._load.cache_clear()
    reload = getattr(module, "reload", None)
    if reload:
        reload()


def validate(name: str, cfg: dict) -> list[str]:
    module, fn = REGISTRY[name]
    return getattr(importlib.import_module(module), fn)(cfg)


# ---- 存取 -------------------------------------------------------------------

async def refresh() -> int:
    """启动时（和需要时）把全部覆盖值从库里读进内存并清缓存。返回覆盖了几项。"""
    global _overrides
    fresh: dict[str, dict] = {}
    try:
        async with AsyncSessionLocal() as session:
            for row in (await session.execute(select(BotWorldState).where(BotWorldState.key.like(PREFIX + "%")))).scalars():
                name = row.key[len(PREFIX):]
                try:
                    data = json.loads(row.value)
                except ValueError:
                    continue
                if name in REGISTRY and isinstance(data, dict):
                    fresh[name] = {k: v for k, v in data.items() if is_tunable(v)}
    except Exception:
        log.warning("读取设置覆盖值失败，沿用文件里的默认值", exc_info=True)
        return 0
    changed = set(_overrides) | set(fresh)
    _overrides = fresh
    for name in changed:
        reload_module(name)
    return sum(len(v) for v in fresh.values())


async def _save(name: str, data: dict) -> None:
    async with AsyncSessionLocal() as session:
        if data:
            await session.merge(BotWorldState(key=PREFIX + name, value=json.dumps(data, ensure_ascii=False)))
        else:
            await session.execute(delete(BotWorldState).where(BotWorldState.key == PREFIX + name))
        await session.commit()


def overrides_of(name: str) -> dict:
    return dict(_overrides.get(name, {}))


async def set_value(name: str, path: str, raw: str) -> tuple[bool, str]:
    """设置一项。返回 (成功, 说明)。"""
    if name not in REGISTRY:
        return False, f"没有这个配置文件：{name}"
    base = defaults(name)
    hit = _walk(base, path.split("."))
    if hit is None or not is_tunable(hit[0][hit[1]]) or any(p.startswith("_") for p in path.split(".")):
        return False, f"{name} 里没有可调的 `{path}`（只能调数字 / 开关）"
    default = hit[0][hit[1]]
    value, err = parse(raw, default)
    if err:
        return False, err
    new = {**_overrides.get(name, {}), path: value}
    errors = validate(name, apply(copy.deepcopy(base), new))
    if errors:
        return False, "配置校验没通过：" + "；".join(errors[:3])
    if value == default:
        new.pop(path)
    try:
        await _save(name, new)
    except Exception:
        log.warning("保存设置失败：%s %s", name, path, exc_info=True)
        return False, "保存失败，请稍后再试"
    _overrides[name] = new
    reload_module(name)
    return True, f"{name} · {path}：{default} → {value}" if value != default else f"{name} · {path} 已是默认值 {default}"


async def reset(name: str, path: str | None = None) -> tuple[bool, str]:
    """恢复默认：某一项，或整份文件。"""
    if name not in REGISTRY:
        return False, f"没有这个配置文件：{name}"
    cur = _overrides.get(name, {})
    if path is not None and path not in cur:
        return False, f"{name} · {path} 本来就是默认值"
    new = {k: v for k, v in cur.items() if path is not None and k != path}
    if path is None and not cur:
        return False, f"{name} 没有被改过"
    try:
        await _save(name, new)
    except Exception:
        log.warning("恢复默认失败：%s", name, exc_info=True)
        return False, "保存失败，请稍后再试"
    if new:
        _overrides[name] = new
    else:
        _overrides.pop(name, None)
    reload_module(name)
    return True, f"{name} · {path} 已恢复默认" if path else f"{name} 已全部恢复默认（{len(cur)} 项）"


# ---- 查询 -------------------------------------------------------------------

def overview() -> list[dict]:
    """每个配置文件：可调项数、被改了几项、文件里的『说明』。"""
    out = []
    for name in REGISTRY:
        cfg = defaults(name)
        out.append({"file": name, "count": sum(1 for _ in leaves(cfg)), "changed": len(_overrides.get(name, {})),
                    "note": str(cfg.get("_说明", ""))[:120]})
    return out


def entries(name: str, query: str = "") -> list[dict]:
    """某文件里的可调项 [{path, default, value, changed}]，query 非空时按路径子串过滤。"""
    over = _overrides.get(name, {})
    out = []
    for path, default in leaves(defaults(name)):
        if query and query not in path:
            continue
        out.append({"path": path, "default": default, "value": over.get(path, default), "changed": path in over})
    return out


def search(query: str, limit: int = 30) -> list[dict]:
    """跨文件按路径子串搜，返回 [{file, path, default, value, changed}]（最多 limit 条）。"""
    out = []
    for name in REGISTRY:
        for e in entries(name, query):
            out.append({"file": name, **e})
            if len(out) >= limit:
                return out
    return out
