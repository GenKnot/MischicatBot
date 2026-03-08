import discord
from utils.sects import SECTS


def _sects_embed(alignment: str) -> discord.Embed:
    stat_names = {"comprehension": "悟性", "physique": "体魄",
                  "fortune": "机缘", "bone": "根骨", "soul": "神识"}
    embed = discord.Embed(title=f"✦ {alignment}宗门 ✦", color=discord.Color.teal())
    for name, data in SECTS.items():
        if data["alignment"] != alignment:
            continue
        req = data["req"]
        req_parts = []
        if req["min_realm"]:
            req_parts.append(req["min_realm"])
        if req["spirit_roots"]:
            req_parts.append(f"{'或'.join(req['spirit_roots'])}灵根")
        if req["single_root"]:
            req_parts.append("单灵根")
        if req["min_stat"]:
            for stat, val in req["min_stat"].items():
                req_parts.append(f"{stat_names.get(stat, stat)}{val}+")
        if req["min_fortune"]:
            req_parts.append(f"机缘{req['min_fortune']}+")
        req_str = "、".join(req_parts) if req_parts else "无特殊要求"
        embed.add_field(
            name=f"{name} · {data['location']}",
            value=f"{data['desc']}\n入门要求：{req_str}",
            inline=False,
        )
    return embed


class SectAlignmentView(discord.ui.View):
    def __init__(self, author):
        super().__init__(timeout=120)
        self.author = author

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user != self.author:
            await interaction.response.send_message("这不是你的面板。", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="正道宗门", style=discord.ButtonStyle.primary)
    async def righteous(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(embed=_sects_embed("正道"))

    @discord.ui.button(label="邪道宗门", style=discord.ButtonStyle.danger)
    async def evil(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(embed=_sects_embed("邪道"))

    @discord.ui.button(label="隐世宗门", style=discord.ButtonStyle.secondary)
    async def hidden(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = discord.Embed(
            title="✦ 隐世宗门 ✦",
            description=(
                "隐世宗门行踪隐秘，不为世人所知。\n\n"
                "据传共有五个隐世宗门散布于天地之间，"
                "有的深藏于秘境之中，有的隐于闹市却无人察觉。\n\n"
                "想要找到他们，或需极高的机缘，或需历经特殊奇遇，"
                "或需满足某些常人难以企及的条件。\n\n"
                "一切，皆看天意。"
            ),
            color=discord.Color.dark_purple(),
        )
        await interaction.response.send_message(embed=embed)
