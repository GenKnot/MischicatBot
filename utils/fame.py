"""名望（U1·江湖百态 P0）：一个人在江湖上有多出名，决定他的事迹能传多远。

和 `players.reputation`（道德声望：打劫会扣、任务和居所有门槛）是两回事：名望只增不减，恶名也是名。
玩家和机器人都有。名望靠事迹积累 —— 每条传闻记下时，主角涨 `score // 2`（见 utils/rumors.record_rumor），
所以突破、杀人、拍下重宝、成了天骄都会让人出名。

传多远（`reach`）：
· 无名（< 50）：只有认识他的人会发现他不见了（由关系网里的熟人自己去打听，P3 以后）；
· 小有名气（50~199）：同城议论；
· 远近闻名（200~）：全服传闻。
"""

import logging

from sqlalchemy import update

from utils.db_async import AsyncSessionLocal, Player

log = logging.getLogger(__name__)

TIERS = ((3000, "名震天下"), (800, "名动一方"), (200, "远近闻名"), (50, "小有名气"), (0, "无名之辈"))
CITY_FAME = 50                  # 起，同城议论
SERVER_FAME = 200               # 起，全服传闻


def tier(fame: int) -> str:
    return next(name for floor, name in TIERS if fame >= floor)


def reach(fame: int) -> str:
    """事迹传多远：none / city / server。"""
    return "server" if fame >= SERVER_FAME else "city" if fame >= CITY_FAME else "none"


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
