"""机器人修士（U1「江湖百态」）的公共护栏。

机器人是 `players` 表里的普通行（`is_bot = 1`），这样打工、钱庄、PvP、排行榜、突破逻辑都能直接复用。
代价是：凡是「遍历全体玩家」的查询都会把机器人带进来，而机器人**没有真实的 Discord 账号**。
这个模块收口三件事，别在各处各写一份：

1. **怎么认出机器人**：`discord_id` 以 `bot_` 开头（`is_bot_id`）。不是数字，所以 `int(discord_id)` 会立刻抛错 ——
   漏过滤的地方会当场炸出来，而不是悄悄把私信发给某个陌生的真人。
2. **只要真人的查询**（通知循环、公共事件报名……）：用 `REAL_PLAYER_SQL`（文本 SQL）或 `real_player()`（ORM 条件）。
3. **发私信一律走 `send_dm`**：对机器人直接返回 False，不去 `fetch_user`。

哪些遍历点要真人、哪些含机器人，登记在 `tests/test_bot_guard.py::TRAVERSALS`，有静态棘轮，新增遍历点会红。
"""

import logging
from typing import NamedTuple

import discord

from utils.db_async import Player

log = logging.getLogger(__name__)

BOT_ID_PREFIX = "bot_"

# 文本 SQL 里的「只要真人」条件。可单独当条件，也可以带别名：f"{REAL_PLAYER_SQL}"
REAL_PLAYER_SQL = "is_bot = 0"

# 机器人能做哪些真人之间的互动：这是**总开关**，三项都开着（用户 2026-10-09 决定）。
# 组队 / 双修不是想约就能约：愿不愿意由好感度和性格决定，见 utils/bot_social.bot_gate。
BOT_CAPABILITIES = {
    "party": True,
    "dual": True,
    "receive_transfer": True,
}

_CAPABILITY_TEXT = {"party": "组队", "dual": "双修", "receive_transfer": "转账"}


class BotUser(NamedTuple):
    """机器人没有 Discord 用户对象；需要 `.id` / `.display_name` 的场合（双修结算文案）用它顶上。"""
    id: str
    display_name: str

    @property
    def mention(self) -> str:
        return f"**{self.display_name}**"


def is_bot_id(discord_id) -> bool:
    return str(discord_id).startswith(BOT_ID_PREFIX)


def real_player():
    """ORM 条件：只要真人。`select(Player).where(real_player(), ...)`"""
    return Player.is_bot == False  # noqa: E712 — SQL 比较，不能用 `is`


def bot_refusal(capability: str, *discord_ids) -> str | None:
    """涉及机器人的互动不被允许时返回提示文字，否则 None。"""
    if BOT_CAPABILITIES.get(capability, False):
        return None
    if any(is_bot_id(i) for i in discord_ids):
        return f"机器人修士暂不支持{_CAPABILITY_TEXT.get(capability, capability)}。"
    return None


async def send_dm(client, discord_id, *args, **kwargs) -> bool:
    """给玩家发私信。机器人没有 Discord 账号：直接返回 False，不去 fetch_user。

    对方关了私信 / 账号不在了（Forbidden、NotFound）是常态：记 debug 并返回 False。
    其余异常原样抛出 —— 那是我们自己的 bug，别被旁路通知吞掉（B5），由调用方按各自的场景处理。
    """
    if is_bot_id(discord_id):
        return False
    try:
        user = await client.fetch_user(int(discord_id))
        await user.send(*args, **kwargs)
        return True
    except (discord.Forbidden, discord.NotFound):
        log.debug("私信发送失败 uid=%s", discord_id, exc_info=True)
        return False
