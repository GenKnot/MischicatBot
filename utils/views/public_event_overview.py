import json

import discord


class PublicEventOverviewView(discord.ui.View):
    def __init__(self, active: dict | None, pending: dict | None, auction: dict | None = None, pe_cog=None):
        super().__init__(timeout=120)
        self.active = active
        self.pending = pending
        self.pe_cog = pe_cog

        from utils.views.spirit_rain import _EventDetailButton
        from utils.views.wanbao_public import _WanbaoEventButton

        event = active or pending
        self.add_item(_EventDetailButton(event["title"] if event else "天降灵雨", event, pe_cog))
        if event:
            data = json.loads(event["data"])
            city = data.get("city", "未知城市")
            self.add_item(_TravelButton(city, event["event_id"]))
        if not (auction and auction["status"] == "ended"):
            self.add_item(_WanbaoEventButton(pe_cog))
        self.add_item(_PEBackToMenuButton(pe_cog))


class _TravelButton(discord.ui.Button):
    def __init__(self, city: str, event_id: str):
        super().__init__(label=f"前往 {city}", style=discord.ButtonStyle.success)
        self.city = city
        self.event_id = event_id

    async def callback(self, interaction: discord.Interaction):
        from utils.views.spirit_rain import TravelToEventView
        view = TravelToEventView(self.city, self.event_id)
        await interaction.response.send_message(f"前往 **{self.city}**：", view=view, ephemeral=True)


class _PEBackToMenuButton(discord.ui.Button):
    def __init__(self, pe_cog=None):
        super().__init__(label="返回主菜单", style=discord.ButtonStyle.secondary)
        self.pe_cog = pe_cog

    async def callback(self, interaction: discord.Interaction):
        from utils.views.world import _send_main_menu
        cog = self.pe_cog.bot.cogs.get("Cultivation") if self.pe_cog else None
        if not cog:
            return await interaction.response.send_message("无法返回。", ephemeral=True)
        await interaction.response.defer()
        await _send_main_menu(interaction, cog)
