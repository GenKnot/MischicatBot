import discord
from utils.alchemy import (
    PILLS, RECIPES, QUALITY_NAMES, NO_YANHUO_CAP,
    list_available_recipes, get_recipes_for_pill, get_recipe_by_id,
    get_mastery_count, get_mastery_label, calc_success_rate,
    get_known_recipes, get_known_recipes_with_choices,
)
from utils.atomic import consume_item
from utils.db_async import AsyncSessionLocal, Inventory

import logging
from utils.views.base import TimedView

log = logging.getLogger(__name__)



async def _get_inventory(discord_id: str) -> dict:
    from sqlalchemy import select
    async with AsyncSessionLocal() as session:
        rows = await session.execute(
            select(Inventory).where(Inventory.discord_id == discord_id)
        )
        return {row.item_id: row.quantity for row in rows.scalars()}


def _pill_tier_label(tier: int) -> str:
    labels = ["", "一阶", "二阶", "三阶", "四阶", "五阶", "六阶", "七阶", "八阶", "九阶"]
    return labels[tier] if tier < len(labels) else f"{tier}阶"


def _quality_cap_label(cap: int, has_yanhuo: bool) -> str:
    effective = cap if has_yanhuo else min(cap, NO_YANHUO_CAP)
    return QUALITY_NAMES[effective]


def _match_recipe(main_items: list[str], aux_choices: dict[int, str]) -> dict | None:
    selected_kinds = set(main_items)
    for r in RECIPES:
        r_kinds = set(ing["item"] for ing in r["main_ingredients"])
        if r_kinds != selected_kinds:
            continue
        if len(aux_choices) != len(r["aux_groups"]):
            continue
        matched = True
        for gi, group in enumerate(r["aux_groups"]):
            chosen = aux_choices.get(gi)
            valid = [o["item"] for o in group["options"]]
            if chosen not in valid:
                matched = False
                break
        if matched:
            return r
    return None


def _auto_match_recipe(qty_map: dict[str, int], alchemy_level: int) -> tuple[dict | None, list[int]]:
    for r in RECIPES:
        if r["alchemy_level_req"] > alchemy_level:
            continue
        main_ok = all(
            qty_map.get(ing["item"], 0) >= ing["qty"]
            for ing in r["main_ingredients"]
        )
        if not main_ok:
            continue
        remaining: dict[str, int] = dict(qty_map)
        for ing in r["main_ingredients"]:
            remaining[ing["item"]] = remaining.get(ing["item"], 0) - ing["qty"]
        aux_choices: list[int] = []
        aux_ok = True
        for group in r["aux_groups"]:
            matched_idx = None
            for j, opt in enumerate(group["options"]):
                if remaining.get(opt["item"], 0) >= opt["qty"]:
                    matched_idx = j
                    break
            if matched_idx is None:
                aux_ok = False
                break
            opt = group["options"][matched_idx]
            remaining[opt["item"]] = remaining.get(opt["item"], 0) - opt["qty"]
            aux_choices.append(matched_idx)
        if aux_ok:
            return r, aux_choices
    return None, []


class AlchemyMainView(TimedView):
    def __init__(self, author: discord.User, player: dict, has_yanhuo: bool, known_ids: set[str], cog=None, known_choices: dict = None):
        super().__init__()
        self.author = author
        self.player = player
        self.has_yanhuo = has_yanhuo
        self.known_ids = known_ids
        self.known_choices = known_choices or {}
        self.cog = cog

    @discord.ui.button(label="已知丹方", style=discord.ButtonStyle.primary, emoji="📜")
    async def known_recipes_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.known_ids:
            await interaction.response.send_message(
                "你还没有掌握任何丹方。\n尝试使用「自由配药」摸索，成功一次后即可记录丹方。",
                ephemeral=True,
            )
            return
        known = [r for r in RECIPES if r["recipe_id"] in self.known_ids
                 and r["alchemy_level_req"] <= self.player.get("alchemy_level", 0)]
        if not known:
            await interaction.response.send_message("没有符合当前品级的已知丹方。", ephemeral=True)
            return
        view = _KnownRecipeSelectView(self.author, self.player, self.has_yanhuo, known, self.known_choices, cog=self.cog)
        await interaction.response.edit_message(content="选择已知丹方：", embed=None, view=view)

    @discord.ui.button(label="自由配药", style=discord.ButtonStyle.secondary, emoji="🔬")
    async def free_mix_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        inventory = await _get_inventory(str(interaction.user.id))
        view = _FreeMixSelectView(self.author, self.player, self.has_yanhuo, inventory, cog=self.cog)
        await interaction.response.edit_message(
            content="自由配药 — 选择要投入的药材（1-5种）：",
            embed=None,
            view=view,
        )

    @discord.ui.button(label="返回技艺", style=discord.ButtonStyle.secondary, emoji="↩️", row=1)
    async def back_crafting_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        from utils.views.crafting import CraftingMenuView, _crafting_overview_embed
        await interaction.response.edit_message(
            content=None,
            embed=_crafting_overview_embed(),
            view=CraftingMenuView(self.author, self.cog),
        )


class _KnownRecipeSelectView(TimedView):
    def __init__(self, author, player, has_yanhuo, known_recipes, known_choices: dict, cog=None):
        super().__init__()
        self.author = author
        self.player = player
        self.has_yanhuo = has_yanhuo
        self.known_choices = known_choices
        self.cog = cog
        options = [
            discord.SelectOption(
                label=r["name"],
                value=r["recipe_id"],
            )
            for r in known_recipes[:25]
        ]
        self.add_item(_KnownRecipeSelect(options))
        self.add_item(_BackToMainButton())


class _KnownRecipeSelect(discord.ui.Select):
    def __init__(self, options):
        super().__init__(placeholder="选择丹方…", options=options)

    async def callback(self, interaction: discord.Interaction):
        recipe = get_recipe_by_id(self.values[0])
        inventory = await _get_inventory(str(interaction.user.id))
        saved_choices = self.view.known_choices.get(recipe["recipe_id"], [])
        if len(saved_choices) < len(recipe["aux_groups"]):
            saved_choices = list(saved_choices) + [0] * (len(recipe["aux_groups"]) - len(saved_choices))
        missing = []
        for ing in recipe["main_ingredients"]:
            if inventory.get(ing["item"], 0) < ing["qty"]:
                missing.append(f"{ing['item']} ×{ing['qty']}")
        for i, group in enumerate(recipe["aux_groups"]):
            opt = group["options"][saved_choices[i]]
            if inventory.get(opt["item"], 0) < opt["qty"]:
                missing.append(f"{opt['item']} ×{opt['qty']}")
        if missing:
            await interaction.response.send_message(
                f"材料不足，无法开炉：{'、'.join(missing)}", ephemeral=True
            )
            return
        confirm_view = _ConfirmView(self.view.author, self.view.player, self.view.has_yanhuo, recipe, inventory, saved_choices, cog=getattr(self.view, "cog", None))
        consumed_lines = []
        for ing in recipe["main_ingredients"]:
            consumed_lines.append(f"· {ing['item']} ×{ing['qty']}")
        for i, group in enumerate(recipe["aux_groups"]):
            opt = group["options"][saved_choices[i]]
            consumed_lines.append(f"· {opt['item']} ×{opt['qty']}")
        await interaction.response.edit_message(
            content=f"即将炼制「{recipe['pill']}」，确认开炉？\n\n消耗材料：\n" + "\n".join(consumed_lines),
            embed=None,
            view=confirm_view,
        )


def _all_herb_names_owned(inventory: dict, alchemy_level: int) -> list[str]:
    seen = set()
    result = []
    for r in RECIPES:
        if r["alchemy_level_req"] > alchemy_level:
            continue
        for ing in r["main_ingredients"]:
            if ing["item"] not in seen:
                seen.add(ing["item"])
                result.append(ing["item"])
        for g in r["aux_groups"]:
            for o in g["options"]:
                if o["item"] not in seen:
                    seen.add(o["item"])
                    result.append(o["item"])
    return sorted(h for h in result if inventory.get(h, 0) > 0)


def _qty_content(qty_map: dict, inventory: dict) -> str:
    lines = ["**已选药材（点 +1 调整用量）：**"]
    for item, qty in qty_map.items():
        have = inventory.get(item, 0)
        lines.append(f"· {item} ×{qty}　（持有 {have}）")
    return "\n".join(lines)


class _FreeMixSelectView(TimedView):
    def __init__(self, author, player, has_yanhuo, inventory, cog=None):
        super().__init__()
        self.author = author
        self.player = player
        self.has_yanhuo = has_yanhuo
        self.inventory = inventory
        self.cog = cog

        herbs = _all_herb_names_owned(inventory, player.get("alchemy_level", 0))
        options = [
            discord.SelectOption(label=h, description=f"持有 {inventory.get(h, 0)}", value=h)
            for h in herbs[:25]
        ]
        if options:
            self.add_item(_FreeMixHerbSelect(options))
        self.add_item(_BackToMainButton())


class _FreeMixHerbSelect(discord.ui.Select):
    def __init__(self, options):
        super().__init__(
            placeholder="选择要投入的药材（1-5种）…",
            options=options,
            min_values=1,
            max_values=min(5, len(options)),
        )

    async def callback(self, interaction: discord.Interaction):
        v = self.view
        qty_map = {item: 1 for item in self.values}
        view = _FreeMixQtyView(v.author, v.player, v.has_yanhuo, v.inventory, qty_map, cog=getattr(v, "cog", None))
        await interaction.response.edit_message(
            content=_qty_content(qty_map, v.inventory),
            embed=None,
            view=view,
        )


class _FreeMixQtyView(TimedView):
    def __init__(self, author, player, has_yanhuo, inventory, qty_map: dict, cog=None):
        super().__init__()
        self.author = author
        self.player = player
        self.has_yanhuo = has_yanhuo
        self.inventory = inventory
        self.qty_map = dict(qty_map)
        self.cog = cog
        self._firing = False

        for i, item in enumerate(qty_map):
            self.add_item(_PlusOneButton(item, row=i % 4))
        self.add_item(_ConfirmFreeMixButton(row=4))
        self.add_item(_BackToMainButton(row=4))


class _PlusOneButton(discord.ui.Button):
    def __init__(self, item: str, row: int):
        super().__init__(label=f"{item} +1", style=discord.ButtonStyle.secondary, row=row)
        self.item = item

    async def callback(self, interaction: discord.Interaction):
        v = self.view
        have = v.inventory.get(self.item, 0)
        current = v.qty_map.get(self.item, 1)
        if current >= have:
            await interaction.response.send_message(
                f"「{self.item}」持有 {have} 个，已达上限。", ephemeral=True
            )
            return
        v.qty_map[self.item] = current + 1
        await interaction.response.edit_message(
            content=_qty_content(v.qty_map, v.inventory),
            view=v,
        )


class _ConfirmFreeMixButton(discord.ui.Button):
    def __init__(self, row: int):
        super().__init__(label="投入丹炉", style=discord.ButtonStyle.primary, row=row)

    async def callback(self, interaction: discord.Interaction):
        v = self.view
        if v._firing:
            await interaction.response.send_message("丹炉运转中，请稍候…", ephemeral=True)
            return
        v._firing = True
        try:
            await interaction.response.defer()
            uid = str(interaction.user.id)
            recipe, aux_choices = _auto_match_recipe(v.qty_map, v.player.get("alchemy_level", 0))

            all_items = []
            for item, qty in v.qty_map.items():
                all_items.extend([item] * qty)

            if recipe is None:
                if not await _consume_free_mix(uid, all_items, v.inventory):
                    await interaction.edit_original_response(
                        content="药材不足，丹炉未能点燃。", embed=None, view=None)
                    return
                await interaction.edit_original_response(
                    content="丹炉轰鸣，烟雾散尽，炉中只剩一堆灰烬。\n继续摸索吧！",
                    embed=None,
                    view=_AshView(v.author, v.player, v.has_yanhuo, v.inventory, cog=getattr(v, "cog", None)),
                )
                return

            from utils.alchemy import attempt_alchemy
            result = await attempt_alchemy(
                discord_id=uid,
                recipe=recipe,
                player_soul=v.player.get("soul", 5),
                alchemy_level=v.player.get("alchemy_level", 0),
                aux_choices=aux_choices,
                inventory=v.inventory,
                has_yanhuo=v.has_yanhuo,
                free_mix=True,
            )
            if not result["ok"] and "reason" in result:
                await interaction.edit_original_response(content=result["reason"], embed=None, view=None)
                return

            # 材料已由 attempt_alchemy 在掷骰前原子扣掉，这里不能再扣一次

            if result["success"]:
                await _give_pill(uid, result["pill"], result["quality_name"])
            elif result.get("lifespan_loss", 0) > 0:
                async with AsyncSessionLocal() as session:
                    from utils.db_async import Player as _Player
                    p = await session.get(_Player, uid)
                    if p:
                        p.lifespan = max(0, p.lifespan - result["lifespan_loss"])
                        if p.lifespan <= 0:
                            p.is_dead = True
                        await session.commit()

            embed = _result_embed(result, recipe, v.inventory)
            fail_view = None if result["success"] else _FailView(v.author, v.player, v.has_yanhuo, cog=getattr(v, "cog", None))
            await interaction.edit_original_response(embed=embed, view=fail_view)
            log.exception("炼丹出错 uid=%s", uid)
            try:
                await interaction.edit_original_response(content=f"炼丹出错：{e}", embed=None, view=None)
            except Exception:
                # 交互过期就发不出去了，没别的办法
                log.debug("炼丹报错消息发送失败", exc_info=True)
        finally:
            v._firing = False


class _AshView(TimedView):
    def __init__(self, author, player, has_yanhuo, inventory, cog=None):
        super().__init__()
        self.author = author
        self.player = player
        self.has_yanhuo = has_yanhuo
        self.inventory = inventory
        self.cog = cog

    @discord.ui.button(label="继续炼丹", style=discord.ButtonStyle.primary)
    async def continue_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        inv = await _get_inventory(str(interaction.user.id))
        view = _FreeMixSelectView(self.author, self.player, self.has_yanhuo, inv, cog=self.cog)
        await interaction.response.edit_message(
            content="自由配药 — 选择要投入的药材（1-5种）：",
            embed=None,
            view=view,
        )

    @discord.ui.button(label="返回炼丹台", style=discord.ButtonStyle.secondary)
    async def back_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        known_map = await get_known_recipes_with_choices(str(interaction.user.id))
        view = AlchemyMainView(self.author, self.player, self.has_yanhuo, set(known_map.keys()), cog=self.cog, known_choices=known_map)
        await interaction.response.edit_message(content="炼丹台：", embed=None, view=view)


class _FailView(TimedView):
    def __init__(self, author, player, has_yanhuo, cog=None):
        super().__init__()
        self.author = author
        self.player = player
        self.has_yanhuo = has_yanhuo
        self.cog = cog

    @discord.ui.button(label="继续炼丹", style=discord.ButtonStyle.primary)
    async def continue_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        known_map = await get_known_recipes_with_choices(str(interaction.user.id))
        view = AlchemyMainView(self.author, self.player, self.has_yanhuo, set(known_map.keys()), cog=self.cog, known_choices=known_map)
        await interaction.response.edit_message(content="炼丹台：", embed=None, view=view)

    @discord.ui.button(label="返回技艺", style=discord.ButtonStyle.secondary)
    async def back_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        from utils.views.crafting import CraftingMenuView, _crafting_overview_embed
        await interaction.response.edit_message(content=None, embed=_crafting_overview_embed(), view=CraftingMenuView(self.author, self.cog))


class _AuxSelectView(TimedView):
    def __init__(self, author, player, has_yanhuo, recipe, inventory, choices_so_far):
        super().__init__()
        self.author = author
        self.player = player
        self.has_yanhuo = has_yanhuo
        self.recipe = recipe
        self.inventory = inventory
        self.choices_so_far = choices_so_far

        group_idx = len(choices_so_far)
        if group_idx < len(recipe["aux_groups"]):
            group = recipe["aux_groups"][group_idx]
            options = [
                discord.SelectOption(
                    label=f"{opt['item']} ×{opt['qty']}",
                    description=f"持有 {inventory.get(opt['item'], 0)}  品质{opt.get('quality_bonus', 0):+d}",
                    value=str(j),
                )
                for j, opt in enumerate(group["options"])
            ]
            self.add_item(_AuxSelect(group["desc"], options, group_idx))
        self.add_item(_BackToMainButton())


class _AuxSelect(discord.ui.Select):
    def __init__(self, desc, options, group_idx):
        super().__init__(placeholder=f"辅药组 {group_idx+1}：{desc}", options=options)
        self.group_idx = group_idx

    async def callback(self, interaction: discord.Interaction):
        v = self.view
        new_choices = v.choices_so_far + [int(self.values[0])]
        if len(new_choices) < len(v.recipe["aux_groups"]):
            next_view = _AuxSelectView(v.author, v.player, v.has_yanhuo, v.recipe, v.inventory, new_choices)
            embed = _recipe_embed(v.recipe, v.player, v.inventory, v.has_yanhuo)
            await interaction.response.edit_message(embed=embed, view=next_view)
        else:
            confirm_view = _ConfirmView(v.author, v.player, v.has_yanhuo, v.recipe, v.inventory, new_choices)
            embed = await _confirm_embed(v.recipe, v.player, v.inventory, new_choices, v.has_yanhuo)
            await interaction.response.edit_message(content=None, embed=embed, view=confirm_view)


class _ConfirmView(TimedView):
    def __init__(self, author, player, has_yanhuo, recipe, inventory, choices, cog=None):
        super().__init__()
        self.author = author
        self.player = player
        self.has_yanhuo = has_yanhuo
        self.recipe = recipe
        self.inventory = inventory
        self.choices = choices
        self.cog = cog

    @discord.ui.button(label="开炉炼丹", style=discord.ButtonStyle.success)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        from utils.alchemy import attempt_alchemy
        uid = str(interaction.user.id)
        result = await attempt_alchemy(
            discord_id=uid,
            recipe=self.recipe,
            player_soul=self.player.get("soul", 5),
            alchemy_level=self.player.get("alchemy_level", 0),
            aux_choices=self.choices,
            inventory=self.inventory,
            has_yanhuo=self.has_yanhuo,
        )
        if not result["ok"] and "reason" in result:
            await interaction.followup.send(result["reason"], ephemeral=True)
            self.stop()
            return

        # 材料已由 attempt_alchemy 在掷骰前原子扣掉，这里不能再扣一次

        if result["success"]:
            await _give_pill(uid, result["pill"], result["quality_name"])
        elif result.get("lifespan_loss", 0) > 0:
            async with AsyncSessionLocal() as session:
                from utils.db_async import Player as _Player
                p = await session.get(_Player, uid)
                if p:
                    p.lifespan = max(0, p.lifespan - result["lifespan_loss"])
                    if p.lifespan <= 0:
                        p.is_dead = True
                    await session.commit()

        embed = _result_embed(result, self.recipe, self.inventory)
        fail_view = None if result["success"] else _FailView(self.author, self.player, self.has_yanhuo, cog=getattr(self, "cog", None))
        await interaction.edit_original_response(embed=embed, view=fail_view)
        self.stop()

    @discord.ui.button(label="取消", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(content="已取消炼丹。", embed=None, view=None)
        self.stop()


class _BackToMainButton(discord.ui.Button):
    def __init__(self, row: int | None = None):
        super().__init__(label="返回炼丹台", style=discord.ButtonStyle.secondary, row=row)

    async def callback(self, interaction: discord.Interaction):
        v = self.view
        uid = str(interaction.user.id)
        known_map = await get_known_recipes_with_choices(uid)
        view = AlchemyMainView(v.author, v.player, v.has_yanhuo, set(known_map.keys()), cog=getattr(v, "cog", None), known_choices=known_map)
        await interaction.response.edit_message(content="炼丹台：", embed=None, view=view)


def _recipe_embed(recipe: dict, player: dict, inventory: dict, has_yanhuo: bool) -> discord.Embed:
    pill_name = recipe["pill"]
    pill_info = PILLS.get(pill_name, {})
    embed = discord.Embed(title=f"丹方：{recipe['name']}", description=pill_info.get("desc", ""), color=0xE8C97A)
    embed.add_field(
        name="基本信息",
        value=(
            f"丹药：{pill_name}（{_pill_tier_label(recipe['pill_tier'])}）\n"
            f"需要品级：{recipe['alchemy_level_req']} 品\n"
            f"基础成功率：{recipe['base_success_rate']}%\n"
            f"品质上限：{_quality_cap_label(recipe['max_quality'], has_yanhuo)}"
            + ("" if has_yanhuo else "（无异火）")
        ),
        inline=False,
    )
    main_lines = []
    for ing in recipe["main_ingredients"]:
        have = inventory.get(ing["item"], 0)
        ok = "✅" if have >= ing["qty"] else "❌"
        main_lines.append(f"{ok} {ing['item']} ×{ing['qty']}（持有 {have}）")
    embed.add_field(name="主药", value="\n".join(main_lines), inline=False)
    for i, group in enumerate(recipe["aux_groups"]):
        lines = []
        for j, opt in enumerate(group["options"]):
            have = inventory.get(opt["item"], 0)
            ok = "✅" if have >= opt["qty"] else "❌"
            bonus_str = f"  品质{opt['quality_bonus']:+d}" if opt.get("quality_bonus") else ""
            lines.append(f"{ok} [{j+1}] {opt['item']} ×{opt['qty']}（持有 {have}）{bonus_str}")
        embed.add_field(name=f"辅药组 {i+1}：{group['desc']}", value="\n".join(lines), inline=False)
    return embed


async def _confirm_embed(recipe, player, inventory, choices, has_yanhuo) -> discord.Embed:
    uid = str(player["discord_id"])
    mastery_count = await get_mastery_count(uid, recipe["pill"])
    success_rate = calc_success_rate(recipe, player.get("alchemy_level", 0), mastery_count)
    lines = []
    for ing in recipe["main_ingredients"]:
        lines.append(f"• {ing['item']} ×{ing['qty']}")
    for i, group in enumerate(recipe["aux_groups"]):
        opt = group["options"][choices[i]]
        lines.append(f"• {opt['item']} ×{opt['qty']}（辅药组 {i+1}）")
    embed = discord.Embed(title="确认开炉", color=0xE8C97A)
    embed.add_field(name="丹方", value=recipe["name"], inline=True)
    embed.add_field(name="成功率", value=f"{success_rate}%", inline=True)
    embed.add_field(name="品质上限", value=_quality_cap_label(recipe["max_quality"], has_yanhuo), inline=True)
    embed.add_field(name="熟练度", value=f"{get_mastery_label(mastery_count)}（{mastery_count}次）", inline=True)
    embed.add_field(name="消耗材料", value="\n".join(lines), inline=False)
    return embed


def _result_embed(result: dict, recipe: dict, inventory: dict = None) -> discord.Embed:
    consumed = result.get("consumed", {})
    consumed_lines = []
    for item, qty in consumed.items():
        remaining = (inventory.get(item, 0) - qty) if inventory else None
        line = f"{item} ×{qty}"
        if remaining is not None:
            line += f"（剩余 {max(0, remaining)}）"
        consumed_lines.append(line)
    consumed_str = "\n".join(consumed_lines)
    if not result["success"]:
        consequence = result.get("consequence", "普通失败")
        lifespan_loss = result.get("lifespan_loss", 0)
        desc = "材料已消耗，无产出。"
        if lifespan_loss:
            desc += f"\n寿元损失 {lifespan_loss} 年。"
        embed = discord.Embed(title=f"炼丹失败 — {consequence}", description=desc, color=0x8B0000)
        embed.add_field(name="今日剩余次数", value=f"{6 - result['daily_count']}/6", inline=True)
        if consumed_str:
            embed.add_field(name="消耗材料", value=consumed_str, inline=False)
        return embed
    quality = result["quality_name"]
    pill = result["pill"]
    first_time = result.get("first_unlock", False)
    color = 0xFFD700 if quality == "无暇" else (0x9B59B6 if "纹" in quality else 0x2ECC71)
    embed = discord.Embed(
        title="炼丹成功！",
        description=f"获得「{quality}{pill}」" + ("\n\n✨ 首次炼成，丹方已记录！" if first_time else ""),
        color=color,
    )
    embed.add_field(name="品质", value=quality, inline=True)
    embed.add_field(name="今日剩余次数", value=f"{6 - result['daily_count']}/6", inline=True)
    embed.add_field(name="熟练度", value=f"{result['mastery_label']}（{result['mastery_count']}次）", inline=True)
    if consumed_str:
        embed.add_field(name="消耗材料", value=consumed_str, inline=False)
    if result.get("leveled_up"):
        embed.add_field(name="品级提升", value=f"恭喜晋升为 {result['alchemy_level']} 品炼丹师！", inline=False)
    return embed


async def _consume_all(discord_id: str, to_consume: dict[str, int]) -> bool:
    """在同一事务里把一组材料扣净。任一不足则整体不扣，返回 False。

    原先的写法是 `if row: row.quantity -= qty` —— 背包里没有这味药时直接
    跳过，等于不花材料也能开炉；数量不够时还会把库存扣成负数。
    """
    async with AsyncSessionLocal() as session:
        for item_id, qty in to_consume.items():
            if not await consume_item(session, discord_id, item_id, qty):
                await session.rollback()
                return False
        await session.commit()
        return True


async def _consume_free_mix(discord_id: str, all_items: list[str], inventory: dict) -> bool:
    to_consume: dict[str, int] = {}
    for item in all_items:
        to_consume[item] = to_consume.get(item, 0) + 1
    return await _consume_all(discord_id, to_consume)


async def _give_pill(discord_id: str, pill_name: str, quality_name: str):
    from sqlalchemy.dialects.sqlite import insert as sqlite_insert
    item_id = pill_name if quality_name == "常规" else f"{quality_name}{pill_name}"
    async with AsyncSessionLocal() as session:
        stmt = sqlite_insert(Inventory).values(
            discord_id=discord_id, item_id=item_id, quantity=1
        ).on_conflict_do_update(
            index_elements=["discord_id", "item_id"],
            set_={"quantity": Inventory.quantity + 1},
        )
        await session.execute(stmt)
        await session.commit()
