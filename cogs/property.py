import time

import discord
from discord.ext import commands

from utils.config import COMMAND_PREFIX
from utils.atomic import spend_stones
from utils.db_async import AsyncSessionLocal
from sqlalchemy import text
from utils.player import get_player
from utils.residence import has_residence, get_residences, add_residence
from utils.world import get_city, SPECIAL_REGIONS
from utils import rules


def _residence_cfg() -> dict:
    """置业 / 洞府的价格、声望门槛、加成（data/game_rules.json 的 character，管理员可以调），用的时候读。"""
    return rules.section("character")["residence"]


def _cave_cfg() -> dict:
    return rules.section("character")["cave"]


def _residence_price(city_name: str) -> int:
    city = get_city(city_name)
    if city and city["region"] == "中州":
        return _residence_cfg()["price_central"]
    return _residence_cfg()["price_normal"]


class PropertyCog(commands.Cog, name="Property"):
    def __init__(self, bot):
        self.bot = bot

    @commands.hybrid_command(name="买房", aliases=["mf"], description="在当前城市购买一处居所")
    async def buy_residence(self, ctx):
        uid = str(ctx.author.id)
        player = await get_player(uid)

        if not player:
            return await ctx.send(f"{ctx.author.mention} 尚未踏入修仙之路。")
        if player["is_dead"]:
            return await ctx.send(f"{ctx.author.mention} 道友已坐化。")

        if player["reputation"] < _residence_cfg()["reputation"]:
            return await ctx.send(
                f"{ctx.author.mention} 声望不足，需要至少 **{_residence_cfg()['reputation']}** 声望才能在城中置业。"
                f"（当前：{player['reputation']}）"
            )

        city = player["current_city"]
        if await has_residence(uid, city):
            return await ctx.send(f"{ctx.author.mention} 道友在 **{city}** 已有居所。")

        price = _residence_price(city)
        if player["spirit_stones"] < price:
            return await ctx.send(
                f"{ctx.author.mention} 灵石不足。在 **{city}** 置业需要 **{price}** 灵石。"
                f"（当前：{player['spirit_stones']}）"
            )

        # 先扣钱再落产权：原先顺序相反且分处两个事务，扣款失败会白送一处居所
        async with AsyncSessionLocal() as session:
            if not await spend_stones(session, uid, price):
                return await ctx.send(
                    f"{ctx.author.mention} 灵石不足。在 **{city}** 置业需要 **{price}** 灵石。"
                )
            await session.commit()
        await add_residence(uid, city)

        embed = discord.Embed(
            title=f"✦ 喜迁新居 · {city} ✦",
            description=(
                f"道友在 **{city}** 置下了一处居所，从此有了落脚之地。\n\n"
                f"**居所加成**（仅在 {city} 生效）\n"
                f"· 修炼速度 +{int(_residence_cfg()['bonus']*100)}%\n"
                f"· 探险次数上限 +{_residence_cfg()['explore_bonus']}"
            ),
            color=discord.Color.teal(),
        )
        embed.set_footer(text=f"花费 {price} 灵石")
        await ctx.send(ctx.author.mention, embed=embed)

    @commands.hybrid_command(name="开辟洞府", aliases=["kpdf"], description="在秘地开辟洞府，获得全局修炼与探险加成")
    async def open_cave(self, ctx, *, region_name: str = None):
        uid = str(ctx.author.id)
        player = await get_player(uid)

        if not player:
            return await ctx.send(f"{ctx.author.mention} 尚未踏入修仙之路。")
        if player["is_dead"]:
            return await ctx.send(f"{ctx.author.mention} 道友已坐化。")

        if player["reputation"] < _cave_cfg()["reputation"]:
            return await ctx.send(
                f"{ctx.author.mention} 声望不足，需要至少 **{_cave_cfg()['reputation']}** 声望才能开辟洞府。"
                f"（当前：{player['reputation']}）"
            )

        if player.get("cave"):
            return await ctx.send(
                f"{ctx.author.mention} 道友已在 **{player['cave']}** 开辟了洞府，无法再开辟第二处。"
            )

        if not region_name:
            lines = "\n".join(f"· **{r['name']}**（{r['type']}）— {r['desc']}" for r in SPECIAL_REGIONS)
            return await ctx.send(
                f"{ctx.author.mention} 请指定秘地名称，用法：`{COMMAND_PREFIX}开辟洞府 [秘地名]`\n\n{lines}"
            )

        target = next((r for r in SPECIAL_REGIONS if r["name"] == region_name), None)
        if not target:
            return await ctx.send(f"{ctx.author.mention} 未找到秘地「{region_name}」。")

        if player["spirit_stones"] < _cave_cfg()["price"]:
            return await ctx.send(
                f"{ctx.author.mention} 灵石不足。开辟洞府需要 **{_cave_cfg()['price']}** 灵石。"
                f"（当前：{player['spirit_stones']}）"
            )

        async with AsyncSessionLocal() as session:
            # 把"灵石够不够"写进 WHERE，连点开辟不会把灵石扣成负数
            result = await session.execute(
                text("UPDATE players SET cave = :cave, spirit_stones = spirit_stones - :price "
                     "WHERE discord_id = :uid AND spirit_stones >= :price"),
                {"cave": region_name, "price": _cave_cfg()["price"], "uid": uid}
            )
            if result.rowcount != 1:
                await session.rollback()
                return await ctx.send(
                    f"{ctx.author.mention} 灵石不足。开辟洞府需要 **{_cave_cfg()['price']}** 灵石。"
                )
            await session.commit()

        embed = discord.Embed(
            title=f"✦ 洞府初成 · {region_name} ✦",
            description=(
                f"道友在 **{region_name}** 深处开辟了一处洞府，灵气汇聚，自成一方天地。\n\n"
                f"**洞府加成**（全局生效）\n"
                f"· 修炼速度 +{int(_cave_cfg()['bonus']*100)}%\n"
                f"· 探险次数上限 +{_cave_cfg()['explore_bonus']}"
            ),
            color=discord.Color.gold(),
        )
        embed.set_footer(text=f"花费 {_cave_cfg()['price']} 灵石")
        await ctx.send(ctx.author.mention, embed=embed)

    @commands.hybrid_command(name="我的居所", aliases=["wdjs"], description="查看自己在各城市的居所与洞府加成")
    async def my_properties(self, ctx):
        uid = str(ctx.author.id)
        player = await get_player(uid)

        if not player:
            return await ctx.send(f"{ctx.author.mention} 尚未踏入修仙之路。")

        residences = await get_residences(uid)
        cave = player.get("cave")

        if not residences and not cave:
            return await ctx.send(f"{ctx.author.mention} 道友尚未置业，可使用 `{COMMAND_PREFIX}买房` 在当前城市购置居所。")

        embed = discord.Embed(title=f"✦ {player['name']} 的居所 ✦", color=discord.Color.teal())

        if residences:
            current = player["current_city"]
            lines = []
            for city in residences:
                active = "✦ 当前所在" if city == current else ""
                lines.append(f"**{city}** {active}")
            embed.add_field(
                name=f"城市居所（{len(residences)} 处）",
                value="\n".join(lines),
                inline=False
            )
            embed.add_field(
                name="居所加成",
                value=f"修炼速度 +{int(_residence_cfg()['bonus']*100)}%，探险次数 +{_residence_cfg()['explore_bonus']}（仅当前城市生效）",
                inline=False
            )

        if cave:
            embed.add_field(name="野外洞府", value=f"**{cave}**", inline=False)
            embed.add_field(
                name="洞府加成",
                value=f"修炼速度 +{int(_cave_cfg()['bonus']*100)}%，探险次数 +{_cave_cfg()['explore_bonus']}（全局生效）",
                inline=False
            )

        await ctx.send(ctx.author.mention, embed=embed)


async def setup(bot):
    await bot.add_cog(PropertyCog(bot))
