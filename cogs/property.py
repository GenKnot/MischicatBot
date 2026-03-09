import time

import discord
from discord.ext import commands

from utils.config import COMMAND_PREFIX
from utils.db import get_conn, has_residence, get_residences
from utils.world import get_city, SPECIAL_REGIONS
from utils.character import (
    RESIDENCE_PRICE_NORMAL, RESIDENCE_PRICE_CENTRAL, CAVE_PRICE,
    REPUTATION_RESIDENCE, REPUTATION_CAVE,
    RESIDENCE_BONUS, CAVE_BONUS,
    RESIDENCE_EXPLORE_BONUS, CAVE_EXPLORE_BONUS,
)


def _get_player(discord_id: str):
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM players WHERE discord_id = ?", (discord_id,)
        ).fetchone()


def _residence_price(city_name: str) -> int:
    city = get_city(city_name)
    if city and city["region"] == "中州":
        return RESIDENCE_PRICE_CENTRAL
    return RESIDENCE_PRICE_NORMAL


class PropertyCog(commands.Cog, name="Property"):
    def __init__(self, bot):
        self.bot = bot

    @commands.hybrid_command(name="买房", aliases=["mf"], description="在当前城市购买一处居所")
    async def buy_residence(self, ctx):
        uid = str(ctx.author.id)
        player = _get_player(uid)

        if not player:
            return await ctx.send(f"{ctx.author.mention} 尚未踏入修仙之路。")
        if player["is_dead"]:
            return await ctx.send(f"{ctx.author.mention} 道友已坐化。")

        if player["reputation"] < REPUTATION_RESIDENCE:
            return await ctx.send(
                f"{ctx.author.mention} 声望不足，需要至少 **{REPUTATION_RESIDENCE}** 声望才能在城中置业。"
                f"（当前：{player['reputation']}）"
            )

        city = player["current_city"]
        if has_residence(uid, city):
            return await ctx.send(f"{ctx.author.mention} 道友在 **{city}** 已有居所。")

        price = _residence_price(city)
        if player["spirit_stones"] < price:
            return await ctx.send(
                f"{ctx.author.mention} 灵石不足。在 **{city}** 置业需要 **{price}** 灵石。"
                f"（当前：{player['spirit_stones']}）"
            )

        with get_conn() as conn:
            conn.execute(
                "INSERT INTO residences (discord_id, city, purchased_at) VALUES (?, ?, ?)",
                (uid, city, time.time())
            )
            conn.execute(
                "UPDATE players SET spirit_stones = spirit_stones - ? WHERE discord_id = ?",
                (price, uid)
            )
            conn.commit()

        embed = discord.Embed(
            title=f"✦ 喜迁新居 · {city} ✦",
            description=(
                f"道友在 **{city}** 置下了一处居所，从此有了落脚之地。\n\n"
                f"**居所加成**（仅在 {city} 生效）\n"
                f"· 修炼速度 +{int(RESIDENCE_BONUS*100)}%\n"
                f"· 探险次数上限 +{RESIDENCE_EXPLORE_BONUS}"
            ),
            color=discord.Color.teal(),
        )
        embed.set_footer(text=f"花费 {price} 灵石")
        await ctx.send(ctx.author.mention, embed=embed)

    @commands.hybrid_command(name="开辟洞府", aliases=["kpdf"], description="在秘地开辟洞府，获得全局修炼与探险加成")
    async def open_cave(self, ctx, *, region_name: str = None):
        uid = str(ctx.author.id)
        player = _get_player(uid)

        if not player:
            return await ctx.send(f"{ctx.author.mention} 尚未踏入修仙之路。")
        if player["is_dead"]:
            return await ctx.send(f"{ctx.author.mention} 道友已坐化。")

        if player["reputation"] < REPUTATION_CAVE:
            return await ctx.send(
                f"{ctx.author.mention} 声望不足，需要至少 **{REPUTATION_CAVE}** 声望才能开辟洞府。"
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

        if player["spirit_stones"] < CAVE_PRICE:
            return await ctx.send(
                f"{ctx.author.mention} 灵石不足。开辟洞府需要 **{CAVE_PRICE}** 灵石。"
                f"（当前：{player['spirit_stones']}）"
            )

        with get_conn() as conn:
            conn.execute(
                "UPDATE players SET cave = ?, spirit_stones = spirit_stones - ? WHERE discord_id = ?",
                (region_name, CAVE_PRICE, uid)
            )
            conn.commit()

        embed = discord.Embed(
            title=f"✦ 洞府初成 · {region_name} ✦",
            description=(
                f"道友在 **{region_name}** 深处开辟了一处洞府，灵气汇聚，自成一方天地。\n\n"
                f"**洞府加成**（全局生效）\n"
                f"· 修炼速度 +{int(CAVE_BONUS*100)}%\n"
                f"· 探险次数上限 +{CAVE_EXPLORE_BONUS}"
            ),
            color=discord.Color.gold(),
        )
        embed.set_footer(text=f"花费 {CAVE_PRICE} 灵石")
        await ctx.send(ctx.author.mention, embed=embed)

    @commands.hybrid_command(name="我的居所", aliases=["wdjs"], description="查看自己在各城市的居所与洞府加成")
    async def my_properties(self, ctx):
        uid = str(ctx.author.id)
        player = _get_player(uid)

        if not player:
            return await ctx.send(f"{ctx.author.mention} 尚未踏入修仙之路。")

        residences = get_residences(uid)
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
                value=f"修炼速度 +{int(RESIDENCE_BONUS*100)}%，探险次数 +{RESIDENCE_EXPLORE_BONUS}（仅当前城市生效）",
                inline=False
            )

        if cave:
            embed.add_field(name="野外洞府", value=f"**{cave}**", inline=False)
            embed.add_field(
                name="洞府加成",
                value=f"修炼速度 +{int(CAVE_BONUS*100)}%，探险次数 +{CAVE_EXPLORE_BONUS}（全局生效）",
                inline=False
            )

        await ctx.send(ctx.author.mention, embed=embed)


async def setup(bot):
    await bot.add_cog(PropertyCog(bot))
