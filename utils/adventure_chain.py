import json
import time
from functools import lru_cache
from pathlib import Path

from sqlalchemy import text

from utils import settings_hub
from utils.db_async import AsyncSessionLocal

_CONFIG_PATH = Path(__file__).resolve().parent.parent / "data" / "adventure_chains_config.json"


@lru_cache(maxsize=4)
def _load(path: str) -> dict:
    return settings_hub.read(Path(path))


def validate(cfg: dict) -> list[str]:
    chances = cfg.get("trigger_chance", {})
    if any(not 0 <= v <= 1 for v in chances.values()):
        return ["trigger_chance 里每个概率应在 0~1"]
    return []


def _load_trigger_chances() -> dict:
    try:
        return _load(str(_CONFIG_PATH)).get("trigger_chance", {})
    except Exception:
        return {}


def get_trigger_chance(chain_id: str, default: float) -> float:
    """奇遇链的触发概率（data/adventure_chains_config.json，管理员可以 `cat!调参` 修改）；配置里没有就用代码给的默认值。"""
    chances = _load_trigger_chances()
    return chances.get(chain_id, default)


async def get_chain_progress(discord_id: str) -> dict:
    async with AsyncSessionLocal() as session:
        row = await session.execute(
            text("SELECT progress FROM adventure_progress WHERE discord_id = :uid"),
            {"uid": discord_id}
        )
        row = row.fetchone()
        if row and row[0]:
            return json.loads(row[0])
        return {}


async def save_chain_progress(discord_id: str, progress: dict):
    async with AsyncSessionLocal() as session:
        await session.execute(
            text("""
                INSERT INTO adventure_progress (discord_id, progress, updated_at)
                VALUES (:uid, :prog, :ts)
                ON CONFLICT(discord_id) DO UPDATE SET progress = :prog, updated_at = :ts
            """),
            {"uid": discord_id, "prog": json.dumps(progress, ensure_ascii=False), "ts": time.time()}
        )
        await session.commit()


async def get_stage(discord_id: str, chain_id: str) -> int:
    progress = await get_chain_progress(discord_id)
    return progress.get(chain_id, {}).get("stage", 0)


async def advance_stage(discord_id: str, chain_id: str, extra_data: dict = None):
    progress = await get_chain_progress(discord_id)
    entry = progress.get(chain_id, {"stage": 0, "completed": False, "data": {}})
    entry["stage"] += 1
    if extra_data:
        entry["data"].update(extra_data)
    progress[chain_id] = entry
    await save_chain_progress(discord_id, progress)


async def mark_completed(discord_id: str, chain_id: str):
    progress = await get_chain_progress(discord_id)
    entry = progress.get(chain_id, {"stage": 0, "completed": False, "data": {}})
    entry["completed"] = True
    progress[chain_id] = entry
    await save_chain_progress(discord_id, progress)


async def is_completed(discord_id: str, chain_id: str) -> bool:
    progress = await get_chain_progress(discord_id)
    return progress.get(chain_id, {}).get("completed", False)


async def apply_chain_rewards(discord_id: str, rewards: dict):
    stat_cols = {
        "spirit_stones", "lifespan", "cultivation", "comprehension",
        "physique", "fortune", "bone", "soul", "reputation"
    }
    for key, val in rewards.items():
        if key in stat_cols:
            async with AsyncSessionLocal() as session:
                await session.execute(
                    text(f"UPDATE players SET {key} = MAX(0, {key} + :val) WHERE discord_id = :uid"),
                    {"val": val, "uid": discord_id}
                )
                await session.commit()

        elif key == "technique":
            async with AsyncSessionLocal() as session:
                row = await session.execute(
                    text("SELECT techniques FROM players WHERE discord_id = :uid"),
                    {"uid": discord_id}
                )
                row = row.fetchone()
                techs = json.loads(row[0] or "[]") if row else []
                existing_names = {
                    (t if isinstance(t, str) else t.get("name", "")) for t in techs
                }
                if val not in existing_names:
                    techs.append({"name": val, "stage": "入门", "equipped": False})
                    await session.execute(
                        text("UPDATE players SET techniques = :t WHERE discord_id = :uid"),
                        {"t": json.dumps(techs, ensure_ascii=False), "uid": discord_id}
                    )
                    await session.commit()

        elif key == "title":
            async with AsyncSessionLocal() as session:
                row = await session.execute(
                    text("SELECT active_buffs FROM players WHERE discord_id = :uid"),
                    {"uid": discord_id}
                )
                row = row.fetchone()
                buffs = json.loads(row[0] or "{}") if row else {}
                titles = buffs.get("titles", [])
                if val not in titles:
                    titles.append(val)
                buffs["titles"] = titles
                await session.execute(
                    text("UPDATE players SET active_buffs = :b WHERE discord_id = :uid"),
                    {"b": json.dumps(buffs, ensure_ascii=False), "uid": discord_id}
                )
                await session.commit()

        elif key == "special_buff":
            async with AsyncSessionLocal() as session:
                row = await session.execute(
                    text("SELECT active_buffs FROM players WHERE discord_id = :uid"),
                    {"uid": discord_id}
                )
                row = row.fetchone()
                buffs = json.loads(row[0] or "{}") if row else {}
                buffs[val["key"]] = val["value"]
                await session.execute(
                    text("UPDATE players SET active_buffs = :b WHERE discord_id = :uid"),
                    {"b": json.dumps(buffs, ensure_ascii=False), "uid": discord_id}
                )
                await session.commit()


def check_chain_trigger(chain: dict, player: dict, stage: int) -> bool:
    if stage >= len(chain["stages"]):
        return False
    trigger = chain["stages"][stage].get("trigger", {})

    if "city" in trigger:
        cities = trigger["city"] if isinstance(trigger["city"], list) else [trigger["city"]]
        if player.get("current_city") not in cities:
            return False

    if "min_realm_index" in trigger:
        from utils.realms import get_realm_index
        if get_realm_index(player.get("realm", "炼气期1层")) < trigger["min_realm_index"]:
            return False

    for stat in ("comprehension", "physique", "fortune", "bone", "soul"):
        if stat in trigger:
            if player.get(stat, 0) < trigger[stat]:
                return False

    if "sect" in trigger:
        if trigger["sect"] == "any":
            if not player.get("sect"):
                return False
        elif player.get("sect") != trigger["sect"]:
            return False

    if "min_rebirth" in trigger:
        if player.get("rebirth_count", 0) < trigger["min_rebirth"]:
            return False

    return True


def get_available_chains(all_chains: list, player: dict, progress: dict) -> list:
    available = []
    for chain in all_chains:
        cid = chain["id"]
        entry = progress.get(cid, {"stage": 0, "completed": False})
        if entry.get("completed"):
            continue
        stage = entry.get("stage", 0)
        if check_chain_trigger(chain, player, stage):
            available.append((chain, stage))
    return available


async def try_fox_charm(discord_id: str, player_obj) -> bool:
    from utils.buffs import has_fox_charm, consume_fox_charm
    raw = player_obj.active_buffs or "{}"
    if not has_fox_charm({"active_buffs": raw}):
        return False
    player_obj.lifespan = 1
    player_obj.active_buffs = consume_fox_charm(raw)
    return True
