import json
import time

import discord
from discord.ext import commands

from utils.db import get_conn
from utils.sects import SECTS, TECHNIQUES, check_requirements, get_technique_cost, next_stage, calc_technique_stat_bonus, TECHNIQUE_STAGES
from utils.character import years_to_seconds, seconds_to_years


def _parse_techniques(raw) -> list:
    data = json.loads(raw or "[]")
    result = []
    for item in data:
        if isinstance(item, str):
            result.append({"name": item, "grade": TECHNIQUES.get(item, {}).get("grade", "黄级上品"), "stage": "入门", "equipped": True})
        elif isinstance(item, dict):
            result.append(item)
    return result


def _save_techniques(uid: str, techniques: list):
    with get_conn() as conn:
        conn.execute("UPDATE players SET techniques = ? WHERE discord_id = ?",
                     (json.dumps(techniques, ensure_ascii=False), uid))
        conn.commit()


class SectCog(commands.Cog, name="Sect"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    def _get_player(self, discord_id: str):
        with get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM players WHERE discord_id = ?", (discord_id,)
            ).fetchone()
            return dict(row) if row else None

    @commands.hybrid_command(name="宗门列表", aliases=["zmlb"], description="查看当前可见的正道与邪道宗门")
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

    @commands.hybrid_command(name="宗门详情", aliases=["zmxq"], description="查看指定宗门的介绍与入门条件")
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
            tech_lines.append(f"**{t}**（{info.get('grade', '?')} · {info.get('type', '未知')}）")

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

    @commands.hybrid_command(name="加入宗门", aliases=["jrzm"], description="尝试加入指定宗门")
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

        techniques = _parse_techniques(player["techniques"])
        existing_names = {t["name"] for t in techniques}
        new_techs = []
        for t_name in sect["techniques"]:
            if t_name not in existing_names:
                new_techs.append(t_name)
                techniques.append({
                    "name": t_name,
                    "grade": TECHNIQUES.get(t_name, {}).get("grade", "黄级上品"),
                    "stage": "入门",
                    "equipped": len([x for x in techniques if x.get("equipped")]) < 5,
                })

        with get_conn() as conn:
            conn.execute(
                "UPDATE players SET sect = ?, sect_rank = ?, techniques = ? WHERE discord_id = ?",
                (name, "外门弟子", json.dumps(techniques, ensure_ascii=False), uid)
            )
            conn.commit()

        tech_str = "、".join(f"**{t}**" for t in new_techs) if new_techs else "（已全部习得）"
        await ctx.send(
            f"{ctx.author.mention} 道友 **{player['name']}** 成功加入 **{name}**，成为外门弟子。\n"
            f"获得功法：{tech_str}"
        )

    @commands.hybrid_command(name="退出宗门", aliases=["qtzm"], description="离开当前所在宗门")
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

    @commands.hybrid_command(name="门派功法", aliases=["mpgf"], description="从宗门处查看或领取门派传承功法")
    async def sect_techniques(self, ctx):
        uid = str(ctx.author.id)
        player = self._get_player(uid)

        if not player:
            return await ctx.send(f"{ctx.author.mention} 尚未踏入修仙之路。")
        if not player["sect"]:
            return await ctx.send(f"{ctx.author.mention} 道友尚未加入任何宗门。")

        sect = SECTS.get(player["sect"])
        if not sect:
            return await ctx.send("宗门数据异常。")

        techniques = _parse_techniques(player["techniques"])
        existing_names = {t["name"] for t in techniques}
        new_techs = []
        for t_name in sect["techniques"]:
            if t_name not in existing_names:
                new_techs.append(t_name)
                techniques.append({
                    "name": t_name,
                    "grade": TECHNIQUES.get(t_name, {}).get("grade", "黄级上品"),
                    "stage": "入门",
                    "equipped": len([x for x in techniques if x.get("equipped")]) < 5,
                })

        if new_techs:
            _save_techniques(uid, techniques)
            tech_str = "、".join(f"**{t}**" for t in new_techs)
            await ctx.send(f"{ctx.author.mention} 从 **{player['sect']}** 领悟了新功法：{tech_str}")
        else:
            lines = []
            for t_name in sect["techniques"]:
                info = TECHNIQUES.get(t_name, {})
                lines.append(f"**{t_name}**（{info.get('grade', '?')} · {info.get('type', '未知')}）")
            embed = discord.Embed(
                title=f"✦ {player['sect']} 传承功法 ✦",
                description="\n".join(lines),
                color=discord.Color.teal(),
            )
            embed.set_footer(text="已全部习得。")
            await ctx.send(embed=embed)

    @commands.hybrid_command(name="我的功法", aliases=["wdgf"], description="查看并管理自己已习得的功法")
    async def my_techniques(self, ctx):
        uid = str(ctx.author.id)
        player = self._get_player(uid)

        if not player:
            return await ctx.send(f"{ctx.author.mention} 尚未踏入修仙之路。")

        techniques = _parse_techniques(player["techniques"])
        if not techniques:
            return await ctx.send(f"{ctx.author.mention} 道友尚未习得任何功法。")

        from utils.views.techniques import TechniquesView, _build_techniques_embed
        cultivation_cog = self.bot.cogs.get("Cultivation")
        embed = _build_techniques_embed(player)
        view = TechniquesView(ctx.author, cultivation_cog or self)
        await ctx.send(ctx.author.mention, embed=embed, view=view)

    @commands.hybrid_command(name="装备功法", aliases=["zbgf"], description="装备或卸下一门已习得的功法")
    async def equip_technique(self, ctx, *, name: str):
        uid = str(ctx.author.id)
        player = self._get_player(uid)

        if not player:
            return await ctx.send(f"{ctx.author.mention} 尚未踏入修仙之路。")

        techniques = _parse_techniques(player["techniques"])
        target = next((t for t in techniques if t["name"] == name), None)
        if not target:
            return await ctx.send(f"{ctx.author.mention} 未习得功法「{name}」。")

        if target.get("equipped"):
            target["equipped"] = False
            _save_techniques(uid, techniques)
            return await ctx.send(f"{ctx.author.mention} 已卸下功法「**{name}**」。")

        equipped_count = sum(1 for t in techniques if t.get("equipped"))
        if equipped_count >= 5:
            return await ctx.send(f"{ctx.author.mention} 已装备5本功法，请先卸下一本再装备新的。")

        target["equipped"] = True
        _save_techniques(uid, techniques)
        await ctx.send(f"{ctx.author.mention} 已装备功法「**{name}**」。")

    @commands.hybrid_command(name="修炼功法", aliases=["xlgf"], description="消耗时间提升指定功法的境界")
    async def train_technique(self, ctx, *, name: str):
        uid = str(ctx.author.id)
        player = self._get_player(uid)

        if not player:
            return await ctx.send(f"{ctx.author.mention} 尚未踏入修仙之路。")
        if player["is_dead"]:
            return await ctx.send(f"{ctx.author.mention} 道友已坐化。")

        now = time.time()
        if player.get("cultivating_until") and now < player["cultivating_until"]:
            return await ctx.send(f"{ctx.author.mention} 道友正在闭关，无法修炼功法。")

        techniques = _parse_techniques(player["techniques"])
        target = next((t for t in techniques if t["name"] == name), None)
        if not target:
            return await ctx.send(f"{ctx.author.mention} 未习得功法「{name}」。")

        current_stage = target.get("stage", "入门")
        nxt = next_stage(current_stage)
        if not nxt:
            return await ctx.send(f"{ctx.author.mention} 「{name}」已达最高阶段【破限】，无法继续修炼。")

        stones_cost, years_cost = get_technique_cost(name, current_stage)

        if player["spirit_stones"] < stones_cost:
            return await ctx.send(
                f"{ctx.author.mention} 灵石不足。\n"
                f"「{name}」{current_stage} → {nxt} 需要 **{stones_cost} 灵石**，"
                f"你当前只有 **{player['spirit_stones']} 灵石**。"
            )

        if player["lifespan"] < years_cost:
            return await ctx.send(
                f"{ctx.author.mention} 寿元不足。修炼「{name}」需消耗 **{years_cost} 年** 寿元。"
            )

        target["stage"] = nxt
        cultivating_until = now + years_to_seconds(years_cost)
        new_stones = player["spirit_stones"] - stones_cost
        new_lifespan = player["lifespan"] - years_cost

        with get_conn() as conn:
            conn.execute(
                "UPDATE players SET techniques = ?, spirit_stones = ?, lifespan = ?, "
                "cultivating_until = ?, cultivating_years = ?, last_active = ? WHERE discord_id = ?",
                (json.dumps(techniques, ensure_ascii=False), new_stones, new_lifespan,
                 cultivating_until, years_cost, now, uid)
            )
            conn.commit()

        info = TECHNIQUES.get(name, {})
        grade = info.get("grade", "?")
        real_hours = years_cost * 2
        embed = discord.Embed(
            title="✦ 功法修炼 ✦",
            description=(
                f"**{name}**（{grade}）\n"
                f"{current_stage} ➜ **{nxt}**\n\n"
                f"消耗灵石：**{stones_cost}**　剩余：{new_stones}\n"
                f"消耗寿元：**{years_cost} 年**　剩余：{new_lifespan} 年\n"
                f"修炼时间：现实 **{real_hours} 小时**\n\n"
                "闭关结束后将收到通知。"
            ),
            color=discord.Color.teal(),
        )
        await ctx.send(ctx.author.mention, embed=embed)

    @commands.hybrid_command(name="功法属性", aliases=["gfsx"], description="查看功法带来的属性加成与修炼进度")
    async def technique_stats(self, ctx):
        uid = str(ctx.author.id)
        player = self._get_player(uid)

        if not player:
            return await ctx.send(f"{ctx.author.mention} 尚未踏入修仙之路。")

        from utils.views.techniques import _build_stats_embed
        embed = _build_stats_embed(player)
        await ctx.send(embed=embed)


async def setup(bot):
    await bot.add_cog(SectCog(bot))
