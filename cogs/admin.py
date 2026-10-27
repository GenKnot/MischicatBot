from discord.ext import commands

from utils import bot_settle, bot_world
from utils.config import COMMAND_PREFIX
from utils.logging_setup import audit


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
            audit("sync", ctx.author, scope="global", count=len(synced))
            return await ctx.send(f"已全局同步 {len(synced)} 个斜杠命令，最多一小时后生效。")

        if ctx.guild is None:
            return await ctx.send(f"私聊里没有服务器可同步，用 `{COMMAND_PREFIX}sync global`。")
        self.bot.tree.copy_global_to(guild=ctx.guild)
        synced = await self.bot.tree.sync(guild=ctx.guild)
        audit("sync", ctx.author, scope="guild", guild=ctx.guild.id, count=len(synced))
        await ctx.send(f"已同步 {len(synced)} 个斜杠命令到本服，立即生效。")

    @commands.command(name="生成机器人")
    @commands.is_owner()
    async def spawn_bots(self, ctx, count: int = 0):
        """往世界里放一批机器人修士（不写个数就用默认；一次最多、总数上限都在 `调参 列表 economy world` 里）。"""
        res = await bot_world.generate_bots(count or None)
        if not res["ok"]:
            return await ctx.send(res["reason"])
        audit("spawn_bots", ctx.author, count=len(res["created"]), by_tier=res["by_tier"])
        tiers = "　".join(f"{t} {n}" for t, n in res["by_tier"].items())
        sample = "、".join(f"{b['name']}（{b['realm']}·{b['city']}）" for b in res["created"][:5])
        await ctx.send(f"已放入 **{len(res['created'])}** 名机器人修士。\n{tiers}\n例如：{sample}")

    @commands.command(name="清除机器人")
    @commands.is_owner()
    async def clear_bots(self, ctx, confirm: str = ""):
        """清除所有机器人及其名下的物品、灵石（不可恢复）。要在后面加上「确认」二字。"""
        if confirm != "确认":
            return await ctx.send(f"这会删除**所有**机器人及其背包 / 装备 / 钱庄，送给机器人的礼物也一并消失，无法恢复。"
                                  f"确定的话发送 `{COMMAND_PREFIX}清除机器人 确认`。")
        res = await bot_world.clear_bots()
        audit("clear_bots", ctx.author, removed=res["removed"], rows=res["rows"])
        await ctx.send(f"已清除 **{res['removed']}** 名机器人。")

    @commands.command(name="结算机器人")
    @commands.is_owner()
    async def settle_bots(self, ctx, force: str = ""):
        """立刻做一次机器人每日结算。已结过的不会重复结；要再结一遍请加「强制」（会再发一次收入、再过一天）。"""
        res = await bot_settle.run_settlement(force=(force == "强制"))
        audit("settle_bots", ctx.author, force=(force == "强制"), **{k: v for k, v in res.items() if v})
        if not res["bots"]:
            return await ctx.send("今天的机器人已经全部结算过了。")
        await ctx.send(
            f"已结算 **{res['settled']}** 名机器人：发出收入 {res['income']:,}、日常开销 {res['upkeep']:,}、买丹 {res['pills']:,}；"
            f"突破成功 {res['breakthroughs']}、失败 {res['bt_failures']}（卡在买不起丹 {res['gate_wait']}、到天花板 {res['capped']}）；"
            f"死亡 {res['deaths']}、补员 {res['refilled']}、出错 {res['errors']}。")

    @sync.error
    @spawn_bots.error
    @clear_bots.error
    @settle_bots.error
    async def sync_error(self, ctx, error):
        if isinstance(error, commands.NotOwner):
            await ctx.send("这条命令只有 bot 所有者能用。")
        elif isinstance(error, commands.BadArgument):
            await ctx.send("参数不对：数量要写整数。")


async def setup(bot):
    await bot.add_cog(AdminCog(bot))
