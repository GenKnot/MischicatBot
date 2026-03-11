import discord
from utils.jobs import JOBS, get_available_jobs, get_locked_jobs, _req_desc, JOB_DAILY_LIMIT

TIER_LABELS = {1: "入门", 2: "普通", 3: "进阶", 4: "高级", 5: "顶端"}
TIER_COLORS = {
    1: discord.Color.light_grey(),
    2: discord.Color.green(),
    3: discord.Color.blue(),
    4: discord.Color.purple(),
    5: discord.Color.gold(),
}


def _jobs_overview_embed(player: dict) -> discord.Embed:
    from utils.db import get_conn
    import time
    uid = player["discord_id"]
    now = time.time()
    with get_conn() as conn:
        row = conn.execute(
            "SELECT job_cooldown_until, job_daily_count, job_daily_reset FROM players WHERE discord_id = ?",
            (uid,)
        ).fetchone()

    cooldown_until = row["job_cooldown_until"] or 0 if row else 0
    daily_count = row["job_daily_count"] or 0 if row else 0
    daily_reset = row["job_daily_reset"] or 0 if row else 0

    reset_date = time.gmtime(daily_reset)
    now_date = time.gmtime(now)
    if (now_date.tm_year, now_date.tm_yday) != (reset_date.tm_year, reset_date.tm_yday):
        daily_count = 0

    on_cooldown = now < cooldown_until
    remaining_cd = int(cooldown_until - now) if on_cooldown else 0

    embed = discord.Embed(
        title=f"✦ {player.get('current_city', '城市')} · 打工 ✦",
        description="以劳力换灵石，立即结算，每日最多 3 次，每次冷却 30 分钟。",
        color=discord.Color.teal(),
    )

    status_lines = [f"今日已打工：**{daily_count}/{JOB_DAILY_LIMIT}**"]
    if on_cooldown:
        status_lines.append(f"冷却中：还需 **{remaining_cd // 60} 分 {remaining_cd % 60} 秒**")
    embed.add_field(name="状态", value="\n".join(status_lines), inline=False)

    available = get_available_jobs(player)
    locked = get_locked_jobs(player)

    if available:
        lines = []
        for j in available:
            tier_label = TIER_LABELS.get(j["tier"], "")
            s_min, s_max = j["reward"]["spirit_stones"]
            extra = []
            if "reputation" in j["reward"]:
                extra.append("声望")
            if "alchemy_exp" in j["reward"]:
                extra.append("炼丹经验")
            if "items" in j["reward"]:
                extra.append("材料")
            extra_str = "+" + "/".join(extra) if extra else ""
            lines.append(f"**{j['name']}**（{tier_label}）— {s_min}~{s_max} 灵石 {extra_str}")
        embed.add_field(name="可接工作", value="\n".join(lines), inline=False)

    if locked:
        lock_lines = []
        for j in locked[:5]:
            lock_lines.append(f"🔒 **{j['name']}** — 需要：{_req_desc(j['req'])}")
        if len(locked) > 5:
            lock_lines.append(f"…还有 {len(locked) - 5} 个未解锁")
        embed.add_field(name="未解锁", value="\n".join(lock_lines), inline=False)

    return embed


class JobsView(discord.ui.View):
    def __init__(self, author, player: dict, cog=None):
        super().__init__(timeout=120)
        self.author = author
        self.player = player
        self.cog = cog
        available = get_available_jobs(player)
        for job in available:
            self.add_item(JobButton(job))
        self.add_item(BackToCityButton())

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user != self.author:
            await interaction.response.send_message("这不是你的面板。", ephemeral=True)
            return False
        return True


class JobButton(discord.ui.Button):
    def __init__(self, job: dict):
        tier = job["tier"]
        styles = {
            1: discord.ButtonStyle.secondary,
            2: discord.ButtonStyle.success,
            3: discord.ButtonStyle.primary,
            4: discord.ButtonStyle.primary,
            5: discord.ButtonStyle.danger,
        }
        super().__init__(label=job["name"], style=styles.get(tier, discord.ButtonStyle.secondary))
        self.job = job

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer()
        from utils.db import get_conn
        from utils.jobs import do_job, _check_req
        uid = str(interaction.user.id)
        with get_conn() as conn:
            row = conn.execute("SELECT * FROM players WHERE discord_id = ?", (uid,)).fetchone()
            if not row:
                return await interaction.followup.send("角色不存在。", ephemeral=True)
            player = dict(row)

        if not _check_req(player, self.job["req"]):
            return await interaction.followup.send("你已不满足此工作的要求。", ephemeral=True)

        result = do_job(player, self.job)

        if not result["ok"]:
            return await interaction.followup.send(result["reason"], ephemeral=True)

        embed = discord.Embed(
            title=f"✦ {result['job_name']} · 完成 ✦",
            color=TIER_COLORS.get(self.job["tier"], discord.Color.teal()),
        )
        embed.add_field(name=result["speaker"], value=f"*{result['dialogue']}*", inline=False)

        reward_lines = [f"灵石 +**{result['spirit_stones']}**"]
        if result["reputation"]:
            reward_lines.append(f"声望 +**{result['reputation']}**")
        if result["alchemy_exp"]:
            reward_lines.append(f"炼丹经验 +**{result['alchemy_exp']}**")
        if result["items"]:
            reward_lines.append("材料：" + "、".join(result["items"]))
        embed.add_field(name="收获", value="\n".join(reward_lines), inline=False)

        if result["risk_triggered"]:
            embed.add_field(
                name="⚠️ 意外",
                value=f"途中遭遇意外，损失 **{result['lifespan_loss']} 年** 寿元。",
                inline=False,
            )

        embed.set_footer(text="冷却 30 分钟后可再次打工")

        with get_conn() as conn:
            updated = dict(conn.execute("SELECT * FROM players WHERE discord_id = ?", (uid,)).fetchone())

        await interaction.followup.send(
            embed=embed,
            view=JobsView(interaction.user, updated, self.view.cog),
        )


class BackToCityButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="返回城市", style=discord.ButtonStyle.secondary)

    async def callback(self, interaction: discord.Interaction):
        from utils.views.city import CityMenuView, _city_menu_embed
        from utils.db import get_conn
        uid = str(interaction.user.id)
        with get_conn() as conn:
            player = dict(conn.execute("SELECT * FROM players WHERE discord_id = ?", (uid,)).fetchone())
        await interaction.response.edit_message(
            embed=_city_menu_embed(player),
            view=CityMenuView(interaction.user, player, self.view.cog),
        )
