import discord
from discord.ext import commands

from utils.config import COMMAND_PREFIX
from utils.db import get_conn
from utils.world import CITIES
from utils.character import seconds_to_years
from utils.player import get_player, is_defending


class TravelCog(commands.Cog, name="Travel"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.hybrid_command(name="移动", aliases=["yd"], description="前往指定城市或秘地")
    async def travel(self, ctx, *, city_name: str = None):
        uid = str(ctx.author.id)
        player = get_player(uid)

        if not player:
            return await ctx.send(f"{ctx.author.mention} 尚未踏入修仙之路，请先使用 `{COMMAND_PREFIX}创建角色`。")
        if player["is_dead"]:
            return await ctx.send(f"{ctx.author.mention} 道友已坐化。")

        # Main (menu) cog provides "返回主菜单" behaviors for views.
        menu_cog = self.bot.cogs.get("Cultivation") or self

        regions = ["东域", "南域", "西域", "北域", "中州"]
        arg = (city_name or "").strip()

        # No args: open travel menu and show all cities grouped by region.
        if not arg:
            from collections import defaultdict
            from utils.views.travel import TravelRegionView

            region_map: dict[str, list[dict]] = defaultdict(list)
            for c in CITIES:
                region_map[c["region"]].append(c)

            embed = discord.Embed(
                title="✦ 移动 · 目的地一览 ✦",
                description="请选择大洲进入城市选择菜单，或直接使用指令前往目的地。",
                color=discord.Color.teal(),
            )
            for region in regions:
                lines = "\n".join(f"**{c['name']}** — {c['desc']}" for c in region_map.get(region, []))
                embed.add_field(name=f"【{region}】", value=lines or "暂无城市。", inline=False)
            embed.set_footer(text=f"用法：{COMMAND_PREFIX}移动 [城市名] / {COMMAND_PREFIX}移动 [大洲名]")

            return await ctx.send(
                ctx.author.mention,
                embed=embed,
                view=TravelRegionView(ctx.author, menu_cog),
            )

        # If input is a region (大洲), open the city-selection submenu.
        if arg in regions:
            from utils.views.travel import TravelCityView
            from utils.world import cities_by_region

            cities = cities_by_region(arg)
            embed = discord.Embed(title=f"✦ {arg} · 选择目的地 ✦", color=discord.Color.teal())
            for c in cities:
                embed.add_field(name=c["name"], value=c["desc"], inline=False)
            return await ctx.send(
                ctx.author.mention,
                embed=embed,
                view=TravelCityView(ctx.author, menu_cog, cities),
            )

        # Optional: allow opening the secret-region submenu directly.
        if arg == "秘地":
            from utils.realms import get_realm_index
            from utils.world import SPECIAL_REGIONS
            from utils.views.travel import TravelSecretView

            player_idx = get_realm_index(player["realm"])
            embed = discord.Embed(title="✦ 秘地 · 选择目的地 ✦", color=discord.Color.gold())
            for r in SPECIAL_REGIONS:
                req_idx = get_realm_index(r["min_realm"])
                locked = player_idx < req_idx
                tag = f"🔒 需 {r['min_realm']}" if locked else f"[{r['type']}]"
                embed.add_field(name=f"{r['name']}  {tag}", value=r["desc"], inline=False)
            return await ctx.send(
                ctx.author.mention,
                embed=embed,
                view=TravelSecretView(ctx.author, menu_cog, player_idx),
            )

        import time
        now = time.time()
        if player["cultivating_until"] and now < player["cultivating_until"]:
            remaining = seconds_to_years(player["cultivating_until"] - now)
            return await ctx.send(
                f"{ctx.author.mention} 道友正在闭关，无法移动。还剩约 **{remaining:.1f} 年**，可使用 `{COMMAND_PREFIX}停止` 提前结束。"
            )
        if player["gathering_until"] and now < player["gathering_until"]:
            remaining = seconds_to_years(player["gathering_until"] - now)
            return await ctx.send(
                f"{ctx.author.mention} 道友正在采集中，无法移动。还剩约 **{remaining:.1f} 年**。"
            )

        from utils.world import get_city, get_region
        from utils.realms import get_realm_index as _get_realm_idx
        target = get_city(arg)
        if not target:
            secret = get_region(arg)
            if secret:
                player_idx = _get_realm_idx(player["realm"])
                req_idx = _get_realm_idx(secret["min_realm"])
                if player_idx < req_idx:
                    return await ctx.send(
                        f"{ctx.author.mention} 境界不足，前往 **{secret['name']}** 需达到 **{secret['min_realm']}**。"
                    )
                target = {"name": secret["name"], "desc": secret["desc"], "region": f"秘地 · {secret['type']}"}
            else:
                matches = [c for c in CITIES if arg in c["name"]]
                if len(matches) == 1:
                    target = matches[0]
                elif len(matches) > 1:
                    names = "、".join(c["name"] for c in matches)
                    return await ctx.send(f"{ctx.author.mention} 找到多个匹配城市：{names}，请输入完整城市名。")
                else:
                    return await ctx.send(f"{ctx.author.mention} 未找到城市「{arg}」，请检查名称是否正确。")

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

    @commands.hybrid_command(name="世界", aliases=["sj"], description="查看天下城市与区域分布")
    async def world_map(self, ctx):
        from collections import defaultdict
        region_map = defaultdict(list)
        for c in CITIES:
            region_map[c["region"]].append(c["name"])

        embed = discord.Embed(title="✦ 天下城市 ✦", color=discord.Color.teal())
        for region, cities in region_map.items():
            embed.add_field(name=region, value="、".join(cities), inline=False)
        embed.set_footer(text=f"使用 {COMMAND_PREFIX}移动 [城市名] 前往目的地")
        await ctx.send(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(TravelCog(bot))
