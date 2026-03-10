import discord
from discord.ext import commands

from utils.config import COMMAND_PREFIX


class MischicatBot(commands.Bot):
    def __init__(self):
        prefix = COMMAND_PREFIX
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(command_prefix=prefix, intents=intents, help_command=None)

    async def setup_hook(self):
        from utils.db import init_db
        init_db()
        await self.load_extension("cogs.music")
        await self.load_extension("cogs.character")
        await self.load_extension("cogs.travel")
        await self.load_extension("cogs.cultivation")
        await self.load_extension("cogs.sect")
        await self.load_extension("cogs.explore")
        await self.load_extension("cogs.property")
        await self.load_extension("cogs.tavern")
        await self.load_extension("cogs.public_events")
        await self.load_extension("cogs.equipment")
        await self.load_extension("cogs.alchemy")
        await self.tree.sync()

    async def on_ready(self):
        print(f"logged in as {self.user}")

    async def on_command_error(self, ctx, error):
        await ctx.send(f"something went wrong: {error}")

    @commands.command(name="sync")
    @commands.is_owner()
    async def sync(self, ctx):
        """手动同步斜杠命令到 Discord（仅 owner 可用）"""
        await self.tree.sync()
        await ctx.send("斜杠命令已同步到 Discord。")
