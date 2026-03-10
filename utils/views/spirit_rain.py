import json
import time

import discord

from utils.db import get_conn


def _get_active_event() -> dict | None:
    now = time.time()
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM public_events WHERE status = 'active' AND ends_at > ? ORDER BY started_at DESC LIMIT 1",
            (now,)
        ).fetchone()
    return dict(row) if row else None


def _get_pending_event() -> dict | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM public_events WHERE status = 'pending' ORDER BY started_at DESC LIMIT 1"
        ).fetchone()
    return dict(row) if row else None


def _today_trigger_ts() -> float:
    from zoneinfo import ZoneInfo
    from datetime import datetime
    now = datetime.now(ZoneInfo("America/Montreal"))
    return now.replace(hour=22, minute=0, second=0, microsecond=0).timestamp()


def _send_main_menu_ephemeral(interaction: discord.Interaction, cog):
    pass


SPIRIT_RAIN_DESC = (
    "天地异象，灵气暴涨，灵雨降临指定城市。\n\n"
    "**活动机制**\n"
    "· 在场修士修炼加成 **+150%**，持续 1 小时（现实）\n"
    "· 灵雨活动每次最多参与 **2 次**，每次间隔 **10 分钟**冷却\n"
    "· 可选择以下活动参与：\n"
    "　💎 **灵雨结晶** — 收集落地灵晶，获得材料与灵石\n"
    "　🧘 **灵雨感悟** — 打坐感悟，有概率获得属性点\n"
    "　💪 **灵雨淬体** — 以体魄承受灵雨（需体魄 ≥ 7）\n\n"
    "**守城（独立系统）**\n"
    "· ⚔️ **参与守城** — 自愿加入守城队伍，贡献战力\n"
    "· 参与守城后将**锁定在城内**直到事件结束，无法离开\n"
    "· 守城与灵雨活动互不影响，可同时参与\n\n"
    "**万兽齐鸣（30% 概率）**\n"
    "· 第 1 名：2件稀有装备 + 大量灵石 + 声望 +50\n"
    "· 第 2-3 名：1件稀有装备 + 灵石 + 声望 +30\n"
    "· 其余守城者：灵石 + 声望 +10\n"
    "· 临阵脱逃者（领取奖励后离城）：结算时公开点名\n"
    "· 在城内未守城的修士有 30% 概率被妖兽袭击，损失寿元\n\n"
    "**触发时间**：每日 22:00（北美东部时间），20:00 起每半小时预告"
)


async def _build_main_menu(interaction: discord.Interaction, cog):
    from utils.views.menu import MainMenuView, _build_menu_embed
    uid = str(interaction.user.id)
    player = cog._get_player(uid)
    if player and not player["is_dead"]:
        updates, _ = cog._settle_time(player)
        cog._apply_updates(uid, updates)
        player = cog._get_player(uid)
    has_player = player is not None and not player["is_dead"]
    can_bt = has_player and cog._can_breakthrough(player)
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
    embed = _build_menu_embed(has_dual)
    view = MainMenuView(interaction.user, has_player, can_bt, cog, player, city_players)
    return embed, view


class TravelToEventView(discord.ui.View):
    def __init__(self, city: str, event_id: str, pe_cog=None):
        super().__init__(timeout=None)
        self.city = city
        self.event_id = event_id
        self.pe_cog = pe_cog

    @discord.ui.button(label="前往城市", style=discord.ButtonStyle.success)
    async def travel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        uid = str(interaction.user.id)
        city = self.city

        with get_conn() as conn:
            row = conn.execute("SELECT * FROM players WHERE discord_id = ?", (uid,)).fetchone()
            if not row:
                return await interaction.followup.send("尚未踏入修仙之路。", ephemeral=True)
            player = dict(row)

        if player["is_dead"]:
            return await interaction.followup.send("道友已坐化。", ephemeral=True)
        if player["current_city"] == city:
            return await interaction.followup.send(f"你已在 **{city}**，无需移动。", ephemeral=True)

        now = time.time()
        is_cultivating = player["cultivating_until"] and now < player["cultivating_until"]
        is_gathering = player["gathering_until"] and now < player["gathering_until"]

        if is_cultivating or is_gathering:
            activity = "闭关修炼" if is_cultivating else player.get("gathering_type", "采集")
            view = ConfirmStopAndTravelView(uid, city, activity, is_cultivating, is_gathering, player)
            return await interaction.followup.send(
                f"道友正在**{activity}**中，前往 **{city}** 需要先停止当前活动。\n是否停止并前往？",
                view=view, ephemeral=True
            )

        if player.get("active_quest"):
            return await interaction.followup.send("道友正在执行任务，无法移动。", ephemeral=True)

        with get_conn() as conn:
            defense_row = conn.execute(
                "SELECT 1 FROM public_event_participants ep "
                "JOIN public_events e ON ep.event_id = e.event_id "
                "WHERE ep.discord_id = ? AND ep.activity = 'defense' AND e.status = 'active'",
                (uid,)
            ).fetchone()
        if defense_row:
            return await interaction.followup.send("你正在守城，无法离开！坚守阵地直到事件结束。", ephemeral=True)

        with get_conn() as conn:
            conn.execute("UPDATE players SET current_city = ?, last_active = ? WHERE discord_id = ?", (city, now, uid))
            conn.commit()
        await interaction.followup.send(f"已传送至 **{city}**，灵雨即将降临，做好准备！", ephemeral=True)

    @discord.ui.button(label="返回主菜单", style=discord.ButtonStyle.secondary)
    async def back_menu(self, interaction: discord.Interaction, button: discord.ui.Button):
        cog = self.pe_cog.bot.cogs.get("Cultivation") if self.pe_cog else None
        if not cog:
            return await interaction.response.send_message("无法返回。", ephemeral=True)
        embed, view = await _build_main_menu(interaction, cog)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)


class ConfirmStopAndTravelView(discord.ui.View):
    def __init__(self, uid: str, city: str, activity: str, is_cultivating: bool, is_gathering: bool, player: dict):
        super().__init__(timeout=60)
        self.uid = uid
        self.city = city
        self.activity = activity
        self.is_cultivating = is_cultivating
        self.is_gathering = is_gathering
        self.player = player

    @discord.ui.button(label="停止并前往", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        if str(interaction.user.id) != self.uid:
            return await interaction.response.send_message("这不是你的操作。", ephemeral=True)

        now = time.time()
        updates = {"current_city": self.city, "last_active": now}

        if self.is_cultivating:
            cult_cog = interaction.client.cogs.get("Cultivation")
            if cult_cog:
                await cult_cog._stop_cultivation_with_pair(self.uid, now, actor_name=interaction.user.display_name)
            else:
                player = self.player
                from utils.character import seconds_to_years, calc_cultivation_gain, get_cultivation_bonus
                elapsed_years = seconds_to_years(now - player["last_active"])
                actual_years = min(int(elapsed_years), player.get("cultivating_years") or 0)
                bonus = get_cultivation_bonus(str(player["discord_id"]), player["current_city"], player.get("cave"))
                if player.get("pill_buff_until") and now < player["pill_buff_until"]:
                    bonus += 0.5
                overflow = player.get("cultivation_overflow") or 0
                if overflow > 0:
                    total_years = player.get("cultivating_years") or 1
                    gain = int(overflow * actual_years / max(total_years, 1))
                else:
                    gain = int(calc_cultivation_gain(actual_years, player["comprehension"], player["spirit_root_type"]) * (1 + bonus))
                updates["cultivation"] = player["cultivation"] + gain
                updates["lifespan"] = max(0, player["lifespan"] - actual_years)
                updates["cultivating_until"] = None
                updates["cultivating_years"] = None
                updates["cultivation_overflow"] = 0

        if self.is_gathering:
            updates["gathering_until"] = None
            updates["gathering_type"] = None

        fields = ", ".join(f"{k} = ?" for k in updates)
        values = list(updates.values()) + [self.uid]
        with get_conn() as conn:
            conn.execute(f"UPDATE players SET {fields} WHERE discord_id = ?", values)
            conn.commit()

        self.stop()
        await interaction.response.edit_message(
            content=f"已停止**{self.activity}**，传送至 **{self.city}**！灵雨即将降临，做好准备！",
            view=None
        )

    @discord.ui.button(label="取消", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        if str(interaction.user.id) != self.uid:
            return await interaction.response.send_message("这不是你的操作。", ephemeral=True)
        self.stop()
        await interaction.response.edit_message(content="已取消。", view=None)


class _EventDetailButton(discord.ui.Button):
    def __init__(self, label: str, event: dict | None, pe_cog=None):
        super().__init__(label=label, style=discord.ButtonStyle.primary)
        self.event = event
        self.pe_cog = pe_cog

    async def callback(self, interaction: discord.Interaction):
        event = self.event

        if not event:
            embed = discord.Embed(title="✦ 天降灵雨 ✦", description=SPIRIT_RAIN_DESC, color=discord.Color.blue())
            embed.set_footer(text="当前无进行中的事件，敬请期待。")
            return await interaction.response.send_message(
                embed=embed, view=_BackToOverviewView(interaction.user, self.pe_cog), ephemeral=True
            )

        data = json.loads(event["data"])
        city = data.get("city", "未知城市")

        if event["status"] == "active":
            remaining = max(0, event["ends_at"] - time.time())
            with get_conn() as conn:
                count = conn.execute(
                    "SELECT COUNT(*) FROM public_event_participants WHERE event_id = ?",
                    (event["event_id"],)
                ).fetchone()[0]
            embed = discord.Embed(title="✦ 天降灵雨 · 进行中 ✦", description=SPIRIT_RAIN_DESC, color=discord.Color.blue())
            embed.add_field(name="当前城市", value=city, inline=True)
            embed.add_field(name="剩余时间", value=f"{remaining/60:.0f} 分钟", inline=True)
            embed.add_field(name="参与人数", value=str(count), inline=True)
            from utils.events.public.spirit_rain import SpiritRainView
            await interaction.response.send_message(
                embed=embed, view=SpiritRainView(event["event_id"], city, self.pe_cog), ephemeral=True
            )
        else:
            remaining = max(0, _today_trigger_ts() - time.time())
            embed = discord.Embed(title="✦ 天降灵雨 · 即将开始 ✦", description=SPIRIT_RAIN_DESC, color=discord.Color.blue())
            embed.add_field(name="降临城市", value=city, inline=True)
            embed.add_field(name="距开始", value=f"{remaining/60:.0f} 分钟", inline=True)
            await interaction.response.send_message(
                embed=embed, view=TravelToEventView(city, event["event_id"], self.pe_cog), ephemeral=True
            )


class _BackToOverviewView(discord.ui.View):
    def __init__(self, author, pe_cog=None):
        super().__init__(timeout=120)
        self.author = author
        self.pe_cog = pe_cog

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user != self.author:
            await interaction.response.send_message("这不是你的面板。", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="返回公共事件", style=discord.ButtonStyle.secondary)
    async def back_overview(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.pe_cog:
            return await interaction.response.send_message("无法返回。", ephemeral=True)
        from utils.views.public_event_overview import PublicEventOverviewView
        from utils.events.public.wanbao import get_active_auction
        active = _get_active_event()
        pending = _get_pending_event() if not active else None
        auction = get_active_auction()
        embed = discord.Embed(
            title="✦ 公共事件 ✦",
            description="天地异象，机缘降临。以下为当前或即将发生的公共事件：",
            color=discord.Color.blue(),
        )
        if active:
            data = json.loads(active["data"])
            city = data.get("city", "未知城市")
            remaining = max(0, active["ends_at"] - time.time())
            embed.add_field(name=f"🔴 {active['title']} · 进行中", value=f"城市：**{city}**　剩余：**{remaining/60:.0f} 分钟**", inline=False)
        elif pending:
            data = json.loads(pending["data"])
            city = data.get("city", "未知城市")
            remaining = max(0, _today_trigger_ts() - time.time())
            embed.add_field(name=f"🟡 {pending['title']} · 即将开始", value=f"城市：**{city}**　约 **{remaining/60:.0f} 分钟**后开始", inline=False)
        else:
            embed.add_field(name="暂无事件", value="下次天降灵雨将于今日 22:00（北美东部时间）触发。", inline=False)
        await interaction.response.defer()
        await interaction.followup.send(embed=embed, view=PublicEventOverviewView(active, pending, auction, self.pe_cog), ephemeral=True)

    @discord.ui.button(label="返回主菜单", style=discord.ButtonStyle.secondary)
    async def back_menu(self, interaction: discord.Interaction, button: discord.ui.Button):
        cog = self.pe_cog.bot.cogs.get("Cultivation") if self.pe_cog else None
        if not cog:
            return await interaction.response.send_message("无法返回。", ephemeral=True)
        embed, view = await _build_main_menu(interaction, cog)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
