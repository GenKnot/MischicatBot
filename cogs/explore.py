import random
import time

import discord
from discord.ext import commands

from utils.config import COMMAND_PREFIX
from utils.db import get_conn
from utils.events import get_event_pool
from utils.character import seconds_to_years, get_explore_limit_bonus

EXPLORE_LIMIT = 8
EXPLORE_RESET_YEARS = 5


def _get_explore_limit(player) -> int:
    bonus = get_explore_limit_bonus(
        player["discord_id"], player["current_city"], player.get("cave")
    )
    return EXPLORE_LIMIT + bonus


def _get_player(discord_id: str):
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM players WHERE discord_id = ?", (discord_id,)
        ).fetchone()
        return dict(row) if row else None


def _apply_rewards(discord_id: str, rewards: dict):
    if not rewards:
        return
    fields = []
    values = []
    stat_map = {
        "spirit_stones": "spirit_stones",
        "lifespan": "lifespan",
        "cultivation": "cultivation",
        "comprehension": "comprehension",
        "physique": "physique",
        "fortune": "fortune",
        "bone": "bone",
        "soul": "soul",
        "reputation": "reputation",
    }
    for key, val in rewards.items():
        if key == "discover_sect":
            import json
            with get_conn() as conn:
                row = conn.execute(
                    "SELECT discovered_sects FROM players WHERE discord_id = ?", (discord_id,)
                ).fetchone()
                discovered = json.loads(row["discovered_sects"] or "[]") if row else []
                if val not in discovered:
                    discovered.append(val)
                    conn.execute(
                        "UPDATE players SET discovered_sects = ? WHERE discord_id = ?",
                        (json.dumps(discovered, ensure_ascii=False), discord_id)
                    )
                    conn.commit()
            continue
        if key == "equipment":
            import random as _r
            from utils.equipment import generate_equipment, get_player_tier
            from utils.db import give_equipment
            eq_spec = val
            chance = eq_spec.get("chance", 1.0)
            if _r.random() < chance:
                with get_conn() as conn:
                    p_row = conn.execute("SELECT realm FROM players WHERE discord_id = ?", (discord_id,)).fetchone()
                tier = get_player_tier(p_row["realm"]) if p_row else 0
                quality_pool = eq_spec.get("quality_pool")
                quality_weights = eq_spec.get("quality_weights")
                if quality_pool and quality_weights:
                    quality = _r.choices(quality_pool, weights=quality_weights, k=1)[0]
                else:
                    quality = eq_spec.get("quality")
                eq = generate_equipment(tier=tier, quality=quality)
                give_equipment(discord_id, eq)
                rewards["_generated_equipment"] = eq
            continue
        col = stat_map.get(key)
        if col:
            fields.append(f"{col} = MAX(0, {col} + ?)")
            values.append(val)
    if fields:
        values.append(discord_id)
        with get_conn() as conn:
            conn.execute(
                f"UPDATE players SET {', '.join(fields)} WHERE discord_id = ?", values
            )
            conn.commit()


def _check_explore_limit(player) -> tuple[bool, str]:
    now_years = time.time() / (2 * 3600)
    reset_year = player["explore_reset_year"] or 0
    count = player["explore_count"] or 0
    limit = _get_explore_limit(player)

    if now_years - reset_year >= EXPLORE_RESET_YEARS:
        return True, ""

    if count < limit:
        return True, ""

    years_left = EXPLORE_RESET_YEARS - (now_years - reset_year)
    return False, f"探险次数已用尽（{limit}/{limit}），约 **{years_left:.1f} 游戏年**后刷新。"


def _increment_explore(discord_id: str, player):
    now_years = time.time() / (2 * 3600)
    reset_year = player["explore_reset_year"] or 0
    count = player["explore_count"] or 0

    if now_years - reset_year >= EXPLORE_RESET_YEARS:
        count = 1
        reset_year = now_years
    else:
        count += 1

    with get_conn() as conn:
        conn.execute(
            "UPDATE players SET explore_count = ?, explore_reset_year = ? WHERE discord_id = ?",
            (count, reset_year, discord_id)
        )
        conn.commit()


def _consume_explore_buffs(discord_id: str, player: dict, rewards: dict):
    from utils.buffs import consume_once_buff, get_spirit_stones_bonus
    raw = player.get("active_buffs") or "{}"
    changed = False

    from utils.buffs import get_explore_rare_bonus
    if get_explore_rare_bonus(player) > 0:
        consumed, raw = consume_once_buff(raw, "explore_rare_bonus_once")
        if consumed:
            changed = True

    stones_bonus = get_spirit_stones_bonus(player)
    if stones_bonus > 0 and rewards.get("spirit_stones", 0) > 0:
        extra = int(rewards["spirit_stones"] * stones_bonus)
        if extra > 0:
            with get_conn() as conn:
                conn.execute(
                    "UPDATE players SET spirit_stones = spirit_stones + ? WHERE discord_id = ?",
                    (extra, discord_id)
                )
                conn.commit()
        _, raw = consume_once_buff(raw, "spirit_stones_bonus_once")
        changed = True

    if changed:
        with get_conn() as conn:
            conn.execute(
                "UPDATE players SET active_buffs = ? WHERE discord_id = ?",
                (raw, discord_id)
            )
            conn.commit()


def _check_condition(player, condition) -> bool:
    if not condition:
        return True
    stat = condition["stat"]
    val = condition["val"]
    return player.get(stat, 0) >= val


def _pick_choice_result(choices, player):
    conditioned = [c for c in choices if c.get("condition")]
    unconditioned = [c for c in choices if not c.get("condition")]

    for c in conditioned:
        if _check_condition(player, c["condition"]):
            return c

    if unconditioned:
        return random.choice(unconditioned)
    return choices[-1]


class ExploreResultView(discord.ui.View):
    def __init__(self, author, cog):
        super().__init__(timeout=120)
        self.author = author
        self.cog = cog

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user != self.author:
            await interaction.response.send_message("这不是你的探险。", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="继续探险", style=discord.ButtonStyle.success)
    async def continue_explore(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        uid = str(interaction.user.id)
        player = _get_player(uid)
        if not player or player["is_dead"]:
            return await interaction.followup.send("无法继续探险。", ephemeral=True)
        ok, msg = _check_explore_limit(player)
        if not ok:
            return await interaction.followup.send(f"{msg}", ephemeral=True)
        now = time.time()
        if player.get("active_quest"):
            import json as _json
            q_data = _json.loads(player["active_quest"])
            return await interaction.followup.send(f"道友正在执行任务「**{q_data['title']}**」，无法探险。", ephemeral=True)
        if player.get("cultivating_until") and now < player["cultivating_until"]:
            return await interaction.followup.send("道友正在闭关，无法探险。", ephemeral=True)
        if player.get("gathering_until") and now < player["gathering_until"]:
            return await interaction.followup.send("道友正在采集中，无法探险。", ephemeral=True)
        from utils.events.public.wanbao import is_auction_locked
        if is_auction_locked(uid):
            return await interaction.followup.send("拍卖会进行中，在万宝楼内无法探险。", ephemeral=True)
        _increment_explore(uid, player)
        player = _get_player(uid)
        event = get_event_pool(dict(player))
        embed = discord.Embed(
            title=f"✦ {event['title']} ✦",
            description=event["desc"],
            color=discord.Color.gold(),
        )
        count = player["explore_count"]
        limit = _get_explore_limit(player)
        embed.set_footer(text=f"本轮探险次数：{count}/{limit}")
        await interaction.followup.send(
            interaction.user.mention,
            embed=embed,
            view=ExploreView(interaction.user, event, player, self.cog)
        )

    @discord.ui.button(label="主菜单", style=discord.ButtonStyle.primary)
    async def main_menu(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        cog = self.cog
        uid = str(interaction.user.id)
        player = _get_player(uid)
        has_player = player is not None and not player["is_dead"]
        from utils.realms import cultivation_needed
        can_bt = has_player and player["cultivation"] >= cultivation_needed(player["realm"])
        import json
        city_players = []
        if has_player:
            with get_conn() as conn:
                rows = conn.execute(
                    "SELECT discord_id, name, realm, cultivation FROM players "
                    "WHERE current_city = ? AND is_dead = 0 AND discord_id != ?",
                    (player["current_city"], uid)
                ).fetchall()
            city_players = [dict(r) for r in rows]
        from utils.views import MainMenuView, _build_menu_embed
        cult_cog = cog.bot.cogs.get("Cultivation")
        import json
        has_dual = has_player and any(
            (t if isinstance(t, str) else t.get("name", "")) == "双修功法"
            for t in json.loads(player["techniques"] or "[]")
        ) if has_player else False
        await interaction.followup.send(
            interaction.user.mention,
            embed=_build_menu_embed(has_dual),
            view=MainMenuView(interaction.user, has_player, can_bt, cult_cog, player, city_players)
        )

    @discord.ui.button(label="帮助", style=discord.ButtonStyle.secondary)
    async def help_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        cult_cog = self.cog.bot.cogs.get("Cultivation")
        if cult_cog:
            ctx = await self.cog.bot.get_context(interaction.message)
            ctx.author = interaction.user
            await cult_cog.help_cmd(ctx)


class ExploreView(discord.ui.View):
    def __init__(self, author, event: dict, player, cog):
        super().__init__(timeout=120)
        self.author = author
        self.event = event
        self.player = player
        self.cog = cog

        seen = set()
        for i, choice in enumerate(event["choices"]):
            if choice["label"] in seen:
                continue
            seen.add(choice["label"])
            has_next = any(
                c.get("next") for c in event["choices"] if c["label"] == choice["label"]
            )
            self.add_item(ExploreChoiceButton(choice["label"], i, has_next))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user != self.author:
            await interaction.response.send_message("这不是你的探险。", ephemeral=True)
            return False
        return True


class ExploreChoiceButton(discord.ui.Button):
    def __init__(self, label: str, index: int, has_next: bool):
        super().__init__(label=label, style=discord.ButtonStyle.primary)
        self.index = index
        self.has_next = has_next

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer()
        for item in self.view.children:
            item.disabled = True
        self.view.stop()
        cog = self.view.cog
        player = self.view.player
        uid = str(interaction.user.id)
        choice = self.view.event["choices"][self.index]

        if choice.get("next"):
            next_event = choice["next"]
            embed = discord.Embed(
                title=self.view.event["title"],
                description=next_event["desc"],
                color=discord.Color.gold(),
            )
            view = ExploreNextView(interaction.user, self.view.event, next_event, player, cog)
            await interaction.followup.send(embed=embed, view=view)
        else:
            result = _pick_choice_result(
                [c for c in self.view.event["choices"] if c["label"] == choice["label"]],
                dict(player)
            )
            _apply_rewards(uid, result["rewards"])
            _consume_explore_buffs(uid, dict(player), result["rewards"])
            desc = result["flavor"] or "平安无事。"
            eq = result["rewards"].get("_generated_equipment")
            if eq:
                desc += f"\n\n🎁 获得装备：**{eq['name']}**（{eq['quality']}·{eq['slot']}）`{eq['equip_id']}`"
            embed = discord.Embed(
                title=f"✦ {self.view.event['title']} · 结果 ✦",
                description=desc,
                color=discord.Color.teal(),
            )
            await interaction.followup.send(embed=embed, view=ExploreResultView(interaction.user, cog))


class ExploreNextView(discord.ui.View):
    def __init__(self, author, original_event, next_event, player, cog):
        super().__init__(timeout=120)
        self.author = author
        self.original_event = original_event
        self.next_event = next_event
        self.player = player
        self.cog = cog

        seen = set()
        for i, choice in enumerate(next_event["choices"]):
            if choice["label"] in seen:
                continue
            seen.add(choice["label"])
            self.add_item(ExploreNextButton(choice["label"], i))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user != self.author:
            await interaction.response.send_message("这不是你的探险。", ephemeral=True)
            return False
        return True


class ExploreNextButton(discord.ui.Button):
    def __init__(self, label: str, index: int):
        super().__init__(label=label, style=discord.ButtonStyle.secondary)
        self.index = index

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer()
        for item in self.view.children:
            item.disabled = True
        self.view.stop()
        uid = str(interaction.user.id)
        player = dict(self.view.player)
        choices = self.view.next_event["choices"]

        same_label = [c for c in choices if c["label"] == choices[self.index]["label"]]
        result = _pick_choice_result(same_label, player)

        _apply_rewards(uid, result["rewards"])
        _consume_explore_buffs(uid, player, result["rewards"])
        desc = result["flavor"] or "平安无事。"
        eq = result["rewards"].get("_generated_equipment")
        if eq:
            desc += f"\n\n🎁 获得装备：**{eq['name']}**（{eq['quality']}·{eq['slot']}）`{eq['equip_id']}`"
        embed = discord.Embed(
            title=f"✦ {self.view.original_event['title']} · 结果 ✦",
            description=desc,
            color=discord.Color.teal(),
        )
        await interaction.followup.send(embed=embed, view=ExploreResultView(interaction.user, self.view.cog))


class ExploreCog(commands.Cog, name="Explore"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.hybrid_command(name="探险", aliases=["tx"], description="在当前城市附近探险，触发机缘或风险事件")
    async def explore(self, ctx):
        uid = str(ctx.author.id)
        player = _get_player(uid)

        if not player:
            return await ctx.send(f"{ctx.author.mention} 尚未踏入修仙之路，请先使用 `{COMMAND_PREFIX}创建角色`。")
        if player["is_dead"]:
            return await ctx.send(f"{ctx.author.mention} 道友已坐化。")

        now = time.time()
        if player.get("cultivating_until") and now < player["cultivating_until"]:
            from utils.character import seconds_to_years
            remaining = seconds_to_years(player["cultivating_until"] - now)
            return await ctx.send(f"{ctx.author.mention} 道友正在闭关，无法探险。还剩约 **{remaining:.1f} 年**。")
        if player.get("gathering_until") and now < player["gathering_until"]:
            from utils.character import seconds_to_years
            remaining = seconds_to_years(player["gathering_until"] - now)
            return await ctx.send(f"{ctx.author.mention} 道友正在采集中，无法探险。还剩约 **{remaining:.1f} 年**。")
        if player.get("active_quest"):
            import json
            q_data = json.loads(player["active_quest"])
            return await ctx.send(f"{ctx.author.mention} 道友正在执行任务「**{q_data['title']}**」，无法探险。")

        from utils.events.public.wanbao import is_auction_locked
        if is_auction_locked(uid):
            return await ctx.send(f"{ctx.author.mention} 拍卖会进行中，在万宝楼内无法探险。")

        ok, msg = _check_explore_limit(player)
        if not ok:
            return await ctx.send(f"{ctx.author.mention} {msg}")

        _increment_explore(uid, player)
        player = _get_player(uid)

        event = get_event_pool(dict(player))
        embed = discord.Embed(
            title=f"✦ {event['title']} ✦",
            description=event["desc"],
            color=discord.Color.gold(),
        )
        count = player["explore_count"]
        limit = _get_explore_limit(player)
        embed.set_footer(text=f"本轮探险次数：{count}/{limit}")
        await ctx.send(
            ctx.author.mention,
            embed=embed,
            view=ExploreView(ctx.author, event, player, self)
        )


async def setup(bot):
    await bot.add_cog(ExploreCog(bot))
