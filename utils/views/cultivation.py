import discord
from utils.views.base import TimedView


class CultivateView(TimedView):
    YEAR_OPTIONS = [
        (1, "1年",  "现实 2 小时"),
        (2, "2年",  "现实 4 小时"),
        (4, "4年",  "现实 8 小时"),
        (8, "8年",  "现实 16 小时"),
    ]

    def __init__(self, author, cog, player: dict):
        super().__init__()
        self.author = author
        self.cog = cog
        self.player = player
        for years, label, hint in self.YEAR_OPTIONS:
            disabled = player["lifespan"] < years
            self.add_item(CultivateButton(years, label, hint, disabled))
        self.add_item(_BackToMenuButton())


class CultivateButton(discord.ui.Button):
    def __init__(self, years: int, label: str, hint: str, disabled: bool):
        super().__init__(label=f"{label}（{hint}）", style=discord.ButtonStyle.primary, disabled=disabled)
        self.years = years

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer()
        await self.view.cog.start_cultivate(interaction, self.years)
        self.view.stop()


class ZhujiBreakthroughView(TimedView):
    def __init__(self, author, cog, player: dict, has_pill: bool, uid: str):
        super().__init__()
        self.author = author
        self.cog = cog
        self.player = player
        self.uid = uid
        self.has_pill = has_pill

        from utils.items import can_skip_pill
        self.can_skip = can_skip_pill(player)

        if has_pill:
            self.add_item(_ZhujiButton("服用筑基丹冲关", use_pill=True))
        self.add_item(_ZhujiButton("直接冲关", use_pill=False))


def _format_pill_result(res: dict, *, win_label: str, fail_label: str, pill: str, use_pill: bool) -> str:
    """把 breakthrough_logic 的丹药突破结果排成一条消息。

    只管措辞；成败、扣丹、狐符、防连点全在逻辑层，这里不再碰数据库。
    """
    if res.get("breakthrough"):
        note = f"（服用{pill}）" if use_pill else ""
        return (
            f"🎉 **{res['name']}** {win_label}{note}！\n"
            f"**{res['old_realm']}** ➜ **{res['new_realm']}**\n"
            f"寿元上限→{res['lifespan_max']}年，当前寿元→{res['lifespan']}年"
        )
    note = f"（{pill}已消耗）" if use_pill else ""
    text = (
        f"💔 **{res['name']}** {fail_label}{note}！{res['fail_msg']}\n"
        f"修为：{res['cultivation']}　寿元：{res['lifespan']}年"
    )
    if res["is_dead"]:
        text += "\n寿元耗尽，魂归天道。"
    elif res["saved_by_charm"]:
        text += "\n危急关头，狐符替你挡下一劫，寿元仅余1年。"
    return text


async def _run_pill_breakthrough(interaction: discord.Interaction, view, handler, *,
                                 win_label: str, fail_label: str, pill: str, use_pill: bool):
    from utils.breakthrough_logic import STALE_MESSAGE
    await interaction.response.defer()
    res = await handler(view.uid, use_pill)
    if not res["success"]:
        await interaction.followup.send(res["message"])
        if res["message"] != STALE_MESSAGE:          # 状态变了可以让玩家再点一次，其余情形面板作废
            view.stop()
        return
    await interaction.followup.send(
        _format_pill_result(res, win_label=win_label, fail_label=fail_label, pill=pill, use_pill=use_pill)
    )
    view.stop()


class _ZhujiButton(discord.ui.Button):
    def __init__(self, label: str, use_pill: bool):
        style = discord.ButtonStyle.success if use_pill else discord.ButtonStyle.primary
        super().__init__(label=label, style=style)
        self.use_pill = use_pill

    async def callback(self, interaction: discord.Interaction):
        from utils.breakthrough_logic import handle_zhuji_breakthrough
        await _run_pill_breakthrough(
            interaction, self.view, handle_zhuji_breakthrough,
            win_label="炼气化液，成功筑基", fail_label="筑基失败", pill="筑基丹", use_pill=self.use_pill,
        )


class _BackToMenuButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="返回主菜单", style=discord.ButtonStyle.secondary, row=1)

    async def callback(self, interaction: discord.Interaction):
        import json
        from sqlalchemy import text
        from utils.db_async import AsyncSessionLocal
        from utils.views.menu import MainMenuView, _build_menu_embed
        from utils.player import get_player, settle_time, apply_updates, can_breakthrough
        await interaction.response.defer()
        cog = self.view.cog
        uid = str(interaction.user.id)
        player = await get_player(uid)
        if player and not player["is_dead"]:
            updates, _ = await settle_time(player)
            await apply_updates(uid, updates)
            player = await get_player(uid)
        has_player = player is not None and not player["is_dead"]
        can_bt = has_player and can_breakthrough(player)
        has_dual = has_player and any(
            (t if isinstance(t, str) else t.get("name", "")) == "双修功法"
            for t in json.loads(player["techniques"] or "[]")
        )
        city_players = []
        if has_player:
            async with AsyncSessionLocal() as session:
                r = await session.execute(
                    text(
                        "SELECT discord_id, name, realm, cultivation FROM players "
                        "WHERE current_city = :city AND is_dead = 0 AND discord_id != :uid"
                    ),
                    {"city": player["current_city"], "uid": uid}
                )
                city_players = [dict(row._mapping) for row in r.fetchall()]
        self.view.stop()
        await interaction.followup.send(
            embed=_build_menu_embed(has_dual),
            view=MainMenuView(interaction.user, has_player, can_bt, cog, player, city_players)
        )


class NingdanBreakthroughView(TimedView):
    def __init__(self, author, cog, player: dict, has_pill: bool, uid: str):
        super().__init__()
        self.author = author
        self.cog = cog
        self.player = player
        self.uid = uid
        if has_pill:
            self.add_item(_MajorBreakthroughButton("服用凝丹丹冲关", "凝丹丹", use_pill=True))
        self.add_item(_MajorBreakthroughButton("直接冲关", "凝丹丹", use_pill=False))


class HuayingBreakthroughView(TimedView):
    def __init__(self, author, cog, player: dict, has_pill: bool, uid: str):
        super().__init__()
        self.author = author
        self.cog = cog
        self.player = player
        self.uid = uid
        if has_pill:
            self.add_item(_MajorBreakthroughButton("服用化婴丹冲关", "化婴丹", use_pill=True))
        self.add_item(_MajorBreakthroughButton("直接冲关", "化婴丹", use_pill=False))


class _MajorBreakthroughButton(discord.ui.Button):
    # 丹药名 → (处理函数名, 成功时的描述)。函数在回调里再取，避免模块导入时的循环依赖。
    _STAGES = {
        "凝丹丹": ("handle_ningdan_breakthrough", "筑基化液，凝结金丹"),
        "化婴丹": ("handle_huaying_breakthrough", "金丹破碎，元婴化形"),
    }

    def __init__(self, label: str, pill_name: str, use_pill: bool):
        style = discord.ButtonStyle.success if use_pill else discord.ButtonStyle.primary
        super().__init__(label=label, style=style)
        self.pill_name = pill_name
        self.use_pill = use_pill

    async def callback(self, interaction: discord.Interaction):
        from utils import breakthrough_logic
        handler_name, win_label = self._STAGES[self.pill_name]
        await _run_pill_breakthrough(
            interaction, self.view, getattr(breakthrough_logic, handler_name),
            win_label=win_label, fail_label="突破失败", pill=self.pill_name, use_pill=self.use_pill,
        )
