import json
import time
import random

import discord
from discord.ext import commands, tasks

from utils.config import COMMAND_PREFIX
from utils.db_async import AsyncSessionLocal, Player
from utils.quests import get_tavern_quests, get_quest
from utils.combat import calc_power
from utils.character import years_to_seconds, seconds_to_years
from utils import quest_logic


QUALITY_EMOJI = {"普通": "⬜", "精良": "🟩", "稀有": "🟦", "史诗": "🟪", "传说": "🟨"}


def _reward_lines(rewards: dict) -> list[str]:
    from utils.sects import TECHNIQUES
    lines = []
    stat_names = {"comprehension": "悟性", "physique": "体魄", "fortune": "机缘",
                  "bone": "根骨", "soul": "神识", "lifespan": "寿元"}
    if rewards.get("spirit_stones"):
        lines.append(f"灵石 +{rewards['spirit_stones']}")
    if rewards.get("reputation"):
        lines.append(f"声望 +{rewards['reputation']}")
    if rewards.get("cultivation"):
        lines.append(f"修为 +{rewards['cultivation']}")
    if rewards.get("lifespan"):
        lines.append(f"寿元 +{rewards['lifespan']} 年")
    if rewards.get("technique"):
        t = rewards["technique"]
        grade = TECHNIQUES.get(t, {}).get("grade", "?")
        lines.append(f"功法：**{t}**（{grade}）")
    if rewards.get("stat_bonus"):
        for stat, val in rewards["stat_bonus"].items():
            lines.append(f"{stat_names.get(stat, stat)} 永久 +{val}")
    if rewards.get("equipment"):
        eq = rewards["equipment"]
        chance = eq.get("chance", 1.0)
        quality_hint = eq.get("quality", "随机")
        if chance < 1.0:
            lines.append(f"装备：{QUALITY_EMOJI.get(quality_hint, '🎲')} {quality_hint}品质（{int(chance*100)}% 概率）")
        else:
            lines.append(f"装备：{QUALITY_EMOJI.get(quality_hint, '🎲')} {quality_hint}品质（必得）")
    return lines


TIER_COLOR = {
    "普通": discord.Color.teal(),
    "精英": discord.Color.gold(),
    "传说": discord.Color.dark_purple(),
}

TIER_EMOJI = {"普通": "📋", "精英": "⚔️", "传说": "🌟"}
QUEST_DURATION = {"普通": 1, "精英": 1, "传说": 1}
GATHER_DURATION = {"普通": 2, "精英": 2, "传说": 2}


class TavernCog(commands.Cog, name="Tavern"):
    def __init__(self, bot):
        self.bot = bot
        self._notified: set[str] = set()

    async def _auto_resolve_quest(self, uid: str):
        result = await quest_logic.resolve_quest(uid)
        if not result.get("success"):
            return
        
        embed = self._build_result_embed(result)
        
        try:
            user = await self.bot.fetch_user(int(uid))
            await user.send(embed=embed)
        except Exception:
            pass

    @tasks.loop(minutes=1)
    async def _quest_notifier(self):
        now = time.time()
        async with AsyncSessionLocal() as session:
            from sqlalchemy import select
            result = await session.execute(
                select(Player).where(
                    Player.active_quest.isnot(None),
                    Player.quest_due <= now,
                    Player.is_dead == 0
                )
            )
            players = result.scalars().all()
        
        for player in players:
            uid = player.discord_id
            if uid in self._notified:
                continue
            self._notified.add(uid)
            await self._auto_resolve_quest(uid)
            self._notified.discard(uid)

    @_quest_notifier.before_loop
    async def _before_notifier(self):
        await self.bot.wait_until_ready()

    async def cog_load(self):
        self._quest_notifier.start()

    async def cog_unload(self):
        self._quest_notifier.cancel()

    @commands.hybrid_command(name="签到", aliases=["qd"], description="每日签到，随机获得灵石/材料/功法/装备")
    async def checkin(self, ctx):
        from utils.views.checkin import CheckinView
        from utils.db_async import AsyncSessionLocal, Player
        import time

        uid = str(ctx.author.id)
        async with AsyncSessionLocal() as session:
            player = await session.get(Player, uid)
        if not player:
            return await ctx.send(f"{ctx.author.mention} 请先创建角色。")

        today = time.strftime("%Y-%m-%d", time.gmtime())
        if (player.checkin_last_date or "") == today:
            return await ctx.send(f"{ctx.author.mention} 今日已签到，明日再来。")

        embed = discord.Embed(
            title="✦ 每日签到 ✦",
            description="点击下方按钮领取今日奖励，每日一次。",
            color=discord.Color.gold(),
        )
        await ctx.send(ctx.author.mention, embed=embed, view=CheckinView(ctx.author, {"discord_id": uid}, self))

    @commands.hybrid_command(name="茶馆", aliases=["cg"], description="前往茶馆接取任务或采集委托")
    async def tavern(self, ctx):
        uid = str(ctx.author.id)
        async with AsyncSessionLocal() as session:
            player = await session.get(Player, uid)
            if not player or player.is_dead:
                return await ctx.send(f"{ctx.author.mention} 尚未踏入修仙之路或已坐化。")

            from utils.world import get_region
            if get_region(player.current_city or ""):
                return await ctx.send(f"{ctx.author.mention} 此处是秘地荒野，没有茶馆。请先返回城市。")

            if player.current_city == "万宝楼":
                from utils.events.public.wanbao import get_active_auction
                auction = await get_active_auction()
                if auction and auction["status"] == "active":
                    return await ctx.send(f"{ctx.author.mention} 万宝楼拍卖会进行中，茶馆暂停营业。请前往其他城市接取任务。")

            if player.active_quest:
                q_data = json.loads(player.active_quest)
                due = player.quest_due or 0
                remaining = seconds_to_years(max(0, due - time.time()))
                return await ctx.send(
                    f"{ctx.author.mention} 你正在执行任务「**{q_data['title']}**」，"
                    f"还需约 **{remaining:.1f} 游戏年**（现实 {remaining*2:.1f} 小时）。\n"
                    f"任务完成后使用 `{COMMAND_PREFIX}交任务` 领取奖励。"
                )

            player_dict = {
                "realm": player.realm,
                "current_city": player.current_city,
            }
            quests = get_tavern_quests(player_dict)
            if not quests or (len(quests) == 1 and "_locked" in quests):
                return await ctx.send(f"{ctx.author.mention} 当前没有适合你境界的任务。")

            embed = discord.Embed(
                title=f"✦ {player.current_city} · 茶馆任务栏 ✦",
                description="掌柜将任务榜递来，上面贴满了各色悬赏……",
                color=discord.Color.teal(),
            )
            for tier, quest_list in quests.items():
                if tier == "_locked":
                    embed.add_field(name="🔒 未解锁", value="\n".join(quest_list), inline=False)
                    continue
                dur = GATHER_DURATION[tier]
                lines = []
                for q in quest_list:
                    reward_preview = "、".join(_reward_lines(q["rewards"])[:2])
                    time_cost = dur if q["type"] == "gather" else QUEST_DURATION[tier]
                    lines.append(
                        f"{TIER_EMOJI[tier]} **{q['title']}**（耗时 {time_cost} 游戏年）\n"
                        f"　{q['desc'][:28]}…\n"
                        f"　奖励：{reward_preview}"
                    )
                embed.add_field(name=f"── {tier}任务 ──", value="\n\n".join(lines), inline=False)

            embed.set_footer(text="战斗任务耗时1年 · 采集任务耗时2年 · 任务期间无法闭关")
            await ctx.send(embed=embed, view=TavernView(ctx.author, quests, self))

    @commands.hybrid_command(name="交任务", aliases=["jrw"], description="在茶馆结算当前进行中的任务")
    async def submit_quest(self, ctx):
        uid = str(ctx.author.id)
        async with AsyncSessionLocal() as session:
            player = await session.get(Player, uid)
            if not player or player.is_dead:
                return await ctx.send(f"{ctx.author.mention} 尚未踏入修仙之路或已坐化。")

            if not player.active_quest:
                return await ctx.send(f"{ctx.author.mention} 当前没有进行中的任务。")

            due = player.quest_due or 0
            now = time.time()
            if now < due:
                remaining = seconds_to_years(due - now)
                return await ctx.send(
                    f"{ctx.author.mention} 任务尚未完成，还需约 **{remaining:.1f} 游戏年**（现实 {remaining*2:.1f} 小时）。"
                )

        result = await quest_logic.resolve_quest(uid)
        if not result.get("success"):
            return await ctx.send(f"{ctx.author.mention} {result.get('message', '任务结算失败')}")
        
        embed = self._build_result_embed(result)
        await ctx.send(ctx.author.mention, embed=embed)
    
    def _build_result_embed(self, result: dict) -> discord.Embed:
        import discord
        quest_name = result.get("quest_name", "任务")
        
        if result.get("victory"):
            embed = discord.Embed(
                title=f"⚔️ {quest_name} · 任务完成",
                description="战斗胜利！",
                color=discord.Color.green()
            )
            rewards = result.get("rewards", {})
            reward_lines = _reward_lines(rewards)
            equipment = result.get("equipment")
            if equipment:
                reward_lines.append(f"🎁 获得装备：**{equipment['name']}**（{equipment['quality']}·{equipment['slot']}）")
            if reward_lines:
                embed.add_field(name="获得奖励", value="\n".join(reward_lines), inline=False)
            if result.get("is_party") and rewards.get("_equip_roll_result"):
                embed.add_field(name="🎲 装备 Roll 点", value=rewards["_equip_roll_result"], inline=False)
        elif result.get("event_desc"):
            embed = discord.Embed(
                title=f"✅ {quest_name} · 任务完成",
                description=result["event_desc"],
                color=discord.Color.green()
            )
            rewards = result.get("rewards", {})
            reward_lines = _reward_lines(rewards)
            if reward_lines:
                embed.add_field(name="获得奖励", value="\n".join(reward_lines), inline=False)
        elif result.get("fatal"):
            embed = discord.Embed(
                title=f"☠️ {quest_name} · 魂归天道",
                description="任务失败，遭遇强敌，不幸陨落。",
                color=discord.Color.dark_red()
            )
            embed.add_field(name="提示", value=f"可使用 `{COMMAND_PREFIX}创建角色` 重入修仙之路。", inline=False)
        elif result.get("escaped"):
            embed = discord.Embed(
                title=f"⚠️ {quest_name} · 任务失败",
                description="战斗失利，成功逃脱。",
                color=discord.Color.orange()
            )
        else:
            lifespan_loss = result.get("lifespan_loss", 0)
            embed = discord.Embed(
                title=f"⚠️ {quest_name} · 任务失败",
                description=f"战斗失利，身受重伤，损失 **{lifespan_loss} 年** 寿元。",
                color=discord.Color.red()
            )
        
        return embed

    @commands.command(name="重置打工", hidden=True)
    async def reset_job(self, ctx, target_id: str = None):
        if str(ctx.author.id) != "304758476448595970":
            return
        uid = target_id or str(ctx.author.id)
        async with AsyncSessionLocal() as session:
            p = await session.get(Player, uid)
            if p:
                p.job_cooldown_until = 0
                p.job_daily_count = 0
                p.job_daily_reset = 0
                await session.commit()
            name = p.name if p else uid
        await ctx.send(f"已重置 **{name}** 的打工冷却与次数。", ephemeral=True)

    @commands.command(name="重置签到", hidden=True)
    async def reset_checkin(self, ctx, target_id: str = None):
        if str(ctx.author.id) != "304758476448595970":
            return
        uid = target_id or str(ctx.author.id)
        async with AsyncSessionLocal() as session:
            p = await session.get(Player, uid)
            if p:
                p.checkin_last_date = None
                await session.commit()
            name = p.name if p else uid
        await ctx.send(f"已重置 **{name}** 的每日签到。", ephemeral=True)

    @commands.command(name="重置赌坊", hidden=True)
    async def reset_gamble(self, ctx, target_id: str = None):
        if str(ctx.author.id) != "304758476448595970":
            return
        uid = target_id or str(ctx.author.id)
        async with AsyncSessionLocal() as session:
            p = await session.get(Player, uid)
            if p:
                p.gamble_daily_count = 0
                p.gamble_daily_reset = 0
                await session.commit()
            name = p.name if p else uid
        await ctx.send(f"已重置 **{name}** 的赌坊次数。", ephemeral=True)

    @commands.command(name="重置轮盘", hidden=True)
    async def reset_roulette(self, ctx, target_id: str = None):
        if str(ctx.author.id) != "304758476448595970":
            return
        uid = target_id or str(ctx.author.id)
        async with AsyncSessionLocal() as session:
            p = await session.get(Player, uid)
            if p:
                p.roulette_daily_count = 0
                p.roulette_daily_reset = 0
                await session.commit()
            name = p.name if p else uid
        await ctx.send(f"已重置 **{name}** 的轮盘次数。")


class TavernView(discord.ui.View):
    def __init__(self, author, quests: dict, cog):
        super().__init__(timeout=120)
        self.author = author
        self.cog = cog
        for tier, quest_list in quests.items():
            if tier == "_locked":
                continue
            for q in quest_list:
                self.add_item(QuestButton(q, tier))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user != self.author:
            await interaction.response.send_message("这不是你的任务栏。", ephemeral=True)
            return False
        return True


class QuestButton(discord.ui.Button):
    def __init__(self, quest: dict, tier: str):
        colors = {"普通": discord.ButtonStyle.secondary,
                  "精英": discord.ButtonStyle.primary,
                  "传说": discord.ButtonStyle.danger}
        super().__init__(
            label=f"{TIER_EMOJI[tier]} {quest['title']}",
            style=colors.get(tier, discord.ButtonStyle.secondary),
        )
        self.quest = quest
        self.tier = tier

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer()
        uid = str(interaction.user.id)
        async with AsyncSessionLocal() as session:
            player = await session.get(Player, uid)
            if not player or player.is_dead:
                return await interaction.followup.send("角色状态异常。", ephemeral=True)

            q = self.quest
            duration = GATHER_DURATION[self.tier] if q["type"] == "gather" else QUEST_DURATION[self.tier]
            reward_lines = _reward_lines(q["rewards"])

            embed = discord.Embed(
                title=f"{TIER_EMOJI[self.tier]} {q['title']}",
                description=q["desc"],
                color=TIER_COLOR.get(self.tier, discord.Color.teal()),
            )
            if q["type"] == "combat":
                player_dict = {
                    "realm": player.realm,
                    "physique": player.physique,
                    "soul": player.soul,
                    "comprehension": player.comprehension,
                    "techniques": player.techniques,
                    "equipment": player.equipment,
                }
                player_power = await calc_power(player_dict)
                enemy_power = q["enemy"]["power"]
                diff = player_power - enemy_power
                if diff > 20:
                    assess = "🟢 胜算较大"
                elif diff > -20:
                    assess = "🟡 势均力敌"
                else:
                    assess = "🔴 凶多吉少"
                embed.add_field(
                    name="目标",
                    value=f"击败 **{q['enemy']['name']}**\n敌方战力：{enemy_power} | 你的战力：{player_power:.1f} | {assess}",
                    inline=False,
                )
            else:
                embed.add_field(name="目标", value=f"前往 **{q['location']}** 完成采集", inline=False)
            embed.add_field(name="耗时", value=f"**{duration} 游戏年**（现实 {duration*2} 小时）", inline=True)
            embed.add_field(name="奖励预览", value="\n".join(reward_lines), inline=False)
            embed.set_footer(text=f"接取后使用 {COMMAND_PREFIX}交任务 领取奖励")

            await interaction.followup.send(
                embed=embed,
                view=QuestConfirmView(interaction.user, q, self.tier, self.view.cog),
            )


class QuestConfirmView(discord.ui.View):
    def __init__(self, author, quest: dict, tier: str, cog):
        super().__init__(timeout=60)
        self.author = author
        self.quest = quest
        self.tier = tier
        self.cog = cog

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user != self.author:
            await interaction.response.send_message("这不是你的任务。", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="接取任务", style=discord.ButtonStyle.success)
    async def accept(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        uid = str(interaction.user.id)
        self.stop()

        result = await quest_logic.start_quest(uid, self.quest, self.tier)
        if not result.get("success"):
            return await interaction.followup.send(result.get("message", "接取任务失败"), ephemeral=True)
        
        duration = result.get("duration", 1)
        party_size = result.get("party_size")
        
        if party_size and party_size > 1:
            await interaction.followup.send(
                f"{interaction.user.mention} 队伍（{party_size}人）已接取任务「**{self.quest['title']}**」。\n"
                f"现实 **{duration*2} 小时** 后自动结算，奖励每人完整发放。"
            )
        else:
            await interaction.followup.send(
                f"{interaction.user.mention} 已接取任务「**{self.quest['title']}**」。\n"
                f"现实 **{duration*2} 小时** 后自动结算。"
            )

    @discord.ui.button(label="放弃", style=discord.ButtonStyle.secondary)
    async def decline(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("已放弃。", ephemeral=True)
        self.stop()


async def setup(bot):
    await bot.add_cog(TavernCog(bot))
