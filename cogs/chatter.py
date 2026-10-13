"""机器人主动搭话的后台发送与屏蔽命令（U1·江湖百态 P5）。

每 30 秒看一眼队列里有没有到点的搭话（突破道贺、公共事件前后、冲突后放话），发到传闻频道（RUMOR_CHANNEL_ID，没设就用公共事件频道，
都没有就不发）。`屏蔽机器人消息`：玩家自己关掉 / 打开机器人的主动搭话（只管搭话，仇恨和拦路不受影响）。
"""

import logging

from discord.ext import commands, tasks

from cogs.rumors import get_rumor_channel
from utils import bot_chatter as bc
from utils import bot_requests as br
from utils.config import COMMAND_PREFIX
from utils.tasks import loop_guard
from utils.views.chatter import send_payload

log = logging.getLogger(__name__)


class ChatterCog(commands.Cog, name="Chatter"):
    def __init__(self, bot):
        self.bot = bot

    @tasks.loop(seconds=30)
    @loop_guard(log, "机器人搭话发送")
    async def _deliver(self):
        channel = get_rumor_channel(self.bot)
        for item in await bc.claim_due():
            if channel is None:
                log.info("没有配置传闻频道，丢弃一条搭话：%s", item["scene"])
                continue
            await send_payload(channel.send, item["payload"])
        await bc.purge_old()
        await br.expire()

    @_deliver.before_loop
    async def _before(self):
        await self.bot.wait_until_ready()

    @commands.hybrid_command(name="屏蔽机器人消息", description="关掉 / 打开机器人修士的主动搭话（不影响仇怨和拦路）")
    async def mute(self, ctx, state: str = ""):
        uid = str(ctx.author.id)
        if state not in ("开", "关"):
            now = "已屏蔽" if await bc.is_muted(uid) else "未屏蔽"
            return await ctx.send(f"当前：{now}。用法：`{COMMAND_PREFIX}屏蔽机器人消息 开`（屏蔽）或 `{COMMAND_PREFIX}屏蔽机器人消息 关`（恢复）。")
        await bc.set_muted(uid, state == "开")
        await ctx.send("已屏蔽机器人的主动搭话（仇怨和拦路不受影响）。" if state == "开" else "已恢复机器人的主动搭话。")

    @commands.hybrid_command(name="委托", description="查看机器人托付给你、或你借出去的事：借款、送信、陪采集")
    async def requests(self, ctx):
        rows = await br.list_for(str(ctx.author.id))
        await ctx.send("📜 **未了结的委托**\n" + "\n".join(f"• {r}" for r in rows) if rows else "你手上没有未了结的委托。")

    async def cog_load(self):
        self._deliver.start()

    async def cog_unload(self):
        self._deliver.cancel()


async def setup(bot):
    await bot.add_cog(ChatterCog(bot))
