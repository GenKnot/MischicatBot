import logging
import random
import time

import discord
from discord.ext import commands, tasks

from utils.character import (
    calc_cultivation_gain, years_to_seconds, seconds_to_years,
    get_cultivation_bonus, get_effective_lifespan_max, REALM_LIFESPAN,
)
from utils.realms import cultivation_needed, lifespan_max_for_realm
from utils.config import COMMAND_PREFIX
from utils.views import MainMenuView, ProfileView, CultivateView, ClaimCultivationView, DualCultivateInviteView, YinYangView, _build_menu_embed
from sqlalchemy import text
from utils.db_async import AsyncSessionLocal
from utils.world import CITIES
from utils.player import get_player, is_defending, settle_time, apply_updates, can_breakthrough

log = logging.getLogger(__name__)

from utils.death_rebirth_logic import (
    check_death, handle_death, handle_rebirth, can_rebirth,
    should_trigger_yinyang, mark_yinyang_triggered, calculate_rebirth_bonus
)
from utils.breakthrough_logic import (
    can_breakthrough as async_can_breakthrough,
    do_breakthrough_chain as async_do_breakthrough_chain,
    handle_zhuji_breakthrough, handle_ningdan_breakthrough, handle_huaying_breakthrough
)
from utils.dual_cultivation_logic import (
    check_dual_requirements, start_dual_cultivation
)
from utils.cultivation_logic import (
    start_cultivation as async_start_cultivation,
    stop_cultivation as async_stop_cultivation,
    claim_cultivation as async_claim_cultivation
)


class CultivationCog(commands.Cog, name="Cultivation"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._notified: set[str] = set()

    def _calc_rebirth_bonus(self, player: dict) -> dict:
        return calculate_rebirth_bonus(player)

    async def _check_dead(self, ctx, player) -> bool:
        uid = str(ctx.author.id)
        is_dead, player_dict = await check_death(uid)
        
        if not is_dead:
            return False
        
        if await self._try_yinyang(ctx, player, uid):
            return True
        
        can_reb, player_dict = await can_rebirth(uid)
        
        if can_reb:
            result = await handle_rebirth(uid, player_dict)
            if result["success"]:
                bonus_str = "  ".join(f"{k} +{v}" for k, v in result["bonus"].items() if v > 0)
                await ctx.send(
                    f"{ctx.author.mention} **{result['name']}** 寿元已尽，魂归天道。\n"
                    f"然而——**{result['reason']}**，道友得以轮回重生！\n"
                    f"第 **{result['rebirth_count']}** 次轮回，携带前世感悟：{bonus_str}\n"
                    f"可使用 `{COMMAND_PREFIX}查看` 查看新角色。"
                )
        else:
            result = await handle_death(uid)
            if result["success"]:
                await ctx.send(
                    f"{ctx.author.mention} 道友 **{result['name']}** 寿元已尽，魂归天道。\n"
                    f"尘归尘，土归土，可使用 `{COMMAND_PREFIX}创建角色` 重入修仙之路。"
                )
        
        return True

    async def _handle_death(self, ctx, player, uid: str):
        pass

    async def _try_yinyang(self, ctx, player, uid: str) -> bool:
        if not should_trigger_yinyang(player):
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
        player = await get_player(uid)
        if not player:
            return await interaction.followup.send(f"尚未踏入修仙之路，请先使用 `{COMMAND_PREFIX}创建角色`。")
        updates, _ = await settle_time(player)
        await apply_updates(uid, updates)
        player = await get_player(uid)
        if player["lifespan"] <= 0 or player["is_dead"]:
            async with AsyncSessionLocal() as session:
                await session.execute(text("UPDATE players SET is_dead = 1 WHERE discord_id = :uid"), {"uid": uid})
                await session.commit()
            return await interaction.followup.send(
                f"道友 **{player['name']}** 寿元已尽，魂归天道。\n可使用 `{COMMAND_PREFIX}创建角色` 重入修仙之路。"
            )
        now = time.time()
        needed = cultivation_needed(player["realm"])
        is_cultivating = bool(player["cultivating_until"] and now < player["cultivating_until"])
        can_bt = can_breakthrough(player)
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
        eff_max = get_effective_lifespan_max(player)
        lifespan_str = f"{player['lifespan']} / {eff_max} 年" + ("（含功法）" if eff_max > player['lifespan_max'] else "")
        embed.add_field(name="寿元", value=lifespan_str, inline=True)
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
        from utils.combat import calc_power, calc_escape_rate
        power = await calc_power(player)
        escape_pct = (await calc_escape_rate(player)) * 100
        embed.add_field(name="综合战力", value=f"{power:.1f}", inline=True)
        embed.add_field(name="逃跑成功率", value=f"{escape_pct:.1f}%", inline=True)
        alchemy_level = player.get("alchemy_level", 0)
        if alchemy_level > 0:
            from utils.alchemy import ALCHEMY_EXP_THRESHOLDS
            alchemy_exp = player.get("alchemy_exp", 0)
            next_exp = ALCHEMY_EXP_THRESHOLDS[alchemy_level + 1] if alchemy_level < 9 and alchemy_level + 1 < len(ALCHEMY_EXP_THRESHOLDS) else None
            exp_str = f"{alchemy_exp} / {next_exp}" if next_exp else f"{alchemy_exp}（满级）"
            embed.add_field(name=f"炼丹师 {alchemy_level} 品", value=f"经验 {exp_str}", inline=False)
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                text("SELECT discord_id, name, realm, cultivation FROM players WHERE current_city = :city AND is_dead = 0 AND discord_id != :uid"),
                {"city": player["current_city"], "uid": uid}
            )
            city_rows = result.fetchall()
        city_players = [dict(r._mapping) for r in city_rows]
        await interaction.followup.send(
            interaction.user.mention, embed=embed,
            view=ProfileView(interaction.user, can_bt, is_cultivating, self, player, city_players)
        )

    async def send_cultivate(self, interaction: discord.Interaction):
        uid = str(interaction.user.id)
        player = await get_player(uid)
        if not player:
            return await interaction.followup.send("尚未踏入修仙之路。")
        updates, _ = await settle_time(player)
        await apply_updates(uid, updates)
        player = await get_player(uid)
        if player["lifespan"] <= 0 or player["is_dead"]:
            return await interaction.followup.send("道友寿元已尽，无法修炼。")
        now = time.time()
        if player["cultivating_until"] and now < player["cultivating_until"]:
            remaining = seconds_to_years(player["cultivating_until"] - now)
            return await interaction.followup.send(f"道友正在闭关，还剩约 **{remaining:.1f} 年**，可使用 `{COMMAND_PREFIX}停止` 提前结束。")
        if player["gathering_until"] and now < player["gathering_until"]:
            remaining = seconds_to_years(player["gathering_until"] - now)
            return await interaction.followup.send(f"道友正在采集中，无法修炼。还剩约 **{remaining:.1f} 年**。")
        if await is_defending(uid):
            return await interaction.followup.send("守城期间无法修炼，专心守城！", ephemeral=True)
        from utils.character import SPIRIT_ROOT_SPEED
        bonus = await get_cultivation_bonus(uid, player["current_city"], player.get("cave"))
        root_mult = SPIRIT_ROOT_SPEED.get(player["spirit_root_type"], 1.0)
        root_label = {
            "单灵根": "极快", "双灵根": "较快", "三灵根": "普通",
            "四灵根": "较慢", "五灵根": "迟缓", "变异灵根": "特殊",
        }.get(player["spirit_root_type"], "未知")
        embed = discord.Embed(
            title="✦ 选择闭关时长 ✦",
            description=(
                f"当前寿元：**{player['lifespan']} 年**\n"
                f"灵根速度：**{root_label}（×{root_mult}）**\n"
                f"修炼加成：**+{int(bonus * 100)}%**\n\n"
                "请选择本次闭关时长："
            ),
            color=discord.Color.teal(),
        )
        await interaction.followup.send(embed=embed, view=CultivateView(interaction.user, self, player))

    async def start_cultivate(self, interaction: discord.Interaction, years: int):
        uid = str(interaction.user.id)

        if await is_defending(uid):
            return await interaction.followup.send("守城期间无法修炼，专心守城！", ephemeral=True)
        
        result = await async_start_cultivation(uid, years)
        
        if not result["success"]:
            return await interaction.followup.send(result["message"])
        
        pill_note = f"（修炼速度加成 +{int(result['speed_bonus'] * 100)}%）\n" if result.get("speed_bonus", 0) > 0 else ""
        
        await interaction.followup.send(
            f"{interaction.user.mention} **{result['name']}** 开始闭关修炼 **{years} 年**（现实 {years * 2} 小时）。\n"
            f"{pill_note}"
            f"修为进度：{result['cultivation']}/{result['needed']}，出关后将获得约 +{result['gain']}\n"
            f"闭关结束后将收到通知。"
        )

    async def claim_cultivation(self, interaction: discord.Interaction, uid: str):
        result = await async_claim_cultivation(uid)
        
        if not result["success"]:
            return await interaction.response.send_message(result["message"])
        
        self._notified.discard(uid)
        
        can_bt = result["cultivation"] >= result["needed"]
        
        embed = discord.Embed(title="✦ 修炼成果已领取 ✦", description=f"**{result['name']}** 出关！", color=discord.Color.teal())
        embed.add_field(name="修为获得", value=f"+{result['gain']}", inline=True)
        embed.add_field(name="当前修为", value=f"{result['cultivation']} / {result['needed']}", inline=True)
        embed.add_field(name="剩余寿元", value=f"{result['lifespan']} 年", inline=True)
        if can_bt:
            embed.add_field(name="提示", value="修为已圆满，可尝试突破！", inline=False)
        await interaction.response.send_message(embed=embed)

    async def send_breakthrough(self, interaction: discord.Interaction):
        uid = str(interaction.user.id)
        player = await get_player(uid)
        if not player:
            return await interaction.followup.send("尚未踏入修仙之路。")
        updates, _ = await settle_time(player)
        await apply_updates(uid, updates)
        player = await get_player(uid)
        now = time.time()
        if player["cultivating_until"] and now < player["cultivating_until"]:
            return await interaction.followup.send("请先结束闭关再尝试突破。")
        if not can_breakthrough(player):
            needed = cultivation_needed(player["realm"])
            return await interaction.followup.send(f"修为尚未圆满，还差 **{needed - player['cultivation']}** 点。")

        if player["realm"] == "炼气期10层":
            from utils.items import calc_zhuji_breakthrough_rate, can_skip_pill
            from utils.inventory import has_item
            from utils.views.cultivation import ZhujiBreakthroughView
            has_pill = await has_item(uid, "筑基丹")
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
            from utils.inventory import has_item
            from utils.views.cultivation import NingdanBreakthroughView
            has_pill = await has_item(uid, "凝丹丹")
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
            from utils.inventory import has_item
            from utils.views.cultivation import HuayingBreakthroughView
            has_pill = await has_item(uid, "化婴丹")
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
        result = await async_do_breakthrough_chain(uid)
        
        if not result["success"]:
            return result["message"]
        
        chain = result["chain"]
        successes = result["successes"]
        fail_line = result["fail_line"]
        
        if len(chain) == 1:
            prefix = "🎉 突破成功！\n" if "➜" in chain[0] else ""
            return prefix + chain[0]
        
        msg = f"🎉 **{player['name']}** 连续突破 {len(successes)} 次！\n" + "\n".join(successes)
        if fail_line:
            msg += f"\n\n{fail_line}"
        return msg

    async def send_stop(self, interaction: discord.Interaction):
        uid = str(interaction.user.id)
        result = await async_stop_cultivation(uid)
        
        if not result["success"]:
            return await interaction.followup.send(result["message"])
        
        if not result["is_dual"]:
            msg = (
                f"**{result['name']}** 退出闭关。\n"
                f"实际修炼 **{result['actual_years']} 年**，获得修为 **+{result['gain']}**。\n"
                f"修为进度：{result['cultivation']}/{result['needed']}　寿元剩余：{result['lifespan']} 年"
            )
        else:
            msg = (
                f"✦ 双修中止 ✦\n"
                f"你停止了双修，**双方已同时出关**。\n\n"
                f"你（**{result['name']}**）：实际修炼 **{result['actual_years']} 年**，修为 **+{result['gain']}**，进度 {result['cultivation']}/{result['needed']}，寿元 {result['lifespan']} 年\n"
                f"对方（**{result['partner_name']}**）：实际修炼 **{result['partner_years']} 年**，修为 **+{result['partner_gain']}**，寿元 {result['partner_lifespan']} 年"
            )
            
            try:
                user = await self.bot.fetch_user(int(result['partner_id']))
                partner_msg = (
                    f"✦ 双修中止 ✦\n"
                    f"因对方提前停止，你也已出关。\n"
                    f"实际修炼 **{result['partner_years']} 年**，获得修为 **+{result['partner_gain']}**。\n"
                    f"修为进度：{result['partner_cultivation']}/{result['partner_needed']}　寿元剩余：{result['partner_lifespan']} 年"
                )
                await user.send(partner_msg)
            except Exception:
                # 对方关了私信是常态，不当错误处理
                log.debug("私信发送失败", exc_info=True)
        
        await interaction.followup.send(f"{interaction.user.mention} {msg}")

    async def _stop_cultivation_with_pair(self, uid: str, now: float, actor_name: str = "") -> str | None:
        result = await async_stop_cultivation(uid)
        
        if not result["success"]:
            return None
        
        if not result["is_dual"]:
            return (
                f"**{result['name']}** 退出闭关。\n"
                f"实际修炼 **{result['actual_years']} 年**，获得修为 **+{result['gain']}**。\n"
                f"修为进度：{result['cultivation']}/{result['needed']}　寿元剩余：{result['lifespan']} 年"
            )
        
        try:
            user = await self.bot.fetch_user(int(result['partner_id']))
            partner_msg = (
                f"✦ 双修中止 ✦\n"
                f"因对方提前停止，你也已出关。\n"
                f"实际修炼 **{result['partner_years']} 年**，获得修为 **+{result['partner_gain']}**。\n"
                f"修为进度：{result['partner_cultivation']}/{result['partner_needed']}　寿元剩余：{result['partner_lifespan']} 年"
            )
            await user.send(partner_msg)
        except Exception:
            pass
        
        return (
            f"✦ 双修中止 ✦\n"
            f"你停止了双修，**双方已同时出关**。\n\n"
            f"你（**{result['name']}**）：实际修炼 **{result['actual_years']} 年**，修为 **+{result['gain']}**，进度 {result['cultivation']}/{result['needed']}，寿元 {result['lifespan']} 年\n"
            f"对方（**{result['partner_name']}**）：实际修炼 **{result['partner_years']} 年**，修为 **+{result['partner_gain']}**，寿元 {result['partner_lifespan']} 年"
        )

    async def _send_menu(self, ctx, *, gameplay_only: bool):
        import json
        uid = str(ctx.author.id)
        player = await get_player(uid)
        if not player or player.get("is_dead"):
            char_cog = self.bot.cogs.get("Character")
            if not char_cog:
                return await ctx.send(f"{ctx.author.mention} 角色系统暂时不可用。")
            return await char_cog.create_character(ctx)
        if player and not player["is_dead"]:
            updates, _ = await settle_time(player)
            await apply_updates(uid, updates)
            player = await get_player(uid)
        has_player = player is not None and not player["is_dead"]
        can_bt = has_player and can_breakthrough(player)
        has_dual = has_player and any(
            (t if isinstance(t, str) else t.get("name", "")) == "双修功法"
            for t in json.loads(player["techniques"] or "[]")
        )
        city_players = []
        if has_player:
            async with AsyncSessionLocal() as session:
                result = await session.execute(
                    text("SELECT discord_id, name, realm, cultivation FROM players WHERE current_city = :city AND is_dead = 0 AND discord_id != :uid"),
                    {"city": player["current_city"], "uid": uid}
                )
                rows = result.fetchall()
            city_players = [dict(r._mapping) for r in rows]
        embed = _build_menu_embed(has_dual, gameplay_only=gameplay_only)
        await ctx.send(embed=embed, view=MainMenuView(ctx.author, has_player, can_bt, self, player, city_players))

    @commands.hybrid_command(name="c", description="主菜单（仅玩法说明）：有角色则打开主菜单，无角色则进入创建流程")
    async def menu_c(self, ctx):
        await self._send_menu(ctx, gameplay_only=True)

    @commands.hybrid_command(name="h", description="完整指令列表：有角色则打开主菜单与指令速查，无角色则进入创建流程")
    async def menu_h(self, ctx):
        await self._send_menu(ctx, gameplay_only=False)

    async def _send_profile_ctx(self, ctx):
        uid = str(ctx.author.id)
        player = await get_player(uid)
        if not player:
            return await ctx.send(f"{ctx.author.mention} 尚未踏入修仙之路，请先使用 `{COMMAND_PREFIX}创建角色`。")
        updates, _ = await settle_time(player)
        await apply_updates(uid, updates)
        player = await get_player(uid)
        if await self._check_dead(ctx, player):
            return
        now = time.time()
        needed = cultivation_needed(player["realm"])
        is_cultivating = bool(player["cultivating_until"] and now < player["cultivating_until"])
        can_bt = can_breakthrough(player)
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
        eff_max = get_effective_lifespan_max(player)
        lifespan_str = f"{player['lifespan']} / {eff_max} 年" + ("（含功法）" if eff_max > player['lifespan_max'] else "")
        embed.add_field(name="寿元", value=lifespan_str, inline=True)
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
        from utils.combat import calc_power, calc_escape_rate
        power = await calc_power(player)
        escape_pct = (await calc_escape_rate(player)) * 100
        embed.add_field(name="综合战力", value=f"{power:.1f}", inline=True)
        embed.add_field(name="逃跑成功率", value=f"{escape_pct:.1f}%", inline=True)
        alchemy_level = player.get("alchemy_level", 0)
        if alchemy_level > 0:
            from utils.alchemy import ALCHEMY_EXP_THRESHOLDS
            alchemy_exp = player.get("alchemy_exp", 0)
            next_exp = ALCHEMY_EXP_THRESHOLDS[alchemy_level + 1] if alchemy_level < 9 and alchemy_level + 1 < len(ALCHEMY_EXP_THRESHOLDS) else None
            exp_str = f"{alchemy_exp} / {next_exp}" if next_exp else f"{alchemy_exp}（满级）"
            embed.add_field(name=f"炼丹师 {alchemy_level} 品", value=f"经验 {exp_str}", inline=False)
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                text("SELECT discord_id, name, realm, cultivation FROM players WHERE current_city = :city AND is_dead = 0 AND discord_id != :uid"),
                {"city": player["current_city"], "uid": uid}
            )
            city_rows = result.fetchall()
        city_players = [dict(r._mapping) for r in city_rows]
        await ctx.send(
            ctx.author.mention, embed=embed,
            view=ProfileView(ctx.author, can_bt, is_cultivating, self, player, city_players)
        )

    @commands.hybrid_command(
        name="我的角色",
        aliases=["m", "me", "我"],
        description="显示我的角色面板",
    )
    async def my_character(self, ctx):
        await self._send_profile_ctx(ctx)

    @commands.hybrid_command(name="查看", aliases=["ck"], description="查看当前角色的修为、寿元与状态")
    async def view(self, ctx):
        await self._send_profile_ctx(ctx)

    @commands.hybrid_command(name="修炼", aliases=["xl"], description="消耗寿元进行闭关修炼，提升修为")
    async def cultivate(self, ctx, years: int = 1):
        uid = str(ctx.author.id)
        player = await get_player(uid)
        if not player:
            return await ctx.send(f"{ctx.author.mention} 尚未踏入修仙之路，请先使用 `{COMMAND_PREFIX}创建角色`。")
        updates, _ = await settle_time(player)
        await apply_updates(uid, updates)
        player = await get_player(uid)
        if await self._check_dead(ctx, player):
            return
        now = time.time()
        if player["cultivating_until"] and now < player["cultivating_until"]:
            remaining = seconds_to_years(player["cultivating_until"] - now)
            return await ctx.send(f"{ctx.author.mention} 道友正在闭关修炼，还剩约 **{remaining:.1f} 年**，可使用 `{COMMAND_PREFIX}停止` 提前结束。")
        if player["gathering_until"] and now < player["gathering_until"]:
            remaining = seconds_to_years(player["gathering_until"] - now)
            return await ctx.send(f"{ctx.author.mention} 道友正在采集中，无法修炼。还剩约 **{remaining:.1f} 年**。")
        if await is_defending(uid):
            return await ctx.send(f"{ctx.author.mention} 守城期间无法修炼，专心守城！")
        if years < 1 or years > 100:
            return await ctx.send("修炼年数需在 1 至 100 之间。")
        if player["lifespan"] < years:
            return await ctx.send(f"{ctx.author.mention} 寿元不足，剩余寿元 **{player['lifespan']} 年**，无法修炼 {years} 年。")
        cultivating_until = now + years_to_seconds(years)
        bonus = await get_cultivation_bonus(uid, player["current_city"], player.get("cave"))
        from utils.buffs import get_cultivation_speed_bonus
        speed_bonus = get_cultivation_speed_bonus(player)
        if speed_bonus > 0:
            bonus += speed_bonus
        gain = int(calc_cultivation_gain(years, player["comprehension"], player["spirit_root_type"]) * (1 + bonus))
        async with AsyncSessionLocal() as session:
            await session.execute(
                text("UPDATE players SET cultivating_until = :until, cultivating_years = :years, last_active = :now WHERE discord_id = :uid"),
                {"until": cultivating_until, "years": years, "now": now, "uid": uid}
            )
            await session.commit()
        needed = cultivation_needed(player["realm"])
        pill_note = f"（修炼速度加成 +{int(speed_bonus * 100)}%）\n" if speed_bonus > 0 else ""
        await ctx.send(
            f"{ctx.author.mention} **{player['name']}** 开始闭关修炼 **{years} 年**。\n"
            f"{pill_note}预计现实时间 **{years * 2} 小时**后结束。\n"
            f"修为进度：{player['cultivation']}/{needed}，出关后将获得约 +{gain}"
        )

    @commands.hybrid_command(name="停止", aliases=["tz"], description="提前结束当前的闭关修炼")
    async def stop_cultivate(self, ctx):
        uid = str(ctx.author.id)
        player = await get_player(uid)
        if not player:
            return await ctx.send(f"{ctx.author.mention} 尚未踏入修仙之路。")
        now = time.time()
        if not player["cultivating_until"] or now >= player["cultivating_until"]:
            return await ctx.send(f"{ctx.author.mention} 道友当前并未在闭关。")
        result = await self._stop_cultivation_with_pair(uid, now, actor_name=ctx.author.display_name)
        if not result:
            return await ctx.send(f"{ctx.author.mention} 道友当前并未在闭关。")
        await ctx.send(f"{ctx.author.mention} {result}")

    @commands.hybrid_command(name="突破", aliases=["tp"], description="尝试突破当前境界，成功可提升大境界与寿元")
    async def breakthrough(self, ctx):
        uid = str(ctx.author.id)
        player = await get_player(uid)
        if not player:
            return await ctx.send(f"{ctx.author.mention} 尚未踏入修仙之路，请先使用 `{COMMAND_PREFIX}创建角色`。")
        updates, _ = await settle_time(player)
        await apply_updates(uid, updates)
        player = await get_player(uid)
        if await self._check_dead(ctx, player):
            return
        now = time.time()
        if player["cultivating_until"] and now < player["cultivating_until"]:
            return await ctx.send(f"{ctx.author.mention} 请先结束闭关再尝试突破。")
        if not can_breakthrough(player):
            needed = cultivation_needed(player["realm"])
            return await ctx.send(f"{ctx.author.mention} 修为尚未圆满，还差 **{needed - player['cultivation']}** 点。")
        if player["realm"] == "炼气期10层":
            from utils.items import calc_zhuji_breakthrough_rate, can_skip_pill
            from utils.inventory import has_item
            from utils.views.cultivation import ZhujiBreakthroughView
            has_pill = await has_item(uid, "筑基丹")
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

    @commands.hybrid_command(name="双修", aliases=["sx"], description="与一名指定修士进行双修，共享修炼收益")
    async def dual_cultivate(self, ctx, target: discord.Member = None):
        import json
        uid = str(ctx.author.id)
        if not target:
            return await ctx.send(f"{ctx.author.mention} 用法：`{COMMAND_PREFIX}双修 @对方`")
        if target == ctx.author:
            return await ctx.send(f"{ctx.author.mention} 无法与自己双修。")
        if target.bot:
            return await ctx.send(f"{ctx.author.mention} 对方不是修士。")

        inviter = await get_player(uid)
        target_player = await get_player(str(target.id))
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
        inv_uid = str(inviter.id)
        tgt_uid = str(target.id)
        
        result = await start_dual_cultivation(inv_uid, tgt_uid)
        
        if not result["success"]:
            return await interaction.followup.send(f"双修失败：{result['message']}")
        
        embed = discord.Embed(
            title="✦ 双修 ✦",
            description=f"{result['flavor']}\n\n双修持续 **1 游戏年**（现实 2 小时）。",
            color=discord.Color.pink()
        )
        embed.add_field(
            name=inviter.display_name,
            value=f"修为 +{result['inviter_gain']}（{result['inviter_cultivation']}/{result['inviter_needed']} → {result['inviter_cultivation']+result['inviter_gain']}/{result['inviter_needed']}）",
            inline=False
        )
        embed.add_field(
            name=target.display_name,
            value=f"修为 +{result['target_gain']}（{result['target_cultivation']}/{result['target_needed']} → {result['target_cultivation']+result['target_gain']}/{result['target_needed']}）",
            inline=False
        )
        await interaction.followup.send(embed=embed)

    @tasks.loop(minutes=1)
    async def _cultivation_notifier(self):
        now = time.time()
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                text("SELECT discord_id, name, cultivation, realm, comprehension, spirit_root_type, cultivating_years, current_city, cave, active_buffs, cultivation_overflow FROM players WHERE cultivating_until IS NOT NULL AND cultivating_until <= :now AND is_dead = 0"),
                {"now": now}
            )
            rows = result.fetchall()
        for row in rows:
            uid = row._mapping["discord_id"]
            if uid in self._notified:
                continue
            self._notified.add(uid)
            years_done = row._mapping["cultivating_years"] or 0
            bonus = await get_cultivation_bonus(uid, row._mapping["current_city"], row._mapping["cave"])
            from utils.buffs import get_cultivation_speed_bonus
            speed_bonus = get_cultivation_speed_bonus(dict(row._mapping))
            if speed_bonus > 0:
                bonus += speed_bonus
            overflow = row._mapping["cultivation_overflow"] or 0
            gain = overflow if overflow > 0 else int(calc_cultivation_gain(years_done, row._mapping["comprehension"], row._mapping["spirit_root_type"]) * (1 + bonus))
            new_cultivation = row._mapping["cultivation"] + gain
            async with AsyncSessionLocal() as session:
                await session.execute(
                    text("UPDATE players SET cultivation = :cultivation, cultivation_overflow = 0, cultivating_until = NULL, cultivating_years = NULL, dual_partner_id = NULL WHERE discord_id = :uid"),
                    {"cultivation": new_cultivation, "uid": uid}
                )
                await session.commit()
            try:
                player = await get_player(uid)
                needed = cultivation_needed(player["realm"])
                can_bt = can_breakthrough(player)
                embed = discord.Embed(title="✦ 闭关结束 ✦", description=f"**{row['name']}** 出关！", color=discord.Color.gold())
                embed.add_field(name="修为获得", value=f"+{gain}", inline=True)
                embed.add_field(name="当前修为", value=f"{player['cultivation']} / {needed}", inline=True)
                embed.add_field(name="剩余寿元", value=f"{player['lifespan']} 年", inline=True)
                if can_bt:
                    embed.add_field(name="提示", value="修为已圆满，可尝试突破！", inline=False)
                user = await self.bot.fetch_user(int(uid))
                await user.send(embed=embed)
            except Exception:
                # 对方关了私信是常态，不当错误处理
                log.debug("私信发送失败", exc_info=True)

    @_cultivation_notifier.before_loop
    async def _before_notifier(self):
        await self.bot.wait_until_ready()

    @tasks.loop(minutes=1)
    async def _gathering_notifier(self):
        now = time.time()
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                text("SELECT discord_id, name, gathering_type, gathering_until, current_city, realm FROM players WHERE gathering_until IS NOT NULL AND gathering_until <= :now AND is_dead = 0"),
                {"now": now}
            )
            rows = result.fetchall()
        for row in rows:
            uid = row._mapping["discord_id"]
            notify_key = f"gather_{uid}"
            if notify_key in self._notified:
                continue
            self._notified.add(notify_key)
            from utils.views.gathering import roll_gathering_rewards
            from utils.realms import get_realm_index as _gri
            from utils.inventory import add_item
            gather_type = row._mapping["gathering_type"] or "采矿"
            region_name = row._mapping["current_city"]
            realm_idx = _gri(row._mapping["realm"])
            async with AsyncSessionLocal() as session:
                result = await session.execute(
                    text("SELECT gathering_until, last_active, gathering_bonus FROM players WHERE discord_id = :uid"),
                    {"uid": uid}
                )
                p = result.fetchone()
            actual_duration = (p._mapping["gathering_until"] - p._mapping["last_active"]) if p and p._mapping["gathering_until"] else 7200
            years_spent = max(0.25, seconds_to_years(actual_duration))
            saved_bonus = p._mapping["gathering_bonus"] if p else 0
            rewards = roll_gathering_rewards(years_spent, realm_idx, region_name, gather_type, gather_bonus=saved_bonus or 0)
            async with AsyncSessionLocal() as session:
                await session.execute(
                    text("UPDATE players SET gathering_until = NULL, gathering_type = NULL WHERE discord_id = :uid"),
                    {"uid": uid}
                )
                await session.commit()
            for item_name, qty in rewards:
                await add_item(uid, item_name, qty)
            try:
                from utils.views.gathering import TYPE_EMOJI
                from utils.items import ITEMS
                emoji = TYPE_EMOJI.get(gather_type, "⛏️")
                embed = discord.Embed(
                    title=f"✦ {emoji} {gather_type}完成 ✦",
                    description=f"**{row._mapping['name']}** 在 **{region_name}** 的{gather_type}已完成！",
                    color=discord.Color.green(),
                )
                if rewards:
                    embed.add_field(name="获得材料", value="\n".join(f"· **{n}** ×{q}" for n, q in rewards), inline=False)
                else:
                    embed.add_field(name="获得材料", value="一无所获…", inline=False)
                total_value = sum(ITEMS.get(n, {}).get("sell_price", 0) * q for n, q in rewards)
                if total_value > 0:
                    embed.set_footer(text=f"材料总价值约 {total_value} 灵石（可使用 {COMMAND_PREFIX}出售 [材料名] 出售）")
                user = await self.bot.fetch_user(int(uid))
                await user.send(embed=embed)
            except Exception:
                # 对方关了私信是常态，不当错误处理
                log.debug("私信发送失败", exc_info=True)

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
