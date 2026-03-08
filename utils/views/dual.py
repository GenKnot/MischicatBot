import discord


class DualCultivateInviteView(discord.ui.View):
    def __init__(self, cog, inviter: discord.User, target: discord.User, multiplier: float, both_virgin: bool):
        super().__init__(timeout=60)
        self.cog = cog
        self.inviter = inviter
        self.target = target
        self.multiplier = multiplier
        self.both_virgin = both_virgin

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user != self.target:
            await interaction.response.send_message("这不是发给你的邀请。", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="接受双修", style=discord.ButtonStyle.success)
    async def accept(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        await self.cog.do_dual_cultivate(interaction, self.inviter, self.target, self.multiplier, self.both_virgin)
        self.stop()

    @discord.ui.button(label="拒绝", style=discord.ButtonStyle.danger)
    async def reject(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(f"**{interaction.user.display_name}** 拒绝了双修邀请。")
        self.stop()
