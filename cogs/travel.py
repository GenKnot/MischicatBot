import discord
from discord.ext import commands

from utils.db import get_conn
from utils.world import CITIES
from utils.character import seconds_to_years
from utils.player import get_player, is_defending


class TravelCog(commands.Cog, name="Travel"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.command(name="移动")
    async def travel(self, ctx, *, city_name: str = None):
        uid = str(ctx.author.id)
        player = get_player(uid)

        if not player:
            return await ctx.send(f"{ctx.author.mention} 尚未踏入修仙之路，请先使用 `cat!创建角色`。")
        if player["is_dead"]:
            return await ctx.send(f"{ctx.author.mention} 道友已坐化。")

        if not city_name:
            city_list = "\n".join(
                f"**{c['name']}**（{c['region']}）— {c['desc']}" for c in CITIES
            )
            return await ctx.send(
                f"{ctx.author.mention} 请指定目的地，用法：`cat!移动 [城市名]`\n\n{city_list}"
            )

        import time
        now = time.time()
        if player["cultivating_until"] and now < player["cultivating_until"]:
            remaining = seconds_to_years(player["cultivating_until"] - now)
            return await ctx.send(
                f"{ctx.author.mention} 道友正在闭关，无法移动。还剩约 **{remaining:.1f} 年**，可使用 `cat!停止` 提前结束。"
            )
        if player["gathering_until"] and now < player["gathering_until"]:
            remaining = seconds_to_years(player["gathering_until"] - now)
            return await ctx.send(
                f"{ctx.author.mention} 道友正在采集中，无法移动。还剩约 **{remaining:.1f} 年**。"
            )

        from utils.world import get_city, get_region
        from utils.realms import get_realm_index as _get_realm_idx
        target = get_city(city_name)
        if not target:
            secret = get_region(city_name)
            if secret:
                player_idx = _get_realm_idx(player["realm"])
                req_idx = _get_realm_idx(secret["min_realm"])
                if player_idx < req_idx:
                    return await ctx.send(
                        f"{ctx.author.mention} 境界不足，前往 **{secret['name']}** 需达到 **{secret['min_realm']}**。"
                    )
                target = {"name": secret["name"], "desc": secret["desc"], "region": f"秘地 · {secret['type']}"}
            else:
                matches = [c for c in CITIES if city_name in c["name"]]
                if len(matches) == 1:
                    target = matches[0]
                elif len(matches) > 1:
                    names = "、".join(c["name"] for c in matches)
                    return await ctx.send(f"{ctx.author.mention} 找到多个匹配城市：{names}，请输入完整城市名。")
                else:
                    return await ctx.send(f"{ctx.author.mention} 未找到城市「{city_name}」，请检查名称是否正确。")

        if target["name"] == player["current_city"]:
            return await ctx.send(f"{ctx.author.mention} 道友已在 **{target['name']}**，无需移动。")

        if is_defending(uid):
            return await ctx.send(f"{ctx.author.mention} 你正在守城，无法离开！坚守阵地直到事件结束。")

        with get_conn() as conn:
            conn.execute("UPDATE players SET current_city = ? WHERE discord_id = ?", (target["name"], uid))
            conn.commit()

        embed = discord.Embed(
            title=f"✦ 抵达 {target['name']} ✦",
            description=target["desc"],
            color=discord.Color.teal(),
        )
        embed.set_footer(text=f"{target['region']} · 原驻地：{player['current_city']}")
        await ctx.send(ctx.author.mention, embed=embed)

    @commands.command(name="世界")
    async def world_map(self, ctx):
        from collections import defaultdict
        region_map = defaultdict(list)
        for c in CITIES:
            region_map[c["region"]].append(c["name"])

        embed = discord.Embed(title="✦ 天下城市 ✦", color=discord.Color.teal())
        for region, cities in region_map.items():
            embed.add_field(name=region, value="、".join(cities), inline=False)
        embed.set_footer(text="使用 cat!移动 [城市名] 前往目的地")
        await ctx.send(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(TravelCog(bot))
