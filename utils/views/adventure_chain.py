import discord
from utils.adventure_chain import apply_chain_rewards, advance_stage, mark_completed
from utils.views.base import TimedView


STAT_NAMES = {"comprehension": "悟性", "physique": "体魄", "fortune": "机缘", "bone": "根骨", "soul": "神识"}


def choice_available(group: list, player: dict) -> bool:
    """一个选项（同名的一组）这位玩家能不能选。

    有无条件的版本，或有条件版本被满足，就能选。否则这是个**纯门槛选项**，属性不够就是不能选 ——
    曾经没人校验这件事：`_pick_best_choice` 找不到满足的会退回 `choices[-1]`，也就是这个带条件的
    选项本身，于是悟性 1 的玩家点「先读完石碑上的文字（需悟性 7）」照样拿到全部好奖励，
    条件形同虚设。
    """
    if any(not c.get("condition") for c in group):
        return True
    return any(player.get(c["condition"]["stat"], 0) >= c["condition"]["val"] for c in group)


def _requirement_hint(group: list) -> str:
    cond = min((c["condition"] for c in group if c.get("condition")), key=lambda c: c["val"])
    return f"（需{STAT_NAMES.get(cond['stat'], cond['stat'])}≥{cond['val']}）"


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
            group = [c for c in stage["choices"] if c["label"] == label]
            if choice_available(group, player):
                self.add_item(ChainChoiceButton(label, i, cog))
            else:
                # 属性不够：按钮照样露出来让玩家知道有这条路，但点不了
                hint = _requirement_hint(group)
                self.add_item(ChainChoiceButton(label[:80 - len(hint)] + hint, i, cog, disabled=True))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.message is not None:
            self.message = interaction.message   # 供超时提示编辑
        if interaction.user != self.author:
            await interaction.response.send_message("这不是你的奇遇。", ephemeral=True)
            return False
        return True


class ChainChoiceButton(discord.ui.Button):
    def __init__(self, label: str, index: int, cog, disabled: bool = False):
        super().__init__(label=label, style=discord.ButtonStyle.primary, disabled=disabled)
        self.index = index
        self.cog = cog

    async def callback(self, interaction: discord.Interaction):
        view = self.view
        uid = str(interaction.user.id)
        chain = view.chain
        stage_idx = view.stage_idx
        player = dict(view.player)
        stage = chain["stages"][stage_idx]
        choices = stage["choices"]
        choice = choices[self.index]
        same_label = [c for c in choices if c["label"] == choice["label"]]

        if not choice_available(same_label, player):
            return await interaction.response.send_message(
                f"条件不足，无法选择这一项{_requirement_hint(same_label)}。", ephemeral=True)

        # 必须在第一个 await 之前占位，见 TimedView.try_claim
        if not view.try_claim():
            return await interaction.response.send_message("此奇遇已处理。", ephemeral=True)
        await interaction.response.defer()
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
