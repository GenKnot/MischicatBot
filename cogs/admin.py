import discord
from discord.ext import commands

from utils.config import COMMAND_PREFIX


class AdminCog(commands.Cog, name="Admin"):
    """只给应用 owner 用的运维命令。"""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.command(name="sync")
    @commands.is_owner()
    async def sync(self, ctx, scope: str = "guild"):
        """同步斜杠命令。默认只同步到当前服务器（立即生效）。

        `cat!sync` 本服同步，`cat!sync global` 全局同步（Discord 那边最多要等一小时）。
        """
        if scope == "global":
            synced = await self.bot.tree.sync()
            return await ctx.send(f"已全局同步 {len(synced)} 个斜杠命令，最多一小时后生效。")

        if ctx.guild is None:
            return await ctx.send(f"私聊里没有服务器可同步，用 `{COMMAND_PREFIX}sync global`。")
        self.bot.tree.copy_global_to(guild=ctx.guild)
        synced = await self.bot.tree.sync(guild=ctx.guild)
        await ctx.send(f"已同步 {len(synced)} 个斜杠命令到本服，立即生效。")

    @sync.error
    async def sync_error(self, ctx, error):
        if isinstance(error, commands.NotOwner):
            await ctx.send("这条命令只有 bot 所有者能用。")


async def setup(bot):
    await bot.add_cog(AdminCog(bot))
