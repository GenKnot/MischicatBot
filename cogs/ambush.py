"""拦路遭遇的后台收尾（U1·江湖百态 P4）：每 15 秒看一眼有没有超时的遭遇。

选择阶段超时算逃跑，交涉阶段超时算拒绝；bot 重启时丢了面板的遭遇也靠这个收尾。出错只记日志（loop_guard）。
"""

import logging

import discord
from discord.ext import commands, tasks

from utils import bot_ambush as ba
from utils.tasks import loop_guard
from utils.views.ambush import outcome_embed

log = logging.getLogger(__name__)


class AmbushCog(commands.Cog, name="Ambush"):
    def __init__(self, bot):
        self.bot = bot

    @tasks.loop(seconds=15)
    @loop_guard(log, "拦路遭遇收尾")
    async def _expire(self):
        await ba.sweep_stuck()
        for item in await ba.process_expired():
            await self._announce(item)

    async def _announce(self, item: dict) -> None:
        """超时收尾后：编辑原消息（去掉按钮），并@玩家说一声结果。找不到频道 / 消息就算了。"""
        enc, res = item["encounter"], item["result"]
        if not enc or not enc.get("channel_id"):
            return
        channel = self.bot.get_channel(int(enc["channel_id"]))
        if channel is None:
            return
        from utils.player import get_player
        leader = await get_player(enc["leader"])
        name = leader["name"] if leader else "拦路者"
        embed = outcome_embed(res, name)
        try:
            if enc.get("message_id"):
                msg = await channel.fetch_message(int(enc["message_id"]))
                await msg.edit(embed=embed, view=None)
            await channel.send(f"<@{enc['target']}> 你没有回应，**{name}** 自行了断了此事。", embed=embed)
        except discord.HTTPException:
            log.warning("拦路超时收尾的消息发送失败：%s", enc["id"], exc_info=True)

    @_expire.before_loop
    async def _before(self):
        await self.bot.wait_until_ready()

    async def cog_load(self):
        self._expire.start()

    async def cog_unload(self):
        self._expire.cancel()


async def setup(bot):
    await bot.add_cog(AmbushCog(bot))
