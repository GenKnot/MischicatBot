import asyncio
import json
import os
import random
import time
import uuid

import discord
from zoneinfo import ZoneInfo
from discord.ext import commands, tasks
from datetime import datetime

from utils.db import get_conn
from utils.character import years_to_seconds, seconds_to_years
from utils.events.public import PUBLIC_EVENTS

MONTREAL_TZ = ZoneInfo("America/Montreal")
PUBLIC_EVENT_CHANNEL_ENV = "PUBLIC_EVENT_CHANNEL_ID"

PREVIEW_HOURS = [20, 20, 21, 21, 22]
PREVIEW_MINUTES = [0, 30, 0, 30, 0]

WANBAO_TRIGGER_HOUR = 20
WANBAO_PREVIEW_HOUR = 18


def _get_announce_channel(bot) -> discord.TextChannel | None:
    channel_id = os.getenv(PUBLIC_EVENT_CHANNEL_ENV)
    if not channel_id:
        return None
    return bot.get_channel(int(channel_id))


def _get_active_event() -> dict | None:
    now = time.time()
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM public_events WHERE status = 'active' AND ends_at > ? ORDER BY started_at DESC LIMIT 1",
            (now,)
        ).fetchone()
    return dict(row) if row else None


def _get_expired_event() -> dict | None:
    now = time.time()
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM public_events WHERE status = 'active' AND ends_at <= ? ORDER BY ends_at ASC LIMIT 1",
            (now,)
        ).fetchone()
    return dict(row) if row else None


def _get_pending_event() -> dict | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM public_events WHERE status = 'pending' ORDER BY started_at DESC LIMIT 1"
        ).fetchone()
    return dict(row) if row else None


def _montreal_now() -> datetime:
    return datetime.now(MONTREAL_TZ)


def _today_trigger_ts() -> float:
    now = _montreal_now()
    trigger = now.replace(hour=22, minute=0, second=0, microsecond=0)
    return trigger.timestamp()


def _last_trigger_date_str() -> str | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT data FROM public_events WHERE event_type = 'spirit_rain' AND status IN ('active', 'ended', 'pending') ORDER BY started_at DESC LIMIT 1"
        ).fetchone()
    if not row:
        return None
    try:
        d = json.loads(row["data"])
        return d.get("trigger_date")
    except Exception:
        return None


class PublicEventsCog(commands.Cog, name="PublicEvents"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._preview_sent: set[int] = set()
        self._wanbao_auction_id: str | None = None
        self._wanbao_preview_sent: set[str] = set()
        self._scheduler.start()

    def cog_unload(self):
        self._scheduler.cancel()

    @tasks.loop(minutes=1)
    async def _scheduler(self):
        await self.bot.wait_until_ready()
        now_mt = _montreal_now()
        today_str = now_mt.strftime("%Y-%m-%d")
        h, m = now_mt.hour, now_mt.minute

        expired = _get_expired_event()
        if expired:
            await self._settle_event(expired)
            return

        active = _get_active_event()
        if active:
            return

        last_date = _last_trigger_date_str()
        if last_date == today_str:
            return

        for i, (ph, pm) in enumerate(zip(PREVIEW_HOURS, PREVIEW_MINUTES)):
            if h == ph and m == pm and i not in self._preview_sent:
                self._preview_sent.add(i)
                if i == 0:
                    await self._prepare_pending_event(today_str)
                    await self._send_preview(i)
                elif i < 4:
                    await self._send_preview(i)
                else:
                    await self._trigger_spirit_rain(today_str)
                break

        if now_mt.hour >= 23 and len(self._preview_sent) > 0:
            if today_str not in (last_date or ""):
                self._preview_sent.clear()

        await self._wanbao_scheduler(now_mt, today_str, h, m)

    async def _prepare_pending_event(self, today_str: str):
        from utils.world import CITIES
        existing = _get_pending_event()
        if existing:
            return
        city = random.choice(CITIES)["name"]
        event_id = str(uuid.uuid4())[:8]
        trigger_ts = _today_trigger_ts()
        data = {"city": city, "trigger_date": today_str, "beast_tide": False}
        with get_conn() as conn:
            conn.execute(
                "INSERT INTO public_events (event_id, event_type, title, started_at, ends_at, status, data) VALUES (?, ?, ?, ?, ?, 'pending', ?)",
                (event_id, "spirit_rain", "天降灵雨", trigger_ts, trigger_ts + 3600, json.dumps(data))
            )
            conn.commit()

    async def _send_preview(self, index: int):
        channel = _get_announce_channel(self.bot)
        if not channel:
            return

        pending = _get_pending_event()
        if not pending:
            return

        data = json.loads(pending["data"])
        city = data.get("city", "未知城市")
        remaining_mins = (4 - index) * 30

        embed = discord.Embed(
            title="⚠️ 天降灵雨 · 预告",
            description=(
                f"天地异象将至！**{remaining_mins} 分钟**后，灵雨将降临 **{city}**。\n\n"
                "在场修士将获得 **+150%** 修炼加成，并可参与特殊活动。\n"
                "提前前往可抢占先机！"
            ),
            color=discord.Color.blue(),
        )
        embed.set_footer(text=f"第 {index + 1}/4 次预告 · 北美东部时间 22:00 正式开始")

        view = TravelToEventView(city, pending["event_id"])
        await channel.send(embed=embed, view=view)

    async def _trigger_spirit_rain(self, today_str: str):
        from utils.world import CITIES
        channel = _get_announce_channel(self.bot)

        pending = _get_pending_event()
        if pending:
            data = json.loads(pending["data"])
            city = data.get("city")
            event_id = pending["event_id"]
            now = time.time()
            ends_at = now + 3600
            with get_conn() as conn:
                conn.execute(
                    "UPDATE public_events SET status = 'active', started_at = ?, ends_at = ? WHERE event_id = ?",
                    (now, ends_at, event_id)
                )
                conn.commit()
        else:
            city = random.choice(CITIES)["name"]
            event_id = str(uuid.uuid4())[:8]
            now = time.time()
            ends_at = now + 3600
            data = {"city": city, "trigger_date": today_str, "beast_tide": False}
            with get_conn() as conn:
                conn.execute(
                    "INSERT INTO public_events (event_id, event_type, title, started_at, ends_at, status, data) VALUES (?, ?, ?, ?, ?, 'active', ?)",
                    (event_id, "spirit_rain", "天降灵雨", now, ends_at, json.dumps(data))
                )
                conn.commit()

        has_beast_tide = random.random() < 0.30
        with get_conn() as conn:
            d = json.loads(conn.execute("SELECT data FROM public_events WHERE event_id = ?", (event_id,)).fetchone()["data"])
            d["beast_tide"] = has_beast_tide
            d["trigger_date"] = today_str
            conn.execute("UPDATE public_events SET data = ? WHERE event_id = ?", (json.dumps(d), event_id))
            conn.commit()

        module = PUBLIC_EVENTS["spirit_rain"]
        await module.on_trigger(self.bot, channel, event_id, city)

    async def _settle_event(self, event: dict):
        channel = _get_announce_channel(self.bot)
        module = PUBLIC_EVENTS.get(event["event_type"])
        if module:
            await module.on_settle(self.bot, channel, event)
        self._preview_sent.clear()

    async def _wanbao_scheduler(self, now_mt, today_str: str, h: int, m: int):
        from utils.events.public.wanbao import (
            get_or_create_auction, get_active_auction, get_current_lot,
            start_auction, advance_lot, settle_lot, get_lots, WANBAO_CITY
        )
        channel = _get_announce_channel(self.bot)

        if h == WANBAO_PREVIEW_HOUR and m == 0:
            key = f"{today_str}_preview1"
            if key not in self._wanbao_preview_sent:
                self._wanbao_preview_sent.add(key)
                auction = get_or_create_auction(today_str)
                if channel:
                    lots = get_lots(auction["auction_id"])
                    embed = discord.Embed(
                        title="✦ 万宝楼大型交易会 · 预告 ✦",
                        description=(
                            f"两个时辰后，万宝楼将举办本期大型拍卖会。\n\n"
                            f"本次共有 **{len(lots)}** 件拍品，包含功法、丹药与灵材。\n"
                            f"想参与的道友请在 **北美东部时间 {WANBAO_TRIGGER_HOUR}:00** 前抵达 **万宝楼**。\n\n"
                            f"可上架物品（每人最多2件），流拍需支付取回费。"
                        ),
                        color=discord.Color.gold(),
                    )
                    view = discord.ui.View(timeout=None)
                    view.add_item(_WanbaoTravelButton())
                    await channel.send(embed=embed, view=view)

        if h == WANBAO_TRIGGER_HOUR - 1 and m == 30:
            key = f"{today_str}_preview2"
            if key not in self._wanbao_preview_sent:
                self._wanbao_preview_sent.add(key)
                auction = get_or_create_auction(today_str)
                if channel:
                    lots = get_lots(auction["auction_id"])
                    embed = discord.Embed(
                        title="✦ 万宝楼交易会 · 30分钟后开始 ✦",
                        description=f"拍卖会即将开始，当前已有 **{len(lots)}** 件拍品。\n前往 **万宝楼** 参与竞拍！",
                        color=discord.Color.gold(),
                    )
                    view = discord.ui.View(timeout=None)
                    view.add_item(_WanbaoTravelButton())
                    await channel.send(embed=embed, view=view)

        if h == WANBAO_TRIGGER_HOUR and m == 0:
            auction = get_or_create_auction(today_str)
            if auction["status"] == "pending":
                first_lot = start_auction(auction["auction_id"])
                if first_lot and channel:
                    from utils.events.public.wanbao import LOT_DURATION
                    from utils.views.wanbao import build_lot_embed, _item_display
                    lots = get_lots(auction["auction_id"])
                    with get_conn() as conn:
                        a = conn.execute("SELECT * FROM wanbao_auctions WHERE auction_id = ?", (auction["auction_id"],)).fetchone()
                    embed = build_lot_embed(dict(first_lot), a["ends_at"], 0, len(lots))
                    embed.title = f"🔔 万宝楼拍卖会开始！第 1/{len(lots)} 件"
                    self._wanbao_auction_id = auction["auction_id"]
                    await channel.send(embed=embed)

        active = get_active_auction()
        if active and active["status"] == "active":
            now = time.time()
            if now >= active["ends_at"]:
                lot = get_current_lot(active["auction_id"])
                if lot:
                    result = settle_lot(lot)
                    if channel:
                        await self._announce_lot_result(channel, result, active["auction_id"])
                    next_lot = advance_lot(active["auction_id"])
                    if next_lot:
                        with get_conn() as conn:
                            a = conn.execute("SELECT * FROM wanbao_auctions WHERE auction_id = ?", (active["auction_id"],)).fetchone()
                        lots = get_lots(active["auction_id"])
                        from utils.views.wanbao import build_lot_embed
                        embed = build_lot_embed(dict(next_lot), a["ends_at"], next_lot["lot_index"], len(lots))
                        if channel:
                            view = discord.ui.View(timeout=None)
                            view.add_item(_WanbaoTravelButton())
                            await channel.send(embed=embed, view=view)
                    else:
                        if channel:
                            await self._announce_auction_end(channel, active["auction_id"])

    async def _announce_lot_result(self, channel, result: dict, auction_id: str):
        lot = result["lot"]
        from utils.views.wanbao import _item_display
        if result["winner_id"]:
            with get_conn() as conn:
                p = conn.execute("SELECT name FROM players WHERE discord_id = ?", (result["winner_id"],)).fetchone()
            winner_name = p["name"] if p else f"<@{result['winner_id']}>"
            seller = "万宝楼" if not lot["seller_id"] else f"<@{lot['seller_id']}>"
            embed = discord.Embed(
                title=f"✅ {_item_display(lot)} · 成交",
                description=(
                    f"得标者：**{winner_name}**\n"
                    f"成交价：**{result['final_price']} 灵石**\n"
                    f"卖家实收：**{result['seller_income']} 灵石**（扣除8%手续费）"
                ),
                color=discord.Color.green(),
            )
        else:
            embed = discord.Embed(
                title=f"❌ {_item_display(lot)} · 流拍",
                description="无人出价，此拍品流拍。" + ("卖家需支付取回费。" if lot["seller_id"] else ""),
                color=discord.Color.red(),
            )
        await channel.send(embed=embed)

    async def _announce_auction_end(self, channel, auction_id: str):
        from utils.events.public.wanbao import get_lots as _get_lots
        lots = _get_lots(auction_id)
        sold = [l for l in lots if l["status"] == "sold"]
        unsold = [l for l in lots if l["status"] == "unsold"]
        with get_conn() as conn:
            conn.execute("DELETE FROM wanbao_frozen WHERE auction_id = ?", (auction_id,))
            conn.commit()
        embed = discord.Embed(
            title="✦ 万宝楼拍卖会圆满结束 ✦",
            description=(
                f"本次共拍出 **{len(sold)}** 件，流拍 **{len(unsold)}** 件。\n"
                "感谢各位道友的参与，下次拍卖会再见！"
            ),
            color=discord.Color.gold(),
        )
        await channel.send(embed=embed)

    @commands.hybrid_command(name="万宝楼", aliases=["wbl"], description="进入万宝楼拍卖界面")
    async def wanbao(self, ctx):
        uid = str(ctx.author.id)
        with get_conn() as conn:
            row = conn.execute("SELECT * FROM players WHERE discord_id = ?", (uid,)).fetchone()
        if not row:
            return await ctx.send(f"{ctx.author.mention} 尚未踏入修仙之路。")
        player = dict(row)
        if player["is_dead"]:
            return await ctx.send(f"{ctx.author.mention} 道友已坐化。")
        if player["current_city"] != "万宝楼":
            return await ctx.send(f"{ctx.author.mention} 需前往 **万宝楼** 方可使用此功能。")

        from utils.events.public.wanbao import get_active_auction, get_lots
        from utils.views.wanbao import WanbaoMainView, build_lots_list_embed
        auction = get_active_auction()
        if not auction:
            return await ctx.send(f"{ctx.author.mention} 当前没有拍卖活动，请等待今日 **北美东部时间 {WANBAO_TRIGGER_HOUR}:00** 的拍卖会。")

        lots = get_lots(auction["auction_id"])
        status_text = {"pending": "等待开始", "active": "进行中", "ended": "已结束"}.get(auction["status"], "未知")
        embed = discord.Embed(
            title="✦ 万宝楼拍卖会 ✦",
            description=f"状态：**{status_text}**　拍品：**{len(lots)}** 件",
            color=discord.Color.gold(),
        )
        view = WanbaoMainView(ctx.author, self)
        await ctx.send(ctx.author.mention, embed=embed, view=view)

    @commands.hybrid_command(name="公共事件", aliases=["ggsj"], description="查看当前或即将发生的世界公共事件")
    async def show_active_event(self, ctx):
        active = _get_active_event()
        pending = _get_pending_event() if not active else None

        embed = discord.Embed(
            title="✦ 公共事件 ✦",
            description="天地异象，机缘降临。以下为当前或即将发生的公共事件：",
            color=discord.Color.blue(),
        )

        if active:
            data = json.loads(active["data"])
            city = data.get("city", "未知城市")
            remaining = max(0, active["ends_at"] - time.time())
            embed.add_field(
                name=f"🔴 {active['title']} · 进行中",
                value=f"城市：**{city}**　剩余：**{remaining/60:.0f} 分钟**",
                inline=False,
            )
        elif pending:
            data = json.loads(pending["data"])
            city = data.get("city", "未知城市")
            remaining = max(0, _today_trigger_ts() - time.time())
            embed.add_field(
                name=f"🟡 {pending['title']} · 即将开始",
                value=f"城市：**{city}**　约 **{remaining/60:.0f} 分钟**后开始",
                inline=False,
            )
        else:
            embed.add_field(
                name="暂无事件",
                value="下次天降灵雨将于今日 22:00（北美东部时间）触发。",
                inline=False,
            )

        view = PublicEventOverviewView(active, pending, self)
        await ctx.send(ctx.author.mention, embed=embed, view=view)

    @commands.hybrid_command(name="预备灵雨", aliases=["ybly"], description="手动预备一场天降灵雨事件（管理员）")
    @commands.has_permissions(administrator=True)
    async def prepare_spirit_rain(self, ctx, city: str = None):
        from utils.world import CITIES
        if not city:
            city = random.choice(CITIES)["name"]
        event_id = str(uuid.uuid4())[:8]
        now_mt = _montreal_now()
        today_str = now_mt.strftime("%Y-%m-%d")
        trigger_ts = _today_trigger_ts()
        data = {"city": city, "trigger_date": today_str, "beast_tide": False}
        with get_conn() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO public_events (event_id, event_type, title, started_at, ends_at, status, data) VALUES (?, ?, ?, ?, ?, 'pending', ?)",
                (event_id, "spirit_rain", "天降灵雨", trigger_ts, trigger_ts + 3600, json.dumps(data))
            )
            conn.commit()
        await ctx.send(f"{ctx.author.mention} 已预备灵雨事件，城市：**{city}**，事件ID：`{event_id}`")


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
                view=view,
                ephemeral=True
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
        from utils.views.world import _send_main_menu
        cog = self.pe_cog.bot.cogs.get("Cultivation") if self.pe_cog else None
        if not cog:
            await interaction.response.send_message("无法返回。", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        await _send_main_menu(interaction, cog)


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
                # 双修时将由 Cultivation 统一处理“停一方=停双方”
                await cult_cog._stop_cultivation_with_pair(self.uid, now, actor_name=interaction.user.display_name)
            else:
                # fallback：仅停止自己（不含双修联动）
                player = self.player
                from utils.character import seconds_to_years, calc_cultivation_gain
                from utils.character import get_cultivation_bonus
                elapsed_years = seconds_to_years(now - player["last_active"])
                actual_years = min(int(elapsed_years), player.get("cultivating_years") or 0)
                bonus = get_cultivation_bonus(str(player["discord_id"]), player["current_city"], player.get("cave"))
                pill_active = player.get("pill_buff_until") and now < player["pill_buff_until"]
                if pill_active:
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


class PublicEventOverviewView(discord.ui.View):
    def __init__(self, active: dict | None, pending: dict | None, pe_cog=None):
        super().__init__(timeout=120)
        self.active = active
        self.pending = pending
        self.pe_cog = pe_cog

        event = active or pending
        self.add_item(_EventDetailButton(event["title"] if event else "天降灵雨", event, pe_cog))
        if event:
            data = json.loads(event["data"])
            city = data.get("city", "未知城市")
            self.add_item(_TravelButton(city, event["event_id"]))
        self.add_item(_PEBackToMenuButton(pe_cog))


class _TravelButton(discord.ui.Button):
    def __init__(self, city: str, event_id: str):
        super().__init__(label=f"前往 {city}", style=discord.ButtonStyle.success)
        self.city = city
        self.event_id = event_id

    async def callback(self, interaction: discord.Interaction):
        view = TravelToEventView(self.city, self.event_id)
        await interaction.response.send_message(f"前往 **{self.city}**：", view=view, ephemeral=True)


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


class _EventDetailButton(discord.ui.Button):
    def __init__(self, label: str, event: dict | None, pe_cog=None):
        super().__init__(label=label, style=discord.ButtonStyle.primary)
        self.event = event
        self.pe_cog = pe_cog

    async def callback(self, interaction: discord.Interaction):
        event = self.event

        if not event:
            embed = discord.Embed(
                title="✦ 天降灵雨 ✦",
                description=SPIRIT_RAIN_DESC,
                color=discord.Color.blue(),
            )
            embed.set_footer(text="当前无进行中的事件，敬请期待。")
            return await interaction.response.send_message(
                embed=embed,
                view=_BackToOverviewView(interaction.user, self.pe_cog),
                ephemeral=True,
            )

        data = json.loads(event["data"])
        city = data.get("city", "未知城市")
        is_active = event["status"] == "active"

        if is_active:
            remaining = max(0, event["ends_at"] - time.time())
            with get_conn() as conn:
                count = conn.execute(
                    "SELECT COUNT(*) FROM public_event_participants WHERE event_id = ?",
                    (event["event_id"],)
                ).fetchone()[0]
            embed = discord.Embed(
                title="✦ 天降灵雨 · 进行中 ✦",
                description=SPIRIT_RAIN_DESC,
                color=discord.Color.blue(),
            )
            embed.add_field(name="当前城市", value=city, inline=True)
            embed.add_field(name="剩余时间", value=f"{remaining/60:.0f} 分钟", inline=True)
            embed.add_field(name="参与人数", value=str(count), inline=True)
            from utils.events.public.spirit_rain import SpiritRainView
            await interaction.response.send_message(
                embed=embed,
                view=SpiritRainView(event["event_id"], city, self.pe_cog),
                ephemeral=True,
            )
        else:
            remaining = max(0, _today_trigger_ts() - time.time())
            embed = discord.Embed(
                title="✦ 天降灵雨 · 即将开始 ✦",
                description=SPIRIT_RAIN_DESC,
                color=discord.Color.blue(),
            )
            embed.add_field(name="降临城市", value=city, inline=True)
            embed.add_field(name="距开始", value=f"{remaining/60:.0f} 分钟", inline=True)
            await interaction.response.send_message(
                embed=embed,
                view=TravelToEventView(city, event["event_id"], self.pe_cog),
                ephemeral=True,
            )


class _PEBackToMenuButton(discord.ui.Button):
    def __init__(self, pe_cog=None):
        super().__init__(label="返回主菜单", style=discord.ButtonStyle.secondary)
        self.pe_cog = pe_cog

    async def callback(self, interaction: discord.Interaction):
        from utils.views.world import _send_main_menu
        cog = None
        if self.pe_cog:
            cog = self.pe_cog.bot.cogs.get("Cultivation")
        if not cog:
            await interaction.response.send_message("无法返回。", ephemeral=True)
            return
        await interaction.response.defer()
        await _send_main_menu(interaction, cog)


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
            await interaction.response.send_message("无法返回。", ephemeral=True)
            return
        ctx = await self.pe_cog.bot.get_context(interaction.message)
        ctx.author = interaction.user
        await interaction.response.defer()
        active = _get_active_event()
        pending = _get_pending_event() if not active else None
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
        await interaction.followup.send(embed=embed, view=PublicEventOverviewView(active, pending, self.pe_cog), ephemeral=True)

    @discord.ui.button(label="返回主菜单", style=discord.ButtonStyle.secondary)
    async def back_menu(self, interaction: discord.Interaction, button: discord.ui.Button):
        from utils.views.world import _send_main_menu
        cog = self.pe_cog.bot.cogs.get("Cultivation") if self.pe_cog else None
        if not cog:
            await interaction.response.send_message("无法返回。", ephemeral=True)
            return
        await interaction.response.defer()
        await _send_main_menu(interaction, cog)


class _WanbaoTravelButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="前往万宝楼", style=discord.ButtonStyle.success)

    async def callback(self, interaction: discord.Interaction):
        uid = str(interaction.user.id)
        with get_conn() as conn:
            row = conn.execute("SELECT * FROM players WHERE discord_id = ?", (uid,)).fetchone()
        if not row:
            return await interaction.response.send_message("尚未创建角色。", ephemeral=True)
        player = dict(row)
        if player["current_city"] == "万宝楼":
            return await interaction.response.send_message("你已在万宝楼。", ephemeral=True)
        now = time.time()
        if player.get("cultivating_until") and now < player["cultivating_until"]:
            return await interaction.response.send_message("正在闭关中，无法移动。", ephemeral=True)
        if player.get("gathering_until") and now < player["gathering_until"]:
            return await interaction.response.send_message("正在采集中，无法移动。", ephemeral=True)
        if player.get("active_quest"):
            return await interaction.response.send_message("正在执行任务，无法移动。", ephemeral=True)
        with get_conn() as conn:
            conn.execute("UPDATE players SET current_city = ?, last_active = ? WHERE discord_id = ?", ("万宝楼", now, uid))
            conn.commit()
        await interaction.response.send_message("已传送至 **万宝楼**，拍卖会即将开始！", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(PublicEventsCog(bot))
