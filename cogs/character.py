import asyncio
import random
import time

import discord
from discord.ext import commands

from utils.character import (
    QUESTIONS, calc_stats, roll_spirit_root, REALM_LIFESPAN,
    years_to_seconds, seconds_to_years,
)
from utils.db import get_conn
from utils.world import CITIES
from utils.player import get_player


class CharacterCog(commands.Cog, name="Character"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._creating: set[str] = set()

    def _calc_rebirth_bonus(self, player: dict) -> dict:
        rebirth_count = player.get("rebirth_count", 0)
        mult = 1 + rebirth_count * 0.5
        return {
            "comprehension": max(0, int((player.get("comprehension", 5) - 5) * 0.3 * mult)),
            "physique":      max(0, int((player.get("physique", 5) - 5) * 0.3 * mult)),
            "fortune":       max(0, int((player.get("fortune", 5) - 5) * 0.3 * mult)),
            "bone":          max(0, int((player.get("bone", 5) - 5) * 0.3 * mult)),
            "soul":          max(0, int((player.get("soul", 5) - 5) * 0.3 * mult)),
        }

    @commands.command(name="创建角色")
    async def create_character(self, ctx):
        uid = str(ctx.author.id)
        existing = get_player(uid)
        if existing and not existing["is_dead"]:
            return await ctx.send(f"{ctx.author.mention} 道友已踏入修仙之路，无需重新创建。")
        if uid in self._creating:
            return await ctx.send(f"{ctx.author.mention} 正在创建中，请完成当前流程。")

        self._creating.add(uid)

        def check(m):
            return m.author == ctx.author and m.channel == ctx.channel

        try:
            await ctx.send(f"{ctx.author.mention} 道友，请问你是男修还是女修？\nA. 男修\nB. 女修")
            msg = await self.bot.wait_for("message", check=check, timeout=60)
            gender_choice = msg.content.strip().upper()
            if gender_choice not in ("A", "B"):
                return await ctx.send("输入有误，创建已取消。")
            gender = "男" if gender_choice == "A" else "女"

            answers = {}
            for i, q in enumerate(QUESTIONS):
                options_text = "\n".join(f"{k}. {v[0]}" for k, v in q["options"].items())
                await ctx.send(f"**第{i+1}问：{q['text']}**\n{options_text}")
                msg = await self.bot.wait_for("message", check=check, timeout=60)
                choice = msg.content.strip().upper()
                if choice not in q["options"]:
                    return await ctx.send("输入有误，创建已取消。")
                answers[i] = choice

            await ctx.send("请赐下你的道号：")
            msg = await self.bot.wait_for("message", check=check, timeout=60)
            name = msg.content.strip()
            if not name or len(name) > 16:
                return await ctx.send("道号无效，创建已取消。")

            stats = calc_stats(answers)
            spirit_root, root_type = roll_spirit_root()
            lifespan = REALM_LIFESPAN["炼气期"]
            now = time.time()
            starting_city = random.choice(CITIES)["name"]

            old = get_player(uid)
            rebirth_bonus = {}
            with get_conn() as conn:
                if old and old["is_dead"]:
                    rebirth_bonus = self._calc_rebirth_bonus(old) if (old.get("sect") == "仙葬谷" or old.get("has_bahongchen")) else {}
                    conn.execute("""
                        UPDATE players SET
                            name=?, gender=?, spirit_root=?, spirit_root_type=?,
                            comprehension=?, physique=?, fortune=?, bone=?, soul=?,
                            lifespan=?, lifespan_max=?, spirit_stones=?,
                            cultivation=0, realm='炼气期1层',
                            cultivating_until=NULL, cultivating_years=NULL,
                            is_dead=0, is_virgin=1, rebirth_count=rebirth_count,
                            sect=NULL, sect_rank=NULL, techniques='[]',
                            cultivation_overflow=0, current_city=?,
                            explore_count=0, explore_reset_year=0,
                            reputation=0, cave=NULL,
                            active_quest=NULL, quest_due=NULL,
                            gathering_until=NULL, gathering_type=NULL,
                            created_at=?, last_active=?
                        WHERE discord_id=?
                    """, (
                        name, gender, spirit_root, root_type,
                        stats["comprehension"] + rebirth_bonus.get("comprehension", 0),
                        stats["physique"] + rebirth_bonus.get("physique", 0),
                        stats["fortune"] + rebirth_bonus.get("fortune", 0),
                        stats["bone"] + rebirth_bonus.get("bone", 0),
                        stats["soul"] + rebirth_bonus.get("soul", 0),
                        lifespan, lifespan, stats["spirit_stones"],
                        starting_city, now, now, uid,
                    ))
                else:
                    conn.execute("""
                        INSERT INTO players (
                            discord_id, name, gender, spirit_root, spirit_root_type,
                            comprehension, physique, fortune, bone, soul,
                            lifespan, lifespan_max, spirit_stones,
                            created_at, last_active, current_city
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        uid, name, gender, spirit_root, root_type,
                        stats["comprehension"], stats["physique"],
                        stats["fortune"], stats["bone"], stats["soul"],
                        lifespan, lifespan, stats["spirit_stones"],
                        now, now, starting_city,
                    ))
                conn.commit()

            speed_label = {
                "单灵根": "极快", "双灵根": "较快", "三灵根": "普通",
                "四灵根": "较慢", "五灵根": "迟缓", "变异灵根": "特殊",
            }[root_type]

            embed = discord.Embed(
                title=f"✦ {name} ✦",
                description=f"{gender}修 · 炼气期1层 · {starting_city}",
                color=discord.Color.teal(),
            )
            embed.add_field(name="灵根", value=f"{root_type}·{spirit_root}（修炼速度：{speed_label}）", inline=False)
            embed.add_field(name="悟性", value=stats["comprehension"] + rebirth_bonus.get("comprehension", 0), inline=True)
            embed.add_field(name="体魄", value=stats["physique"] + rebirth_bonus.get("physique", 0), inline=True)
            embed.add_field(name="机缘", value=stats["fortune"] + rebirth_bonus.get("fortune", 0), inline=True)
            embed.add_field(name="根骨", value=stats["bone"] + rebirth_bonus.get("bone", 0), inline=True)
            embed.add_field(name="神识", value=stats["soul"] + rebirth_bonus.get("soul", 0), inline=True)
            embed.add_field(name="寿元", value=f"{lifespan} 年", inline=True)
            embed.add_field(name="灵石", value=stats["spirit_stones"], inline=True)
            if rebirth_bonus and any(v > 0 for v in rebirth_bonus.values()):
                bonus_str = "  ".join(f"{k} +{v}" for k, v in rebirth_bonus.items() if v > 0)
                embed.add_field(name="✨ 轮回感悟", value=bonus_str, inline=False)
            embed.set_footer(text="天道有常，长生路远，望道友珍重。")
            await ctx.send(f"天地感应，灵根初现……\n{ctx.author.mention}", embed=embed)

        except asyncio.TimeoutError:
            await ctx.send(f"{ctx.author.mention} 响应超时，创建已取消。")
        finally:
            self._creating.discard(uid)

    @commands.command(name="解散队伍")
    async def disband_party(self, ctx):
        from utils.views.party import disband_party
        msg = await disband_party(str(ctx.author.id), self.bot)
        await ctx.send(f"{ctx.author.mention} {msg}")

    @commands.command(name="help")
    async def help_cmd(self, ctx):
        import json
        uid = str(ctx.author.id)
        player = get_player(uid)
        has_dual = False
        if player:
            has_dual = any(
                (t if isinstance(t, str) else t.get("name", "")) == "双修功法"
                for t in json.loads(player.get("techniques") or "[]")
            )
        from utils.views.menu import _build_menu_embed
        await ctx.send(ctx.author.mention, embed=_build_menu_embed(has_dual))


async def setup(bot: commands.Bot):
    await bot.add_cog(CharacterCog(bot))
