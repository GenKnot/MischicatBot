import asyncio
import random
import time

import discord
from discord.ext import commands, tasks

from utils.character import (
    QUESTIONS, calc_stats, roll_spirit_root, SPIRIT_ROOT_SPEED, REALM_LIFESPAN,
    calc_cultivation_gain, years_to_seconds, seconds_to_years,
    AUTO_CULTIVATE_THRESHOLD_YEARS, get_cultivation_bonus,
    RESIDENCE_PRICE_NORMAL, RESIDENCE_PRICE_CENTRAL, CAVE_PRICE,
    REPUTATION_RESIDENCE, REPUTATION_CAVE,
)
from utils.realms import (
    cultivation_needed, lifespan_max_for_realm, next_realm,
    roll_breakthrough, apply_failure,
)
from utils.views import MainMenuView, ProfileView, CultivateView, ClaimCultivationView, DualCultivateInviteView, YinYangView, _build_menu_embed
from utils.db import get_conn
from utils.world import CITIES


class CultivationCog(commands.Cog, name="Cultivation"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._creating = set()
        self._notified: set[str] = set()  # track already-notified players this session

    def _get_player(self, discord_id: str):
        with get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM players WHERE discord_id = ?", (discord_id,)
            ).fetchone()
            return dict(row) if row else None

    def _settle_time(self, player):
        now = time.time()
        elapsed_years = seconds_to_years(now - player["last_active"])
        new_lifespan = max(0, player["lifespan"] - int(elapsed_years))
        updates = {"lifespan": new_lifespan, "last_active": now, "cultivation": player["cultivation"]}
        cultivating = player["cultivating_until"] and now < player["cultivating_until"]
        if not cultivating and elapsed_years >= AUTO_CULTIVATE_THRESHOLD_YEARS:
            bonus = get_cultivation_bonus(player["discord_id"], player["current_city"], player.get("cave"))
            gain = calc_cultivation_gain(
                int(elapsed_years), player["comprehension"], player["spirit_root_type"]
            )
            gain = int(gain * (1 + bonus))
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
            uid = str(ctx.author.id)
            if await self._try_yinyang(ctx, player, uid):
                return True
            with get_conn() as conn:
                conn.execute("UPDATE players SET is_dead = 1 WHERE discord_id = ?", (uid,))
                conn.commit()
            await ctx.send(
                f"{ctx.author.mention} 道友 **{player['name']}** 寿元已尽，魂归天道。\n"
                "尘归尘，土归土，可使用 `cat!创建角色` 重入修仙之路。"
            )
            return True
        return False

    async def _try_yinyang(self, ctx, player, uid: str) -> bool:
        import random as _r
        import json
        if player.get("has_bahongchen") or player.get("rebirth_count", 0) > 0:
            return False
        if _r.random() > 0.0003:
            return False
        from utils.events.adventure import YINYANG_EVENT, YINYANG_FINALE
        from cogs.explore import ExploreView
        embed = discord.Embed(
            title=f"✦ {YINYANG_EVENT['title']} ✦",
            description=YINYANG_EVENT["desc"],
            color=discord.Color.dark_purple(),
        )
        await ctx.send(ctx.author.mention, embed=embed,
                       view=YinYangView(ctx.author, YINYANG_EVENT, YINYANG_FINALE, player, self, uid))
        return True

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
        if player.get("escape_rate", 0) > 0:
            embed.add_field(name="逃跑成功率", value=f"+{player['escape_rate']}%", inline=True)
        if player.get("has_bahongchen"):
            embed.add_field(name="奇遇", value="阴阳两界 · 已触发", inline=False)
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

        bonus = get_cultivation_bonus(uid, player["current_city"], player.get("cave"))
        embed = discord.Embed(
            title="✦ 选择闭关时长 ✦",
            description=(
                f"当前寿元：**{player['lifespan']} 年**\n"
                f"修炼加成：**+{int(bonus * 100)}%**\n\n"
                "请选择本次闭关时长："
            ),
            color=discord.Color.teal(),
        )
        await interaction.followup.send(embed=embed, view=CultivateView(interaction.user, self, player))

    async def start_cultivate(self, interaction: discord.Interaction, years: int):
        """Called by CultivateButton after user picks a duration."""
        uid = str(interaction.user.id)
        player = self._get_player(uid)
        if not player:
            return await interaction.followup.send("尚未踏入修仙之路。")
        updates, _ = self._settle_time(player)
        self._apply_updates(uid, updates)
        player = self._get_player(uid)
        if player["lifespan"] < years:
            return await interaction.followup.send(f"寿元不足，无法修炼 {years} 年。")
        now = time.time()
        cultivating_until = now + years_to_seconds(years)
        bonus = get_cultivation_bonus(uid, player["current_city"], player.get("cave"))
        gain = int(calc_cultivation_gain(years, player["comprehension"], player["spirit_root_type"]) * (1 + bonus))
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
        real_hours = years * 2
        await interaction.followup.send(
            f"{interaction.user.mention} **{player['name']}** 开始闭关修炼 **{years} 年**（现实 {real_hours} 小时）。\n"
            f"修为进度：{player['cultivation']}/{needed} → {new_cultivation}/{needed}\n"
            f"闭关结束后将收到通知。"
        )

    async def claim_cultivation(self, interaction: discord.Interaction, uid: str):
        """Called when player clicks 领取 in the DM notification."""
        player = self._get_player(uid)
        if not player:
            return await interaction.response.send_message("角色不存在。")
        now = time.time()
        if player["cultivating_until"] and now < player["cultivating_until"]:
            return await interaction.response.send_message("闭关尚未结束，请耐心等待。")
        if not player["cultivating_until"]:
            return await interaction.response.send_message("当前没有待领取的修炼成果。")
        with get_conn() as conn:
            conn.execute(
                "UPDATE players SET cultivating_until = NULL, cultivating_years = NULL WHERE discord_id = ?",
                (uid,)
            )
            conn.commit()
        self._notified.discard(uid)
        player = self._get_player(uid)
        needed = cultivation_needed(player["realm"])
        can_bt = self._can_breakthrough(player)
        embed = discord.Embed(
            title="✦ 修炼成果已领取 ✦",
            description=f"**{player['name']}** 出关！",
            color=discord.Color.teal(),
        )
        embed.add_field(name="当前修为", value=f"{player['cultivation']} / {needed}", inline=True)
        embed.add_field(name="剩余寿元", value=f"{player['lifespan']} 年", inline=True)
        if can_bt:
            embed.add_field(name="提示", value="修为已圆满，可尝试突破！", inline=False)
        await interaction.response.send_message(embed=embed)

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

        if player["realm"] == "炼气期10层":
            from utils.items import calc_zhuji_breakthrough_rate, can_skip_pill
            from utils.db import has_item
            from utils.views.cultivation import ZhujiBreakthroughView
            has_pill = has_item(uid, "筑基丹")
            skip = can_skip_pill(player)
            rate_no_pill = calc_zhuji_breakthrough_rate(player, use_pill=False)
            rate_with_pill = calc_zhuji_breakthrough_rate(player, use_pill=True)
            embed = discord.Embed(
                title="✦ 炼气化液 · 筑基之关 ✦",
                description=(
                    "炼气期圆满，天地大关横亘于前。\n"
                    "筑基之关乃修仙路上第一道天堑，非有大机缘者难以跨越。\n\n"
                    f"当前突破成功率：**{rate_no_pill}%**\n"
                    + (f"服用筑基丹后：**{rate_with_pill}%**\n" if has_pill else "（背包中无筑基丹）\n")
                    + ("\n✨ 悟性与机缘皆已大成，可直接冲关！" if skip else "")
                ),
                color=discord.Color.gold(),
            )
            await interaction.followup.send(
                embed=embed,
                view=ZhujiBreakthroughView(interaction.user, self, player, has_pill, uid)
            )
            return

        result = await self._do_breakthrough_chain(uid, player, now)
        await interaction.followup.send(result)

    async def _do_breakthrough_chain(self, uid: str, player: dict, now: float) -> str:
        chain = []
        current = player
        while True:
            nxt = next_realm(current["realm"])
            if not nxt:
                chain.append(f"道友已至大道巅峰。")
                break
            success, outcome = roll_breakthrough(current["realm"], current["physique"], current["bone"], current["cultivation"])
            if success:
                new_lifespan_max = lifespan_max_for_realm(nxt)
                lifespan_gain = max(0, new_lifespan_max - current["lifespan_max"])
                new_lifespan = current["lifespan"] + lifespan_gain
                with get_conn() as conn:
                    conn.execute(
                        "UPDATE players SET realm = ?, lifespan = ?, lifespan_max = ?, cultivation = 0, last_active = ? WHERE discord_id = ?",
                        (nxt, new_lifespan, new_lifespan_max, now, uid)
                    )
                    conn.commit()
                lifespan_line = f"寿元上限→{new_lifespan_max}年" if lifespan_gain > 0 else f"寿元{new_lifespan}年"
                chain.append(f"**{current['realm']}** ➜ **{nxt}**（{lifespan_line}）")
                current = self._get_player(uid)
                if not self._can_breakthrough(current):
                    break
            else:
                new_cultivation, new_lifespan, fail_msg = apply_failure(current["cultivation"], current["lifespan"], outcome)
                with get_conn() as conn:
                    conn.execute("UPDATE players SET cultivation = ?, lifespan = ?, last_active = ? WHERE discord_id = ?",
                                 (new_cultivation, new_lifespan, now, uid))
                    conn.commit()
                current = self._get_player(uid)
                if current["lifespan"] <= 0:
                    with get_conn() as conn:
                        conn.execute("UPDATE players SET is_dead = 1 WHERE discord_id = ?", (uid,))
                        conn.commit()
                    chain.append(f"突破失败，{fail_msg}寿元耗尽，魂归天道。")
                else:
                    needed = cultivation_needed(current["realm"])
                    chain.append(f"突破失败，{fail_msg}修为：{new_cultivation}/{needed}　寿元：{new_lifespan}年")
                break

        if len(chain) == 1:
            prefix = "🎉 突破成功！\n" if "➜" in chain[0] else ""
            return prefix + chain[0]
        successes = [c for c in chain if "➜" in c]
        fail_line = next((c for c in chain if "➜" not in c), "")
        msg = f"🎉 **{player['name']}** 连续突破 {len(successes)} 次！\n" + "\n".join(successes)
        if fail_line:
            msg += f"\n\n{fail_line}"
        return msg

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

    @commands.command(name="解散队伍")
    async def disband_party(self, ctx):
        from utils.views.party import disband_party
        msg = await disband_party(str(ctx.author.id), self.bot)
        await ctx.send(f"{ctx.author.mention} {msg}")

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

        import json
        has_dual = has_player and any(
            (t if isinstance(t, str) else t.get("name", "")) == "双修功法"
            for t in json.loads(player["techniques"] or "[]")
        )

        city_players = []
        if has_player:
            with get_conn() as conn:
                rows = conn.execute(
                    "SELECT discord_id, name, realm, cultivation FROM players "
                    "WHERE current_city = ? AND is_dead = 0 AND discord_id != ?",
                    (player["current_city"], uid)
                ).fetchall()
            city_players = [dict(r) for r in rows]


        await ctx.send(embed=_build_menu_embed(has_dual), view=MainMenuView(ctx.author, has_player, can_bt, self, player, city_players))

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
        if player.get("escape_rate", 0) > 0:
            embed.add_field(name="逃跑成功率", value=f"+{player['escape_rate']}%", inline=True)
        if player.get("has_bahongchen"):
            embed.add_field(name="奇遇", value="阴阳两界 · 已触发", inline=False)

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
        bonus = get_cultivation_bonus(uid, player["current_city"], player.get("cave"))
        gain = int(calc_cultivation_gain(years, player["comprehension"], player["spirit_root_type"]) * (1 + bonus))
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

        if player["realm"] == "炼气期10层":
            from utils.items import calc_zhuji_breakthrough_rate, can_skip_pill
            from utils.db import has_item
            from utils.views.cultivation import ZhujiBreakthroughView
            has_pill = has_item(uid, "筑基丹")
            skip = can_skip_pill(player)
            rate_no_pill = calc_zhuji_breakthrough_rate(player, use_pill=False)
            rate_with_pill = calc_zhuji_breakthrough_rate(player, use_pill=True)
            embed = discord.Embed(
                title="✦ 炼气化液 · 筑基之关 ✦",
                description=(
                    "炼气期圆满，天地大关横亘于前。\n"
                    "筑基之关乃修仙路上第一道天堑，非有大机缘者难以跨越。\n\n"
                    f"当前突破成功率：**{rate_no_pill}%**\n"
                    + (f"服用筑基丹后：**{rate_with_pill}%**\n" if has_pill else "（背包中无筑基丹）\n")
                    + ("\n✨ 悟性与机缘皆已大成，可直接冲关！" if skip else "")
                ),
                color=discord.Color.gold(),
            )
            await ctx.send(
                ctx.author.mention,
                embed=embed,
                view=ZhujiBreakthroughView(ctx.author, self, player, has_pill, uid)
            )
            return

        result = await self._do_breakthrough_chain(uid, player, now)
        await ctx.send(f"{ctx.author.mention} {result}")

    @commands.command(name="双修")
    async def dual_cultivate(self, ctx, target: discord.Member = None):
        uid = str(ctx.author.id)

        if not target:
            return await ctx.send(f"{ctx.author.mention} 用法：`cat!双修 @对方`")
        if target == ctx.author:
            return await ctx.send(f"{ctx.author.mention} 无法与自己双修。")
        if target.bot:
            return await ctx.send(f"{ctx.author.mention} 对方不是修士。")

        import json
        inviter = self._get_player(uid)
        target_player = self._get_player(str(target.id))

        if not inviter or inviter["is_dead"]:
            return await ctx.send(f"{ctx.author.mention} 尚未踏入修仙之路或已坐化。")
        if not target_player or target_player["is_dead"]:
            return await ctx.send(f"{ctx.author.mention} 对方尚未踏入修仙之路或已坐化。")

        inv_techs = json.loads(inviter["techniques"] or "[]")
        tgt_techs = json.loads(target_player["techniques"] or "[]")

        inv_has = any(t if isinstance(t, str) else t.get("name") == "双修功法" for t in (json.loads(inviter["techniques"] or "[]") if isinstance(json.loads(inviter["techniques"] or "[]"), list) else []))
        tgt_has = any(t if isinstance(t, str) else t.get("name") == "双修功法" for t in (json.loads(target_player["techniques"] or "[]") if isinstance(json.loads(target_player["techniques"] or "[]"), list) else []))

        def _has_dual(raw):
            data = json.loads(raw or "[]")
            for t in data:
                name = t if isinstance(t, str) else t.get("name", "")
                if name == "双修功法":
                    return True
            return False

        if not _has_dual(inviter["techniques"]) and not _has_dual(target_player["techniques"]):
            return await ctx.send(f"{ctx.author.mention} 双方均未习得「双修功法」，无法双修。")

        if inviter["current_city"] != target_player["current_city"]:
            return await ctx.send(
                f"{ctx.author.mention} 双修需在同一城市，请先找到对方所在之处。"
            )

        now = time.time()
        cooldown_secs = years_to_seconds(2)
        for p, mention in [(inviter, ctx.author.mention), (target_player, target.mention)]:
            if p["last_dual_cultivate"] and now - p["last_dual_cultivate"] < cooldown_secs:
                remaining = seconds_to_years(cooldown_secs - (now - p["last_dual_cultivate"]))
                return await ctx.send(f"{mention} 双修冷却中，还需等待 **{remaining:.1f} 游戏年**。")

        for p, mention in [(inviter, ctx.author.mention), (target_player, target.mention)]:
            if p["cultivating_until"] and now < p["cultivating_until"]:
                return await ctx.send(f"{mention} 正在闭关，无法双修。")

        if inviter["lifespan"] < 1:
            return await ctx.send(f"{ctx.author.mention} 寿元不足，无法双修。")
        if target_player["lifespan"] < 1:
            return await ctx.send(f"{ctx.author.mention} 对方寿元不足，无法双修。")

        inv_virgin = bool(inviter["is_virgin"])
        tgt_virgin = bool(target_player["is_virgin"])
        both_virgin = inv_virgin and tgt_virgin
        if both_virgin:
            multiplier = random.uniform(10, 20)
        elif inv_virgin or tgt_virgin:
            multiplier = 5.0
        else:
            multiplier = 1.2

        if both_virgin:
            mult_desc = f"双方皆为清白之身，阴阳交融，修为暴涨（**{multiplier:.1f}倍**）"
        elif inv_virgin or tgt_virgin:
            mult_desc = "一方清白之身，修为大增（**5倍**）"
        else:
            mult_desc = "双修加持，修为略有提升（**1.2倍**）"

        embed = discord.Embed(
            title="✦ 双修邀请 ✦",
            description=(
                f"**{ctx.author.display_name}** 邀请 {target.mention} 进行双修。\n\n"
                f"{mult_desc}\n"
                f"双修将消耗双方各 **1 游戏年** 寿元，持续现实 **2 小时**。\n\n"
                f"{target.mention} 是否接受？"
            ),
            color=discord.Color.pink(),
        )
        await ctx.send(
            target.mention,
            embed=embed,
            view=DualCultivateInviteView(self, ctx.author, target, multiplier, both_virgin),
        )

    async def do_dual_cultivate(
        self,
        interaction: discord.Interaction,
        inviter: discord.User,
        target: discord.User,
        multiplier: float,
        both_virgin: bool,
    ):
        """双方确认后执行双修逻辑。"""
        import json
        now = time.time()
        inv_uid = str(inviter.id)
        tgt_uid = str(target.id)

        inv_p = self._get_player(inv_uid)
        tgt_p = self._get_player(tgt_uid)

        if not inv_p or not tgt_p:
            return await interaction.followup.send("双修失败：角色数据异常。")

        cooldown_secs = years_to_seconds(2)
        for p, name in [(inv_p, inviter.display_name), (tgt_p, target.display_name)]:
            if p["lifespan"] < 1:
                return await interaction.followup.send(f"双修失败：**{name}** 寿元不足。")
            if p["last_dual_cultivate"] and now - p["last_dual_cultivate"] < cooldown_secs:
                return await interaction.followup.send(f"双修失败：**{name}** 冷却未结束。")
            if p["cultivating_until"] and now < p["cultivating_until"]:
                return await interaction.followup.send(f"双修失败：**{name}** 正在闭关。")

        inv_virgin = bool(inv_p["is_virgin"])
        tgt_virgin = bool(tgt_p["is_virgin"])
        both_virgin = inv_virgin and tgt_virgin
        if both_virgin:
            multiplier = random.uniform(10, 20)
        elif inv_virgin or tgt_virgin:
            multiplier = 5.0
        else:
            multiplier = 1.2

        years = 1
        cultivating_until = now + years_to_seconds(years)

        def _calc(p):
            base = calc_cultivation_gain(years, p["comprehension"], p["spirit_root_type"])
            bonus = get_cultivation_bonus(str(p["discord_id"]), p["current_city"], p.get("cave"))
            return int(base * (1 + bonus) * multiplier)

        inv_gain = _calc(inv_p)
        tgt_gain = _calc(tgt_p)

        with get_conn() as conn:
            for p, gain, uid in [(inv_p, inv_gain, inv_uid), (tgt_p, tgt_gain, tgt_uid)]:
                new_cult = p["cultivation"] + gain
                new_life = p["lifespan"] - years
                conn.execute("""
                    UPDATE players SET
                        cultivation = ?, lifespan = ?,
                        cultivating_until = ?, cultivating_years = ?,
                        last_dual_cultivate = ?, is_virgin = 0, last_active = ?
                    WHERE discord_id = ?
                """, (new_cult, new_life, cultivating_until, years, now, now, uid))
            conn.commit()

        inv_needed = cultivation_needed(inv_p["realm"])
        tgt_needed = cultivation_needed(tgt_p["realm"])

        if both_virgin:
            flavor = (
                "灵气缠绵，呼吸交织，两道身影在朦胧的灵雾中渐渐靠近……\n"
                "初尝禁果，羞意难掩，却又欲罢不能。\n"
                "阴阳之力在体内激荡翻涌，如决堤之水，修为暴涨。\n\n"
                f"💮 **{inviter.display_name}** 失去了处男状态\n"
                f"💮 **{target.display_name}** 失去了处女状态\n\n"
                f"修为暴涨（**{multiplier:.1f}倍**）"
            )
        elif inv_virgin or tgt_virgin:
            virgin_one = inviter.display_name if inv_virgin else target.display_name
            gender_word = "处男" if (inv_virgin and inv_p["gender"] == "男") or (tgt_virgin and tgt_p["gender"] == "男") else "处女"
            flavor = (
                "灵气流转，肌肤相触，一股陌生而炽热的感觉涌遍全身……\n"
                "懵懂与悸动交织，那道防线悄然崩塌。\n"
                "阴阳之力借此契机奔涌而出，修为大幅提升。\n\n"
                f"💮 **{virgin_one}** 失去了{gender_word}状态\n\n"
                "修为大增（**5倍**）"
            )
        else:
            flavor = (
                "两道灵识相互感应，阴阳之气缓缓流转交融。\n"
                "虽无初次的惊涛骇浪，却也有一番绵绵细水的滋味。\n\n"
                "修为略有提升（**1.2倍**）"
            )

        embed = discord.Embed(
            title="✦ 双修 ✦",
            description=f"{flavor}\n\n双修持续 **1 游戏年**（现实 2 小时）。",
            color=discord.Color.pink(),
        )
        embed.add_field(
            name=inviter.display_name,
            value=f"修为 +{inv_gain}（{inv_p['cultivation']}/{inv_needed} → {inv_p['cultivation']+inv_gain}/{inv_needed}）",
            inline=False,
        )
        embed.add_field(
            name=target.display_name,
            value=f"修为 +{tgt_gain}（{tgt_p['cultivation']}/{tgt_needed} → {tgt_p['cultivation']+tgt_gain}/{tgt_needed}）",
            inline=False,
        )
        await interaction.followup.send(embed=embed)

    @commands.command(name="移动")
    async def travel(self, ctx, *, city_name: str = None):
        uid = str(ctx.author.id)
        player = self._get_player(uid)

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

        now = time.time()
        if player["cultivating_until"] and now < player["cultivating_until"]:
            remaining = seconds_to_years(player["cultivating_until"] - now)
            return await ctx.send(
                f"{ctx.author.mention} 道友正在闭关，无法移动。还剩约 **{remaining:.1f} 年**，可使用 `cat!停止` 提前结束。"
            )

        from utils.world import get_city
        target = get_city(city_name)
        if not target:
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

        with get_conn() as conn:
            conn.execute(
                "UPDATE players SET current_city = ? WHERE discord_id = ?",
                (target["name"], uid)
            )
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

    @commands.command(name="help")
    async def help_cmd(self, ctx):
        embed = discord.Embed(
            title="✦ 命令一览 ✦",
            color=discord.Color.teal(),
        )
        embed.add_field(name="基础", value=(
            "`cat!c` — 主菜单（含背包/功法/装备快捷按钮）\n"
            "`cat!创建角色` — 创建角色\n"
            "`cat!查看` — 查看角色面板\n"
            "`cat!修炼 [年数]` — 开始闭关\n"
            "`cat!停止` — 提前结束闭关\n"
            "`cat!突破` — 尝试突破境界（炼气10层需筑基丹）"
        ), inline=False)
        embed.add_field(name="探险", value=(
            "`cat!探险` — 随机触发事件（每5游戏年8次）"
        ), inline=False)
        embed.add_field(name="茶馆任务", value=(
            "`cat!茶馆` — 查看并接取任务（战斗类1年·采集类2年）\n"
            "`cat!交任务` — 手动结算当前任务\n"
            "· 任务到时间后自动结算并 DM 通知\n"
            "· 组队接任务：战力叠加，奖励每人完整发放"
        ), inline=False)
        embed.add_field(name="组队", value=(
            "· 点击城市玩家列表中的玩家名字 → 邀请组队 / 发起攻击\n"
            "`cat!解散队伍` — 队长解散队伍（DM 通知所有成员）\n"
            "· 主菜单有「查看队伍」和「退出队伍」按钮"
        ), inline=False)
        embed.add_field(name="双修", value=(
            "`cat!双修 @对方` — 邀请他人进行双修（需一方持有「双修功法」）\n"
            "· 双方皆为清白之身时修为暴涨，冷却 2 游戏年"
        ), inline=False)
        embed.add_field(name="移动", value=(
            "`cat!移动 [城市名]` — 前往目标城市（队长移动队员跟随）\n"
            "`cat!世界` — 查看天下城市列表"
        ), inline=False)
        embed.add_field(name="宗门", value=(
            "`cat!宗门列表` — 查看所有宗门\n"
            "`cat!宗门详情 [宗门名]` — 查看入门要求与功法\n"
            "`cat!加入宗门 [宗门名]` — 加入宗门\n"
            "`cat!退出宗门` — 离开宗门\n"
            "`cat!门派功法` — 查看宗门功法，若有缺漏会自动补发"
        ), inline=False)
        embed.add_field(name="功法", value=(
            "`cat!我的功法` — 查看已习得功法与装备状态\n"
            "`cat!装备功法 [功法名]` — 装备/卸下功法（最多5本）\n"
            "`cat!修炼功法 [功法名]` — 消耗灵石与寿元提升功法阶段\n"
            "　　阶段：入门→熟练→精通→小成→大成→圆满→破限\n"
            "`cat!功法属性` — 查看已装备功法的属性加成"
        ), inline=False)
        embed.add_field(name="背包 / 道具", value=(
            "`cat!背包` — 查看丹药、道具与装备列表\n"
            "`cat!使用 [道具名]` — 使用丹药（如：续命丹、聚灵丹）"
        ), inline=False)
        embed.add_field(name="装备", value=(
            "`cat!装备详情` — 查看当前装备及属性加成\n"
            "`cat!装备 [装备ID]` — 装备指定物品（ID见背包）\n"
            "`cat!卸下 [装备ID]` — 卸下装备\n"
            "`cat!丢弃装备 [装备ID]` — 永久丢弃装备\n"
            "· 装备分武器/防具/饰品三槽，有境界要求\n"
            "· 品质：普通⬜ 精良🟩 稀有🟦 史诗🟪 传说🟨"
        ), inline=False)
        embed.add_field(name="居所", value=(
            "`cat!买房` — 在当前城市置业（声望≥300）\n"
            "`cat!开辟洞府 [秘地名]` — 开辟野外洞府（声望≥600）\n"
            "`cat!我的居所` — 查看居所与加成"
        ), inline=False)
        embed.add_field(name="公共事件", value=(
            "`cat!公共事件` — 查看当前全服事件状态\n"
            "· 每10游戏年自动触发一次（拍卖会/试炼/妖兽潮等）\n"
            "· 需在 .env 设置 PUBLIC_EVENT_CHANNEL_ID 指定广播频道"
        ), inline=False)
        embed.add_field(name="音乐", value=(
            "`cat!play [歌曲/链接]` — 播放音乐\n"
            "`cat!skip` — 跳过当前曲目\n"
            "`cat!stop` — 停止播放"
        ), inline=False)
        embed.add_field(name="奇遇", value=(
            "传闻修士坐化之际，有极小概率触发神秘奇遇。\n"
            "经历者将获得永久跨世加成，无论几度轮回皆不消散。\n"
            "至于是何奇遇……只有亲历者方知。"
        ), inline=False)
        embed.set_footer(text="现实 2 小时 = 游戏 1 年 · 寿元归零则坐化 · cat!c 打开主菜单")
        await ctx.send(embed=embed)

    @commands.command(name="创建角色")
    async def create_character(self, ctx):
        uid = str(ctx.author.id)

        if self._get_player(uid) and not self._get_player(uid)["is_dead"]:
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

            old = self._get_player(uid)
            with get_conn() as conn:
                if old and old["is_dead"]:
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
                            created_at=?, last_active=?
                        WHERE discord_id=?
                    """, (
                        name, gender, spirit_root, root_type,
                        stats["comprehension"], stats["physique"],
                        stats["fortune"], stats["bone"], stats["soul"],
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


    @tasks.loop(minutes=1)
    async def _cultivation_notifier(self):
        now = time.time()
        with get_conn() as conn:
            rows = conn.execute(
                "SELECT discord_id, name, cultivation, realm FROM players WHERE cultivating_until IS NOT NULL AND cultivating_until <= ? AND is_dead = 0",
                (now,)
            ).fetchall()
        for row in rows:
            uid = row["discord_id"]
            if uid in self._notified:
                continue
            self._notified.add(uid)
            with get_conn() as conn:
                conn.execute(
                    "UPDATE players SET cultivating_until = NULL, cultivating_years = NULL WHERE discord_id = ?",
                    (uid,)
                )
                conn.commit()
            try:
                player = self._get_player(uid)
                needed = cultivation_needed(player["realm"])
                can_bt = self._can_breakthrough(player)
                embed = discord.Embed(
                    title="✦ 闭关结束 ✦",
                    description=f"**{row['name']}** 出关！",
                    color=discord.Color.gold(),
                )
                embed.add_field(name="当前修为", value=f"{player['cultivation']} / {needed}", inline=True)
                embed.add_field(name="剩余寿元", value=f"{player['lifespan']} 年", inline=True)
                if can_bt:
                    embed.add_field(name="提示", value="修为已圆满，可尝试突破！", inline=False)
                user = await self.bot.fetch_user(int(uid))
                await user.send(embed=embed)
            except Exception:
                pass

    @_cultivation_notifier.before_loop
    async def _before_notifier(self):
        await self.bot.wait_until_ready()

    async def cog_load(self):
        self._cultivation_notifier.start()

    async def cog_unload(self):
        self._cultivation_notifier.cancel()


async def setup(bot):
    await bot.add_cog(CultivationCog(bot))
