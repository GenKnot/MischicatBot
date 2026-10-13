"""江湖设置（U1·江湖百态 P0）：服务器管理员选世界模式、死亡保护期，随时开关拦路。

· `江湖初始化`：逐项说明每个选项的后果，选完点确认才生效。第一次谁能点？bot 所有者，或有『管理服务器』权限的人；
  初始化之后只有记下的管理员（和所有者）能再改。
· `江湖设置`：看当前设置。 · `拦路开关 开/关`：管理员随时关掉机器人拦路（立即生效，不用重启）。
"""

import discord
from discord.ext import commands

from utils import world_settings as ws
from utils.config import COMMAND_PREFIX
from utils.logging_setup import audit


async def can_manage(bot, user, guild_perms) -> bool:
    """有没有资格改江湖设置。"""
    if await bot.is_owner(user):
        return True
    settings = await ws.get_all()
    if settings["initialized"]:
        return str(user.id) in settings["admin_ids"]
    return bool(getattr(guild_perms, "manage_guild", False))


def mode_embed(selected: str | None = None, protect: float = 1.0) -> discord.Embed:
    e = discord.Embed(title="🏯 江湖初始化", description="请选择这个服务器的江湖有多残酷。**每一项的后果都写在下面，请完整阅读。**",
                      color=discord.Color.dark_gold())
    for name, m in ws.MODES.items():
        mark = "✅ " if name == selected else ""
        e.add_field(name=f"{mark}{m['title']}", value=m["detail"], inline=False)
    e.add_field(name="🛡️ 死亡保护期", value=(f"玩家被杀后，在这段时间内不会再被机器人拦路。当前：**{protect:g} 天**"
                                          f"（游戏里 1 年 = 现实 2 小时；0 表示没有保护）。"), inline=False)
    e.set_footer(text="选好模式后点『确认』才会生效。之后可以用同一个命令重新设置。")
    return e


class ModeSelect(discord.ui.Select):
    def __init__(self, view_ref):
        super().__init__(placeholder="选择世界模式", options=[
            discord.SelectOption(label=m["title"].split(" ", 1)[1], value=name, description=m["short"][:100])
            for name, m in ws.MODES.items()])
        self.view_ref = view_ref

    async def callback(self, interaction: discord.Interaction):
        self.view_ref.mode = self.values[0]
        await interaction.response.edit_message(embed=mode_embed(self.view_ref.mode, self.view_ref.protect), view=self.view_ref)


class ProtectSelect(discord.ui.Select):
    def __init__(self, view_ref):
        super().__init__(placeholder="选择死亡保护期", options=[
            discord.SelectOption(label=f"{d:g} 天" if d else "不设保护", value=str(d), default=(d == 1.0))
            for d in ws.PROTECT_CHOICES])
        self.view_ref = view_ref

    async def callback(self, interaction: discord.Interaction):
        self.view_ref.protect = float(self.values[0])
        await interaction.response.edit_message(embed=mode_embed(self.view_ref.mode, self.view_ref.protect), view=self.view_ref)


class SetupView(discord.ui.View):
    def __init__(self, author_id: int, current: dict):
        super().__init__(timeout=300)
        self.author_id = author_id
        self.mode, self.protect = None, float(current["death_protect_days"])
        self.add_item(ModeSelect(self))
        self.add_item(ProtectSelect(self))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("这不是你的设置面板。", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="确认", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.mode is None:
            return await interaction.response.send_message("还没有选世界模式。", ephemeral=True)
        await ws.initialize(str(interaction.user.id), self.mode, self.protect)
        audit("world_setup", interaction.user, mode=self.mode, protect_days=self.protect)
        self.stop()
        await interaction.response.edit_message(
            content=f"江湖已设定：{ws.MODES[self.mode]['title']}，死亡保护 {self.protect:g} 天。", embed=None, view=None)


class WorldSetupCog(commands.Cog, name="WorldSetup"):
    def __init__(self, bot):
        self.bot = bot

    async def _allowed(self, ctx) -> bool:
        perms = getattr(ctx.author, "guild_permissions", None)
        if await can_manage(self.bot, ctx.author, perms):
            return True
        await ctx.send("只有服务器管理员（或 bot 所有者）能改江湖设置。")
        return False

    @commands.hybrid_command(name="江湖初始化", description="（管理员）选择这个服务器的世界模式，了解每个选项的后果")
    async def setup_world(self, ctx):
        if not await self._allowed(ctx):
            return
        current = await ws.get_all()
        await ctx.send(embed=mode_embed(None, current["death_protect_days"]), view=SetupView(ctx.author.id, current))

    @commands.hybrid_command(name="江湖设置", description="（管理员）查看当前的江湖设置")
    async def show_world(self, ctx):
        if not await self._allowed(ctx):
            return
        await ctx.send(ws.describe(await ws.get_all()))

    @commands.hybrid_command(name="拦路开关", description="（管理员）开 / 关机器人拦路，立即生效")
    async def ambush_switch(self, ctx, state: str = ""):
        if not await self._allowed(ctx):
            return
        if state not in ("开", "关"):
            return await ctx.send(f"用法：`{COMMAND_PREFIX}拦路开关 开` 或 `{COMMAND_PREFIX}拦路开关 关`。")
        await ws.set_values(ambush_enabled=(state == "开"))
        audit("ambush_switch", ctx.author, state=state)
        await ctx.send(f"机器人拦路已{'开启' if state == '开' else '关闭'}。")


async def setup(bot):
    await bot.add_cog(WorldSetupCog(bot))
