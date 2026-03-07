import random
import time

import discord
from discord.ext import commands

from utils.db import get_conn
from utils.events import get_event_pool
from utils.character import seconds_to_years

EXPLORE_LIMIT = 8
EXPLORE_RESET_YEARS = 5


def _get_player(discord_id: str):
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM players WHERE discord_id = ?", (discord_id,)
        ).fetchone()


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

    if now_years - reset_year >= EXPLORE_RESET_YEARS:
        return True, ""

    if count < EXPLORE_LIMIT:
        return True, ""

    years_left = EXPLORE_RESET_YEARS - (now_years - reset_year)
    return False, f"探险次数已用尽（{EXPLORE_LIMIT}/{EXPLORE_LIMIT}），约 **{years_left:.1f} 游戏年**后刷新。"


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


class ExploreView(discord.ui.View):
    def __init__(self, author, event: dict, player, cog):
        super().__init__(timeout=120)
        self.author = author
        self.event = event
        self.player = player
        self.cog = cog

        for i, choice in enumerate(event["choices"]):
            if not choice.get("next"):
                self.add_item(ExploreChoiceButton(choice["label"], i, False))
            else:
                self.add_item(ExploreChoiceButton(choice["label"], i, True))

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
            embed = discord.Embed(
                title=f"✦ {self.view.event['title']} · 结果 ✦",
                description=result["flavor"] or "平安无事。",
                color=discord.Color.teal(),
            )
            await interaction.followup.send(embed=embed)


class ExploreNextView(discord.ui.View):
    def __init__(self, author, original_event, next_event, player, cog):
        super().__init__(timeout=120)
        self.author = author
        self.original_event = original_event
        self.next_event = next_event
        self.player = player
        self.cog = cog

        for i, choice in enumerate(next_event["choices"]):
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
        uid = str(interaction.user.id)
        player = dict(self.view.player)
        choices = self.view.next_event["choices"]

        same_label = [c for c in choices if c["label"] == choices[self.index]["label"]]
        result = _pick_choice_result(same_label, player)

        _apply_rewards(uid, result["rewards"])
        embed = discord.Embed(
            title=f"✦ {self.view.original_event['title']} · 结果 ✦",
            description=result["flavor"] or "平安无事。",
            color=discord.Color.teal(),
        )
        await interaction.followup.send(embed=embed)


class ExploreCog(commands.Cog, name="Explore"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.command(name="探险")
    async def explore(self, ctx):
        uid = str(ctx.author.id)
        player = _get_player(uid)

        if not player:
            return await ctx.send(f"{ctx.author.mention} 尚未踏入修仙之路，请先使用 `cat!创建角色`。")
        if player["is_dead"]:
            return await ctx.send(f"{ctx.author.mention} 道友已坐化。")

        ok, msg = _check_explore_limit(player)
        if not ok:
            return await ctx.send(f"{ctx.author.mention} {msg}")

        _increment_explore(uid, player)
        player = _get_player(uid)

        event = random.choice(get_event_pool(dict(player)))
        embed = discord.Embed(
            title=f"✦ {event['title']} ✦",
            description=event["desc"],
            color=discord.Color.gold(),
        )
        count = player["explore_count"]
        embed.set_footer(text=f"本轮探险次数：{count}/{EXPLORE_LIMIT}")
        await ctx.send(
            ctx.author.mention,
            embed=embed,
            view=ExploreView(ctx.author, event, player, self)
        )


async def setup(bot):
    await bot.add_cog(ExploreCog(bot))
