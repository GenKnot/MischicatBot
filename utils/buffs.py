import json
import time


def _load(player) -> dict:
    raw = player.get("active_buffs") if isinstance(player, dict) else getattr(player, "active_buffs", "{}")
    try:
        return json.loads(raw or "{}")
    except Exception:
        return {}


def _now() -> float:
    return time.time()


def get_buffs(player) -> dict:
    buffs = _load(player)
    now = _now()
    cleaned = {}
    for key, val in buffs.items():
        if isinstance(val, dict) and "expires_at" in val:
            if val["expires_at"] > now:
                cleaned[key] = val
        else:
            cleaned[key] = val
    return cleaned


def has_buff(player, key: str) -> bool:
    return key in get_buffs(player)


def get_buff_value(player, key: str, default=0):
    buffs = get_buffs(player)
    entry = buffs.get(key)
    if entry is None:
        return default
    if isinstance(entry, dict):
        return entry.get("value", default)
    return entry


def buffs_to_json(buffs: dict) -> str:
    return json.dumps(buffs, ensure_ascii=False)


def apply_buff(player_buffs_json: str, key: str, value, expires_at: float | None = None, charges: int | None = None) -> str:
    try:
        buffs = json.loads(player_buffs_json or "{}")
    except Exception:
        buffs = {}
    entry: dict = {"value": value}
    if expires_at is not None:
        entry["expires_at"] = expires_at
    if charges is not None:
        entry["charges"] = charges
    buffs[key] = entry
    return json.dumps(buffs, ensure_ascii=False)


def consume_once_buff(player_buffs_json: str, key: str) -> tuple[bool, str]:
    try:
        buffs = json.loads(player_buffs_json or "{}")
    except Exception:
        buffs = {}
    if key not in buffs:
        return False, json.dumps(buffs, ensure_ascii=False)
    del buffs[key]
    return True, json.dumps(buffs, ensure_ascii=False)


def consume_charge_buff(player_buffs_json: str, key: str) -> tuple[bool, str]:
    try:
        buffs = json.loads(player_buffs_json or "{}")
    except Exception:
        buffs = {}
    if key not in buffs:
        return False, json.dumps(buffs, ensure_ascii=False)
    entry = buffs[key]
    charges = entry.get("charges", 1) - 1
    if charges <= 0:
        del buffs[key]
    else:
        buffs[key]["charges"] = charges
    return True, json.dumps(buffs, ensure_ascii=False)


def get_cultivation_speed_bonus(player) -> float:
    buffs = get_buffs(player)
    entry = buffs.get("cultivation_speed_bonus")
    if not entry:
        return 0.0
    pct = entry.get("value", 0) if isinstance(entry, dict) else entry
    return pct / 100.0


def get_combat_power_bonus(player) -> float:
    buffs = get_buffs(player)
    entry = buffs.get("combat_power_bonus")
    if not entry:
        return 0.0
    pct = entry.get("value", 0) if isinstance(entry, dict) else entry
    return pct / 100.0


def get_stat_temp(player) -> dict:
    buffs = get_buffs(player)
    entry = buffs.get("stat_temp")
    if not entry:
        return {}
    return entry.get("value", {}) if isinstance(entry, dict) else {}


def get_escape_bonus(player) -> float:
    buffs = get_buffs(player)
    entry = buffs.get("escape_bonus_once")
    if not entry:
        return 0.0
    pct = entry.get("value", 0) if isinstance(entry, dict) else entry
    return pct / 100.0


def get_explore_rare_bonus(player) -> float:
    buffs = get_buffs(player)
    entry = buffs.get("explore_rare_bonus_once")
    if not entry:
        return 0.0
    pct = entry.get("value", 0) if isinstance(entry, dict) else entry
    return pct / 100.0


def get_gather_bonus(player) -> float:
    buffs = get_buffs(player)
    entry = buffs.get("gather_bonus_once")
    if not entry:
        return 0.0
    pct = entry.get("value", 0) if isinstance(entry, dict) else entry
    return pct / 100.0


def get_spirit_stones_bonus(player) -> float:
    buffs = get_buffs(player)
    entry = buffs.get("spirit_stones_bonus_once")
    if not entry:
        return 0.0
    pct = entry.get("value", 0) if isinstance(entry, dict) else entry
    return pct / 100.0


def get_reputation_bonus(player) -> float:
    buffs = get_buffs(player)
    entry = buffs.get("reputation_bonus_once")
    if not entry:
        return 0.0
    pct = entry.get("value", 0) if isinstance(entry, dict) else entry
    return pct / 100.0
