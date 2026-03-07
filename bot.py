import os

import discord
from discord.ext import commands


class MischicatBot(commands.Bot):
    def __init__(self):
        prefix = os.getenv("COMMAND_PREFIX", "cat!")
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(command_prefix=prefix, intents=intents, help_command=None)

    async def setup_hook(self):
        from utils.db import init_db
        init_db()
        await self.load_extension("cogs.music")
        await self.load_extension("cogs.cultivation")
        await self.load_extension("cogs.sect")
        await self.load_extension("cogs.explore")
        await self.load_extension("cogs.property")

    async def on_ready(self):
        print(f"logged in as {self.user}")

    async def on_command_error(self, ctx, error):
        await ctx.send(f"something went wrong: {error}")
