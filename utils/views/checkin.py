import discord
from utils.checkin import do_checkin
from utils.equipment import format_equipment


def _checkin_result_embed(result: dict, player: dict) -> discord.Embed:
    if not result["ok"]:
        embed = discord.Embed(description=result["reason"], color=discord.Color.red())
        return embed

    cat = result["category"]
    CATEGORY_TITLES = {
        "spirit_stones": "💰 灵石",
        "material":      "🌿 材料",
        "technique":     "📖 功法",
        "equipment":     "⚔️ 装备",
    }
    title = f"✦ 每日签到 · {CATEGORY_TITLES.get(cat, cat)} ✦"
    embed = discord.Embed(title=title, color=discord.Color.gold())

    if cat == "spirit_stones":
        embed.description = f"获得灵石 **+{result['spirit_stones']}**"

    elif cat == "material":
        embed.description = f"获得材料：**{result['item_name']}** ×1"

    elif cat == "technique":
        tech = result["technique"]
        if result["already_known"]:
            embed.description = f"获得功法：**{tech}**\n（已习得，缘分已尽，功法化为感悟）"
        else:
            embed.description = f"获得功法：**{tech}**\n已自动加入功法列表，可前往技艺修炼。"

    elif cat == "equipment":
        eq = result["equipment"]
        embed.description = f"获得装备：\n{format_equipment(eq)}"

    embed.set_footer(text="明日可再次签到")
    return embed


class CheckinView(discord.ui.View):
    def __init__(self, author, player: dict, cog=None):
        super().__init__(timeout=60)
        self.author = author
        self.player = player
        self.cog = cog

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user != self.author:
            await interaction.response.send_message("这不是你的面板。", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="签到", style=discord.ButtonStyle.success, emoji="🎁")
    async def checkin_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        button.disabled = True
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(view=self)

        result = await do_checkin(str(interaction.user.id))
        embed = _checkin_result_embed(result, self.player)

        done_view = discord.ui.View(timeout=60)
        back_btn = discord.ui.Button(label="返回城市", style=discord.ButtonStyle.secondary)
        cog = self.cog

        async def _back(inter: discord.Interaction):
            from utils.views.city import CityMenuView, _city_menu_embed
            from utils.db import get_conn
            uid = str(inter.user.id)
            with get_conn() as conn:
                player = dict(conn.execute("SELECT * FROM players WHERE discord_id = ?", (uid,)).fetchone())
            await inter.response.edit_message(embed=_city_menu_embed(player), view=CityMenuView(inter.user, player, cog))

        back_btn.callback = _back
        done_view.add_item(back_btn)
        await interaction.edit_original_response(embed=embed, view=done_view)

