import discord
from utils.adventure_chain import apply_chain_rewards, advance_stage, mark_completed
from utils.views.base import TimedView


class ChainStageView(TimedView):
    def __init__(self, author, chain: dict, stage_idx: int, player: dict, cog):
        super().__init__()
        self.author = author
        self.chain = chain
        self.stage_idx = stage_idx
        self.player = player
        self.cog = cog

        stage = chain["stages"][stage_idx]
        seen = set()
        for i, choice in enumerate(stage["choices"]):
            label = choice["label"]
            if label in seen:
                continue
            seen.add(label)
            self.add_item(ChainChoiceButton(label, i, cog))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.message is not None:
            self.message = interaction.message   # 供超时提示编辑
        if interaction.user != self.author:
            await interaction.response.send_message("这不是你的奇遇。", ephemeral=True)
            return False
        return True


class ChainChoiceButton(discord.ui.Button):
    def __init__(self, label: str, index: int, cog):
        super().__init__(label=label, style=discord.ButtonStyle.primary)
        self.index = index
        self.cog = cog

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer()
        for item in self.view.children:
            item.disabled = True
        self.view.stop()

        uid = str(interaction.user.id)
        chain = self.view.chain
        stage_idx = self.view.stage_idx
        player = dict(self.view.player)
        stage = chain["stages"][stage_idx]
        choices = stage["choices"]
        choice = choices[self.index]
        same_label = [c for c in choices if c["label"] == choice["label"]]
        selected = _pick_best_choice(same_label, player)

        if selected.get("rewards"):
            await apply_chain_rewards(uid, selected["rewards"])

        if selected.get("advance"):
            if selected.get("is_final"):
                await mark_completed(uid, chain["id"])
            else:
                await advance_stage(uid, chain["id"])

        is_final = selected.get("is_final", False)
        color = discord.Color.gold() if is_final else discord.Color.teal()
        embed = discord.Embed(
            title=f"✦ {chain['name']} · {stage['title']} · 结果 ✦",
            description=selected["flavor"],
            color=color,
        )
        if is_final:
            embed.set_footer(text="✨ 奇遇完成")

        from cogs.explore import ExploreResultView
        await interaction.followup.send(
            embed=embed,
            view=ExploreResultView(interaction.user, self.cog)
        )


def _pick_best_choice(choices: list, player: dict) -> dict:
    for c in choices:
        cond = c.get("condition")
        if cond and player.get(cond["stat"], 0) >= cond["val"]:
            return c
    for c in choices:
        if not c.get("condition"):
            return c
    return choices[-1]
