import discord
from discord.ext import commands

from utils.config import COMMAND_PREFIX
from utils.db_async import AsyncSessionLocal, Player, Inventory
from utils.alchemy import PILLS, RECIPES, QUALITY_NAMES, list_available_recipes, get_mastery_count, get_mastery_label
from utils.views.alchemy import AlchemyMainView

ADMIN_ID = "304758476448595970"


async def _get_player(discord_id: str):
    async with AsyncSessionLocal() as session:
        return await session.get(Player, discord_id)


async def _get_inventory(discord_id: str) -> dict:
    from sqlalchemy import select
    async with AsyncSessionLocal() as session:
        rows = await session.execute(
            select(Inventory).where(Inventory.discord_id == discord_id)
        )
        return {row.item_id: row.quantity for row in rows.scalars()}


class AlchemyCog(commands.Cog, name="Alchemy"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.command(name="炼丹")
    async def alchemy(self, ctx: commands.Context):
        uid = str(ctx.author.id)
        player = await _get_player(uid)
        if not player:
            await ctx.send("你还没有角色，请先使用 `cat!开始` 创建角色。")
            return
        if player.is_dead:
            await ctx.send("你已坐化，无法炼丹。")
            return
        if player.alchemy_level == 0:
            await ctx.send(
                "你尚未入门炼丹之道。\n"
                "使用 `cat!学炼丹` 拜师入门，成为一品炼丹师后方可开炉。"
            )
            return

        player_dict = {c.key: getattr(player, c.key) for c in player.__table__.columns}
        has_yanhuo = bool(getattr(player, "yanhuo", None))
        available = list_available_recipes(player.alchemy_level)
        if not available:
            await ctx.send("你当前品级没有可用丹方。")
            return

        from utils.alchemy import get_known_recipes
        known_ids = await get_known_recipes(uid)
        view = AlchemyMainView(ctx.author, player_dict, has_yanhuo, known_ids)
        await ctx.send(
            f"**炼丹台**\n"
            f"炼丹师品级：{player.alchemy_level} 品  |  "
            f"今日剩余次数：{max(0, 6 - player.alchemy_daily_count)}/6\n"
            f"选择要炼制的丹药：",
            view=view,
        )

    @commands.command(name="学炼丹")
    async def learn_alchemy(self, ctx: commands.Context):
        uid = str(ctx.author.id)
        player = await _get_player(uid)
        if not player:
            await ctx.send("你还没有角色。")
            return
        if player.alchemy_level > 0:
            await ctx.send(f"你已经是 {player.alchemy_level} 品炼丹师了。")
            return

        async with AsyncSessionLocal() as session:
            p = await session.get(Player, uid)
            p.alchemy_level = 1
            await session.commit()

        await ctx.send(
            "你拜入炼丹一道，成为一品炼丹师。\n"
            "从此可炼制一阶丹药，使用 `cat!炼丹` 开炉。"
        )

    @commands.command(name="炼丹信息")
    async def alchemy_info(self, ctx: commands.Context):
        uid = str(ctx.author.id)
        player = await _get_player(uid)
        if not player:
            await ctx.send("你还没有角色。")
            return

        from utils.alchemy import ALCHEMY_EXP_THRESHOLDS
        level = player.alchemy_level
        exp = player.alchemy_exp
        daily = player.alchemy_daily_count

        if level == 0:
            await ctx.send("你尚未入门炼丹，使用 `cat!学炼丹` 拜师入门。")
            return

        next_exp = ALCHEMY_EXP_THRESHOLDS[level + 1] if level < 9 and level + 1 < len(ALCHEMY_EXP_THRESHOLDS) else None
        exp_str = f"{exp} / {next_exp}" if next_exp else f"{exp}（已满级）"

        available = list_available_recipes(level)
        pill_names = sorted(set(r["pill"] for r in available))

        embed = discord.Embed(title="炼丹信息", color=0xE8C97A)
        embed.add_field(name="炼丹师品级", value=f"{level} 品", inline=True)
        embed.add_field(name="炼丹经验", value=exp_str, inline=True)
        embed.add_field(name="今日次数", value=f"{daily}/6", inline=True)
        embed.add_field(
            name=f"可炼丹药（{len(pill_names)} 种）",
            value="、".join(pill_names) if pill_names else "无",
            inline=False,
        )
        await ctx.send(embed=embed)

    @commands.command(name="炼丹熟练度")
    async def alchemy_mastery(self, ctx: commands.Context):
        uid = str(ctx.author.id)
        player = await _get_player(uid)
        if not player or player.alchemy_level == 0:
            await ctx.send("你尚未入门炼丹。")
            return

        from sqlalchemy import select
        from utils.db_async import AlchemyMastery
        async with AsyncSessionLocal() as session:
            rows = await session.execute(
                select(AlchemyMastery).where(AlchemyMastery.discord_id == uid)
            )
            records = {row.pill_name: row.count for row in rows.scalars()}

        if not records:
            await ctx.send("你还没有炼制过任何丹药。")
            return

        lines = []
        for pill, count in sorted(records.items(), key=lambda x: -x[1]):
            label = get_mastery_label(count)
            lines.append(f"• {pill}：{label}（{count} 次）")

        embed = discord.Embed(title="炼丹熟练度", color=0xE8C97A)
        embed.description = "\n".join(lines)
        await ctx.send(embed=embed)

    @commands.command(name="丹方查询")
    async def recipe_lookup(self, ctx: commands.Context):
        uid = str(ctx.author.id)
        player = await _get_player(uid)
        if not player or player.alchemy_level == 0:
            await ctx.send("你尚未入门炼丹。")
            return

        from utils.alchemy import get_known_recipes, get_recipe_by_id
        known_ids = await get_known_recipes(uid)
        if not known_ids:
            await ctx.send("你还没有掌握任何丹方，通过自由配药摸索后方可记录。")
            return

        has_yanhuo = bool(getattr(player, "yanhuo", None))
        from utils.views.alchemy import _quality_cap_label, _pill_tier_label
        embed = discord.Embed(title="我的丹方", color=0xE8C97A)
        embed.description = f"已掌握 {len(known_ids)} 个丹方"

        for recipe_id in sorted(known_ids):
            r = get_recipe_by_id(recipe_id)
            if not r:
                continue
            cap_label = _quality_cap_label(r["max_quality"], has_yanhuo)
            main = "、".join(f"{i['item']}×{i['qty']}" for i in r["main_ingredients"])
            aux_lines = []
            for g in r["aux_groups"]:
                opts = " / ".join(f"{o['item']}×{o['qty']}" for o in g["options"])
                aux_lines.append(f"{g['desc']}：{opts}")
            value = (
                f"需要品级：{r['alchemy_level_req']} 品  成功率：{r['base_success_rate']}%  上限：{cap_label}\n"
                f"主药：{main}\n" + "\n".join(aux_lines)
            )
            embed.add_field(name=r["name"], value=value, inline=False)

        await ctx.send(embed=embed)

    @commands.command(name="调试炼丹")
    async def debug_alchemy(self, ctx: commands.Context, level: int = 5):
        if str(ctx.author.id) != ADMIN_ID:
            return
        uid = str(ctx.author.id)
        async with AsyncSessionLocal() as session:
            p = await session.get(Player, uid)
            if p:
                p.alchemy_level = level
                p.alchemy_exp = 0
                p.alchemy_daily_count = 0
                await session.commit()
        await ctx.send(f"已将炼丹师品级设为 {level} 品，今日次数重置。")


async def setup(bot: commands.Bot):
    await bot.add_cog(AlchemyCog(bot))
