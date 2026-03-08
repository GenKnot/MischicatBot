import discord
from discord.ext import commands

from utils.db import get_conn, get_equipment_list, get_equipped, equip_item, unequip_item, discard_equipment
from utils.equipment import format_equipment, equip_stat_bonus, get_player_tier, QUALITY_COLOR, STAT_NAMES, SLOTS


class EquipmentCog(commands.Cog, name="Equipment"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    def _get_player(self, discord_id: str):
        with get_conn() as conn:
            row = conn.execute("SELECT * FROM players WHERE discord_id = ?", (discord_id,)).fetchone()
            return dict(row) if row else None

    @commands.command(name="背包")
    async def backpack(self, ctx):
        uid = str(ctx.author.id)
        player = self._get_player(uid)
        if not player or player["is_dead"]:
            return await ctx.send(f"{ctx.author.mention} 尚未踏入修仙之路。")

        from utils.db import get_inventory
        items = get_inventory(uid)
        equips = get_equipment_list(uid)

        embed = discord.Embed(title=f"✦ {player['name']} 的背包 ✦", color=discord.Color.teal())

        if items:
            lines = []
            from utils.items import ITEMS
            for item_id, qty in items.items():
                info = ITEMS.get(item_id, {})
                lines.append(f"· **{item_id}** ×{qty}　{info.get('desc', '')}")
            embed.add_field(name="丹药 / 道具", value="\n".join(lines), inline=False)
        else:
            embed.add_field(name="丹药 / 道具", value="空空如也", inline=False)

        if equips:
            equipped = [e for e in equips if e["equipped"]]
            unequipped = [e for e in equips if not e["equipped"]]
            if equipped:
                lines = [f"{QUALITY_COLOR.get(e['quality'], '⬜')} **{e['name']}**（已装备）" for e in equipped]
                embed.add_field(name="装备栏", value="\n".join(lines), inline=False)
            if unequipped:
                lines = [f"{QUALITY_COLOR.get(e['quality'], '⬜')} **{e['name']}**　`{e['equip_id']}`" for e in unequipped]
                embed.add_field(name="未装备", value="\n".join(lines[:10]), inline=False)
        else:
            embed.add_field(name="装备", value="无装备", inline=False)

        embed.set_footer(text="使用 cat!装备 [ID] 装备物品 · cat!卸下 [ID] 卸下 · cat!装备详情 查看属性加成")
        await ctx.send(ctx.author.mention, embed=embed)

    @commands.command(name="装备详情")
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

    @commands.command(name="装备")
    async def equip(self, ctx, equip_id: str = None):
        uid = str(ctx.author.id)
        if not equip_id:
            return await ctx.send(f"{ctx.author.mention} 用法：`cat!装备 [装备ID]`，可在 `cat!背包` 中查看ID。")
        player = self._get_player(uid)
        if not player or player["is_dead"]:
            return await ctx.send(f"{ctx.author.mention} 尚未踏入修仙之路。")

        tier = get_player_tier(player["realm"])
        ok, msg = equip_item(uid, equip_id, tier)
        await ctx.send(f"{ctx.author.mention} {msg}")

    @commands.command(name="卸下")
    async def unequip(self, ctx, equip_id: str = None):
        uid = str(ctx.author.id)
        if not equip_id:
            return await ctx.send(f"{ctx.author.mention} 用法：`cat!卸下 [装备ID]`")
        ok, msg = unequip_item(uid, equip_id)
        await ctx.send(f"{ctx.author.mention} {msg}")

    @commands.command(name="丢弃装备")
    async def discard(self, ctx, equip_id: str = None):
        uid = str(ctx.author.id)
        if not equip_id:
            return await ctx.send(f"{ctx.author.mention} 用法：`cat!丢弃装备 [装备ID]`")
        ok, msg = discard_equipment(uid, equip_id)
        await ctx.send(f"{ctx.author.mention} {msg}")

    @commands.command(name="使用")
    async def use_item(self, ctx, *, item_name: str = None):
        uid = str(ctx.author.id)
        if not item_name:
            return await ctx.send(f"{ctx.author.mention} 用法：`cat!使用 [道具名]`")
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
            new_lifespan = min(player["lifespan"] + gain, player["lifespan_max"])
            actual = new_lifespan - player["lifespan"]
            with get_conn() as conn:
                conn.execute("UPDATE players SET lifespan = ? WHERE discord_id = ?", (new_lifespan, uid))
                conn.commit()
            remove_item(uid, item_name)
            return await ctx.send(f"{ctx.author.mention} 服用「{item_name}」，寿元恢复 **+{actual}年**（当前 {new_lifespan} 年）。")

        if "cultivation_speed_bonus" in effect:
            remove_item(uid, item_name)
            return await ctx.send(
                f"{ctx.author.mention} 服用「{item_name}」，下次修炼速度提升 **+{effect['cultivation_speed_bonus']}%**。\n"
                "（提示：聚灵丹效果将在下次 `cat!修炼` 时自动生效，当前版本为提示功能）"
            )

        if "breakthrough_bonus" in effect:
            remove_item(uid, item_name)
            return await ctx.send(
                f"{ctx.author.mention} 服用「{item_name}」，下次突破成功率 **+{effect['breakthrough_bonus']}%**。\n"
                "（提示：请立即使用 `cat!突破` 以享受加成）"
            )

        await ctx.send(f"{ctx.author.mention} 「{item_name}」暂时无法直接使用。")


async def setup(bot: commands.Bot):
    await bot.add_cog(EquipmentCog(bot))
