import discord
from utils.world import get_city, get_region


def _city_menu_embed(player: dict) -> discord.Embed:
    city_name = player.get("current_city", "未知")
    city = get_city(city_name)
    region = get_region(city_name)

    if city:
        desc = city["desc"]
        region_tag = f"所属地区：**{city['region']}**"
    elif region:
        desc = region["desc"]
        region_tag = f"秘地类型：**{region['type']}**"
    else:
        desc = "此地信息不详。"
        region_tag = ""

    embed = discord.Embed(
        title=f"✦ {city_name} ✦",
        description=desc,
        color=discord.Color.teal(),
    )
    if region_tag:
        embed.add_field(name="位置", value=region_tag, inline=True)

    with_conn_lines = []
    from utils.db import get_conn
    with get_conn() as conn:
        others = conn.execute(
            "SELECT name, realm FROM players WHERE current_city = ? AND is_dead = 0 AND discord_id != ?",
            (city_name, player["discord_id"])
        ).fetchall()
    if others:
        with_conn_lines = [f"· **{r['name']}**　{r['realm']}" for r in others[:5]]
        if len(others) > 5:
            with_conn_lines.append(f"…共 {len(others)} 名修士在此")
        embed.add_field(name="在场修士", value="\n".join(with_conn_lines), inline=False)

    return embed


class CityMenuView(discord.ui.View):
    def __init__(self, author, player: dict, cog=None):
        super().__init__(timeout=120)
        self.author = author
        self.player = player
        self.cog = cog

        is_region = get_region(player.get("current_city", "")) is not None

        if not is_region:
            self.add_item(CityMenuButton("茶馆", "tavern", discord.ButtonStyle.primary))
            self.add_item(CityMenuButton("打工", "jobs", discord.ButtonStyle.success))
            self.add_item(CityMenuButton("每日签到", "checkin", discord.ButtonStyle.success))
            self.add_item(CityMenuButton("赌坊", "gamble", discord.ButtonStyle.danger))

        self.add_item(CityMenuButton("返回主菜单", "menu", discord.ButtonStyle.secondary))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user != self.author:
            await interaction.response.send_message("这不是你的面板。", ephemeral=True)
            return False
        return True


class CityMenuButton(discord.ui.Button):
    def __init__(self, label: str, action: str, style: discord.ButtonStyle):
        super().__init__(label=label, style=style)
        self.action = action

    async def callback(self, interaction: discord.Interaction):
        cog = self.view.cog

        if self.action == "tavern":
            await interaction.response.defer()
            tavern_cog = cog.bot.cogs.get("Tavern") if cog else None
            if tavern_cog:
                ctx = await cog.bot.get_context(interaction.message)
                ctx.author = interaction.user
                await tavern_cog.tavern(ctx)
            else:
                await interaction.followup.send("茶馆暂时不可用。", ephemeral=True)

        elif self.action == "jobs":
            from utils.views.jobs import JobsView, _jobs_overview_embed
            from utils.db import get_conn
            uid = str(interaction.user.id)
            with get_conn() as conn:
                player = dict(conn.execute("SELECT * FROM players WHERE discord_id = ?", (uid,)).fetchone())
            await interaction.response.edit_message(
                embed=_jobs_overview_embed(player),
                view=JobsView(interaction.user, player, cog),
            )

        elif self.action == "menu":
            from utils.views.world import _send_main_menu
            if not cog:
                await interaction.response.send_message("无法返回。", ephemeral=True)
                return
            await interaction.response.defer()
            await _send_main_menu(interaction, cog)

        elif self.action == "checkin":
            from utils.views.checkin import CheckinView, _checkin_result_embed
            from utils.db import get_conn
            import time
            uid = str(interaction.user.id)
            with get_conn() as conn:
                player = dict(conn.execute("SELECT * FROM players WHERE discord_id = ?", (uid,)).fetchone())
            today = time.strftime("%Y-%m-%d", time.gmtime())
            last = player.get("checkin_last_date") or ""
            if last == today:
                await interaction.response.send_message("今日已签到，明日再来。", ephemeral=True)
                return
            embed = discord.Embed(
                title="✦ 每日签到 ✦",
                description="点击下方按钮领取今日奖励，每日一次。",
                color=discord.Color.gold(),
            )
            await interaction.response.edit_message(
                embed=embed,
                view=CheckinView(interaction.user, player, cog),
            )

        elif self.action == "gamble":
            from utils.views.gamble import GambleView, _gamble_overview_embed
            from utils.db import get_conn
            uid = str(interaction.user.id)
            with get_conn() as conn:
                player = dict(conn.execute("SELECT * FROM players WHERE discord_id = ?", (uid,)).fetchone())
            await interaction.response.edit_message(
                embed=_gamble_overview_embed(player),
                view=GambleView(interaction.user, player, cog),
            )
