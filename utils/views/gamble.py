import discord
from utils.gamble import do_gamble, BET_OPTIONS, DAILY_LIMIT


def _gamble_overview_embed(player: dict) -> discord.Embed:
    import time
    daily_count = player.get("gamble_daily_count") or 0
    daily_reset = player.get("gamble_daily_reset") or 0
    now = time.time()
    reset_date = time.gmtime(daily_reset)
    now_date = time.gmtime(now)
    if (now_date.tm_year, now_date.tm_yday) != (reset_date.tm_year, reset_date.tm_yday):
        daily_count = 0

    remaining = DAILY_LIMIT - daily_count
    embed = discord.Embed(
        title="✦ 赌坊 · 押注台 ✦",
        description=(
            "财富与命运，皆在一掷之间。\n\n"
            f"今日剩余次数：**{remaining} / {DAILY_LIMIT}**\n"
            f"当前灵石：**{player.get('spirit_stones', 0):,}**\n\n"
            "选择押注金额："
        ),
        color=discord.Color.dark_gold(),
    )
    embed.set_footer(text="大赢 ×5 · 赢 ×2 · 小赢 ×1.5 · 输 ×0")
    return embed


class GambleView(discord.ui.View):
    def __init__(self, author, player: dict, cog=None):
        super().__init__(timeout=120)
        self.author = author
        self.player = player
        self.cog = cog

        import time
        daily_count = player.get("gamble_daily_count") or 0
        daily_reset = player.get("gamble_daily_reset") or 0
        now = time.time()
        reset_date = time.gmtime(daily_reset)
        now_date = time.gmtime(now)
        if (now_date.tm_year, now_date.tm_yday) != (reset_date.tm_year, reset_date.tm_yday):
            daily_count = 0
        exhausted = daily_count >= DAILY_LIMIT

        for bet in BET_OPTIONS:
            btn = discord.ui.Button(
                label=f"押注 {bet:,}",
                style=discord.ButtonStyle.primary,
                disabled=exhausted or player.get("spirit_stones", 0) < bet,
                custom_id=str(bet),
            )
            btn.callback = self._make_callback(bet)
            self.add_item(btn)

        back_btn = discord.ui.Button(label="返回城市", style=discord.ButtonStyle.secondary)
        back_btn.callback = self._back
        self.add_item(back_btn)

    def _make_callback(self, bet: int):
        async def callback(interaction: discord.Interaction):
            for item in self.children:
                item.disabled = True
            await interaction.response.edit_message(view=self)

            result = await do_gamble(str(interaction.user.id), bet)
            if not result["ok"]:
                await interaction.edit_original_response(
                    embed=discord.Embed(description=result["reason"], color=discord.Color.red()),
                    view=_back_only_view(self.author, self.player, self.cog),
                )
                return

            label = result["label"]
            net = result["net"]
            color_map = {
                "大赢": discord.Color.gold(),
                "赢":   discord.Color.green(),
                "小赢": discord.Color.teal(),
                "输":   discord.Color.red(),
            }
            sign = "+" if net >= 0 else ""
            embed = discord.Embed(
                title=f"✦ {label} ✦",
                description=(
                    f"*{result['message']}*\n\n"
                    f"押注：**{bet:,}** 灵石\n"
                    f"结算：**{sign}{net:,}** 灵石\n\n"
                    f"今日剩余次数：**{result['daily_limit'] - result['daily_count']} / {result['daily_limit']}**"
                ),
                color=color_map.get(label, discord.Color.greyple()),
            )
            await interaction.edit_original_response(
                embed=embed,
                view=_back_only_view(self.author, self.player, self.cog),
            )
        return callback

    async def _back(self, interaction: discord.Interaction):
        await _go_back(interaction, self.author, self.player, self.cog)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user != self.author:
            await interaction.response.send_message("这不是你的面板。", ephemeral=True)
            return False
        return True


def _back_only_view(author, player, cog):
    view = discord.ui.View(timeout=60)
    back_btn = discord.ui.Button(label="返回城市", style=discord.ButtonStyle.secondary)

    async def _back(interaction: discord.Interaction):
        await _go_back(interaction, author, player, cog)

    back_btn.callback = _back
    view.add_item(back_btn)
    return view


async def _go_back(interaction: discord.Interaction, author, player, cog):
    from utils.views.city import CityMenuView, _city_menu_embed
    from utils.db import get_conn
    uid = str(interaction.user.id)
    with get_conn() as conn:
        p = dict(conn.execute("SELECT * FROM players WHERE discord_id = ?", (uid,)).fetchone())
    await interaction.response.edit_message(
        embed=_city_menu_embed(p),
        view=CityMenuView(interaction.user, p, cog),
    )
