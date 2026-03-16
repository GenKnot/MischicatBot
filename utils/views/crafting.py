import discord
from sqlalchemy import text
from utils.db_async import AsyncSessionLocal


def _crafting_overview_embed() -> discord.Embed:
    embed = discord.Embed(
        title="✦ 技艺 ✦",
        description=(
            "修仙之路不止于修炼，掌握一门技艺可让道友如虎添翼。\n"
            "天下技艺分五门，各有所长，各有所需。"
        ),
        color=discord.Color.teal(),
    )
    embed.add_field(
        name="🔥 炼丹",
        value=(
            "以灵草为引，丹火为媒，炼制各类丹药。\n"
            "丹药可恢复寿元、提升修炼速度、强化属性，乃修仙必备之物。\n"
            "炼丹等级越高，可炼制的丹药品阶越高，品质上限也随之提升。"
        ),
        inline=False,
    )
    embed.add_field(
        name="⚙️ 锻造",
        value=(
            "以灵矿为材，淬炼兵器与防具。\n"
            "矿石品级决定装备境界，辅以木材草药可影响属性偏向。\n"
            "炼器师品级越高，可锻造的品质上限越高。"
        ),
        inline=False,
    )
    embed.add_field(
        name="🪆 练傀（敬请期待）",
        value=(
            "以特殊材料塑造傀儡，注入神识驱使其战斗或劳作。\n"
            "傀儡可代替主人探险、守城，甚至参与战斗。\n"
            "傀儡品质越高，能力越强，消耗的神识也越多。"
        ),
        inline=False,
    )
    embed.add_field(
        name="🔮 阵法（敬请期待）",
        value=(
            "以灵石为基，布置攻守兼备的法阵。\n"
            "阵法可用于保护洞府、困敌于阵中，或增幅修炼效率。\n"
            "阵法师需要极高的悟性，方能领悟天地间的阵道奥秘。"
        ),
        inline=False,
    )
    embed.add_field(
        name="📜 制符（敬请期待）",
        value=(
            "以灵纸为载，以神识为墨，绘制各类符箓。\n"
            "符箓可一次性使用，效果涵盖攻击、防御、辅助等多种类型。\n"
            "高阶符箓威力惊人，但制作难度极高，废品率不低。"
        ),
        inline=False,
    )
    return embed


class CraftingMenuView(discord.ui.View):
    def __init__(self, author, cog):
        super().__init__(timeout=120)
        self.author = author
        self.cog = cog

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user != self.author:
            await interaction.response.send_message("这不是你的面板。", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="🔥 炼丹", style=discord.ButtonStyle.primary, row=0)
    async def alchemy_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        from utils.views.alchemy import AlchemyMainView
        from utils.alchemy import get_known_recipes_with_choices
        uid = str(interaction.user.id)
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                text("SELECT * FROM players WHERE discord_id = :uid"),
                {"uid": uid},
            )
            row = result.fetchone()
            player = dict(row._mapping)
        if player.get("alchemy_level", 0) == 0 and player.get("current_city") != "丹阁":
            await interaction.response.send_message(
                "你尚未入门炼丹之道。\n前往**中州·丹阁**参加入门考核，获得炼丹师资质后方可开炉。",
                ephemeral=True,
            )
            return
        has_yanhuo = bool(player.get("yanhuo"))
        known_map = await get_known_recipes_with_choices(uid)
        view = AlchemyMainView(self.author, player, has_yanhuo, set(known_map.keys()), cog=self.cog, known_choices=known_map)
        await interaction.response.edit_message(
            content="炼丹台：",
            embed=None,
            view=view,
        )

    @discord.ui.button(label="⚙️ 锻造", style=discord.ButtonStyle.primary, row=0)
    async def forge_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        from utils.views.forging import ForgingMainView, _forging_main_embed
        from utils.forging import FORGING_CITIES
        uid = str(interaction.user.id)
        async with AsyncSessionLocal() as session:
            result = await session.execute(text("SELECT * FROM players WHERE discord_id = :uid"), {"uid": uid})
            row = result.fetchone()
            player = dict(row._mapping)
        if player.get("forging_level", 0) == 0 and player.get("current_city") not in FORGING_CITIES:
            cities_str = "、".join(FORGING_CITIES)
            await interaction.response.send_message(
                f"你尚未入门炼器之道。\n前往铸造坊所在城市（{cities_str}）参加入门考核，获得炼器师资质后方可开炉。",
                ephemeral=True,
            )
            return
        await interaction.response.edit_message(
            embed=_forging_main_embed(player),
            view=ForgingMainView(self.author, player, self.cog),
        )

    @discord.ui.button(label="🪆 练傀", style=discord.ButtonStyle.secondary, row=0, disabled=True)
    async def puppet_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("练傀系统尚未开放。", ephemeral=True)

    @discord.ui.button(label="🔮 阵法", style=discord.ButtonStyle.secondary, row=1, disabled=True)
    async def array_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("阵法系统尚未开放。", ephemeral=True)

    @discord.ui.button(label="📜 制符", style=discord.ButtonStyle.secondary, row=1, disabled=True)
    async def talisman_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("制符系统尚未开放。", ephemeral=True)

    @discord.ui.button(label="返回主菜单", style=discord.ButtonStyle.secondary, row=1)
    async def back_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        from utils.views.world import _send_main_menu
        await interaction.response.defer()
        await _send_main_menu(interaction, self.cog)


CraftingView = CraftingMenuView
