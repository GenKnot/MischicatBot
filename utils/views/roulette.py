import discord
from utils.roulette import BET, DAILY_LIMIT, SLOTS, WHEEL, do_roulette


def _wheel_overview_embed(player: dict) -> discord.Embed:
    import time
    daily_count = player.get("roulette_daily_count") or 0
    daily_reset = player.get("roulette_daily_reset") or 0
    now = time.time()
    reset_date = time.gmtime(daily_reset)
    now_date = time.gmtime(now)
    if (now_date.tm_year, now_date.tm_yday) != (reset_date.tm_year, reset_date.tm_yday):
        daily_count = 0

    remaining = DAILY_LIMIT - daily_count
    wheel_str = " ".join(s["emoji"] for s in WHEEL)

    slot_lines = "\n".join(
        f"{s['emoji']} **{s['label']}** — {s['count']} 格（{round(s['count']/12*100)}%）"
        for s in SLOTS
    )

    embed = discord.Embed(
        title="🎡 轮转赌坊",
        description=(
            f"{wheel_str}\n\n"
            "转盘共 12 格，固定押注 **500 灵石**，转到哪格算哪格。\n\n"
            f"{slot_lines}\n\n"
            f"今日剩余：**{remaining} / {DAILY_LIMIT}**　　灵石：**{player.get('spirit_stones', 0):,}**"
        ),
        color=discord.Color.dark_gold(),
    )
    return embed


class RouletteView(discord.ui.View):
    def __init__(self, author, player: dict, cog=None):
        super().__init__(timeout=120)
        self.author = author
        self.player = player
        self.cog = cog

        import time
        daily_count = player.get("roulette_daily_count") or 0
        daily_reset = player.get("roulette_daily_reset") or 0
        now = time.time()
        reset_date = time.gmtime(daily_reset)
        now_date = time.gmtime(now)
        if (now_date.tm_year, now_date.tm_yday) != (reset_date.tm_year, reset_date.tm_yday):
            daily_count = 0

        exhausted = daily_count >= DAILY_LIMIT
        no_stones = player.get("spirit_stones", 0) < BET

        self.spin_btn.disabled = exhausted or no_stones

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user != self.author:
            await interaction.response.send_message("这不是你的面板。", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="🎡 转动转盘（500 灵石）", style=discord.ButtonStyle.danger)
    async def spin_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        uid = str(interaction.user.id)
        result = await do_roulette(uid)

        from sqlalchemy import text
        from utils.db_async import AsyncSessionLocal
        async with AsyncSessionLocal() as session:
            res = await session.execute(text("SELECT * FROM players WHERE discord_id = :uid"), {"uid": uid})
            updated = dict(res.fetchone()._mapping)

        if not result["ok"]:
            await interaction.response.send_message(result["reason"], ephemeral=True)
            return

        slot = result["slot"]
        net = result["net"]

        if net > 0:
            color = discord.Color.gold() if result["payout"] >= BET * 5 else discord.Color.green()
        elif net == 0:
            color = discord.Color.greyple()
        else:
            color = discord.Color.red()

        wheel_parts = []
        seen = False
        for s in WHEEL:
            if not seen and s["label"] == slot["label"] and s["emoji"] == slot["emoji"]:
                wheel_parts.append(f"**[{s['emoji']}]**")
                seen = True
            else:
                wheel_parts.append(s["emoji"])
        wheel_str = " ".join(wheel_parts)

        sign = "+" if net >= 0 else ""
        title_map = {
            10.0: "💎 大吉！× 10",
            5.0:  "🔥 走运！× 5",
            2.0:  "🟡 小赚 × 2",
            1.0:  "⚪ 回本 × 1",
            0.5:  "🌑 小亏 × 0.5",
            0.0:  "💀 全输 × 0",
        }
        title = title_map.get(slot["multiplier"], slot["label"])

        result_embed = discord.Embed(
            title=f"🎡 {title}",
            description=(
                f"{wheel_str}\n\n"
                f"押注：**{BET:,}** 灵石　结算：**{sign}{net:,}** 灵石\n"
                f"今日剩余：**{result['daily_limit'] - result['daily_count']} / {result['daily_limit']}**"
            ),
            color=color,
        )

        await interaction.response.edit_message(
            embed=_wheel_overview_embed(updated),
            view=RouletteView(self.author, updated, self.cog),
        )
        await interaction.followup.send(embed=result_embed, view=RouletteResultView(self.author, updated, self.cog))

    @discord.ui.button(label="返回城市", style=discord.ButtonStyle.secondary)
    async def back_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await _go_back(interaction, self.author, self.cog)


class RouletteResultView(discord.ui.View):
    def __init__(self, author, player: dict, cog=None):
        super().__init__(timeout=120)
        self.author = author
        self.player = player
        self.cog = cog

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user != self.author:
            await interaction.response.send_message("这不是你的面板。", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="🎡 再来一次", style=discord.ButtonStyle.danger)
    async def again_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        uid = str(interaction.user.id)
        from sqlalchemy import text
        from utils.db_async import AsyncSessionLocal
        async with AsyncSessionLocal() as session:
            res = await session.execute(text("SELECT * FROM players WHERE discord_id = :uid"), {"uid": uid})
            updated = dict(res.fetchone()._mapping)
        await interaction.response.edit_message(
            embed=_wheel_overview_embed(updated),
            view=RouletteView(self.author, updated, self.cog),
        )

    @discord.ui.button(label="返回城市", style=discord.ButtonStyle.secondary)
    async def back_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await _go_back(interaction, self.author, self.cog)


async def _go_back(interaction: discord.Interaction, author, cog):
    from utils.views.city import CityMenuView, _city_menu_embed
    from sqlalchemy import text
    from utils.db_async import AsyncSessionLocal
    uid = str(interaction.user.id)
    async with AsyncSessionLocal() as session:
        result = await session.execute(text("SELECT * FROM players WHERE discord_id = :uid"), {"uid": uid})
        p = dict(result.fetchone()._mapping)
    await interaction.response.edit_message(
        embed=await _city_menu_embed(p),
        view=CityMenuView(interaction.user, p, cog),
    )
