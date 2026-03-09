import discord
from utils.world import SPECIAL_REGIONS, cities_by_region
from utils.sects import SECTS


def _world_overview_embed() -> discord.Embed:
    return discord.Embed(
        title="✦ 天下舆图 ✦",
        description=(
            "此方天地幅员辽阔，分东域、南域、西域、北域、中州五大区域，"
            "共三十座城市，另有十处特殊秘地散布其间。\n\n"
            "天下宗门林立，正邪各据一方。除世人皆知的十大宗门外，"
            "据传尚有数个隐世宗门隐匿于天地之间——"
            "有的需极高机缘方可得见，有的需历经奇遇方能叩响山门，"
            "更有传言某些宗门只对特定之人开放，凡人难以企及。\n\n"
            "请选择你想了解的内容："
        ),
        color=discord.Color.teal(),
    )


async def _send_main_menu(interaction: discord.Interaction, cog):
    import json
    from utils.views.menu import MainMenuView, _build_menu_embed
    uid = str(interaction.user.id)
    player = cog._get_player(uid)
    if player and not player["is_dead"]:
        updates, _ = cog._settle_time(player)
        cog._apply_updates(uid, updates)
        player = cog._get_player(uid)
    has_player = player is not None and not player["is_dead"]
    can_bt = has_player and cog._can_breakthrough(player)
    has_dual = has_player and any(
        (t if isinstance(t, str) else t.get("name", "")) == "双修功法"
        for t in json.loads(player["techniques"] or "[]")
    )
    city_players = []
    if has_player:
        from utils.db import get_conn
        with get_conn() as conn:
            rows = conn.execute(
                "SELECT discord_id, name, realm, cultivation FROM players "
                "WHERE current_city = ? AND is_dead = 0 AND discord_id != ?",
                (player["current_city"], uid)
            ).fetchall()
        city_players = [dict(r) for r in rows]
    await interaction.followup.send(
        embed=_build_menu_embed(has_dual),
        view=MainMenuView(interaction.user, has_player, can_bt, cog, player, city_players)
    )


class WorldMenuView(discord.ui.View):
    def __init__(self, author, cog=None):
        super().__init__(timeout=120)
        self.author = author
        self.cog = cog

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user != self.author:
            await interaction.response.send_message("这不是你的面板。", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="城市", style=discord.ButtonStyle.primary)
    async def cities_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        from utils.views.travel import CityRegionView
        await interaction.response.send_message(
            embed=discord.Embed(title="✦ 天下城市 ✦", description="共三十座城市，分布于五大区域，请选择区域查看详情：", color=discord.Color.blue()),
            view=CityRegionView(interaction.user, self.cog),
        )

    @discord.ui.button(label="秘地", style=discord.ButtonStyle.secondary)
    async def regions_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = discord.Embed(title="✦ 特殊秘地 ✦", description="天地间散布着十二处特殊秘地，各有奇险：", color=discord.Color.gold())
        for r in SPECIAL_REGIONS:
            req = f"（需 {r['min_realm']} 以上）" if r["min_realm"] != "炼气期1层" else ""
            embed.add_field(name=f"{r['name']}  [{r['type']}]{req}", value=r["desc"], inline=False)
        await interaction.response.send_message(embed=embed, view=_BackToWorldView(interaction.user, self.cog))

    @discord.ui.button(label="宗门", style=discord.ButtonStyle.secondary)
    async def sects_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        from utils.views.sects import SectAlignmentView
        embed = discord.Embed(
            title="✦ 天下宗门 ✦",
            description="天下宗门分正道与邪道两派，各有传承。\n另有隐世宗门数个，行踪不定，有缘自会相遇。\n\n请选择阵营查看详情：",
            color=discord.Color.teal(),
        )
        await interaction.response.send_message(embed=embed, view=SectAlignmentView(interaction.user, self.cog))

    @discord.ui.button(label="返回主菜单", style=discord.ButtonStyle.secondary, row=1)
    async def back_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.cog:
            await interaction.response.send_message("无法返回。", ephemeral=True)
            return
        await interaction.response.defer()
        await _send_main_menu(interaction, self.cog)


class _BackToWorldView(discord.ui.View):
    def __init__(self, author, cog=None):
        super().__init__(timeout=120)
        self.author = author
        self.cog = cog

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user != self.author:
            await interaction.response.send_message("这不是你的面板。", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="返回世界", style=discord.ButtonStyle.secondary)
    async def back_world(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(embed=_world_overview_embed(), view=WorldMenuView(interaction.user, self.cog))

    @discord.ui.button(label="返回主菜单", style=discord.ButtonStyle.secondary)
    async def back_menu(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.cog:
            await interaction.response.send_message("无法返回。", ephemeral=True)
            return
        await interaction.response.defer()
        await _send_main_menu(interaction, self.cog)
