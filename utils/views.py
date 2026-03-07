import discord
from utils.world import CITIES, SPECIAL_REGIONS, cities_by_region
from utils.sects import SECTS


class MainMenuView(discord.ui.View):
    def __init__(self, author, has_player: bool, can_breakthrough: bool, cog):
        super().__init__(timeout=120)
        self.author = author
        self.cog = cog

        if not has_player:
            self.add_item(MenuButton("创建角色", discord.ButtonStyle.success, "create"))
            self.add_item(MenuButton("我的角色", discord.ButtonStyle.primary, "profile", disabled=True))
            self.add_item(MenuButton("修炼", discord.ButtonStyle.primary, "cultivate", disabled=True))
            self.add_item(MenuButton("世界", discord.ButtonStyle.secondary, "world"))
            self.add_item(MenuButton("探险", discord.ButtonStyle.secondary, "explore", disabled=True))
        else:
            self.add_item(MenuButton("我的角色", discord.ButtonStyle.primary, "profile"))
            self.add_item(MenuButton("修炼", discord.ButtonStyle.success, "cultivate"))
            self.add_item(MenuButton("世界", discord.ButtonStyle.secondary, "world"))
            if can_breakthrough:
                self.add_item(MenuButton("突破", discord.ButtonStyle.danger, "breakthrough"))
            self.add_item(MenuButton("探险", discord.ButtonStyle.secondary, "explore"))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user != self.author:
            await interaction.response.send_message("这不是你的面板。", ephemeral=True)
            return False
        return True


class MenuButton(discord.ui.Button):
    def __init__(self, label: str, style: discord.ButtonStyle, action: str, disabled: bool = False):
        super().__init__(label=label, style=style, disabled=disabled)
        self.action = action

    async def callback(self, interaction: discord.Interaction):
        cog = self.view.cog

        if self.action == "world":
            await interaction.response.send_message(
                embed=_world_overview_embed(),
                view=WorldMenuView(interaction.user),
            )
            return

        await interaction.response.defer()

        try:
            if self.action == "create":
                ctx = await cog.bot.get_context(interaction.message)
                ctx.author = interaction.user
                await cog.create_character(ctx)
            elif self.action == "profile":
                await cog.send_profile(interaction)
            elif self.action == "cultivate":
                await cog.send_cultivate(interaction)
            elif self.action == "breakthrough":
                await cog.send_breakthrough(interaction)
            elif self.action == "stop":
                await cog.send_stop(interaction)
            elif self.action == "explore":
                explore_cog = cog.bot.cogs.get("Explore")
                if explore_cog:
                    ctx = await cog.bot.get_context(interaction.message)
                    ctx.author = interaction.user
                    await explore_cog.explore(ctx)
                else:
                    await interaction.followup.send("探险系统暂时不可用。", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"出错了：{e}", ephemeral=True)


class ProfileView(discord.ui.View):
    def __init__(self, author, can_breakthrough: bool, is_cultivating: bool, cog):
        super().__init__(timeout=120)
        self.author = author
        self.cog = cog

        self.add_item(MenuButton("修炼", discord.ButtonStyle.success, "cultivate"))
        if is_cultivating:
            self.add_item(MenuButton("停止闭关", discord.ButtonStyle.danger, "stop"))
        if can_breakthrough:
            self.add_item(MenuButton("突破", discord.ButtonStyle.danger, "breakthrough"))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user != self.author:
            await interaction.response.send_message("这不是你的面板。", ephemeral=True)
            return False
        return True


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


class WorldMenuView(discord.ui.View):
    def __init__(self, author):
        super().__init__(timeout=120)
        self.author = author

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user != self.author:
            await interaction.response.send_message("这不是你的面板。", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="城市", style=discord.ButtonStyle.primary)
    async def cities_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(
            embed=_cities_embed(),
            view=CityRegionView(interaction.user),
        )

    @discord.ui.button(label="秘地", style=discord.ButtonStyle.secondary)
    async def regions_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(embed=_special_regions_embed())

    @discord.ui.button(label="宗门", style=discord.ButtonStyle.secondary)
    async def sects_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(
            embed=_sects_overview_embed(),
            view=SectAlignmentView(interaction.user),
        )


def _cities_embed() -> discord.Embed:
    return discord.Embed(
        title="✦ 天下城市 ✦",
        description="共三十座城市，分布于五大区域，请选择区域查看详情：",
        color=discord.Color.blue(),
    )


class CityRegionView(discord.ui.View):
    def __init__(self, author):
        super().__init__(timeout=120)
        self.author = author
        for region in ["东域", "南域", "西域", "北域", "中州"]:
            self.add_item(CityRegionButton(region))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user != self.author:
            await interaction.response.send_message("这不是你的面板。", ephemeral=True)
            return False
        return True


class CityRegionButton(discord.ui.Button):
    def __init__(self, region: str):
        super().__init__(label=region, style=discord.ButtonStyle.secondary)
        self.region = region

    async def callback(self, interaction: discord.Interaction):
        cities = cities_by_region(self.region)
        embed = discord.Embed(title=f"✦ {self.region} ✦", color=discord.Color.blue())
        for c in cities:
            embed.add_field(name=c["name"], value=c["desc"], inline=False)
        await interaction.response.send_message(embed=embed)


def _special_regions_embed() -> discord.Embed:
    embed = discord.Embed(
        title="✦ 特殊秘地 ✦",
        description="天地间散布着十处特殊秘地，各有奇险：",
        color=discord.Color.gold(),
    )
    for r in SPECIAL_REGIONS:
        req = f"（需 {r['min_realm']} 以上）" if r["min_realm"] != "炼气期1层" else ""
        embed.add_field(
            name=f"{r['name']}  [{r['type']}]{req}",
            value=r["desc"],
            inline=False,
        )
    return embed


def _sects_overview_embed() -> discord.Embed:
    return discord.Embed(
        title="✦ 天下宗门 ✦",
        description=(
            "天下宗门分正道与邪道两派，各有传承。\n"
            "另有隐世宗门数个，行踪不定，有缘自会相遇。\n\n"
            "请选择阵营查看详情："
        ),
        color=discord.Color.teal(),
    )


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
