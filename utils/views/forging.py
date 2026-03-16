import discord
from utils.forging import (
    FORGING_CITIES, ORE_TIERS, ORE_TO_EQUIP_TIER,
    SLOT_MAIN_ORE_QTY, AUX_WOOD_STAT_BIAS, AUX_HERB_STAT_BIAS,
    DAILY_LIMIT, get_available_qualities, get_forging_level_label,
    get_forging_mastery, attempt_forge, attempt_reforge,
    FORGING_EXP_THRESHOLDS,
)
from utils.equipment import QUALITY_COLOR, QUALITY_ORDER, STAT_NAMES, TIER_NAMES, format_equipment
from utils.db_async import AsyncSessionLocal
from sqlalchemy import text


async def _get_player(uid: str) -> dict | None:
    async with AsyncSessionLocal() as session:
        result = await session.execute(text("SELECT * FROM players WHERE discord_id = :uid"), {"uid": uid})
        row = result.fetchone()
        return dict(row._mapping) if row else None


async def _get_inventory(uid: str) -> dict:
    from utils.inventory import get_inventory
    return await get_inventory(uid)


def _forging_main_embed(player: dict) -> discord.Embed:
    import time
    forging_level = player.get("forging_level", 0)
    forging_exp = player.get("forging_exp", 0)
    mastery_count = player.get("forging_mastery_count", 0)
    daily_count = player.get("forging_daily_count", 0)
    daily_reset = player.get("forging_daily_reset", 0)

    reset_date = time.gmtime(daily_reset)
    now_date = time.gmtime(time.time())
    if (now_date.tm_year, now_date.tm_yday) != (reset_date.tm_year, reset_date.tm_yday):
        daily_count = 0

    mastery_label, _ = get_forging_mastery(mastery_count)

    embed = discord.Embed(
        title="⚙️ 铸造坊",
        description="以灵矿为材，淬炼兵器与防具。",
        color=discord.Color.dark_grey(),
    )
    embed.add_field(
        name="炼器师品级",
        value=f"{get_forging_level_label(forging_level)}　熟练度：{mastery_label}（{mastery_count}次）",
        inline=False,
    )
    if forging_level > 0:
        next_threshold = FORGING_EXP_THRESHOLDS[forging_level + 1] if forging_level < 9 else None
        exp_str = f"{forging_exp}" if next_threshold is None else f"{forging_exp} / {next_threshold}"
        embed.add_field(name="炼器经验", value=exp_str, inline=True)
    embed.add_field(name="今日锻造", value=f"{daily_count} / {DAILY_LIMIT}", inline=True)

    if forging_level > 0:
        from utils.forging import get_max_quality_for_level
        max_q = get_max_quality_for_level(forging_level)
        embed.add_field(name="可锻造上限", value=f"{QUALITY_COLOR[max_q]} {max_q}", inline=True)

    return embed


class ForgingMainView(discord.ui.View):
    def __init__(self, author, player: dict, cog=None):
        super().__init__(timeout=120)
        self.author = author
        self.player = player
        self.cog = cog
        forging_level = player.get("forging_level", 0)
        if forging_level == 0:
            self.reforge_btn.disabled = True
        else:
            self.exam_btn.disabled = True

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user != self.author:
            await interaction.response.send_message("这不是你的面板。", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="📋 参加入门考核", style=discord.ButtonStyle.success, row=0)
    async def exam_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        from utils.forging import start_forging_exam, EXAM_COST, EXAM_MATERIALS, FORGING_CITIES
        uid = str(interaction.user.id)
        player = await _get_player(uid)
        if player.get("forging_level", 0) > 0:
            await interaction.response.send_message("你已经是炼器师了，无需再参加考核。", ephemeral=True)
            return
        if player.get("current_city") not in FORGING_CITIES:
            cities_str = "、".join(FORGING_CITIES)
            await interaction.response.send_message(f"需前往铸造坊城市（{cities_str}）才能参加考核。", ephemeral=True)
            return
        inventory = await _get_inventory(uid)
        has_exam_mats = any(inventory.get(k, 0) > 0 for k in EXAM_MATERIALS)
        if has_exam_mats:
            await interaction.response.send_message("你手上还有考核材料，直接前往技艺→锻造开始锻造即可。若材料已用完，可花 300 灵石补充。", ephemeral=True)
            return
        result = await start_forging_exam(uid)
        if not result["ok"]:
            await interaction.response.send_message(result["reason"], ephemeral=True)
            return
        mats_str = "、".join(f"{k}×{v}" for k, v in EXAM_MATERIALS.items())
        embed = discord.Embed(
            title="📋 炼器入门考核",
            description=(
                f"已缴纳 **{EXAM_COST}** 灵石，获得考核材料：**{mats_str}**\n\n"
                "前往技艺→锻造，用这批材料炼出第一件装备，即可获得1品炼器师资质。\n"
                "材料用完可花 **300 灵石** 补充。"
            ),
            color=discord.Color.gold(),
        )
        updated = await _get_player(uid)
        await interaction.response.edit_message(embed=embed, view=ForgingMainView(self.author, updated, self.cog))

    @discord.ui.button(label="⚙️ 锻造装备", style=discord.ButtonStyle.primary, row=1)
    async def forge_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        uid = str(interaction.user.id)
        player = await _get_player(uid)
        inventory = await _get_inventory(uid)
        view = ForgeSlotSelectView(self.author, player, inventory, cog=self.cog)
        await interaction.response.edit_message(embed=_forge_slot_embed(), view=view)

    @discord.ui.button(label="🔥 淬炼（洗词缀）", style=discord.ButtonStyle.danger, row=1)
    async def reforge_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        uid = str(interaction.user.id)
        player = await _get_player(uid)
        inventory = await _get_inventory(uid)
        from utils.equipment_db import get_equipment_list
        equip_list = await get_equipment_list(uid)
        if not equip_list:
            await interaction.response.send_message("你没有任何装备可以淬炼。", ephemeral=True)
            return
        view = ReforgeSelectView(self.author, player, inventory, equip_list, cog=self.cog)
        await interaction.response.edit_message(embed=_reforge_select_embed(equip_list), view=view)

    @discord.ui.button(label="返回技艺", style=discord.ButtonStyle.secondary, row=2)
    async def back_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        from utils.views.crafting import CraftingMenuView, _crafting_overview_embed
        await interaction.response.edit_message(embed=_crafting_overview_embed(), view=CraftingMenuView(self.author, self.cog))


def _forge_slot_embed() -> discord.Embed:
    return discord.Embed(
        title="⚙️ 锻造 · 选择类型",
        description="选择要锻造的装备类型。",
        color=discord.Color.dark_grey(),
    )


class ForgeSlotSelectView(discord.ui.View):
    def __init__(self, author, player: dict, inventory: dict, cog=None):
        super().__init__(timeout=120)
        self.author = author
        self.player = player
        self.inventory = inventory
        self.cog = cog

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user != self.author:
            await interaction.response.send_message("这不是你的面板。", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="⚔️ 武器", style=discord.ButtonStyle.primary)
    async def weapon_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._go_ore("武器", interaction)

    @discord.ui.button(label="🛡️ 防具", style=discord.ButtonStyle.primary)
    async def armor_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._go_ore("防具", interaction)

    @discord.ui.button(label="💍 饰品", style=discord.ButtonStyle.primary)
    async def accessory_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._go_ore("饰品", interaction)

    @discord.ui.button(label="返回", style=discord.ButtonStyle.secondary)
    async def back_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        uid = str(interaction.user.id)
        player = await _get_player(uid)
        await interaction.response.edit_message(embed=_forging_main_embed(player), view=ForgingMainView(self.author, player, self.cog))

    async def _go_ore(self, slot: str, interaction: discord.Interaction):
        view = ForgeOreSelectView(self.author, self.player, self.inventory, slot, cog=self.cog)
        await interaction.response.edit_message(embed=_forge_ore_embed(slot, self.inventory), view=view)


def _forge_ore_embed(slot: str, inventory: dict) -> discord.Embed:
    embed = discord.Embed(
        title=f"⚙️ 锻造 · {slot} · 选择主材",
        description=f"选择主矿石（需要 {SLOT_MAIN_ORE_QTY[slot]} 个），矿石品级决定装备境界要求。",
        color=discord.Color.dark_grey(),
    )
    lines = []
    for ore in ORE_TIERS:
        qty = inventory.get(ore, 0)
        tier = ORE_TO_EQUIP_TIER[ore]
        tier_name = TIER_NAMES[min(tier, len(TIER_NAMES) - 1)]
        needed = SLOT_MAIN_ORE_QTY[slot]
        status = f"✅ 持有 {qty}" if qty >= needed else f"❌ 持有 {qty}（需 {needed}）"
        lines.append(f"**{ore}** — {tier_name}期装备　{status}")
    embed.add_field(name="可用矿石", value="\n".join(lines), inline=False)
    return embed


class ForgeOreSelectView(discord.ui.View):
    def __init__(self, author, player: dict, inventory: dict, slot: str, cog=None):
        super().__init__(timeout=120)
        self.author = author
        self.player = player
        self.inventory = inventory
        self.slot = slot
        self.cog = cog
        needed = SLOT_MAIN_ORE_QTY[slot]
        for ore in ORE_TIERS:
            qty = inventory.get(ore, 0)
            self.add_item(OreButton(ore, qty >= needed))

        self.add_item(BackToSlotButton())

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user != self.author:
            await interaction.response.send_message("这不是你的面板。", ephemeral=True)
            return False
        return True


class OreButton(discord.ui.Button):
    def __init__(self, ore: str, has_enough: bool):
        super().__init__(
            label=ore,
            style=discord.ButtonStyle.success if has_enough else discord.ButtonStyle.secondary,
            disabled=not has_enough,
        )
        self.ore = ore

    async def callback(self, interaction: discord.Interaction):
        view: ForgeOreSelectView = self.view
        uid = str(interaction.user.id)
        player = await _get_player(uid)
        inventory = await _get_inventory(uid)
        next_view = ForgeQualitySelectView(view.author, player, inventory, view.slot, self.ore, cog=view.cog)
        await interaction.response.edit_message(
            embed=_forge_quality_embed(view.slot, self.ore, player),
            view=next_view,
        )


class BackToSlotButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="返回", style=discord.ButtonStyle.secondary)

    async def callback(self, interaction: discord.Interaction):
        view: ForgeOreSelectView = self.view
        uid = str(interaction.user.id)
        player = await _get_player(uid)
        inventory = await _get_inventory(uid)
        await interaction.response.edit_message(
            embed=_forge_slot_embed(),
            view=ForgeSlotSelectView(view.author, player, inventory, cog=view.cog),
        )


def _forge_quality_embed(slot: str, ore: str, player: dict) -> discord.Embed:
    forging_level = player.get("forging_level", 0)
    available = get_available_qualities(forging_level)
    embed = discord.Embed(
        title=f"⚙️ 锻造 · {slot} · 选择品质",
        description=f"主材：**{ore}**\n选择目标品质，品质越高成功率越低。",
        color=discord.Color.dark_grey(),
    )
    lines = []
    from utils.forging import calc_forge_success_rate, get_forging_mastery_count
    mastery_count = player.get("forging_mastery_count", 0)
    for q in available:
        rate = calc_forge_success_rate(forging_level, q, player.get("bone", 5), mastery_count)
        lines.append(f"{QUALITY_COLOR[q]} **{q}** — 成功率 {rate}%")
    embed.add_field(name="可选品质", value="\n".join(lines), inline=False)
    return embed


class ForgeQualitySelectView(discord.ui.View):
    def __init__(self, author, player: dict, inventory: dict, slot: str, ore: str, cog=None):
        super().__init__(timeout=120)
        self.author = author
        self.player = player
        self.inventory = inventory
        self.slot = slot
        self.ore = ore
        self.cog = cog
        forging_level = player.get("forging_level", 0)
        available = get_available_qualities(forging_level)
        for q in available:
            self.add_item(QualityButton(q))
        self.add_item(BackToOreButton())

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user != self.author:
            await interaction.response.send_message("这不是你的面板。", ephemeral=True)
            return False
        return True


class QualityButton(discord.ui.Button):
    def __init__(self, quality: str):
        styles = {
            "普通": discord.ButtonStyle.secondary,
            "精良": discord.ButtonStyle.success,
            "稀有": discord.ButtonStyle.primary,
            "史诗": discord.ButtonStyle.primary,
            "传说": discord.ButtonStyle.danger,
        }
        super().__init__(label=f"{QUALITY_COLOR[quality]} {quality}", style=styles.get(quality, discord.ButtonStyle.secondary))
        self.quality = quality

    async def callback(self, interaction: discord.Interaction):
        view: ForgeQualitySelectView = self.view
        uid = str(interaction.user.id)
        player = await _get_player(uid)
        inventory = await _get_inventory(uid)
        next_view = ForgeAuxSelectView(view.author, player, inventory, view.slot, view.ore, self.quality, cog=view.cog)
        await interaction.response.edit_message(
            embed=_forge_aux_embed(view.slot, view.ore, self.quality, inventory),
            view=next_view,
        )


class BackToOreButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="返回", style=discord.ButtonStyle.secondary)

    async def callback(self, interaction: discord.Interaction):
        view: ForgeQualitySelectView = self.view
        uid = str(interaction.user.id)
        player = await _get_player(uid)
        inventory = await _get_inventory(uid)
        await interaction.response.edit_message(
            embed=_forge_ore_embed(view.slot, inventory),
            view=ForgeOreSelectView(view.author, player, inventory, view.slot, cog=view.cog),
        )


def _forge_aux_embed(slot: str, ore: str, quality: str, inventory: dict) -> discord.Embed:
    embed = discord.Embed(
        title=f"⚙️ 锻造 · {slot} · 辅材（可选）",
        description=f"主材：**{ore}**　品质：{QUALITY_COLOR[quality]} **{quality}**\n\n辅材影响装备属性偏向，可不选直接锻造。",
        color=discord.Color.dark_grey(),
    )
    wood_lines = []
    for wood, stats in AUX_WOOD_STAT_BIAS.items():
        qty = inventory.get(wood, 0)
        stat_str = "/".join(STAT_NAMES.get(s, s) for s in stats)
        wood_lines.append(f"**{wood}**（持有{qty}）→ 偏向 {stat_str}")
    embed.add_field(name="木材辅材", value="\n".join(wood_lines) if wood_lines else "无", inline=False)

    herb_lines = []
    for herb, stats in AUX_HERB_STAT_BIAS.items():
        qty = inventory.get(herb, 0)
        stat_str = "/".join(STAT_NAMES.get(s, s) for s in stats)
        herb_lines.append(f"**{herb}**（持有{qty}）→ 偏向 {stat_str}")
    embed.add_field(name="草药辅材", value="\n".join(herb_lines) if herb_lines else "无", inline=False)
    return embed


class ForgeAuxSelectView(discord.ui.View):
    def __init__(self, author, player: dict, inventory: dict, slot: str, ore: str, quality: str, aux_wood: str | None = None, aux_herb: str | None = None, cog=None):
        super().__init__(timeout=120)
        self.author = author
        self.player = player
        self.inventory = inventory
        self.slot = slot
        self.ore = ore
        self.quality = quality
        self.aux_wood = aux_wood
        self.aux_herb = aux_herb
        self.cog = cog

        wood_options = [
            discord.SelectOption(label=w, description="/".join(STAT_NAMES.get(s, s) for s in stats), value=w)
            for w, stats in AUX_WOOD_STAT_BIAS.items()
            if inventory.get(w, 0) >= 1
        ]
        if wood_options:
            wood_options.insert(0, discord.SelectOption(label="不使用木材", value="none_wood"))
            self.add_item(AuxSelect("wood", "选择木材辅材（可选）", wood_options))

        herb_options = [
            discord.SelectOption(label=h, description="/".join(STAT_NAMES.get(s, s) for s in stats), value=h)
            for h, stats in AUX_HERB_STAT_BIAS.items()
            if inventory.get(h, 0) >= 1
        ]
        if herb_options:
            herb_options.insert(0, discord.SelectOption(label="不使用草药", value="none_herb"))
            self.add_item(AuxSelect("herb", "选择草药辅材（可选）", herb_options))

        self.add_item(ForgeConfirmButton())
        self.add_item(BackToQualityButton())

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user != self.author:
            await interaction.response.send_message("这不是你的面板。", ephemeral=True)
            return False
        return True


class AuxSelect(discord.ui.Select):
    def __init__(self, aux_type: str, placeholder: str, options: list):
        super().__init__(placeholder=placeholder, options=options, min_values=1, max_values=1)
        self.aux_type = aux_type

    async def callback(self, interaction: discord.Interaction):
        view: ForgeAuxSelectView = self.view
        val = self.values[0]
        if self.aux_type == "wood":
            view.aux_wood = None if val == "none_wood" else val
        else:
            view.aux_herb = None if val == "none_herb" else val
        await interaction.response.defer()


class ForgeConfirmButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="🔨 开始锻造", style=discord.ButtonStyle.danger)

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer()
        view: ForgeAuxSelectView = self.view
        uid = str(interaction.user.id)
        player = await _get_player(uid)
        inventory = await _get_inventory(uid)

        result = await attempt_forge(
            discord_id=uid,
            slot=view.slot,
            ore_name=view.ore,
            target_quality=view.quality,
            aux_wood=view.aux_wood,
            aux_herb=view.aux_herb,
            inventory=inventory,
            player_bone=player.get("bone", 5),
            forging_level=player.get("forging_level", 0),
        )

        if not result["ok"] and "reason" in result:
            await interaction.followup.send(result["reason"], ephemeral=True)
            return

        updated_player = await _get_player(uid)
        embed = _forge_result_embed(result, view.slot, view.ore, view.quality)
        await interaction.followup.edit_message(
            interaction.message.id,
            embed=embed,
            view=ForgingMainView(view.author, updated_player, view.cog),
        )


class BackToQualityButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="返回", style=discord.ButtonStyle.secondary)

    async def callback(self, interaction: discord.Interaction):
        view: ForgeAuxSelectView = self.view
        uid = str(interaction.user.id)
        player = await _get_player(uid)
        inventory = await _get_inventory(uid)
        await interaction.response.edit_message(
            embed=_forge_quality_embed(view.slot, view.ore, player),
            view=ForgeQualitySelectView(view.author, player, inventory, view.slot, view.ore, cog=view.cog),
        )


def _forge_result_embed(result: dict, slot: str, ore: str, quality: str) -> discord.Embed:
    if result.get("success"):
        eq = result["equipment"]
        embed = discord.Embed(
            title="⚙️ 锻造成功",
            description=format_equipment(eq),
            color=discord.Color.green(),
        )
        consumed_str = "、".join(f"{k}×{v}" for k, v in result["consumed"].items())
        embed.add_field(name="消耗材料", value=consumed_str, inline=True)
        embed.add_field(name="成功率", value=f"{result['success_rate']}%", inline=True)
        embed.add_field(name="熟练度", value=f"{result['mastery_label']}（{result['mastery_count']}次）", inline=True)
        if result.get("leveled_up") or result.get("exam_passed"):
            level_msg = "🎉 恭喜通过炼器入门考核，获得 **1品炼器师** 资质！" if result.get("exam_passed") else f"炼器师晋升至 **{result['forging_level']}品**！"
            embed.add_field(name="🎉 升级", value=level_msg, inline=False)
    else:
        consequence = result.get("consequence", "普通失败")
        embed = discord.Embed(
            title=f"⚙️ 锻造失败 · {consequence}",
            color=discord.Color.red(),
        )
        consumed_str = "、".join(f"{k}×{v}" for k, v in result["consumed"].items())
        embed.add_field(name="消耗材料", value=consumed_str, inline=True)
        embed.add_field(name="成功率", value=f"{result['success_rate']}%", inline=True)
        if result.get("lifespan_loss", 0) > 0:
            embed.add_field(name="⚠️ 走火", value=f"炉火爆炸，损失 **{result['lifespan_loss']} 年** 寿元。", inline=False)
    return embed


def _reforge_select_embed(equip_list: list[dict]) -> discord.Embed:
    embed = discord.Embed(
        title="🔥 淬炼 · 选择装备",
        description="消耗同品级矿石 + 灵石，重新随机装备词缀。",
        color=discord.Color.orange(),
    )
    from utils.forging import ORE_TIERS, RELIQUARY_COST_MULTIPLIER, QUALITY_ORDER
    lines = []
    for eq in equip_list[:10]:
        q = eq["quality"]
        ore_idx = min(QUALITY_ORDER.index(q), len(ORE_TIERS) - 1)
        ore_needed = ORE_TIERS[ore_idx]
        cost = 200 * RELIQUARY_COST_MULTIPLIER[q]
        lines.append(f"`{eq['equip_id']}` {QUALITY_COLOR[q]} **{eq['name']}** — 需 {ore_needed}×2 + {cost}灵石")
    embed.add_field(name="你的装备", value="\n".join(lines) if lines else "无", inline=False)
    return embed


class ReforgeSelectView(discord.ui.View):
    def __init__(self, author, player: dict, inventory: dict, equip_list: list[dict], cog=None):
        super().__init__(timeout=120)
        self.author = author
        self.player = player
        self.inventory = inventory
        self.equip_list = equip_list
        self.cog = cog

        options = [
            discord.SelectOption(
                label=f"{eq['name'][:40]}",
                description=f"{eq['quality']} · {eq['slot']} · ID:{eq['equip_id']}",
                value=eq["equip_id"],
            )
            for eq in equip_list[:25]
        ]
        self.add_item(ReforgeEquipSelect(options))
        self.add_item(BackFromReforgeButton())

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user != self.author:
            await interaction.response.send_message("这不是你的面板。", ephemeral=True)
            return False
        return True


class ReforgeEquipSelect(discord.ui.Select):
    def __init__(self, options):
        super().__init__(placeholder="选择要淬炼的装备", options=options)

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer()
        view: ReforgeSelectView = self.view
        uid = str(interaction.user.id)
        equip_id = self.values[0]
        player = await _get_player(uid)
        inventory = await _get_inventory(uid)

        from utils.forging import ORE_TIERS, QUALITY_ORDER, RELIQUARY_COST_MULTIPLIER
        from utils.equipment_db import get_equipment_by_id
        eq = await get_equipment_by_id(equip_id, uid)
        if not eq:
            await interaction.followup.send("装备不存在。", ephemeral=True)
            return

        q = eq["quality"]
        ore_idx = min(QUALITY_ORDER.index(q), len(ORE_TIERS) - 1)
        ore_needed = ORE_TIERS[ore_idx]

        result = await attempt_reforge(
            discord_id=uid,
            equip_id=equip_id,
            ore_name=ore_needed,
            inventory=inventory,
            spirit_stones=player.get("spirit_stones", 0),
        )

        if not result["ok"]:
            await interaction.followup.send(result["reason"], ephemeral=True)
            return

        embed = discord.Embed(
            title="🔥 淬炼完成",
            color=discord.Color.orange(),
        )
        embed.add_field(name="原装备", value=result["old_name"], inline=False)
        embed.add_field(name="淬炼后", value=result["new_name"], inline=False)
        stats_str = "　".join(f"{STAT_NAMES.get(k, k)} +{v}" for k, v in result["new_stats"].items())
        embed.add_field(name="新属性", value=stats_str, inline=False)
        embed.add_field(name="消耗", value=f"{result['ore_used']}×{result['ore_qty']} + {result['stone_cost']}灵石", inline=False)

        updated_player = await _get_player(uid)
        await interaction.followup.edit_message(
            interaction.message.id,
            embed=embed,
            view=ForgingMainView(view.author, updated_player, view.cog),
        )


class BackFromReforgeButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="返回", style=discord.ButtonStyle.secondary)

    async def callback(self, interaction: discord.Interaction):
        view: ReforgeSelectView = self.view
        uid = str(interaction.user.id)
        player = await _get_player(uid)
        await interaction.response.edit_message(
            embed=_forging_main_embed(player),
            view=ForgingMainView(view.author, player, view.cog),
        )
