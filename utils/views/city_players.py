import random
import discord
from utils.realms import get_realm_index
from utils.world import SPECIAL_REGIONS


def _city_players_embed(city_players: list, viewer: dict) -> discord.Embed:
    viewer_realm_idx = get_realm_index(viewer["realm"]) if viewer else 0
    viewer_cultivation = viewer["cultivation"] if viewer else 0
    embed = discord.Embed(title="✦ 同城修士 ✦", color=discord.Color.teal())
    if not city_players:
        embed.description = "此地暂无其他修士。"
        return embed
    lines = []
    for p in city_players:
        p_realm_idx = get_realm_index(p["realm"])
        stronger = p_realm_idx > viewer_realm_idx or (
            p_realm_idx == viewer_realm_idx and p["cultivation"] > viewer_cultivation
        )
        if stronger:
            lines.append(f"**{p['name']}** · ???　修为：???")
        else:
            lines.append(f"**{p['name']}** · {p['realm']}　修为：{p['cultivation']}")
    embed.description = "\n".join(lines)
    return embed


class CityPlayersView(discord.ui.View):
    def __init__(self, author, city_players: list, viewer: dict, cog=None):
        super().__init__(timeout=120)
        self.author = author
        self.cog = cog
        viewer_idx = get_realm_index(viewer["realm"]) if viewer else 0
        for p in city_players[:5]:
            self.add_item(CityPlayerButton(p, viewer_idx))
        self.add_item(_BackToMenuButton(cog))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user != self.author:
            await interaction.response.send_message("这不是你的面板。", ephemeral=True)
            return False
        return True


class _BackToMenuButton(discord.ui.Button):
    def __init__(self, cog):
        super().__init__(label="返回主菜单", style=discord.ButtonStyle.secondary)
        self.cog = cog

    async def callback(self, interaction: discord.Interaction):
        from utils.views.world import _send_main_menu
        if not self.cog:
            await interaction.response.send_message("无法返回。", ephemeral=True)
            return
        await interaction.response.defer()
        await _send_main_menu(interaction, self.cog)


class CityPlayerButton(discord.ui.Button):
    def __init__(self, target_player: dict, viewer_realm_idx: int):
        super().__init__(label=target_player["name"], style=discord.ButtonStyle.secondary)
        self.target_player = target_player
        self.viewer_realm_idx = viewer_realm_idx

    async def callback(self, interaction: discord.Interaction):
        from utils.db import get_conn
        from utils.views.combat import PlayerActionView
        uid = str(interaction.user.id)
        with get_conn() as conn:
            viewer = dict(conn.execute("SELECT * FROM players WHERE discord_id = ?", (uid,)).fetchone())
            target = dict(conn.execute("SELECT * FROM players WHERE discord_id = ?",
                                       (self.target_player["discord_id"],)).fetchone())
        if not viewer or not target:
            return await interaction.response.send_message("数据异常。", ephemeral=True)

        viewer_idx = get_realm_index(viewer["realm"])
        target_idx = get_realm_index(target["realm"])
        hide_cultivation = target_idx > viewer_idx or (
            target_idx == viewer_idx and target["cultivation"] > viewer["cultivation"]
        )

        pvp_zone_names = {r["name"] for r in SPECIAL_REGIONS}
        in_pvp = viewer.get("current_city", "") in pvp_zone_names

        lines = [
            f"**{target['name']}** · {target['gender']}修",
            f"境界：{'???' if hide_cultivation else target['realm']}",
            f"修为：{'???' if hide_cultivation else target['cultivation']}",
            f"寿元：{target['lifespan']} 年",
            f"宗门：{target['sect'] or '无'}",
        ]
        if not in_pvp:
            lines.append("\n*此地为安全区域，无法发起攻击。*")
        embed = discord.Embed(title=f"✦ {target['name']} ✦", description="\n".join(lines), color=discord.Color.teal())
        await interaction.response.send_message(
            embed=embed,
            view=PlayerActionView(interaction.user, viewer, target, in_pvp),
            ephemeral=True,
        )
