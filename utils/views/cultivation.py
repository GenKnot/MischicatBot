import discord


class CultivateView(discord.ui.View):
    YEAR_OPTIONS = [
        (1, "1年",  "现实 2 小时"),
        (2, "2年",  "现实 4 小时"),
        (4, "4年",  "现实 8 小时"),
        (8, "8年",  "现实 16 小时"),
    ]

    def __init__(self, author, cog, player: dict):
        super().__init__(timeout=60)
        self.author = author
        self.cog = cog
        self.player = player
        for years, label, hint in self.YEAR_OPTIONS:
            disabled = player["lifespan"] < years
            self.add_item(CultivateButton(years, label, hint, disabled))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user != self.author:
            await interaction.response.send_message("这不是你的面板。", ephemeral=True)
            return False
        return True


class CultivateButton(discord.ui.Button):
    def __init__(self, years: int, label: str, hint: str, disabled: bool):
        super().__init__(label=f"{label}（{hint}）", style=discord.ButtonStyle.primary, disabled=disabled)
        self.years = years

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer()
        await self.view.cog.start_cultivate(interaction, self.years)
        self.view.stop()


class ClaimCultivationView(discord.ui.View):
    def __init__(self, cog, uid: str):
        super().__init__(timeout=300)
        self.cog = cog
        self.uid = uid

    @discord.ui.button(label="领取修炼成果", style=discord.ButtonStyle.success)
    async def claim(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        await self.cog.claim_cultivation(interaction, self.uid)
        self.stop()
