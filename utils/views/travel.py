import discord
from utils.world import cities_by_region


class TravelRegionView(discord.ui.View):
    def __init__(self, author, cog):
        super().__init__(timeout=120)
        self.author = author
        self.cog = cog
        for region in ["东域", "南域", "西域", "北域", "中州"]:
            self.add_item(TravelRegionButton(region))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user != self.author:
            await interaction.response.send_message("这不是你的面板。", ephemeral=True)
            return False
        return True


class TravelRegionButton(discord.ui.Button):
    def __init__(self, region: str):
        super().__init__(label=region, style=discord.ButtonStyle.secondary)
        self.region = region

    async def callback(self, interaction: discord.Interaction):
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
        ctx = await self.view.cog.bot.get_context(interaction.message)
        ctx.author = interaction.user
        await self.view.cog.travel(ctx, city_name=self.city_name)


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
