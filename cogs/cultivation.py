import random
import time

import discord
from discord.ext import commands, tasks

from utils.character import (
    calc_cultivation_gain, years_to_seconds, seconds_to_years,
    get_cultivation_bonus, REALM_LIFESPAN,
)
from utils.realms import (
    cultivation_needed, lifespan_max_for_realm, next_realm,
    roll_breakthrough, apply_failure,
)
from utils.views import MainMenuView, ProfileView, CultivateView, ClaimCultivationView, DualCultivateInviteView, YinYangView, _build_menu_embed
from utils.db import get_conn
from utils.world import CITIES
from utils.player import get_player, is_defending, settle_time, apply_updates, can_breakthrough


class CultivationCog(commands.Cog, name="Cultivation"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._notified: set[str] = set()

    def _get_player(self, discord_id: str):
        return get_player(discord_id)

    def _is_defending(self, uid: str) -> bool:
        return is_defending(uid)

    def _settle_time(self, player):
        return settle_time(player)

    def _apply_updates(self, discord_id: str, updates: dict):
        apply_updates(discord_id, updates)

    def _can_breakthrough(self, player) -> bool:
        return can_breakthrough(player)

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

    async def _check_dead(self, ctx, player) -> bool:
        if player["lifespan"] <= 0 or player["is_dead"]:
            uid = str(ctx.author.id)
            if await self._try_yinyang(ctx, player, uid):
                return True
            await self._handle_death(ctx, player, uid)
            return True
        return False

    async def _handle_death(self, ctx, player, uid: str):
        import json
        sect = player.get("sect") or ""
        has_bahongchen = player.get("has_bahongchen", 0)
        rebirth_count = player.get("rebirth_count", 0)
        is_xianzang = sect == "仙葬谷"
        can_rebirth = is_xianzang or bool(has_bahongchen)

        if can_rebirth:
            bonus = self._calc_rebirth_bonus(player)
            new_rebirth = rebirth_count + 1
            lifespan = REALM_LIFESPAN["炼气期"]
            now = time.time()
            starting_city = random.choice(CITIES)["name"]
            with get_conn() as conn:
                conn.execute("""
                    UPDATE players SET
                        realm='炼气期1层', cultivation=0, lifespan=?, lifespan_max=?,
                        spirit_stones=?, is_dead=0, is_virgin=1,
                        sect=NULL, sect_rank=NULL,
                        cultivating_until=NULL, cultivating_years=NULL,
                        active_quest=NULL, quest_due=NULL,
                        gathering_until=NULL, gathering_type=NULL,
                        explore_count=0, explore_reset_year=0,
                        current_city=?, last_active=?,
                        rebirth_count=?,
                        comprehension = comprehension + ?,
                        physique = physique + ?,
                        fortune = fortune + ?,
                        bone = bone + ?,
                        soul = soul + ?
                    WHERE discord_id=?
                """, (
                    lifespan, lifespan, 500,
                    starting_city, now, new_rebirth,
                    bonus["comprehension"], bonus["physique"],
                    bonus["fortune"], bonus["bone"], bonus["soul"],
                    uid
                ))
                conn.commit()
            reason = "仙葬谷轮回传承" if is_xianzang else "阴阳奇遇感应"
            bonus_str = "  ".join(f"{k} +{v}" for k, v in bonus.items() if v > 0)
            await ctx.send(
                f"{ctx.author.mention} **{player['name']}** 寿元已尽，魂归天道。\n"
                f"然而——**{reason}**，道友得以轮回重生！\n"
                f"第 **{new_rebirth}** 次轮回，携带前世感悟：{bonus_str}\n"
                f"可使用 `cat!查看` 查看新角色。"
            )
        else:
            with get_conn() as conn:
                conn.execute("UPDATE players SET is_dead = 1 WHERE discord_id = ?", (uid,))
                conn.commit()
            await ctx.send(
                f"{ctx.author.mention} 道友 **{player['name']}** 寿元已尽，魂归天道。\n"
                "尘归尘，土归土，可使用 `cat!创建角色` 重入修仙之路。"
            )

    async def _try_yinyang(self, ctx, player, uid: str) -> bool:
        import random as _r
        if player.get("has_bahongchen") or player.get("rebirth_count", 0) > 0:
            return False
        if _r.random() > 0.0003:
            return False
        from utils.events.adventure import YINYANG_EVENT, YINYANG_FINALE
        embed = discord.Embed(
            title=f"✦ {YINYANG_EVENT['title']} ✦",
            description=YINYANG_EVENT["desc"],
            color=discord.Color.dark_purple(),
        )
        await ctx.send(ctx.author.mention, embed=embed,
                       view=YinYangView(ctx.author, YINYANG_EVENT, YINYANG_FINALE, player, self, uid))
        return True

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
        elif player["gathering_until"] and now < player["gathering_until"]:
            remaining = seconds_to_years(player["gathering_until"] - now)
            gtype = player.get("gathering_type", "采集")
            status = f"{gtype}中（还剩 {remaining:.1f} 年）"
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
        with get_conn() as conn:
            city_rows = conn.execute(
                "SELECT discord_id, name, realm, cultivation FROM players "
                "WHERE current_city = ? AND is_dead = 0 AND discord_id != ?",
                (player["current_city"], uid)
            ).fetchall()
        city_players = [dict(r) for r in city_rows]
        await interaction.followup.send(
            interaction.user.mention, embed=embed,
            view=ProfileView(interaction.user, can_bt, is_cultivating, self, player, city_players)
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
        if player["gathering_until"] and now < player["gathering_until"]:
            remaining = seconds_to_years(player["gathering_until"] - now)
            return await interaction.followup.send(f"道友正在采集中，无法修炼。还剩约 **{remaining:.1f} 年**。")
        if self._is_defending(uid):
            return await interaction.followup.send("守城期间无法修炼，专心守城！", ephemeral=True)
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
        uid = str(interaction.user.id)
        player = self._get_player(uid)
        if not player:
            return await interaction.followup.send("尚未踏入修仙之路。")
        if self._is_defending(uid):
            return await interaction.followup.send("守城期间无法修炼，专心守城！", ephemeral=True)
        updates, _ = self._settle_time(player)
        self._apply_updates(uid, updates)
        player = self._get_player(uid)
        if player["lifespan"] < years:
            return await interaction.followup.send(f"寿元不足，无法修炼 {years} 年。")
        now = time.time()
        cultivating_until = now + years_to_seconds(years)
        bonus = get_cultivation_bonus(uid, player["current_city"], player.get("cave"))
        pill_active = player.get("pill_buff_until") and now < player["pill_buff_until"]
        if pill_active:
            bonus += 0.5
        gain = int(calc_cultivation_gain(years, player["comprehension"], player["spirit_root_type"]) * (1 + bonus))
        new_lifespan = player["lifespan"] - years
        with get_conn() as conn:
            conn.execute("""
                UPDATE players SET lifespan = ?,
                    cultivating_until = ?, cultivating_years = ?, last_active = ?
                WHERE discord_id = ?
            """, (new_lifespan, cultivating_until, years, now, uid))
            conn.commit()
        needed = cultivation_needed(player["realm"])
        pill_note = "（聚灵丹加持中 +50%）\n" if pill_active else ""
        await interaction.followup.send(
            f"{interaction.user.mention} **{player['name']}** 开始闭关修炼 **{years} 年**（现实 {years * 2} 小时）。\n"
            f"{pill_note}"
            f"修为进度：{player['cultivation']}/{needed}，出关后将获得约 +{gain}\n"
            f"闭关结束后将收到通知。"
        )

    async def claim_cultivation(self, interaction: discord.Interaction, uid: str):
        player = self._get_player(uid)
        if not player:
            return await interaction.response.send_message("角色不存在。")
        now = time.time()
        if player["cultivating_until"] and now < player["cultivating_until"]:
            return await interaction.response.send_message("闭关尚未结束，请耐心等待。")
        if not player["cultivating_until"]:
            return await interaction.response.send_message("当前没有待领取的修炼成果。")
        years_done = player.get("cultivating_years") or 0
        bonus = get_cultivation_bonus(uid, player["current_city"], player.get("cave"))
        pill_active = player.get("pill_buff_until") and now < player["pill_buff_until"]
        if pill_active:
            bonus += 0.5
        gain = int(calc_cultivation_gain(years_done, player["comprehension"], player["spirit_root_type"]) * (1 + bonus))
        new_cultivation = player["cultivation"] + gain
        with get_conn() as conn:
            conn.execute(
                "UPDATE players SET cultivation = ?, cultivating_until = NULL, cultivating_years = NULL WHERE discord_id = ?",
                (new_cultivation, uid)
            )
            conn.commit()
        self._notified.discard(uid)
        player = self._get_player(uid)
        needed = cultivation_needed(player["realm"])
        can_bt = self._can_breakthrough(player)
        embed = discord.Embed(title="✦ 修炼成果已领取 ✦", description=f"**{player['name']}** 出关！", color=discord.Color.teal())
        embed.add_field(name="修为获得", value=f"+{gain}", inline=True)
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
            await interaction.followup.send(embed=embed, view=ZhujiBreakthroughView(interaction.user, self, player, has_pill, uid))
            return

        if player["realm"] == "筑基期10层":
            from utils.items.breakthrough import calc_ningdan_breakthrough_rate
            from utils.db import has_item
            from utils.views.cultivation import NingdanBreakthroughView
            has_pill = has_item(uid, "凝丹丹")
            rate_no_pill = calc_ningdan_breakthrough_rate(player, use_pill=False)
            rate_with_pill = calc_ningdan_breakthrough_rate(player, use_pill=True)
            embed = discord.Embed(
                title="✦ 筑基化液 · 结丹之关 ✦",
                description=(
                    "筑基期圆满，金丹之道近在眼前。\n"
                    "凝结金丹，方可踏入真正的修仙之路。\n\n"
                    f"当前突破成功率：**{rate_no_pill}%**\n"
                    + (f"服用凝丹丹后：**{rate_with_pill}%**\n" if has_pill else "（背包中无凝丹丹）\n")
                ),
                color=discord.Color.gold(),
            )
            await interaction.followup.send(embed=embed, view=NingdanBreakthroughView(interaction.user, self, player, has_pill, uid))
            return

        if player["realm"] == "结丹期后期":
            from utils.items.breakthrough import calc_huaying_breakthrough_rate
            from utils.db import has_item
            from utils.views.cultivation import HuayingBreakthroughView
            has_pill = has_item(uid, "化婴丹")
            rate_no_pill = calc_huaying_breakthrough_rate(player, use_pill=False)
            rate_with_pill = calc_huaying_breakthrough_rate(player, use_pill=True)
            embed = discord.Embed(
                title="✦ 金丹破碎 · 元婴之关 ✦",
                description=(
                    "结丹期圆满，元婴之道横亘于前。\n"
                    "金丹破碎，元婴化形，此关凶险万分。\n\n"
                    f"当前突破成功率：**{rate_no_pill}%**\n"
                    + (f"服用化婴丹后：**{rate_with_pill}%**\n" if has_pill else "（背包中无化婴丹）\n")
                ),
                color=discord.Color.gold(),
            )
            await interaction.followup.send(embed=embed, view=HuayingBreakthroughView(interaction.user, self, player, has_pill, uid))
            return

        if player["realm"] == "元婴期后期":
            embed = discord.Embed(
                title="✦ 元婴圆满 · 化神之壁 ✦",
                description=(
                    "天地初开，大道未全，化神之路尚未显现于世。\n\n"
                    "道友元婴已臻圆满，然化神之关非修为可破——\n"
                    "须得五行归一，灵根补全，方有一线机缘叩响化神之门。\n\n"
                    "此路尚在封印之中，静待天机降临。"
                ),
                color=discord.Color.dark_purple(),
            )
            embed.set_footer(text="化神之道，缘起天定，强求不得。")
            return await interaction.followup.send(embed=embed)

        result = await self._do_breakthrough_chain(uid, player, now)
        await interaction.followup.send(result)

    async def _do_breakthrough_chain(self, uid: str, player: dict, now: float) -> str:
        chain = []
        current = player
        while True:
            nxt = next_realm(current["realm"])
            if not nxt:
                chain.append("道友已至大道巅峰。")
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
        overflow = player.get("cultivation_overflow") or 0
        if overflow > 0:
            total_years = player.get("cultivating_years") or 1
            gain = int(overflow * actual_years / max(total_years, 1))
        else:
            bonus = get_cultivation_bonus(uid, player["current_city"], player.get("cave"))
            pill_active = player.get("pill_buff_until") and now < player["pill_buff_until"]
            if pill_active:
                bonus += 0.5
            gain = int(calc_cultivation_gain(actual_years, player["comprehension"], player["spirit_root_type"]) * (1 + bonus))
        new_cultivation = player["cultivation"] + gain
        new_lifespan = player["lifespan"]
        with get_conn() as conn:
            conn.execute("""
                UPDATE players SET cultivation = ?, lifespan = ?,
                    cultivation_overflow = 0,
                    cultivating_until = NULL, cultivating_years = NULL, last_active = ?
                WHERE discord_id = ?
            """, (new_cultivation, new_lifespan, now, uid))
            conn.commit()
        needed = cultivation_needed(player["realm"])
        await interaction.followup.send(
            f"{interaction.user.mention} **{player['name']}** 退出闭关。\n"
            f"实际修炼 **{actual_years} 年**，获得修为 **+{gain}**。\n"
            f"修为进度：{new_cultivation}/{needed}　寿元剩余：{new_lifespan} 年"
        )

    @commands.command(name="c")
    async def menu(self, ctx):
        import json
        uid = str(ctx.author.id)
        player = self._get_player(uid)
        if player and not player["is_dead"]:
            updates, _ = self._settle_time(player)
            self._apply_updates(uid, updates)
            player = self._get_player(uid)
        has_player = player is not None and not player["is_dead"]
        can_bt = has_player and self._can_breakthrough(player)
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
        elif player["gathering_until"] and now < player["gathering_until"]:
            remaining = seconds_to_years(player["gathering_until"] - now)
            gtype = player.get("gathering_type", "采集")
            status = f"{gtype}中（还剩 {remaining:.1f} 年）"
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
        with get_conn() as conn:
            city_rows = conn.execute(
                "SELECT discord_id, name, realm, cultivation FROM players "
                "WHERE current_city = ? AND is_dead = 0 AND discord_id != ?",
                (player["current_city"], uid)
            ).fetchall()
        city_players = [dict(r) for r in city_rows]
        await ctx.send(ctx.author.mention, embed=embed,
                       view=ProfileView(ctx.author, can_bt, is_cultivating, self, player, city_players))

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
            return await ctx.send(f"{ctx.author.mention} 道友正在闭关修炼，还剩约 **{remaining:.1f} 年**，可使用 `cat!停止` 提前结束。")
        if player["gathering_until"] and now < player["gathering_until"]:
            remaining = seconds_to_years(player["gathering_until"] - now)
            return await ctx.send(f"{ctx.author.mention} 道友正在采集中，无法修炼。还剩约 **{remaining:.1f} 年**。")
        if self._is_defending(uid):
            return await ctx.send(f"{ctx.author.mention} 守城期间无法修炼，专心守城！")
        if years < 1 or years > 100:
            return await ctx.send("修炼年数需在 1 至 100 之间。")
        if player["lifespan"] < years:
            return await ctx.send(f"{ctx.author.mention} 寿元不足，剩余寿元 **{player['lifespan']} 年**，无法修炼 {years} 年。")
        cultivating_until = now + years_to_seconds(years)
        bonus = get_cultivation_bonus(uid, player["current_city"], player.get("cave"))
        pill_active = player.get("pill_buff_until") and now < player["pill_buff_until"]
        if pill_active:
            bonus += 0.5
        gain = int(calc_cultivation_gain(years, player["comprehension"], player["spirit_root_type"]) * (1 + bonus))
        new_lifespan = player["lifespan"] - years
        with get_conn() as conn:
            conn.execute("""
                UPDATE players SET lifespan = ?, cultivating_until = ?, cultivating_years = ?, last_active = ?
                WHERE discord_id = ?
            """, (new_lifespan, cultivating_until, years, now, uid))
            conn.commit()
        needed = cultivation_needed(player["realm"])
        pill_note = "（聚灵丹加持中 +50%）\n" if pill_active else ""
        await ctx.send(
            f"{ctx.author.mention} **{player['name']}** 开始闭关修炼 **{years} 年**。\n"
            f"{pill_note}预计现实时间 **{years * 2} 小时**后结束。\n"
            f"修为进度：{player['cultivation']}/{needed}，出关后将获得约 +{gain}"
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
        overflow = player.get("cultivation_overflow") or 0
        if overflow > 0:
            total_years = player.get("cultivating_years") or 1
            gain = int(overflow * actual_years / max(total_years, 1))
        else:
            bonus = get_cultivation_bonus(uid, player["current_city"], player.get("cave"))
            pill_active = player.get("pill_buff_until") and now < player["pill_buff_until"]
            if pill_active:
                bonus += 0.5
            gain = int(calc_cultivation_gain(actual_years, player["comprehension"], player["spirit_root_type"]) * (1 + bonus))
        new_cultivation = player["cultivation"] + gain
        new_lifespan = player["lifespan"]
        with get_conn() as conn:
            conn.execute("""
                UPDATE players SET cultivation = ?, lifespan = ?,
                    cultivation_overflow = 0,
                    cultivating_until = NULL, cultivating_years = NULL, last_active = ?
                WHERE discord_id = ?
            """, (new_cultivation, new_lifespan, now, uid))
            conn.commit()
        needed = cultivation_needed(player["realm"])
        await ctx.send(
            f"{ctx.author.mention} **{player['name']}** 退出闭关。\n"
            f"实际修炼 **{actual_years} 年**，获得修为 **+{gain}**。\n"
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
            return await ctx.send(f"{ctx.author.mention} 修为尚未圆满，还差 **{needed - player['cultivation']}** 点。")
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
            await ctx.send(ctx.author.mention, embed=embed,
                           view=ZhujiBreakthroughView(ctx.author, self, player, has_pill, uid))
            return
        result = await self._do_breakthrough_chain(uid, player, now)
        await ctx.send(f"{ctx.author.mention} {result}")

    @commands.command(name="双修")
    async def dual_cultivate(self, ctx, target: discord.Member = None):
        import json
        uid = str(ctx.author.id)
        if not target:
            return await ctx.send(f"{ctx.author.mention} 用法：`cat!双修 @对方`")
        if target == ctx.author:
            return await ctx.send(f"{ctx.author.mention} 无法与自己双修。")
        if target.bot:
            return await ctx.send(f"{ctx.author.mention} 对方不是修士。")

        inviter = self._get_player(uid)
        target_player = self._get_player(str(target.id))
        if not inviter or inviter["is_dead"]:
            return await ctx.send(f"{ctx.author.mention} 尚未踏入修仙之路或已坐化。")
        if not target_player or target_player["is_dead"]:
            return await ctx.send(f"{ctx.author.mention} 对方尚未踏入修仙之路或已坐化。")

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
            return await ctx.send(f"{ctx.author.mention} 双修需在同一城市，请先找到对方所在之处。")

        now = time.time()
        cooldown_secs = years_to_seconds(2)
        for p, mention in [(inviter, ctx.author.mention), (target_player, target.mention)]:
            if p["last_dual_cultivate"] and now - p["last_dual_cultivate"] < cooldown_secs:
                remaining = seconds_to_years(cooldown_secs - (now - p["last_dual_cultivate"]))
                return await ctx.send(f"{mention} 双修冷却中，还需等待 **{remaining:.1f} 游戏年**。")
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
            mult_desc = f"双方皆为清白之身，阴阳交融，修为暴涨（**{multiplier:.1f}倍**）"
        elif inv_virgin or tgt_virgin:
            multiplier = 5.0
            mult_desc = "一方清白之身，修为大增（**5倍**）"
        else:
            multiplier = 1.2
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
        await ctx.send(target.mention, embed=embed,
                       view=DualCultivateInviteView(self, ctx.author, target, multiplier, both_virgin))

    async def do_dual_cultivate(self, interaction, inviter, target, multiplier, both_virgin):
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
                new_life = p["lifespan"] - years
                conn.execute("""
                    UPDATE players SET lifespan = ?, cultivation_overflow = ?,
                        cultivating_until = ?, cultivating_years = ?,
                        last_dual_cultivate = ?, is_virgin = 0, last_active = ?
                    WHERE discord_id = ?
                """, (new_life, gain, cultivating_until, years, now, now, uid))
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
        embed = discord.Embed(title="✦ 双修 ✦",
                              description=f"{flavor}\n\n双修持续 **1 游戏年**（现实 2 小时）。",
                              color=discord.Color.pink())
        embed.add_field(name=inviter.display_name,
                        value=f"修为 +{inv_gain}（{inv_p['cultivation']}/{inv_needed} → {inv_p['cultivation']+inv_gain}/{inv_needed}）",
                        inline=False)
        embed.add_field(name=target.display_name,
                        value=f"修为 +{tgt_gain}（{tgt_p['cultivation']}/{tgt_needed} → {tgt_p['cultivation']+tgt_gain}/{tgt_needed}）",
                        inline=False)
        await interaction.followup.send(embed=embed)

    @tasks.loop(minutes=1)
    async def _cultivation_notifier(self):
        now = time.time()
        with get_conn() as conn:
            rows = conn.execute(
                "SELECT discord_id, name, cultivation, realm, comprehension, spirit_root_type, "
                "cultivating_years, current_city, cave, pill_buff_until, cultivation_overflow FROM players "
                "WHERE cultivating_until IS NOT NULL AND cultivating_until <= ? AND is_dead = 0",
                (now,)
            ).fetchall()
        for row in rows:
            uid = row["discord_id"]
            if uid in self._notified:
                continue
            self._notified.add(uid)
            years_done = row["cultivating_years"] or 0
            bonus = get_cultivation_bonus(uid, row["current_city"], row["cave"])
            pill_active = row["pill_buff_until"] and now < row["pill_buff_until"]
            if pill_active:
                bonus += 0.5
            overflow = row["cultivation_overflow"] or 0
            gain = overflow if overflow > 0 else int(calc_cultivation_gain(years_done, row["comprehension"], row["spirit_root_type"]) * (1 + bonus))
            new_cultivation = row["cultivation"] + gain
            with get_conn() as conn:
                conn.execute(
                    "UPDATE players SET cultivation = ?, cultivation_overflow = 0, cultivating_until = NULL, cultivating_years = NULL WHERE discord_id = ?",
                    (new_cultivation, uid)
                )
                conn.commit()
            try:
                player = self._get_player(uid)
                needed = cultivation_needed(player["realm"])
                can_bt = self._can_breakthrough(player)
                embed = discord.Embed(title="✦ 闭关结束 ✦", description=f"**{row['name']}** 出关！", color=discord.Color.gold())
                embed.add_field(name="修为获得", value=f"+{gain}", inline=True)
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

    @tasks.loop(minutes=1)
    async def _gathering_notifier(self):
        now = time.time()
        with get_conn() as conn:
            rows = conn.execute(
                "SELECT discord_id, name, gathering_type, gathering_until, current_city, realm FROM players "
                "WHERE gathering_until IS NOT NULL AND gathering_until <= ? AND is_dead = 0",
                (now,)
            ).fetchall()
        for row in rows:
            uid = row["discord_id"]
            notify_key = f"gather_{uid}"
            if notify_key in self._notified:
                continue
            self._notified.add(notify_key)
            from utils.views.gathering import roll_gathering_rewards
            from utils.realms import get_realm_index as _gri
            from utils.db import add_item
            gather_type = row["gathering_type"] or "采矿"
            region_name = row["current_city"]
            realm_idx = _gri(row["realm"])
            with get_conn() as conn:
                p = conn.execute("SELECT gathering_until, last_active FROM players WHERE discord_id = ?", (uid,)).fetchone()
                actual_duration = (p["gathering_until"] - p["last_active"]) if p and p["gathering_until"] else 7200
                years_spent = max(0.25, seconds_to_years(actual_duration))
            rewards = roll_gathering_rewards(years_spent, realm_idx, region_name, gather_type)
            with get_conn() as conn:
                conn.execute("UPDATE players SET gathering_until = NULL, gathering_type = NULL WHERE discord_id = ?", (uid,))
                conn.commit()
            for item_name, qty in rewards:
                add_item(uid, item_name, qty)
            try:
                from utils.views.gathering import TYPE_EMOJI
                from utils.items import ITEMS
                emoji = TYPE_EMOJI.get(gather_type, "⛏️")
                embed = discord.Embed(
                    title=f"✦ {emoji} {gather_type}完成 ✦",
                    description=f"**{row['name']}** 在 **{region_name}** 的{gather_type}已完成！",
                    color=discord.Color.green(),
                )
                if rewards:
                    embed.add_field(name="获得材料", value="\n".join(f"· **{n}** ×{q}" for n, q in rewards), inline=False)
                else:
                    embed.add_field(name="获得材料", value="一无所获…", inline=False)
                total_value = sum(ITEMS.get(n, {}).get("sell_price", 0) * q for n, q in rewards)
                if total_value > 0:
                    embed.set_footer(text=f"材料总价值约 {total_value} 灵石（可使用 cat!出售 [材料名] 出售）")
                user = await self.bot.fetch_user(int(uid))
                await user.send(embed=embed)
            except Exception:
                pass

    @_gathering_notifier.before_loop
    async def _before_gathering_notifier(self):
        await self.bot.wait_until_ready()

    async def cog_load(self):
        self._cultivation_notifier.start()
        self._gathering_notifier.start()

    async def cog_unload(self):
        self._cultivation_notifier.cancel()
        self._gathering_notifier.cancel()


async def setup(bot):
    await bot.add_cog(CultivationCog(bot))
