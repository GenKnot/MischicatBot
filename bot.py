import asyncio
import logging

import discord
from discord.ext import commands

from utils.config import COMMAND_PREFIX

# 日志配置在 main.py 里统一做（utils/logging_setup.py）
log = logging.getLogger("mischicat.bot")


class MischicatBot(commands.Bot):
    def __init__(self):
        prefix = COMMAND_PREFIX
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(command_prefix=prefix, intents=intents, help_command=None)

    async def setup_hook(self):
        # Alembic 负责建表和后续所有 schema 变更。同步的，丢到线程里跑。
        from utils.migrate import run_migrations
        await asyncio.to_thread(run_migrations)
        # 遗留的 41 条 ALTER，给还没升级过的老库补字段。已冻结，别往里加新的。
        from utils.db import init_db
        await asyncio.to_thread(init_db)
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
        await self.load_extension("cogs.admin")
        await self.tree.sync()

    async def on_ready(self):
        log.info("logged in as %s", self.user)

    async def on_command_error(self, ctx, error):
        if isinstance(error, commands.CommandNotFound):
            return
        log.error("Command error from %s (id=%s): %s", ctx.author, ctx.author.id, error)
        await ctx.send("❌ 出了点问题，请稍后再试。")

