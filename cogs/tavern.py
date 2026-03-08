import json
import time
import random

import discord
from discord.ext import commands, tasks

from utils.db import get_conn
from utils.quests import get_tavern_quests, get_quest
from utils.combat import roll_combat, calc_power, roll_escape
from utils.realms import get_realm_index
from utils.sects import TECHNIQUES
from utils.character import years_to_seconds, seconds_to_years


def _get_player(discord_id: str):
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM players WHERE discord_id = ?", (discord_id,)).fetchone()
        return dict(row) if row else None


def _reward_lines(rewards: dict) -> list[str]:
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
    return lines


def _apply_quest_rewards(uid: str, rewards: dict):
    fields = []
    values = []
    for key in ["spirit_stones", "reputation", "cultivation", "lifespan"]:
        if rewards.get(key):
            fields.append(f"{key} = {key} + ?")
            values.append(rewards[key])
    if rewards.get("stat_bonus"):
        for stat, val in rewards["stat_bonus"].items():
            fields.append(f"{stat} = {stat} + ?")
            values.append(val)
    if fields:
        values.append(uid)
        with get_conn() as conn:
            conn.execute(f"UPDATE players SET {', '.join(fields)} WHERE discord_id = ?", values)
            conn.commit()
    if rewards.get("technique"):
        t_name = rewards["technique"]
        with get_conn() as conn:
            row = conn.execute("SELECT techniques FROM players WHERE discord_id = ?", (uid,)).fetchone()
            techs = json.loads(row["techniques"] or "[]")
            existing = {(t if isinstance(t, str) else t.get("name", "")) for t in techs}
            if t_name not in existing:
                equipped_count = sum(1 for t in techs if isinstance(t, dict) and t.get("equipped"))
                techs.append({
                    "name": t_name,
                    "grade": TECHNIQUES.get(t_name, {}).get("grade", "黄级上品"),
                    "stage": "入门",
                    "equipped": equipped_count < 5,
                })
                conn.execute("UPDATE players SET techniques = ? WHERE discord_id = ?",
                             (json.dumps(techs, ensure_ascii=False), uid))
                conn.commit()


def _clear_quest(uid: str):
    with get_conn() as conn:
        conn.execute("UPDATE players SET active_quest = NULL, quest_due = NULL WHERE discord_id = ?", (uid,))
        conn.commit()


GATHER_EVENTS = [
    {
        "flavor": "一路顺风，采集顺利完成。",
        "outcome": "success",
        "bonus": {},
    },
    {
        "flavor": "途中遭遇妖兽袭击，奋力击退，有惊无险。",
        "outcome": "combat",
        "bonus": {},
    },
    {
        "flavor": "意外发现一处隐秘洞穴，内有前人遗留的修炼心得。",
        "outcome": "bonus",
        "bonus": {"cultivation": 200, "comprehension_chance": True},
    },
    {
        "flavor": "采集途中踩中灵脉节点，灵气涌入体内，根骨得到淬炼。",
        "outcome": "bonus",
        "bonus": {"bone": 1},
    },
    {
        "flavor": "遭遇同行修士争抢，双方交手，你略占上风，对方悻悻离去。",
        "outcome": "combat",
        "bonus": {"spirit_stones": 500},
    },
    {
        "flavor": "发现一株罕见灵药，顺手带回，药铺掌柜喜出望外。",
        "outcome": "bonus",
        "bonus": {"spirit_stones": 2000, "lifespan": 5},
    },
]

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

    async def _auto_resolve_quest(self, uid: str, player: dict):
        q_data = json.loads(player["active_quest"])
        q = get_quest(q_data["id"])
        if not q:
            _clear_quest(uid)
            return
        tier = q_data.get("tier", "普通")
        _clear_quest(uid)
        player = _get_player(uid)

        if q["type"] == "combat":
            embed = await self._build_combat_embed(uid, player, q, tier)
        else:
            embed = await self._build_gather_embed(uid, player, q, tier)

        try:
            user = await self.bot.fetch_user(int(uid))
            await user.send(embed=embed)
        except Exception:
            pass

    async def _build_combat_embed(self, uid, player, q, tier) -> discord.Embed:
        from utils.db import get_conn as _get_conn
        enemy = q["enemy"]
        party_id = player.get("party_id")
        if party_id:
            with _get_conn() as conn:
                members = [dict(r) for r in conn.execute(
                    "SELECT * FROM players WHERE party_id = ? AND is_dead = 0", (party_id,)).fetchall()]
            player_power = sum(calc_power(m) for m in members) * random.uniform(0.85, 1.15)
            party_note = f"（队伍 {len(members)} 人战力叠加）"
        else:
            player_power = calc_power(player) * random.uniform(0.85, 1.15)
            party_note = ""
        enemy_power = enemy["power"] * random.uniform(0.85, 1.15)
        won = player_power > enemy_power

        combat_flavors_win = [
            f"你与**{enemy['name']}**激战三百回合，对方力竭认败。",
            f"**{enemy['name']}**来势汹汹，你以奇招制胜，一击定乾坤。",
            f"灵气激荡，你压制住**{enemy['name']}**，将其击溃。",
        ]
        combat_flavors_lose = [
            f"**{enemy['name']}**实力超出预期，你力战不敌，狼狈撤退。",
            f"你与**{enemy['name']}**缠斗许久，终因体力不支败下阵来。",
        ]

        embed = discord.Embed(
            title=f"⚔️ {q['title']} · 任务结算",
            color=discord.Color.green() if won else discord.Color.red(),
        )
        embed.add_field(name="战斗经过", value=random.choice(combat_flavors_win if won else combat_flavors_lose), inline=False)
        embed.add_field(name="战力对比", value=f"你{party_note}：**{player_power:.1f}** vs {enemy['name']}：**{enemy_power:.1f}**", inline=False)

        if won:
            _apply_quest_rewards(uid, q["rewards"])
            embed.add_field(name="获得奖励", value="\n".join(_reward_lines(q["rewards"])), inline=False)
        else:
            escaped, escape_pct = roll_escape(player)
            if escaped:
                loss = {"普通": 2, "精英": 5, "传说": 10}[tier]
                with get_conn() as conn:
                    conn.execute("UPDATE players SET lifespan = MAX(0, lifespan - ?) WHERE discord_id = ?", (loss, uid))
                    conn.commit()
                embed.add_field(name="逃跑成功", value=f"逃跑成功率 {escape_pct}%，受伤撤退，损失 **{loss} 年** 寿元。", inline=False)
            else:
                power_gap = max(0, enemy_power - player_power)
                death_chance = min(0.6, 0.1 + power_gap / (enemy["power"] * 2))
                if random.random() < death_chance:
                    with get_conn() as conn:
                        conn.execute("UPDATE players SET is_dead = 1, lifespan = 0 WHERE discord_id = ?", (uid,))
                        conn.commit()
                    embed.color = discord.Color.dark_red()
                    embed.add_field(name="☠️ 魂归天道", value=f"逃跑失败（成功率仅 {escape_pct}%），**{enemy['name']}** 给予致命一击。\n**{player['name']}** 就此陨落，魂归天道。\n可使用 `cat!创建角色` 重入修仙之路。", inline=False)
                else:
                    heavy_loss = random.randint(10, 30)
                    with get_conn() as conn:
                        conn.execute("UPDATE players SET lifespan = MAX(1, lifespan - ?) WHERE discord_id = ?", (heavy_loss, uid))
                        conn.commit()
                    embed.add_field(name="重伤撤退", value=f"逃跑失败（成功率 {escape_pct}%），身受重伤，险些丧命。\n损失 **{heavy_loss} 年** 寿元，侥幸逃得一命。", inline=False)
        return embed

    async def _build_gather_embed(self, uid, player, q, tier) -> discord.Embed:
        event = random.choice(GATHER_EVENTS)
        embed = discord.Embed(
            title=f"✅ {q['title']} · 任务结算",
            description=event["flavor"],
            color=discord.Color.green(),
        )
        if event["outcome"] == "combat":
            enemy_power = random.uniform(50, 200) * (get_realm_index(player["realm"]) + 1)
            player_power = calc_power(player) * random.uniform(0.85, 1.15)
            won = player_power > enemy_power
            if won:
                embed.add_field(name="遭遇战", value=f"战力 {player_power:.1f} 击败来敌（{enemy_power:.1f}），有惊无险。", inline=False)
                bonus = event.get("bonus", {})
                if bonus:
                    _apply_quest_rewards(uid, bonus)
                    embed.add_field(name="额外收获", value="\n".join(_reward_lines(bonus)), inline=False)
            else:
                loss = {"普通": 1, "精英": 3, "传说": 8}[tier]
                with get_conn() as conn:
                    conn.execute("UPDATE players SET lifespan = MAX(0, lifespan - ?) WHERE discord_id = ?", (loss, uid))
                    conn.commit()
                embed.add_field(name="遭遇战", value=f"遭遇强敌（{enemy_power:.1f}），受伤撤退，损失 **{loss} 年** 寿元。", inline=False)
        elif event["outcome"] == "bonus":
            bonus = dict(event.get("bonus", {}))
            if bonus.pop("comprehension_chance", None) and random.random() < 0.4:
                bonus["comprehension"] = 1
            if bonus:
                _apply_quest_rewards(uid, bonus)
                embed.add_field(name="意外收获", value="\n".join(_reward_lines(bonus)), inline=False)

        _apply_quest_rewards(uid, q["rewards"])
        embed.add_field(name="任务奖励", value="\n".join(_reward_lines(q["rewards"])), inline=False)
        return embed

    @tasks.loop(minutes=1)
    async def _quest_notifier(self):
        now = time.time()
        with get_conn() as conn:
            rows = conn.execute(
                "SELECT discord_id, name, active_quest, quest_due FROM players "
                "WHERE active_quest IS NOT NULL AND quest_due <= ? AND is_dead = 0",
                (now,)
            ).fetchall()
        for row in rows:
            uid = row["discord_id"]
            if uid in self._notified:
                continue
            self._notified.add(uid)
            player = _get_player(uid)
            if not player or not player.get("active_quest"):
                continue
            await self._auto_resolve_quest(uid, player)
            self._notified.discard(uid)

    @_quest_notifier.before_loop
    async def _before_notifier(self):
        await self.bot.wait_until_ready()

    async def cog_load(self):
        self._quest_notifier.start()

    async def cog_unload(self):
        self._quest_notifier.cancel()


    @commands.command(name="茶馆")
    async def tavern(self, ctx):
        uid = str(ctx.author.id)
        player = _get_player(uid)
        if not player or player["is_dead"]:
            return await ctx.send(f"{ctx.author.mention} 尚未踏入修仙之路或已坐化。")

        if player.get("active_quest"):
            q_data = json.loads(player["active_quest"])
            due = player.get("quest_due") or 0
            remaining = seconds_to_years(max(0, due - time.time()))
            return await ctx.send(
                f"{ctx.author.mention} 你正在执行任务「**{q_data['title']}**」，"
                f"还需约 **{remaining:.1f} 游戏年**（现实 {remaining*2:.1f} 小时）。\n"
                f"任务完成后使用 `cat!交任务` 领取奖励。"
            )

        quests = get_tavern_quests(player)
        if not quests:
            return await ctx.send(f"{ctx.author.mention} 当前没有适合你境界的任务。")

        embed = discord.Embed(
            title=f"✦ {player['current_city']} · 茶馆任务栏 ✦",
            description="掌柜将任务榜递来，上面贴满了各色悬赏……",
            color=discord.Color.teal(),
        )
        for tier, quest_list in quests.items():
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

    @commands.command(name="交任务")
    async def submit_quest(self, ctx):
        uid = str(ctx.author.id)
        player = _get_player(uid)
        if not player or player["is_dead"]:
            return await ctx.send(f"{ctx.author.mention} 尚未踏入修仙之路或已坐化。")

        if not player.get("active_quest"):
            return await ctx.send(f"{ctx.author.mention} 当前没有进行中的任务。")

        due = player.get("quest_due") or 0
        now = time.time()
        if now < due:
            remaining = seconds_to_years(due - now)
            return await ctx.send(
                f"{ctx.author.mention} 任务尚未完成，还需约 **{remaining:.1f} 游戏年**（现实 {remaining*2:.1f} 小时）。"
            )

        q_data = json.loads(player["active_quest"])
        q = get_quest(q_data["id"])
        if not q:
            _clear_quest(uid)
            return await ctx.send(f"{ctx.author.mention} 任务数据异常，已清除。")

        tier = q_data.get("tier", "普通")
        _clear_quest(uid)
        player = _get_player(uid)

        if q["type"] == "combat":
            embed = await self._build_combat_embed(uid, player, q, tier)
        else:
            embed = await self._build_gather_embed(uid, player, q, tier)
        await ctx.send(ctx.author.mention, embed=embed)




class TavernView(discord.ui.View):
    def __init__(self, author, quests: dict, cog):
        super().__init__(timeout=120)
        self.author = author
        self.cog = cog
        for tier, quest_list in quests.items():
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
        player = _get_player(uid)
        if not player or player["is_dead"]:
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
            player_power = calc_power(player)
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
        embed.set_footer(text="接取后使用 cat!交任务 领取奖励")

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
        player = _get_player(uid)
        self.stop()

        if player.get("cultivating_until") and time.time() < player["cultivating_until"]:
            return await interaction.followup.send("闭关中无法接取任务，请先结束闭关。", ephemeral=True)
        if player.get("active_quest"):
            return await interaction.followup.send("已有进行中的任务，请先完成。", ephemeral=True)

        q = self.quest
        duration = GATHER_DURATION[self.tier] if q["type"] == "gather" else QUEST_DURATION[self.tier]
        due = time.time() + years_to_seconds(duration)

        q_store = {"id": q["id"], "title": q["title"], "tier": self.tier}
        with get_conn() as conn:
            party_id = player.get("party_id")
            if party_id:
                members = [dict(r) for r in conn.execute(
                    "SELECT discord_id FROM players WHERE party_id = ? AND is_dead = 0", (party_id,)).fetchall()]
                for m in members:
                    conn.execute("UPDATE players SET active_quest = ?, quest_due = ? WHERE discord_id = ?",
                                 (json.dumps(q_store, ensure_ascii=False), due, m["discord_id"]))
            else:
                conn.execute("UPDATE players SET active_quest = ?, quest_due = ? WHERE discord_id = ?",
                             (json.dumps(q_store, ensure_ascii=False), due, uid))
            conn.commit()

        party_id = player.get("party_id")
        if party_id:
            with get_conn() as conn:
                count = conn.execute("SELECT COUNT(*) FROM players WHERE party_id = ?", (party_id,)).fetchone()[0]
            await interaction.followup.send(
                f"{interaction.user.mention} 队伍（{count}人）已接取任务「**{q['title']}**」。\n"
                f"现实 **{duration*2} 小时** 后自动结算，奖励每人完整发放。"
            )
        else:
            await interaction.followup.send(
                f"{interaction.user.mention} 已接取任务「**{q['title']}**」。\n"
                f"现实 **{duration*2} 小时** 后自动结算。"
            )

    @discord.ui.button(label="放弃", style=discord.ButtonStyle.secondary)
    async def decline(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("已放弃。", ephemeral=True)
        self.stop()


class VictoryLootView(discord.ui.View):
    def __init__(self, author, uid: str, quest: dict):
        super().__init__(timeout=60)
        self.author = author
        self.uid = uid
        self.quest = quest

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user != self.author:
            await interaction.response.send_message("这不是你的战利品。", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="打劫灵石", style=discord.ButtonStyle.primary)
    async def loot_stones(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        loot = random.randint(
            int(self.quest["rewards"]["spirit_stones"] * 0.3),
            int(self.quest["rewards"]["spirit_stones"] * 0.6),
        )
        with get_conn() as conn:
            conn.execute("UPDATE players SET spirit_stones = spirit_stones + ? WHERE discord_id = ?",
                         (loot, self.uid))
            conn.commit()
        await interaction.followup.send(f"从敌人身上搜刮了 **{loot}** 灵石。")
        self.stop()

    @discord.ui.button(label="废去修为", style=discord.ButtonStyle.danger)
    async def cripple(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("你以特殊手法封印了对方的修为，令其打回原形。（对方修为清零）")
        self.stop()

    @discord.ui.button(label="击杀", style=discord.ButtonStyle.danger)
    async def kill(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("你取了对方性命，此事将在江湖中流传。声名大噪，亦或臭名昭著。")
        self.stop()


async def setup(bot):
    await bot.add_cog(TavernCog(bot))
