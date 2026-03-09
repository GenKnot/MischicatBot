import discord
from utils.world import cities_by_region, SPECIAL_REGIONS
from utils.realms import get_realm_index


class TravelRegionView(discord.ui.View):
    def __init__(self, author, cog):
        super().__init__(timeout=120)
        self.author = author
        self.cog = cog
        for region in ["东域", "南域", "西域", "北域", "中州"]:
            self.add_item(TravelRegionButton(region))
        self.add_item(TravelRegionButton("秘地", style=discord.ButtonStyle.danger))
        self.add_item(_BackToMenuButton(row=1))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user != self.author:
            await interaction.response.send_message("这不是你的面板。", ephemeral=True)
            return False
        return True


class TravelRegionButton(discord.ui.Button):
    def __init__(self, region: str, style=None):
        super().__init__(label=region, style=style or discord.ButtonStyle.secondary)
        self.region = region

    async def callback(self, interaction: discord.Interaction):
        if self.region == "秘地":
            from utils.db import get_conn
            uid = str(interaction.user.id)
            with get_conn() as conn:
                row = conn.execute("SELECT realm FROM players WHERE discord_id = ?", (uid,)).fetchone()
            player_realm = row["realm"] if row else "炼气期1层"
            player_idx = get_realm_index(player_realm)

            embed = discord.Embed(title="✦ 秘地 · 选择目的地 ✦", color=discord.Color.gold())
            for r in SPECIAL_REGIONS:
                req_idx = get_realm_index(r["min_realm"])
                locked = player_idx < req_idx
                tag = f"🔒 需 {r['min_realm']}" if locked else f"[{r['type']}]"
                embed.add_field(name=f"{r['name']}  {tag}", value=r["desc"], inline=False)

            view = TravelSecretView(self.view.author, self.view.cog, player_idx)
            await interaction.response.send_message(embed=embed, view=view)
            return

        cities = cities_by_region(self.region)
        embed = discord.Embed(title=f"✦ {self.region} · 选择目的地 ✦", color=discord.Color.teal())
        for c in cities:
            embed.add_field(name=c["name"], value=c["desc"], inline=False)
        await interaction.response.send_message(embed=embed, view=TravelCityView(self.view.author, self.view.cog, cities))


class TravelCityView(discord.ui.View):
    def __init__(self, author, cog, cities: list):
        super().__init__(timeout=120)
        self.author = author
        self.cog = cog
        for c in cities:
            self.add_item(TravelCityButton(c["name"]))
        self.add_item(_BackToMenuButton(row=1))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user != self.author:
            await interaction.response.send_message("这不是你的面板。", ephemeral=True)
            return False
        return True


class TravelCityButton(discord.ui.Button):
    def __init__(self, city_name: str):
        super().__init__(label=city_name, style=discord.ButtonStyle.primary)
        self.city_name = city_name

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer()
        bot = self.view.cog.bot
        travel_cog = bot.cogs.get("Travel") or self.view.cog
        ctx = await bot.get_context(interaction.message)
        ctx.author = interaction.user
        await travel_cog.travel(ctx, city_name=self.city_name)


class TravelSecretView(discord.ui.View):
    def __init__(self, author, cog, player_realm_idx: int):
        super().__init__(timeout=120)
        self.author = author
        self.cog = cog
        for r in SPECIAL_REGIONS:
            req_idx = get_realm_index(r["min_realm"])
            disabled = player_realm_idx < req_idx
            self.add_item(TravelSecretButton(r["name"], r["type"], disabled))
        self.add_item(_BackToMenuButton(row=1))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user != self.author:
            await interaction.response.send_message("这不是你的面板。", ephemeral=True)
            return False
        return True


class TravelSecretButton(discord.ui.Button):
    def __init__(self, name: str, rtype: str, disabled: bool):
        emoji_map = {
            "秘境": "🌀", "采矿": "⛏️", "采药": "🌿", "探索": "🔍",
            "修炼": "🧘", "伐木": "🪓", "钓鱼": "🎣",
        }
        emoji = emoji_map.get(rtype, "📍")
        super().__init__(label=name, emoji=emoji, style=discord.ButtonStyle.primary, disabled=disabled)
        self.secret_name = name

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer()
        bot = self.view.cog.bot
        travel_cog = bot.cogs.get("Travel") or self.view.cog
        ctx = await bot.get_context(interaction.message)
        ctx.author = interaction.user
        await travel_cog.travel(ctx, city_name=self.secret_name)


class CityRegionView(discord.ui.View):
    def __init__(self, author, cog=None):
        super().__init__(timeout=120)
        self.author = author
        self.cog = cog
        for region in ["东域", "南域", "西域", "北域", "中州"]:
            self.add_item(CityRegionButton(region))
        self.add_item(_BackToWorldButton(row=1))
        self.add_item(_BackToMenuButton(row=1))

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


class _BackToWorldButton(discord.ui.Button):
    def __init__(self, row: int = 0):
        super().__init__(label="返回世界", style=discord.ButtonStyle.secondary, row=row)

    async def callback(self, interaction: discord.Interaction):
        from utils.views.world import WorldMenuView, _world_overview_embed
        await interaction.response.send_message(
            embed=_world_overview_embed(),
            view=WorldMenuView(interaction.user, self.view.cog)
        )


class _BackToMenuButton(discord.ui.Button):
    def __init__(self, row: int = 0):
        super().__init__(label="返回主菜单", style=discord.ButtonStyle.secondary, row=row)

    async def callback(self, interaction: discord.Interaction):
        from utils.views.world import _send_main_menu
        cog = self.view.cog
        if not cog:
            await interaction.response.send_message("无法返回。", ephemeral=True)
            return
        await interaction.response.defer()
        await _send_main_menu(interaction, cog)
