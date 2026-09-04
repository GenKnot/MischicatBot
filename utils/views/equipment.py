import discord
from utils.equipment_db import get_equipment_list, equip_item, unequip_item, discard_equipment
from utils.equipment import QUALITY_COLOR, STAT_NAMES, TIER_NAMES, get_player_tier, equip_stat_bonus
from utils.views.base import TimedView


def _build_equipment_embed(player: dict, equips: list[dict]) -> discord.Embed:
    equipped = [e for e in equips if e["equipped"]]
    unequipped = [e for e in equips if not e["equipped"]]
    embed = discord.Embed(title="✦ 装备管理 ✦", color=discord.Color.teal())

    if equipped:
        lines = []
        for e in equipped:
            stats_str = "  ".join(f"{STAT_NAMES.get(k, k)}+{v}" for k, v in e["stats"].items())
            icon = QUALITY_COLOR.get(e["quality"], "⬜")
            lines.append(f"{icon} **{e['name']}**（{e['slot']}）\n　{stats_str}")
        bonus = equip_stat_bonus(equipped)
        if bonus:
            bonus_str = "  ".join(f"{STAT_NAMES.get(k, k)}+{v}" for k, v in bonus.items())
            lines.append(f"\n总加成：{bonus_str}")
        embed.add_field(name="已装备", value="\n".join(lines), inline=False)
    else:
        embed.add_field(name="已装备", value="暂无", inline=False)

    if unequipped:
        lines = []
        for e in unequipped:
            stats_str = "  ".join(f"{STAT_NAMES.get(k, k)}+{v}" for k, v in e["stats"].items())
            icon = QUALITY_COLOR.get(e["quality"], "⬜")
            tier_label = TIER_NAMES[min(e["tier"], len(TIER_NAMES) - 1)]
            lines.append(f"{icon} **{e['name']}**（{e['slot']} · {tier_label}）\n　{stats_str}")
        embed.add_field(name="背包中", value="\n".join(lines), inline=False)

    return embed


class EquipmentManageView(TimedView):
    def __init__(self, author, cog):
        super().__init__()
        self.author = author
        self.cog = cog

    @discord.ui.button(label="装备", style=discord.ButtonStyle.success, row=0)
    async def equip_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        uid = str(interaction.user.id)
        equips = await get_equipment_list(uid)
        unequipped = [e for e in equips if not e["equipped"]]
        if not unequipped:
            return await interaction.response.send_message("背包中没有可装备的装备。", ephemeral=True)
        options = []
        for e in unequipped[:25]:
            icon = QUALITY_COLOR.get(e["quality"], "⬜")
            tier_label = TIER_NAMES[min(e["tier"], len(TIER_NAMES) - 1)]
            stats_str = "  ".join(f"{STAT_NAMES.get(k,k)}+{v}" for k, v in list(e["stats"].items())[:3])
            options.append(discord.SelectOption(
                label=e["name"][:40],
                value=e["equip_id"],
                description=f"{e['slot']} · {tier_label} · {stats_str}"[:100],
                emoji=icon,
            ))
        await interaction.response.send_message(
            embed=discord.Embed(title="选择要装备的物品", color=discord.Color.green()),
            view=_EquipSelectView(self.author, self.cog, options),
            ephemeral=True,
        )

    @discord.ui.button(label="卸下", style=discord.ButtonStyle.danger, row=0)
    async def unequip_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        uid = str(interaction.user.id)
        equips = await get_equipment_list(uid)
        equipped = [e for e in equips if e["equipped"]]
        if not equipped:
            return await interaction.response.send_message("当前没有已装备的装备。", ephemeral=True)
        options = []
        for e in equipped[:25]:
            icon = QUALITY_COLOR.get(e["quality"], "⬜")
            stats_str = "  ".join(f"{STAT_NAMES.get(k,k)}+{v}" for k, v in list(e["stats"].items())[:3])
            options.append(discord.SelectOption(
                label=e["name"][:40],
                value=e["equip_id"],
                description=f"{e['slot']} · {stats_str}"[:100],
                emoji=icon,
            ))
        await interaction.response.send_message(
            embed=discord.Embed(title="选择要卸下的装备", color=discord.Color.red()),
            view=_UnequipSelectView(self.author, self.cog, options),
            ephemeral=True,
        )

    @discord.ui.button(label="丢弃", style=discord.ButtonStyle.secondary, row=0)
    async def discard_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        uid = str(interaction.user.id)
        equips = await get_equipment_list(uid)
        if not equips:
            return await interaction.response.send_message("没有任何装备可丢弃。", ephemeral=True)
        options = []
        for e in equips[:25]:
            icon = QUALITY_COLOR.get(e["quality"], "⬜")
            tier_label = TIER_NAMES[min(e["tier"], len(TIER_NAMES) - 1)]
            note = "已装备·先卸下" if e["equipped"] else tier_label
            options.append(discord.SelectOption(
                label=e["name"][:40],
                value=e["equip_id"],
                description=f"{e['slot']} · {note}"[:100],
                emoji=icon,
            ))
        await interaction.response.send_message(
            embed=discord.Embed(
                title="选择要丢弃的装备",
                description="⚠️ 丢弃后无法找回，已装备的请先卸下。",
                color=discord.Color.dark_grey(),
            ),
            view=_DiscardSelectView(self.author, self.cog, options),
            ephemeral=True,
        )

    @discord.ui.button(label="返回主菜单", style=discord.ButtonStyle.secondary, row=1)
    async def back_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        from utils.views.world import _send_main_menu
        await interaction.response.defer()
        await _send_main_menu(interaction, self.cog)


class _EquipSelectView(TimedView):
    def __init__(self, author, cog, options):
        super().__init__()
        self.author = author
        self.cog = cog
        self.select.options = options

    @discord.ui.select(placeholder="选择装备...", min_values=1, max_values=1)
    async def select(self, interaction: discord.Interaction, select: discord.ui.Select):
        from utils.player import get_player
        uid = str(interaction.user.id)
        player = await get_player(uid)
        tier = get_player_tier(player["realm"])
        ok, msg = await equip_item(uid, select.values[0], tier)
        if ok:
            await _refresh_main_panel(interaction, self.author, self.cog, msg)
        else:
            await interaction.response.send_message(msg, ephemeral=True)

    @discord.ui.button(label="返回装备面板", style=discord.ButtonStyle.secondary)
    async def back_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await _go_equipment_panel(interaction, self.author, self.cog)


class _UnequipSelectView(TimedView):
    def __init__(self, author, cog, options):
        super().__init__()
        self.author = author
        self.cog = cog
        self.select.options = options

    @discord.ui.select(placeholder="选择装备...", min_values=1, max_values=1)
    async def select(self, interaction: discord.Interaction, select: discord.ui.Select):
        uid = str(interaction.user.id)
        ok, msg = await unequip_item(uid, select.values[0])
        if ok:
            await _refresh_main_panel(interaction, self.author, self.cog, msg)
        else:
            await interaction.response.send_message(msg, ephemeral=True)

    @discord.ui.button(label="返回装备面板", style=discord.ButtonStyle.secondary)
    async def back_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await _go_equipment_panel(interaction, self.author, self.cog)


class _DiscardSelectView(TimedView):
    def __init__(self, author, cog, options):
        super().__init__()
        self.author = author
        self.cog = cog
        self.select.options = options

    @discord.ui.select(placeholder="选择装备...", min_values=1, max_values=1)
    async def select(self, interaction: discord.Interaction, select: discord.ui.Select):
        uid = str(interaction.user.id)
        ok, msg = await discard_equipment(uid, select.values[0])
        if ok:
            await _refresh_main_panel(interaction, self.author, self.cog, msg)
        else:
            await interaction.response.send_message(msg, ephemeral=True)

    @discord.ui.button(label="返回装备面板", style=discord.ButtonStyle.secondary)
    async def back_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await _go_equipment_panel(interaction, self.author, self.cog)


async def _go_equipment_panel(interaction: discord.Interaction, author, cog):
    from utils.player import get_player
    uid = str(author.id)
    player = await get_player(uid)
    equips = await get_equipment_list(uid)
    embed = _build_equipment_embed(player, equips)
    await interaction.response.edit_message(embed=embed, view=EquipmentManageView(author, cog))


async def _refresh_main_panel(interaction: discord.Interaction, author, cog, msg: str):
    from utils.player import get_player
    uid = str(author.id)
    player = await get_player(uid)
    equips = await get_equipment_list(uid)
    embed = _build_equipment_embed(player, equips)
    embed.set_footer(text=msg)
    await interaction.response.edit_message(embed=embed, view=EquipmentManageView(author, cog))
