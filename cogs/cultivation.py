import asyncio
import random
import time

import discord
from discord.ext import commands

from utils.character import (
    QUESTIONS, calc_stats, roll_spirit_root, SPIRIT_ROOT_SPEED, REALM_LIFESPAN,
    calc_cultivation_gain, years_to_seconds, seconds_to_years,
    AUTO_CULTIVATE_THRESHOLD_YEARS,
)
from utils.realms import (
    cultivation_needed, lifespan_max_for_realm, next_realm,
    roll_breakthrough, apply_failure,
)
from utils.views import MainMenuView, ProfileView
from utils.db import get_conn
from utils.world import CITIES


class CultivationCog(commands.Cog, name="Cultivation"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._creating = set()

    def _get_player(self, discord_id: str):
        with get_conn() as conn:
            return conn.execute(
                "SELECT * FROM players WHERE discord_id = ?", (discord_id,)
            ).fetchone()

    def _settle_time(self, player):
        now = time.time()
        elapsed_years = seconds_to_years(now - player["last_active"])
        new_lifespan = max(0, player["lifespan"] - int(elapsed_years))
        updates = {"lifespan": new_lifespan, "last_active": now, "cultivation": player["cultivation"]}
        cultivating = player["cultivating_until"] and now < player["cultivating_until"]
        if not cultivating and elapsed_years >= AUTO_CULTIVATE_THRESHOLD_YEARS:
            gain = calc_cultivation_gain(
                int(elapsed_years), player["comprehension"], player["spirit_root_type"]
            )
            updates["cultivation"] = player["cultivation"] + gain
        return updates, elapsed_years

    def _apply_updates(self, discord_id: str, updates: dict):
        fields = ", ".join(f"{k} = ?" for k in updates)
        values = list(updates.values()) + [discord_id]
        with get_conn() as conn:
            conn.execute(f"UPDATE players SET {fields} WHERE discord_id = ?", values)
            conn.commit()

    async def _check_dead(self, ctx, player) -> bool:
        if player["lifespan"] <= 0 or player["is_dead"]:
            with get_conn() as conn:
                conn.execute("UPDATE players SET is_dead = 1 WHERE discord_id = ?", (str(ctx.author.id),))
                conn.commit()
            await ctx.send(
                f"{ctx.author.mention} 道友 **{player['name']}** 寿元已尽，魂归天道。\n"
                "尘归尘，土归土，可使用 `cat!创建角色` 重入修仙之路。"
            )
            return True
        return False

    def _can_breakthrough(self, player) -> bool:
        return player["cultivation"] >= cultivation_needed(player["realm"])

    async def send_profile(self, interaction: discord.Interaction):
        uid = str(interaction.user.id)
        player = self._get_player(uid)
        if not player:
            return await interaction.followup.send("尚未踏入修仙之路，请先使用 `cat!创建角色`。")
        updates, _ = self._settle_time(player)
        self._apply_updates(uid, updates)
        player = self._get_player(uid)
        if player["lifespan"] <= 0 or player["is_dead"]:
            with get_conn() as conn:
                conn.execute("UPDATE players SET is_dead = 1 WHERE discord_id = ?", (uid,))
                conn.commit()
            return await interaction.followup.send(
                f"道友 **{player['name']}** 寿元已尽，魂归天道。\n可使用 `cat!创建角色` 重入修仙之路。"
            )
        now = time.time()
        needed = cultivation_needed(player["realm"])
        is_cultivating = bool(player["cultivating_until"] and now < player["cultivating_until"])
        can_bt = self._can_breakthrough(player)
        if is_cultivating:
            remaining = seconds_to_years(player["cultivating_until"] - now)
            status = f"闭关中（还剩 {remaining:.1f} 年）"
        else:
            status = "空闲"
        speed_label = {
            "单灵根": "极快", "双灵根": "较快", "三灵根": "普通",
            "四灵根": "较慢", "五灵根": "迟缓", "变异灵根": "特殊",
        }.get(player["spirit_root_type"], "未知")
        embed = discord.Embed(
            title=f"✦ {player['name']} ✦",
            description=f"{player['gender']}修 · {player['realm']}　｜　{status}　｜　{player['current_city']}",
            color=discord.Color.teal(),
        )
        embed.add_field(name="灵根", value=f"{player['spirit_root_type']}·{player['spirit_root']}（{speed_label}）", inline=False)
        embed.add_field(name="修为", value=f"{player['cultivation']} / {needed}", inline=False)
        embed.add_field(name="寿元", value=f"{player['lifespan']} / {player['lifespan_max']} 年", inline=True)
        embed.add_field(name="灵石", value=player["spirit_stones"], inline=True)
        embed.add_field(name="悟性", value=player["comprehension"], inline=True)
        embed.add_field(name="体魄", value=player["physique"], inline=True)
        embed.add_field(name="机缘", value=player["fortune"], inline=True)
        embed.add_field(name="根骨", value=player["bone"], inline=True)
        embed.add_field(name="神识", value=player["soul"], inline=True)
        virgin_label = ("处男" if player["gender"] == "男" else "处女") if player["is_virgin"] else ("非处男" if player["gender"] == "男" else "非处女")
        embed.add_field(name="身", value=virgin_label, inline=True)
        await interaction.followup.send(
            interaction.user.mention,
            embed=embed,
            view=ProfileView(interaction.user, can_bt, is_cultivating, self)
        )

    async def send_cultivate(self, interaction: discord.Interaction):
        uid = str(interaction.user.id)
        player = self._get_player(uid)
        if not player:
            return await interaction.followup.send("尚未踏入修仙之路。")
        updates, _ = self._settle_time(player)
        self._apply_updates(uid, updates)
        player = self._get_player(uid)
        if player["lifespan"] <= 0 or player["is_dead"]:
            return await interaction.followup.send("道友寿元已尽，无法修炼。")
        now = time.time()
        if player["cultivating_until"] and now < player["cultivating_until"]:
            remaining = seconds_to_years(player["cultivating_until"] - now)
            return await interaction.followup.send(f"道友正在闭关，还剩约 **{remaining:.1f} 年**，可使用 `cat!停止` 提前结束。")
        years = 1
        if player["lifespan"] < years:
            return await interaction.followup.send(f"寿元不足，无法修炼。")
        cultivating_until = now + years_to_seconds(years)
        gain = calc_cultivation_gain(years, player["comprehension"], player["spirit_root_type"])
        new_cultivation = player["cultivation"] + gain
        new_lifespan = player["lifespan"] - years
        with get_conn() as conn:
            conn.execute("""
                UPDATE players SET cultivation = ?, lifespan = ?,
                    cultivating_until = ?, cultivating_years = ?, last_active = ?
                WHERE discord_id = ?
            """, (new_cultivation, new_lifespan, cultivating_until, years, now, uid))
            conn.commit()
        needed = cultivation_needed(player["realm"])
        await interaction.followup.send(
            f"{interaction.user.mention} **{player['name']}** 开始闭关修炼 **1 年**（现实2小时）。\n"
            f"修为进度：{player['cultivation']}/{needed} → {new_cultivation}/{needed}"
        )

    async def send_breakthrough(self, interaction: discord.Interaction):
        uid = str(interaction.user.id)
        player = self._get_player(uid)
        if not player:
            return await interaction.followup.send("尚未踏入修仙之路。")
        updates, _ = self._settle_time(player)
        self._apply_updates(uid, updates)
        player = self._get_player(uid)
        now = time.time()
        if player["cultivating_until"] and now < player["cultivating_until"]:
            return await interaction.followup.send("请先结束闭关再尝试突破。")
        if not self._can_breakthrough(player):
            needed = cultivation_needed(player["realm"])
            return await interaction.followup.send(f"修为尚未圆满，还差 **{needed - player['cultivation']}** 点。")
        nxt = next_realm(player["realm"])
        if not nxt:
            return await interaction.followup.send("道友已至大道巅峰。")
        success, outcome = roll_breakthrough(player["realm"], player["physique"], player["bone"], player["cultivation"])
        if success:
            new_lifespan_max = lifespan_max_for_realm(nxt)
            lifespan_gain = max(0, new_lifespan_max - player["lifespan_max"])
            new_lifespan = min(player["lifespan"] + lifespan_gain, new_lifespan_max)
            with get_conn() as conn:
                conn.execute("""
                    UPDATE players SET realm = ?, cultivation = 0,
                        lifespan = ?, lifespan_max = ?, last_active = ?
                    WHERE discord_id = ?
                """, (nxt, new_lifespan, new_lifespan_max, now, uid))
                conn.commit()
            await interaction.followup.send(
                f"🎉 {interaction.user.mention} **{player['name']}** 突破成功！\n"
                f"**{player['realm']}** ➜ **{nxt}**\n"
                f"寿元上限提升至 {new_lifespan_max} 年，当前寿元 {new_lifespan} 年。"
            )
        else:
            new_cultivation, new_lifespan, fail_msg = apply_failure(player["cultivation"], player["lifespan"], outcome)
            with get_conn() as conn:
                conn.execute("UPDATE players SET cultivation = ?, lifespan = ?, last_active = ? WHERE discord_id = ?",
                             (new_cultivation, new_lifespan, now, uid))
                conn.commit()
            player = self._get_player(uid)
            if player["lifespan"] <= 0:
                with get_conn() as conn:
                    conn.execute("UPDATE players SET is_dead = 1 WHERE discord_id = ?", (uid,))
                    conn.commit()
                return await interaction.followup.send(f"道友 **{player['name']}** 突破失败，{fail_msg}\n寿元耗尽，魂归天道。")
            needed = cultivation_needed(player["realm"])
            await interaction.followup.send(
                f"{interaction.user.mention} **{player['name']}** 突破失败。{fail_msg}\n"
                f"修为：{new_cultivation}/{needed}　寿元剩余：{new_lifespan} 年"
            )

    async def send_stop(self, interaction: discord.Interaction):
        uid = str(interaction.user.id)
        player = self._get_player(uid)
        if not player:
            return await interaction.followup.send("尚未踏入修仙之路。")
        now = time.time()
        if not player["cultivating_until"] or now >= player["cultivating_until"]:
            return await interaction.followup.send("道友当前并未在闭关。")
        elapsed_years = seconds_to_years(now - player["last_active"])
        actual_years = min(int(elapsed_years), player["cultivating_years"])
        gain = calc_cultivation_gain(actual_years, player["comprehension"], player["spirit_root_type"])
        new_cultivation = player["cultivation"] + gain
        new_lifespan = max(0, player["lifespan"] - actual_years)
        with get_conn() as conn:
            conn.execute("""
                UPDATE players SET cultivation = ?, lifespan = ?,
                    cultivating_until = NULL, cultivating_years = NULL, last_active = ?
                WHERE discord_id = ?
            """, (new_cultivation, new_lifespan, now, uid))
            conn.commit()
        needed = cultivation_needed(player["realm"])
        await interaction.followup.send(
            f"{interaction.user.mention} **{player['name']}** 退出闭关。\n"
            f"实际修炼 **{actual_years} 年**，获得修为 **{gain}**。\n"
            f"修为进度：{new_cultivation}/{needed}　寿元剩余：{new_lifespan} 年"
        )

    @commands.command(name="c")
    async def menu(self, ctx):
        uid = str(ctx.author.id)
        player = self._get_player(uid)

        if player and not player["is_dead"]:
            updates, _ = self._settle_time(player)
            self._apply_updates(uid, updates)
            player = self._get_player(uid)

        has_player = player is not None and not player["is_dead"]
        can_bt = has_player and self._can_breakthrough(player)

        embed = discord.Embed(
            title="✦ 修仙长生路 ✦",
            description=(
                "天地初开，灵气充盈，万物皆可修仙。\n"
                "踏入此道，以寿元换修为，历经炼气、筑基、结丹……直至飞升成仙。\n\n"
                "**基本规则**\n"
                "· 现实 2 小时 = 游戏 1 年，寿元随时间流逝\n"
                "· 修炼消耗寿元，换取修为积累\n"
                "· 修为积满可尝试突破，失败有代价\n"
                "· 寿元归零，角色坐化，需重新创建\n"
                "· 超过 2 年未行动，自动进入修炼状态"
            ),
            color=discord.Color.teal(),
        )
        embed.set_footer(text="天道有常，长生路远，望道友珍重。")
        await ctx.send(embed=embed, view=MainMenuView(ctx.author, has_player, can_bt, self))

    @commands.command(name="查看")
    async def view(self, ctx):
        uid = str(ctx.author.id)
        player = self._get_player(uid)

        if not player:
            return await ctx.send(f"{ctx.author.mention} 尚未踏入修仙之路，请先使用 `cat!创建角色`。")

        updates, _ = self._settle_time(player)
        self._apply_updates(uid, updates)
        player = self._get_player(uid)

        if await self._check_dead(ctx, player):
            return

        now = time.time()
        needed = cultivation_needed(player["realm"])
        is_cultivating = bool(player["cultivating_until"] and now < player["cultivating_until"])
        can_bt = self._can_breakthrough(player)

        if is_cultivating:
            remaining = seconds_to_years(player["cultivating_until"] - now)
            status = f"闭关中（还剩 {remaining:.1f} 年）"
        else:
            status = "空闲"

        speed_label = {
            "单灵根": "极快", "双灵根": "较快", "三灵根": "普通",
            "四灵根": "较慢", "五灵根": "迟缓", "变异灵根": "特殊",
        }.get(player["spirit_root_type"], "未知")

        embed = discord.Embed(
            title=f"✦ {player['name']} ✦",
            description=f"{player['gender']}修 · {player['realm']}　｜　{status}　｜　{player['current_city']}",
            color=discord.Color.teal(),
        )
        embed.add_field(name="灵根", value=f"{player['spirit_root_type']}·{player['spirit_root']}（{speed_label}）", inline=False)
        embed.add_field(name="修为", value=f"{player['cultivation']} / {needed}", inline=False)
        embed.add_field(name="寿元", value=f"{player['lifespan']} / {player['lifespan_max']} 年", inline=True)
        embed.add_field(name="灵石", value=player["spirit_stones"], inline=True)
        embed.add_field(name="悟性", value=player["comprehension"], inline=True)
        embed.add_field(name="体魄", value=player["physique"], inline=True)
        embed.add_field(name="机缘", value=player["fortune"], inline=True)
        embed.add_field(name="根骨", value=player["bone"], inline=True)
        embed.add_field(name="神识", value=player["soul"], inline=True)
        virgin_label = ("处男" if player["gender"] == "男" else "处女") if player["is_virgin"] else ("非处男" if player["gender"] == "男" else "非处女")
        embed.add_field(name="身", value=virgin_label, inline=True)

        await ctx.send(
            ctx.author.mention,
            embed=embed,
            view=ProfileView(ctx.author, can_bt, is_cultivating, self)
        )

    @commands.command(name="修炼")
    async def cultivate(self, ctx, years: int = 1):
        uid = str(ctx.author.id)
        player = self._get_player(uid)

        if not player:
            return await ctx.send(f"{ctx.author.mention} 尚未踏入修仙之路，请先使用 `cat!创建角色`。")

        updates, _ = self._settle_time(player)
        self._apply_updates(uid, updates)
        player = self._get_player(uid)

        if await self._check_dead(ctx, player):
            return

        now = time.time()

        if player["cultivating_until"] and now < player["cultivating_until"]:
            remaining = seconds_to_years(player["cultivating_until"] - now)
            return await ctx.send(
                f"{ctx.author.mention} 道友正在闭关修炼，还剩约 **{remaining:.1f} 年**，"
                "可使用 `cat!停止` 提前结束。"
            )

        if years < 1 or years > 100:
            return await ctx.send("修炼年数需在 1 至 100 之间。")

        if player["lifespan"] < years:
            return await ctx.send(
                f"{ctx.author.mention} 寿元不足，剩余寿元 **{player['lifespan']} 年**，"
                f"无法修炼 {years} 年。"
            )

        cultivating_until = now + years_to_seconds(years)
        gain = calc_cultivation_gain(years, player["comprehension"], player["spirit_root_type"])
        new_cultivation = player["cultivation"] + gain
        new_lifespan = player["lifespan"] - years

        with get_conn() as conn:
            conn.execute("""
                UPDATE players SET
                    cultivation = ?, lifespan = ?,
                    cultivating_until = ?, cultivating_years = ?,
                    last_active = ?
                WHERE discord_id = ?
            """, (new_cultivation, new_lifespan, cultivating_until, years, now, uid))
            conn.commit()

        needed = cultivation_needed(player["realm"])
        await ctx.send(
            f"{ctx.author.mention} **{player['name']}** 开始闭关修炼 **{years} 年**。\n"
            f"预计现实时间 **{years * 2} 小时**后结束。\n"
            f"修为进度：{player['cultivation']}/{needed} → {new_cultivation}/{needed}"
        )

    @commands.command(name="停止")
    async def stop_cultivate(self, ctx):
        uid = str(ctx.author.id)
        player = self._get_player(uid)

        if not player:
            return await ctx.send(f"{ctx.author.mention} 尚未踏入修仙之路。")

        now = time.time()

        if not player["cultivating_until"] or now >= player["cultivating_until"]:
            return await ctx.send(f"{ctx.author.mention} 道友当前并未在闭关。")

        elapsed_years = seconds_to_years(now - player["last_active"])
        actual_years = min(int(elapsed_years), player["cultivating_years"])
        gain = calc_cultivation_gain(actual_years, player["comprehension"], player["spirit_root_type"])
        new_cultivation = player["cultivation"] + gain
        new_lifespan = max(0, player["lifespan"] - actual_years)

        with get_conn() as conn:
            conn.execute("""
                UPDATE players SET
                    cultivation = ?, lifespan = ?,
                    cultivating_until = NULL, cultivating_years = NULL,
                    last_active = ?
                WHERE discord_id = ?
            """, (new_cultivation, new_lifespan, now, uid))
            conn.commit()

        needed = cultivation_needed(player["realm"])
        await ctx.send(
            f"{ctx.author.mention} **{player['name']}** 退出闭关。\n"
            f"实际修炼 **{actual_years} 年**，获得修为 **{gain}**。\n"
            f"修为进度：{new_cultivation}/{needed}　寿元剩余：{new_lifespan} 年"
        )

    @commands.command(name="突破")
    async def breakthrough(self, ctx):
        uid = str(ctx.author.id)
        player = self._get_player(uid)

        if not player:
            return await ctx.send(f"{ctx.author.mention} 尚未踏入修仙之路，请先使用 `cat!创建角色`。")

        updates, _ = self._settle_time(player)
        self._apply_updates(uid, updates)
        player = self._get_player(uid)

        if await self._check_dead(ctx, player):
            return

        now = time.time()
        if player["cultivating_until"] and now < player["cultivating_until"]:
            return await ctx.send(f"{ctx.author.mention} 请先结束闭关再尝试突破。")

        if not self._can_breakthrough(player):
            needed = cultivation_needed(player["realm"])
            return await ctx.send(
                f"{ctx.author.mention} 修为尚未圆满，还差 **{needed - player['cultivation']}** 点。"
            )

        nxt = next_realm(player["realm"])
        if not nxt:
            return await ctx.send(f"{ctx.author.mention} 道友已至大道巅峰，天地间再无更高境界。")

        success, outcome = roll_breakthrough(
            player["realm"], player["physique"], player["bone"], player["cultivation"]
        )

        if success:
            new_lifespan_max = lifespan_max_for_realm(nxt)
            lifespan_gain = max(0, new_lifespan_max - player["lifespan_max"])
            new_lifespan = min(player["lifespan"] + lifespan_gain, new_lifespan_max)

            with get_conn() as conn:
                conn.execute("""
                    UPDATE players SET
                        realm = ?, cultivation = 0,
                        lifespan = ?, lifespan_max = ?,
                        last_active = ?
                    WHERE discord_id = ?
                """, (nxt, new_lifespan, new_lifespan_max, now, uid))
                conn.commit()

            await ctx.send(
                f"🎉 {ctx.author.mention} **{player['name']}** 突破成功！\n"
                f"**{player['realm']}** ➜ **{nxt}**\n"
                f"寿元上限提升至 {new_lifespan_max} 年，当前寿元 {new_lifespan} 年。"
            )
        else:
            new_cultivation, new_lifespan, fail_msg = apply_failure(
                player["cultivation"], player["lifespan"], outcome
            )
            with get_conn() as conn:
                conn.execute("""
                    UPDATE players SET
                        cultivation = ?, lifespan = ?, last_active = ?
                    WHERE discord_id = ?
                """, (new_cultivation, new_lifespan, now, uid))
                conn.commit()

            player = self._get_player(uid)
            if await self._check_dead(ctx, player):
                return

            needed = cultivation_needed(player["realm"])
            await ctx.send(
                f"{ctx.author.mention} **{player['name']}** 突破失败。{fail_msg}\n"
                f"修为：{new_cultivation}/{needed}　寿元剩余：{new_lifespan} 年"
            )

    @commands.command(name="创建角色")
    async def create_character(self, ctx):
        uid = str(ctx.author.id)

        if self._get_player(uid):
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

            with get_conn() as conn:
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
            embed.add_field(name="悟性", value=stats["comprehension"], inline=True)
            embed.add_field(name="体魄", value=stats["physique"], inline=True)
            embed.add_field(name="机缘", value=stats["fortune"], inline=True)
            embed.add_field(name="根骨", value=stats["bone"], inline=True)
            embed.add_field(name="神识", value=stats["soul"], inline=True)
            embed.add_field(name="寿元", value=f"{lifespan} 年", inline=True)
            embed.add_field(name="灵石", value=stats["spirit_stones"], inline=True)
            embed.set_footer(text="天道有常，长生路远，望道友珍重。")

            await ctx.send(f"天地感应，灵根初现……\n{ctx.author.mention}", embed=embed)

        except asyncio.TimeoutError:
            await ctx.send(f"{ctx.author.mention} 响应超时，创建已取消。")
        finally:
            self._creating.discard(uid)


async def setup(bot):
    await bot.add_cog(CultivationCog(bot))
