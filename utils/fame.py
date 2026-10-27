"""名望（U1·江湖百态 P0）：一个人在江湖上有多出名，决定他的事迹能传多远。

和 `players.reputation`（道德声望：打劫会扣、任务和居所有门槛）是两回事：名望只增不减，恶名也是名。
玩家和机器人都有。名望靠事迹积累 —— 每条传闻记下时，主角涨 `score // 2`（见 utils/rumors.record_rumor），
所以突破、杀人、拍下重宝、成了天骄都会让人出名。

传多远（`reach`）：
· 无名（< 50）：只有认识他的人会发现他不见了（由关系网里的熟人自己去打听，P3 以后）；
· 小有名气（50~199）：同城议论；
· 远近闻名（200~）：全服传闻。
"""

import json
import logging
from functools import lru_cache
from pathlib import Path

from sqlalchemy import update

from utils import settings_hub
from utils.db_async import AsyncSessionLocal, Player

log = logging.getLogger(__name__)

_PATH = Path(__file__).resolve().parent.parent / "data" / "bot_fame.json"


@lru_cache(maxsize=1)
def _load() -> dict:
    return settings_hub.read(_PATH)


def load() -> dict:
    return _load()


def reload() -> None:
    _load.cache_clear()


def validate(cfg: dict) -> list[str]:
    errors = []
    tiers = cfg.get("tiers", {})
    if not tiers or min(tiers.values()) != 0 or any(v < 0 for v in tiers.values()):
        errors.append("tiers: 至少一档，最低一档的起点必须是 0，起点不能为负")
    if len(set(tiers.values())) != len(tiers):
        errors.append("tiers: 各档起点不能相同")
    if not 0 <= cfg.get("city_fame", -1) <= cfg.get("server_fame", -2):
        errors.append("city_fame 应 ≥ 0 且不超过 server_fame")
    if cfg.get("score_divisor", 0) < 1:
        errors.append("score_divisor 应 ≥ 1")
    return errors


def tier(fame: int) -> str:
    return next(name for name, floor in sorted(load()["tiers"].items(), key=lambda kv: -kv[1]) if fame >= floor)


def reach(fame: int) -> str:
    """事迹传多远：none / city / server。"""
    cfg = load()
    return "server" if fame >= cfg["server_fame"] else "city" if fame >= cfg["city_fame"] else "none"


def gain(score: int) -> int:
    """一条传闻让主角涨多少名望。"""
    return max(1, score // load()["score_divisor"])


async def add_fame(player_id: str, delta: int, session=None) -> None:
    """给一个人加名望（原子自增；传了 session 就跟着它的事务走）。出错只记 warning。"""
    if delta <= 0:
        return
    try:
        if session is not None:
            await session.execute(update(Player).where(Player.discord_id == player_id).values(fame=Player.fame + delta))
            return
        async with AsyncSessionLocal() as s:
            await s.execute(update(Player).where(Player.discord_id == player_id).values(fame=Player.fame + delta))
            await s.commit()
    except Exception:
        log.warning("加名望失败：%s +%s", player_id, delta, exc_info=True)
