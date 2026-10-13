"""机器人世界的后台任务：每日结算（U1「江湖百态」）。

每 10 分钟看一眼有没有没结算的机器人（`bot_personality.settled_day` 不是今天的），有就结。
一天只会结一次：结算自己靠数据库里的认领保证（见 utils/bot_settle.py），所以这里循环多跑、手动结算、
bot 重启都不会重复发钱。整轮出错只记日志（loop_guard），下一轮再来。
"""

import logging

from discord.ext import commands, tasks

from utils import bot_grudges, bot_settle
from utils.tasks import loop_guard

log = logging.getLogger(__name__)


class BotWorldCog(commands.Cog, name="BotWorld"):
    def __init__(self, bot):
        self.bot = bot

    @tasks.loop(minutes=10)
    @loop_guard(log, "机器人每日结算")
    async def _daily_settlement(self):
        await bot_settle.run_settlement()

    @commands.hybrid_command(name="仇人", description="查看你的仇人：谁欠你的账、为什么（含前世的仇）")
    async def enemies(self, ctx):
        text = await bot_grudges.format_list(str(ctx.author.id))
        await ctx.send(("📜 **你的仇人**\n" + text) if text else "你在江湖上还没有仇人。")

    @_daily_settlement.before_loop
    async def _before_settlement(self):
        await self.bot.wait_until_ready()

    async def cog_load(self):
        self._daily_settlement.start()

    async def cog_unload(self):
        self._daily_settlement.cancel()


async def setup(bot):
    await bot.add_cog(BotWorldCog(bot))
