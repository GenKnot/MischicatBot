"""江湖传闻：频道广播与茶馆听闻（U1「江湖百态」）。规则与数值见 utils/rumors.py、data/rumors.json。

· 后台每 10 分钟看一次：到了下一个『游戏年』（现实 2 小时）、频道不冷清，就把还没播过的传闻里最精彩的一条播出去；
· `cat!传闻`：茶馆听闻，完整列表（真人事迹单列）；
· `cat!传闻开关`：真人关闭 / 重新打开『我的事迹进传闻』（默认公开）。

广播频道用环境变量 `RUMOR_CHANNEL_ID`；没设就用公共事件的频道（`PUBLIC_EVENT_CHANNEL_ID`）；都没有就不广播。
"""

import logging
import os
import time
from datetime import datetime, timedelta, timezone

import discord
from discord.ext import commands, tasks

from cogs.public_events import PUBLIC_EVENT_CHANNEL_ENV
from utils import rumors
from utils.config import COMMAND_PREFIX
from utils.db_async import AsyncSessionLocal, Player
from utils.tasks import loop_guard

log = logging.getLogger(__name__)

RUMOR_CHANNEL_ENV = "RUMOR_CHANNEL_ID"


def get_rumor_channel(bot):
    channel_id = os.getenv(RUMOR_CHANNEL_ENV) or os.getenv(PUBLIC_EVENT_CHANNEL_ENV)
    if not channel_id:
        return None
    return bot.get_channel(int(channel_id))


async def channel_is_active(channel, hours: float) -> bool:
    """最近 `hours` 小时里频道有没有真人发过言：凌晨没人的时候 bot 不自说自话。"""
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    try:
        async for msg in channel.history(limit=50, after=since):
            if not msg.author.bot:
                return True
    except Exception:
        log.warning("读取频道历史失败，本轮不广播传闻", exc_info=True)
    return False


def rumor_line(r) -> str:
    return f"{'⭐ ' if r.is_human else ''}{r.content}　<t:{int(r.created_at)}:R>"


class RumorsCog(commands.Cog, name="Rumors"):
    def __init__(self, bot):
        self.bot = bot

    # ---- 频道广播 -------------------------------------------------------------
    @tasks.loop(minutes=10)
    @loop_guard(log, "传闻广播")
    async def _broadcast_loop(self):
        await self.broadcast_once()

    @_broadcast_loop.before_loop
    async def _before_loop(self):
        await self.bot.wait_until_ready()

    async def broadcast_once(self, now: float | None = None) -> bool:
        """到点了就播一条。返回有没有播出去。"""
        now = now or time.time()
        await rumors.prune(now)
        cfg = rumors.load_config()["broadcast"]
        if not cfg["enabled"]:
            return False
        channel = get_rumor_channel(self.bot)
        if channel is None or not await rumors.broadcast_due(now):
            return False
        if not await channel_is_active(channel, cfg["cold_hours"]):
            return False
        pick = await rumors.pick_broadcast(now)
        if pick is None or not await rumors.claim_broadcast(pick.id, now):
            return False
        embed = discord.Embed(title="📜 江湖传闻", description=rumor_line(pick).rsplit("　<t:", 1)[0], color=discord.Color.dark_gold())
        embed.set_footer(text=f"{COMMAND_PREFIX}传闻 查看更多　·　{COMMAND_PREFIX}传闻开关 管理自己的事迹")
        await channel.send(embed=embed)
        return True

    async def cog_load(self):
        self._broadcast_loop.start()

    async def cog_unload(self):
        self._broadcast_loop.cancel()

    # ---- 茶馆听闻 -------------------------------------------------------------
    @commands.hybrid_command(name="传闻", aliases=["cw"], description="在茶馆听听最近的江湖传闻")
    async def listen(self, ctx):
        data = await rumors.recent()
        embed = discord.Embed(title="📜 茶馆听闻 · 江湖传闻", color=discord.Color.dark_gold())
        embed.add_field(name="⭐ 修士事迹", value="\n".join(rumor_line(r) for r in data["human"]) or "最近还没有修士的事迹传出来。",
                        inline=False)
        embed.add_field(name="江湖闲谈", value="\n".join(rumor_line(r) for r in data["bot"]) or "江湖上最近风平浪静。",
                        inline=False)
        embed.set_footer(text=f"传闻保留 {rumors.load_config()['retention_days']} 天　·　{COMMAND_PREFIX}传闻开关 可以让自己的事迹不再出现")
        await ctx.send(embed=embed)

    @commands.hybrid_command(name="传闻开关", aliases=["cwkg"], description="开启 / 关闭「我的事迹进入江湖传闻」")
    async def toggle(self, ctx):
        uid = str(ctx.author.id)
        async with AsyncSessionLocal() as session:
            player = await session.get(Player, uid)
        if not player:
            return await ctx.send(f"{ctx.author.mention} 请先创建角色。")
        off = await rumors.toggle_optout(uid)
        await ctx.send(f"{ctx.author.mention} " + (
            "已关闭：你之后的事迹不会再进入江湖传闻（已有的不受影响）。再发一次这条命令可以重新打开。" if off
            else "已重新打开：你的事迹会进入江湖传闻，实名。"))


async def setup(bot):
    await bot.add_cog(RumorsCog(bot))
