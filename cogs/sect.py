import json
import time

import discord
from discord.ext import commands

from utils.db import get_conn
from utils.sects import SECTS, TECHNIQUES, check_requirements


class SectCog(commands.Cog, name="Sect"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    def _get_player(self, discord_id: str):
        with get_conn() as conn:
            return conn.execute(
                "SELECT * FROM players WHERE discord_id = ?", (discord_id,)
            ).fetchone()

    @commands.command(name="宗门列表")
    async def sect_list(self, ctx):
        normal = {k: v for k, v in SECTS.items() if v["alignment"] != "隐世"}
        embed = discord.Embed(title="✦ 天下宗门 ✦", color=discord.Color.teal())

        for alignment in ["正道", "邪道"]:
            lines = []
            for name, data in normal.items():
                if data["alignment"] == alignment:
                    lines.append(f"**{name}** · {data['location']}\n{data['desc']}")
            embed.add_field(name=f"── {alignment} ──", value="\n\n".join(lines), inline=False)

        embed.set_footer(text="隐世宗门不在此列，需缘分方可得见。")
        await ctx.send(embed=embed)

    @commands.command(name="宗门详情")
    async def sect_detail(self, ctx, *, name: str):
        sect = SECTS.get(name)
        if not sect:
            return await ctx.send(f"未找到宗门「{name}」。")
        if sect["alignment"] == "隐世":
            return await ctx.send("此宗门行踪隐秘，无从查阅。")

        req = sect["req"]
        req_lines = []
        if req["min_realm"]:
            req_lines.append(f"境界：{req['min_realm']} 以上")
        if req["spirit_roots"]:
            req_lines.append(f"灵根：含 {'或'.join(req['spirit_roots'])} 属性")
        if req["single_root"]:
            req_lines.append("灵根：单灵根")
        if req["min_stat"]:
            stat_names = {"comprehension": "悟性", "physique": "体魄",
                          "fortune": "机缘", "bone": "根骨", "soul": "神识"}
            for stat, val in req["min_stat"].items():
                req_lines.append(f"{stat_names.get(stat, stat)}：{val} 以上")
        if req["min_fortune"]:
            req_lines.append(f"机缘：{req['min_fortune']} 以上")
        if not req_lines:
            req_lines.append("无特殊要求")

        tech_lines = []
        for t in sect["techniques"]:
            info = TECHNIQUES.get(t, {})
            tech_lines.append(f"**{t}**（{info.get('type', '未知')}）")

        embed = discord.Embed(
            title=f"✦ {name} ✦",
            description=sect["desc"],
            color=discord.Color.teal(),
        )
        embed.add_field(name="阵营", value=sect["alignment"], inline=True)
        embed.add_field(name="驻地", value=sect["location"], inline=True)
        embed.add_field(name="入门要求", value="\n".join(req_lines), inline=False)
        embed.add_field(name="传承功法", value="\n".join(tech_lines), inline=False)
        await ctx.send(embed=embed)

    @commands.command(name="加入宗门")
    async def join_sect(self, ctx, *, name: str):
        uid = str(ctx.author.id)
        player = self._get_player(uid)

        if not player:
            return await ctx.send(f"{ctx.author.mention} 尚未踏入修仙之路。")
        if player["is_dead"]:
            return await ctx.send(f"{ctx.author.mention} 道友已坐化。")
        if player["sect"]:
            return await ctx.send(f"{ctx.author.mention} 道友已在 **{player['sect']}** 门下，请先退出宗门。")

        sect = SECTS.get(name)
        if not sect:
            return await ctx.send(f"未找到宗门「{name}」。")

        ok, msg = check_requirements(dict(player), name)
        if not ok:
            return await ctx.send(f"{ctx.author.mention} 无法加入 **{name}**：{msg}")

        starter = sect["techniques"][0]
        techniques = json.loads(player["techniques"] or "[]")
        if starter not in techniques:
            techniques.append(starter)

        with get_conn() as conn:
            conn.execute(
                "UPDATE players SET sect = ?, sect_rank = ?, techniques = ? WHERE discord_id = ?",
                (name, "外门弟子", json.dumps(techniques, ensure_ascii=False), uid)
            )
            conn.commit()

        await ctx.send(
            f"{ctx.author.mention} 道友 **{player['name']}** 成功加入 **{name}**，成为外门弟子。\n"
            f"获得入门功法：**{starter}**"
        )

    @commands.command(name="退出宗门")
    async def leave_sect(self, ctx):
        uid = str(ctx.author.id)
        player = self._get_player(uid)

        if not player:
            return await ctx.send(f"{ctx.author.mention} 尚未踏入修仙之路。")
        if not player["sect"]:
            return await ctx.send(f"{ctx.author.mention} 道友并未加入任何宗门。")

        sect_name = player["sect"]
        with get_conn() as conn:
            conn.execute(
                "UPDATE players SET sect = NULL, sect_rank = NULL WHERE discord_id = ?", (uid,)
            )
            conn.commit()

        await ctx.send(f"{ctx.author.mention} 道友已离开 **{sect_name}**，功法仍在，但宗门资源不再可用。")

    @commands.command(name="我的功法")
    async def my_techniques(self, ctx):
        uid = str(ctx.author.id)
        player = self._get_player(uid)

        if not player:
            return await ctx.send(f"{ctx.author.mention} 尚未踏入修仙之路。")

        techniques = json.loads(player["techniques"] or "[]")
        if not techniques:
            return await ctx.send(f"{ctx.author.mention} 道友尚未习得任何功法。")

        lines = []
        for t in techniques:
            info = TECHNIQUES.get(t, {})
            lines.append(f"**{t}**（{info.get('type', '未知')}）")

        embed = discord.Embed(
            title=f"✦ {player['name']} 的功法 ✦",
            description="\n".join(lines),
            color=discord.Color.teal(),
        )
        if player["sect"]:
            embed.set_footer(text=f"宗门：{player['sect']} · {player['sect_rank']}")
        await ctx.send(embed=embed)


async def setup(bot):
    await bot.add_cog(SectCog(bot))
