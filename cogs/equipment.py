import discord
from discord.ext import commands

from utils.config import COMMAND_PREFIX
from utils.db import get_conn, get_equipment_list, get_equipped, equip_item, unequip_item, discard_equipment
from utils.equipment import format_equipment, equip_stat_bonus, get_player_tier, QUALITY_COLOR, STAT_NAMES, SLOTS


class EquipmentCog(commands.Cog, name="Equipment"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    def _get_player(self, discord_id: str):
        with get_conn() as conn:
            row = conn.execute("SELECT * FROM players WHERE discord_id = ?", (discord_id,)).fetchone()
            return dict(row) if row else None

    @commands.hybrid_command(name="背包", aliases=["bb"], description="查看当前角色的背包与装备")
    async def backpack(self, ctx):
        uid = str(ctx.author.id)
        player = self._get_player(uid)
        if not player or player["is_dead"]:
            return await ctx.send(f"{ctx.author.mention} 尚未踏入修仙之路。")

        from utils.db import get_inventory
        items = get_inventory(uid)
        equips = get_equipment_list(uid)

        pages = _build_backpack_pages(player, items, equips)
        cog = self.bot.cogs.get("Cultivation")
        view = BackpackPageView(ctx.author, pages, cog)
        await ctx.send(ctx.author.mention, embed=pages[0], view=view)

    @commands.hybrid_command(name="装备详情", aliases=["zbxq"], description="查看已装备装备的详细属性与总加成")
    async def equip_details(self, ctx):
        uid = str(ctx.author.id)
        player = self._get_player(uid)
        if not player or player["is_dead"]:
            return await ctx.send(f"{ctx.author.mention} 尚未踏入修仙之路。")

        equipped = get_equipped(uid)
        if not equipped:
            return await ctx.send(f"{ctx.author.mention} 当前未装备任何装备。")

        embed = discord.Embed(title="✦ 当前装备属性 ✦", color=discord.Color.teal())
        for eq in equipped:
            embed.add_field(name=format_equipment(eq).split("\n")[0], value="\n".join(format_equipment(eq).split("\n")[1:]), inline=False)

        bonus = equip_stat_bonus(equipped)
        if bonus:
            bonus_str = "  ".join(f"{STAT_NAMES.get(k, k)} +{v}" for k, v in bonus.items())
            embed.add_field(name="总属性加成", value=bonus_str, inline=False)

        await ctx.send(ctx.author.mention, embed=embed)

    @commands.hybrid_command(name="装备", aliases=["zb"], description="根据装备ID穿上指定装备")
    async def equip(self, ctx, equip_id: str = None):
        uid = str(ctx.author.id)
        if not equip_id:
            return await ctx.send(f"{ctx.author.mention} 用法：`{COMMAND_PREFIX}装备 [装备ID]`，可在 `{COMMAND_PREFIX}背包` 中查看ID。")
        player = self._get_player(uid)
        if not player or player["is_dead"]:
            return await ctx.send(f"{ctx.author.mention} 尚未踏入修仙之路。")

        tier = get_player_tier(player["realm"])
        ok, msg = equip_item(uid, equip_id, tier)
        await ctx.send(f"{ctx.author.mention} {msg}")

    @commands.hybrid_command(name="卸下", aliases=["xx"], description="根据装备ID卸下指定装备")
    async def unequip(self, ctx, equip_id: str = None):
        uid = str(ctx.author.id)
        if not equip_id:
            return await ctx.send(f"{ctx.author.mention} 用法：`{COMMAND_PREFIX}卸下 [装备ID]`")
        ok, msg = unequip_item(uid, equip_id)
        await ctx.send(f"{ctx.author.mention} {msg}")

    @commands.hybrid_command(name="丢弃装备", aliases=["dqzb"], description="根据装备ID永久丢弃一件装备")
    async def discard(self, ctx, equip_id: str = None):
        uid = str(ctx.author.id)
        if not equip_id:
            return await ctx.send(f"{ctx.author.mention} 用法：`{COMMAND_PREFIX}丢弃装备 [装备ID]`")
        ok, msg = discard_equipment(uid, equip_id)
        await ctx.send(f"{ctx.author.mention} {msg}")

    @commands.hybrid_command(name="使用", aliases=["sy"], description="使用背包中的丹药或道具")
    async def use_item(self, ctx, *, item_name: str = None):
        uid = str(ctx.author.id)
        if not item_name:
            return await ctx.send(f"{ctx.author.mention} 用法：`{COMMAND_PREFIX}使用 [道具名]`")
        player = self._get_player(uid)
        if not player or player["is_dead"]:
            return await ctx.send(f"{ctx.author.mention} 尚未踏入修仙之路。")

        from utils.db import has_item, remove_item
        from utils.items import ITEMS
        import time

        item_info = ITEMS.get(item_name)
        if not item_info:
            return await ctx.send(f"{ctx.author.mention} 未知道具「{item_name}」。")
        if not has_item(uid, item_name):
            return await ctx.send(f"{ctx.author.mention} 背包中没有「{item_name}」。")

        effect = item_info.get("effect", {})

        if "lifespan" in effect:
            gain = effect["lifespan"]
            if player["lifespan"] >= player["lifespan_max"]:
                return await ctx.send(
                    f"{ctx.author.mention} 当前寿元 **{player['lifespan']}年** 已达上限（{player['lifespan_max']}年），"
                    f"「{item_name}」无法生效。"
                )
            new_lifespan = min(player["lifespan"] + gain, player["lifespan_max"])
            actual = new_lifespan - player["lifespan"]
            with get_conn() as conn:
                conn.execute("UPDATE players SET lifespan = ? WHERE discord_id = ?", (new_lifespan, uid))
                conn.commit()
            remove_item(uid, item_name)
            return await ctx.send(f"{ctx.author.mention} 服用「{item_name}」，寿元恢复 **+{actual}年**（当前 {new_lifespan}/{player['lifespan_max']} 年）。")

        if "lifespan_extend" in effect:
            gain = effect["lifespan_extend"]
            new_lifespan = player["lifespan"] + gain
            with get_conn() as conn:
                conn.execute("UPDATE players SET lifespan = ? WHERE discord_id = ?", (new_lifespan, uid))
                conn.commit()
            remove_item(uid, item_name)
            over = ""
            if new_lifespan > player["lifespan_max"]:
                over = f"（超出上限 {new_lifespan - player['lifespan_max']} 年）"
            return await ctx.send(f"{ctx.author.mention} 服用「{item_name}」，寿元 **+{gain}年**（当前 {new_lifespan}/{player['lifespan_max']} 年）{over}")

        if "cultivation_speed_bonus" in effect:
            import time as _t
            buff_years = 2
            buff_until = _t.time() + buff_years * 2 * 3600
            with get_conn() as conn:
                conn.execute(
                    "UPDATE players SET pill_buff_until = ? WHERE discord_id = ?",
                    (buff_until, uid)
                )
                conn.commit()
            remove_item(uid, item_name)
            return await ctx.send(
                f"{ctx.author.mention} 服用「{item_name}」，修炼速度提升 **+{effect['cultivation_speed_bonus']}%**，持续 **2 游戏年**（现实 4 小时）。"
            )

        if "breakthrough_bonus" in effect:
            remove_item(uid, item_name)
            return await ctx.send(
                f"{ctx.author.mention} 服用「{item_name}」，下次突破成功率 **+{effect['breakthrough_bonus']}%**。\n"
                f"（提示：请立即使用 `{COMMAND_PREFIX}突破` 以享受加成）"
            )

        await ctx.send(f"{ctx.author.mention} 「{item_name}」暂时无法直接使用。")


    @commands.hybrid_command(name="出售", aliases=["cs"], description="出售背包中的指定物品换取灵石")
    async def sell_item(self, ctx, *, args: str = None):
        uid = str(ctx.author.id)
        if not args:
            return await ctx.send(f"{ctx.author.mention} 用法：`{COMMAND_PREFIX}出售 [物品名] [数量]`，例如 `{COMMAND_PREFIX}出售 铜矿石 5`")
        player = self._get_player(uid)
        if not player or player["is_dead"]:
            return await ctx.send(f"{ctx.author.mention} 尚未踏入修仙之路。")

        parts = args.rsplit(" ", 1)
        item_name = parts[0].strip()
        quantity = 1
        if len(parts) == 2:
            try:
                quantity = int(parts[1])
            except ValueError:
                item_name = args.strip()
        if quantity < 1:
            return await ctx.send(f"{ctx.author.mention} 数量需大于 0。")

        from utils.items import ITEMS
        from utils.db import get_inventory, remove_item
        item_info = ITEMS.get(item_name)
        if not item_info:
            return await ctx.send(f"{ctx.author.mention} 未知物品「{item_name}」。")
        sell_price = item_info.get("sell_price", 0)
        if sell_price <= 0:
            return await ctx.send(f"{ctx.author.mention} 「{item_name}」无法出售。")

        inv = get_inventory(uid)
        owned = inv.get(item_name, 0)
        if owned < quantity:
            return await ctx.send(f"{ctx.author.mention} 背包中只有 **{owned}** 个「{item_name}」。")

        total = sell_price * quantity
        ok = remove_item(uid, item_name, quantity)
        if not ok:
            return await ctx.send(f"{ctx.author.mention} 出售失败。")

        with get_conn() as conn:
            conn.execute(
                "UPDATE players SET spirit_stones = spirit_stones + ? WHERE discord_id = ?",
                (total, uid)
            )
            conn.commit()

        await ctx.send(
            f"{ctx.author.mention} 出售 **{item_name}** ×{quantity}，获得 **{total} 灵石**"
            f"（单价 {sell_price}）。"
        )


def _build_backpack_pages(player: dict, items: dict, equips: list) -> list[discord.Embed]:
    from utils.items import ITEMS
    pages = []
    title = f"✦ {player['name']} 的背包 ✦"
    footer = f"使用 {COMMAND_PREFIX}装备 [ID] 装备物品 · {COMMAND_PREFIX}卸下 [ID] 卸下 · {COMMAND_PREFIX}装备详情 查看属性加成"

    item_lines = []
    if items:
        for item_id, qty in items.items():
            info = ITEMS.get(item_id, {})
            item_lines.append(f"· **{item_id}** ×{qty}　{info.get('desc', '')}")
    else:
        item_lines = ["空空如也"]

    equipped = [e for e in equips if e["equipped"]] if equips else []
    unequipped = [e for e in equips if not e["equipped"]] if equips else []
    equip_lines = [f"{QUALITY_COLOR.get(e['quality'], '⬜')} **{e['name']}**（已装备）" for e in equipped]
    unequip_lines = [f"{QUALITY_COLOR.get(e['quality'], '⬜')} **{e['name']}**　`{e['equip_id']}`" for e in unequipped]

    def _chunk(lines: list[str], limit: int = 900) -> list[list[str]]:
        chunks, cur, cur_len = [], [], 0
        for line in lines:
            if cur_len + len(line) + 1 > limit and cur:
                chunks.append(cur)
                cur, cur_len = [], 0
            cur.append(line)
            cur_len += len(line) + 1
        if cur:
            chunks.append(cur)
        return chunks or [[]]

    item_chunks = _chunk(item_lines)
    equip_chunks = _chunk(equip_lines + (["---未装备---"] if unequip_lines and equip_lines else []) + unequip_lines)

    all_sections = []
    for i, chunk in enumerate(item_chunks):
        label = "丹药 / 道具" if i == 0 else f"丹药 / 道具（续{i}）"
        all_sections.append((label, "\n".join(chunk)))
    for i, chunk in enumerate(equip_chunks):
        label = "装备" if i == 0 else f"装备（续{i}）"
        all_sections.append((label, "\n".join(chunk)))
    if not equips:
        all_sections.append(("装备", "无装备"))

    FIELDS_PER_PAGE = 4
    for i in range(0, max(len(all_sections), 1), FIELDS_PER_PAGE):
        embed = discord.Embed(title=title, color=discord.Color.teal())
        for name, value in all_sections[i:i + FIELDS_PER_PAGE]:
            embed.add_field(name=name, value=value or "空", inline=False)
        embed.set_footer(text=footer)
        pages.append(embed)

    total = len(pages)
    for idx, embed in enumerate(pages):
        if total > 1:
            embed.set_footer(text=f"第 {idx+1} / {total} 页　|　{footer}")
    return pages


class BackpackPageView(discord.ui.View):
    def __init__(self, author, pages: list[discord.Embed], cog=None):
        super().__init__(timeout=120)
        self.author = author
        self.pages = pages
        self.page = 0
        self.cog = cog
        self._update_buttons()

    def _update_buttons(self):
        self.prev_btn.disabled = self.page == 0
        self.next_btn.disabled = self.page >= len(self.pages) - 1

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user != self.author:
            await interaction.response.send_message("这不是你的面板。", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="◀", style=discord.ButtonStyle.secondary)
    async def prev_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.page -= 1
        self._update_buttons()
        await interaction.response.edit_message(embed=self.pages[self.page], view=self)

    @discord.ui.button(label="▶", style=discord.ButtonStyle.secondary)
    async def next_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.page += 1
        self._update_buttons()
        await interaction.response.edit_message(embed=self.pages[self.page], view=self)

    @discord.ui.button(label="返回主菜单", style=discord.ButtonStyle.secondary)
    async def back_menu(self, interaction: discord.Interaction, button: discord.ui.Button):
        from utils.views.world import _send_main_menu
        if not self.cog:
            await interaction.response.send_message("无法返回。", ephemeral=True)
            return
        await interaction.response.defer()
        await _send_main_menu(interaction, self.cog)


async def setup(bot: commands.Bot):
    await bot.add_cog(EquipmentCog(bot))
