import discord
from utils.alchemy import (
    PILLS, RECIPES, QUALITY_NAMES, NO_YANHUO_CAP,
    list_available_recipes, get_recipes_for_pill, get_recipe_by_id,
    get_mastery_count, get_mastery_label, calc_success_rate,
    get_known_recipes,
)
from utils.db_async import AsyncSessionLocal, Inventory


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
    for r in RECIPES:
        r_mains = sorted(i["item"] for i in r["main_ingredients"])
        if sorted(main_items) != r_mains:
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


class AlchemyMainView(discord.ui.View):
    def __init__(self, author: discord.User, player: dict, has_yanhuo: bool, known_ids: set[str]):
        super().__init__(timeout=120)
        self.author = author
        self.player = player
        self.has_yanhuo = has_yanhuo
        self.known_ids = known_ids

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user != self.author:
            await interaction.response.send_message("这不是你的面板。", ephemeral=True)
            return False
        return True

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
        view = _KnownRecipeSelectView(self.author, self.player, self.has_yanhuo, known)
        await interaction.response.edit_message(content="选择已知丹方：", embed=None, view=view)

    @discord.ui.button(label="自由配药", style=discord.ButtonStyle.secondary, emoji="🔬")
    async def free_mix_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        inventory = await _get_inventory(str(interaction.user.id))
        view = _FreeMixMainIngView(self.author, self.player, self.has_yanhuo, inventory)
        await interaction.response.edit_message(
            content="自由配药 — 选择主药（可多选，按确认）：",
            embed=None,
            view=view,
        )


class _KnownRecipeSelectView(discord.ui.View):
    def __init__(self, author, player, has_yanhuo, known_recipes):
        super().__init__(timeout=120)
        self.author = author
        self.player = player
        self.has_yanhuo = has_yanhuo
        options = [
            discord.SelectOption(
                label=r["name"],
                description=f"成功率 {r['base_success_rate']}%  上限 {_quality_cap_label(r['max_quality'], has_yanhuo)}",
                value=r["recipe_id"],
            )
            for r in known_recipes[:25]
        ]
        self.add_item(_KnownRecipeSelect(options))
        self.add_item(_BackToMainButton())

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user != self.author:
            await interaction.response.send_message("这不是你的面板。", ephemeral=True)
            return False
        return True


class _KnownRecipeSelect(discord.ui.Select):
    def __init__(self, options):
        super().__init__(placeholder="选择丹方…", options=options)

    async def callback(self, interaction: discord.Interaction):
        recipe = get_recipe_by_id(self.values[0])
        inventory = await _get_inventory(str(interaction.user.id))
        view = _AuxSelectView(self.view.author, self.view.player, self.view.has_yanhuo, recipe, inventory, [])
        embed = _recipe_embed(recipe, self.view.player, inventory, self.view.has_yanhuo)
        await interaction.response.edit_message(content=None, embed=embed, view=view)


def _all_herb_names(alchemy_level: int) -> list[str]:
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
    return sorted(result)


class _FreeMixMainIngView(discord.ui.View):
    def __init__(self, author, player, has_yanhuo, inventory):
        super().__init__(timeout=120)
        self.author = author
        self.player = player
        self.has_yanhuo = has_yanhuo
        self.inventory = inventory
        self.selected_mains: list[str] = []

        herbs = _all_herb_names(player.get("alchemy_level", 1))
        owned = [h for h in herbs if inventory.get(h, 0) > 0]
        options = [
            discord.SelectOption(label=h, description=f"持有 {inventory.get(h,0)}", value=h)
            for h in owned[:25]
        ]
        if options:
            self.add_item(_MainIngSelect(options))
        self.add_item(_BackToMainButton())

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user != self.author:
            await interaction.response.send_message("这不是你的面板。", ephemeral=True)
            return False
        return True


class _MainIngSelect(discord.ui.Select):
    def __init__(self, options):
        super().__init__(
            placeholder="选择主药（可多选）…",
            options=options,
            min_values=1,
            max_values=min(2, len(options)),
        )

    async def callback(self, interaction: discord.Interaction):
        v = self.view
        v.selected_mains = list(self.values)
        candidates = [
            r for r in RECIPES
            if r["alchemy_level_req"] <= v.player.get("alchemy_level", 1)
            and sorted(i["item"] for i in r["main_ingredients"]) == sorted(v.selected_mains)
        ]
        if not candidates:
            await interaction.response.send_message(
                f"以「{'、'.join(v.selected_mains)}」为主药，暂时没有匹配的丹方。\n换个组合试试？",
                ephemeral=True,
            )
            return
        first = candidates[0]
        view = _FreeAuxSelectView(v.author, v.player, v.has_yanhuo, first, v.inventory, [], v.selected_mains)
        await interaction.response.edit_message(
            content=f"主药：{'、'.join(v.selected_mains)}\n选择辅药组 1：{first['aux_groups'][0]['desc']}",
            embed=None,
            view=view,
        )


class _FreeAuxSelectView(discord.ui.View):
    def __init__(self, author, player, has_yanhuo, recipe, inventory, choices_so_far, main_items):
        super().__init__(timeout=120)
        self.author = author
        self.player = player
        self.has_yanhuo = has_yanhuo
        self.recipe = recipe
        self.inventory = inventory
        self.choices_so_far = choices_so_far
        self.main_items = main_items

        group_idx = len(choices_so_far)
        if group_idx < len(recipe["aux_groups"]):
            group = recipe["aux_groups"][group_idx]
            owned_options = [
                discord.SelectOption(
                    label=f"{opt['item']} ×{opt['qty']}",
                    description=f"持有 {inventory.get(opt['item'], 0)}",
                    value=opt["item"],
                )
                for opt in group["options"]
            ]
            all_options = owned_options + [
                discord.SelectOption(label="其他草药（自行尝试）", value="__other__")
            ]
            self.add_item(_FreeAuxSelect(group["desc"], all_options[:25], group_idx))
        self.add_item(_BackToMainButton())

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user != self.author:
            await interaction.response.send_message("这不是你的面板。", ephemeral=True)
            return False
        return True


class _FreeAuxSelect(discord.ui.Select):
    def __init__(self, desc, options, group_idx):
        super().__init__(placeholder=f"辅药组 {group_idx+1}：{desc}", options=options)
        self.group_idx = group_idx

    async def callback(self, interaction: discord.Interaction):
        v = self.view
        chosen_item = self.values[0]
        if chosen_item == "__other__":
            await interaction.response.send_message(
                "选择了未知辅药，炼丹将继续但可能无法匹配任何丹方，结果未知。",
                ephemeral=True,
            )
            chosen_item = "__unknown__"

        new_choices_items = v.choices_so_far + [chosen_item]
        total_groups = len(v.recipe["aux_groups"])

        if len(new_choices_items) < total_groups:
            next_group = v.recipe["aux_groups"][len(new_choices_items)]
            next_view = _FreeAuxSelectView(
                v.author, v.player, v.has_yanhuo, v.recipe, v.inventory, new_choices_items, v.main_items
            )
            await interaction.response.edit_message(
                content=f"主药：{'、'.join(v.main_items)}\n选择辅药组 {len(new_choices_items)+1}：{next_group['desc']}",
                view=next_view,
            )
        else:
            aux_dict = {i: item for i, item in enumerate(new_choices_items)}
            matched = _match_recipe(v.main_items, aux_dict)
            if not matched:
                await interaction.response.edit_message(
                    content=(
                        "这个配方没有匹配到任何已知丹方。\n"
                        "材料已消耗，炉中只剩一堆灰烬。继续摸索吧！"
                    ),
                    embed=None,
                    view=None,
                )
                await _consume_free_mix(str(interaction.user.id), v.main_items, new_choices_items, v.inventory)
                return

            choices_idx = []
            for gi, group in enumerate(matched["aux_groups"]):
                chosen = new_choices_items[gi]
                for j, opt in enumerate(group["options"]):
                    if opt["item"] == chosen:
                        choices_idx.append(j)
                        break
                else:
                    choices_idx.append(0)

            confirm_view = _ConfirmView(v.author, v.player, v.has_yanhuo, matched, v.inventory, choices_idx)
            embed = await _confirm_embed(matched, v.player, v.inventory, choices_idx, v.has_yanhuo)
            await interaction.response.edit_message(
                content="配方命中！确认开炉：",
                embed=embed,
                view=confirm_view,
            )


class _AuxSelectView(discord.ui.View):
    def __init__(self, author, player, has_yanhuo, recipe, inventory, choices_so_far):
        super().__init__(timeout=120)
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

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user != self.author:
            await interaction.response.send_message("这不是你的面板。", ephemeral=True)
            return False
        return True


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


class _ConfirmView(discord.ui.View):
    def __init__(self, author, player, has_yanhuo, recipe, inventory, choices):
        super().__init__(timeout=60)
        self.author = author
        self.player = player
        self.has_yanhuo = has_yanhuo
        self.recipe = recipe
        self.inventory = inventory
        self.choices = choices

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user != self.author:
            await interaction.response.send_message("这不是你的面板。", ephemeral=True)
            return False
        return True

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

        await _consume_ingredients(uid, self.recipe, self.choices)

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

        embed = _result_embed(result, self.recipe)
        await interaction.edit_original_response(embed=embed, view=None)
        self.stop()

    @discord.ui.button(label="取消", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(content="已取消炼丹。", embed=None, view=None)
        self.stop()


class _BackToMainButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="返回", style=discord.ButtonStyle.secondary)

    async def callback(self, interaction: discord.Interaction):
        v = self.view
        uid = str(interaction.user.id)
        known_ids = await get_known_recipes(uid)
        view = AlchemyMainView(v.author, v.player, v.has_yanhuo, known_ids)
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


def _result_embed(result: dict, recipe: dict) -> discord.Embed:
    if not result["success"]:
        consequence = result.get("consequence", "普通失败")
        lifespan_loss = result.get("lifespan_loss", 0)
        desc = "材料已消耗，无产出。"
        if lifespan_loss:
            desc += f"\n寿元损失 {lifespan_loss} 年。"
        embed = discord.Embed(title=f"炼丹失败 — {consequence}", description=desc, color=0x8B0000)
        embed.add_field(name="成功率", value=f"{result['success_rate']}%", inline=True)
        embed.add_field(name="今日剩余次数", value=f"{6 - result['daily_count']}/6", inline=True)
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
    embed.add_field(name="成功率", value=f"{result['success_rate']}%", inline=True)
    embed.add_field(name="今日剩余次数", value=f"{6 - result['daily_count']}/6", inline=True)
    embed.add_field(name="熟练度", value=f"{result['mastery_label']}（{result['mastery_count']}次）", inline=True)
    if result.get("leveled_up"):
        embed.add_field(name="品级提升", value=f"恭喜晋升为 {result['alchemy_level']} 品炼丹师！", inline=False)
    return embed


async def _consume_ingredients(discord_id: str, recipe: dict, choices: list[int]):
    async with AsyncSessionLocal() as session:
        to_consume: dict[str, int] = {}
        for ing in recipe["main_ingredients"]:
            to_consume[ing["item"]] = to_consume.get(ing["item"], 0) + ing["qty"]
        for i, group in enumerate(recipe["aux_groups"]):
            opt = group["options"][choices[i]]
            to_consume[opt["item"]] = to_consume.get(opt["item"], 0) + opt["qty"]
        for item_id, qty in to_consume.items():
            row = await session.get(Inventory, (discord_id, item_id))
            if row:
                row.quantity -= qty
                if row.quantity <= 0:
                    await session.delete(row)
        await session.commit()


async def _consume_free_mix(discord_id: str, main_items: list[str], aux_items: list[str], inventory: dict):
    async with AsyncSessionLocal() as session:
        to_consume: dict[str, int] = {}
        for item in main_items:
            to_consume[item] = to_consume.get(item, 0) + 1
        for item in aux_items:
            if item not in ("__unknown__", "__other__"):
                to_consume[item] = to_consume.get(item, 0) + 1
        for item_id, qty in to_consume.items():
            row = await session.get(Inventory, (discord_id, item_id))
            if row:
                row.quantity -= qty
                if row.quantity <= 0:
                    await session.delete(row)
        await session.commit()


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
