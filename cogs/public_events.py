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
from utils.views.spirit_rain import TravelToEventView, _get_active_event, _get_pending_event, _today_trigger_ts
from utils.views.wanbao_public import _WanbaoTravelButton, WANBAO_DESC
from utils.views.public_event_overview import PublicEventOverviewView

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



def _get_expired_event() -> dict | None:
    now = time.time()
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM public_events WHERE status = 'active' AND ends_at <= ? ORDER BY ends_at ASC LIMIT 1",
            (now,)
        ).fetchone()
    return dict(row) if row else None



def _montreal_now() -> datetime:
    return datetime.now(MONTREAL_TZ)



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
        self._lot_task: asyncio.Task | None = None
        self._scheduler.start()

    def cog_unload(self):
        self._scheduler.cancel()
        if self._lot_task and not self._lot_task.done():
            self._lot_task.cancel()

    @tasks.loop(minutes=1)
    async def _scheduler(self):
        await self.bot.wait_until_ready()
        now_mt = _montreal_now()
        today_str = now_mt.strftime("%Y-%m-%d")
        h, m = now_mt.hour, now_mt.minute

        expired = _get_expired_event()
        if expired:
            await self._settle_event(expired)

        active = _get_active_event()

        if not active:
            last_date = _last_trigger_date_str()
            if last_date != today_str:
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
                last_date = _last_trigger_date_str()
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
                    from utils.views.wanbao import build_lot_embed, PublicBidView
                    lots = get_lots(auction["auction_id"])
                    with get_conn() as conn:
                        a = conn.execute("SELECT * FROM wanbao_auctions WHERE auction_id = ?", (auction["auction_id"],)).fetchone()
                    embed = build_lot_embed(dict(first_lot), a["ends_at"], 0, len(lots))
                    embed.title = f"🔔 万宝楼拍卖会开始！第 1/{len(lots)} 件"
                    self._wanbao_auction_id = auction["auction_id"]
                    view = PublicBidView(auction["auction_id"], 0, len(lots))
                    await channel.send(embed=embed, view=view)
                    if self._lot_task is None or self._lot_task.done():
                        self._lot_task = asyncio.create_task(self._run_lot_timer(auction["auction_id"]))

        active = get_active_auction()
        if active and active["status"] == "active":
            if self._lot_task is None or self._lot_task.done():
                print(f"[万宝楼] 检测到进行中拍卖，重启 lot timer: {active['auction_id']}")
                self._lot_task = asyncio.create_task(self._run_lot_timer(active["auction_id"]))

    async def _run_lot_timer(self, auction_id: str):
        from utils.events.public.wanbao import (
            get_current_lot, settle_lot, advance_lot, get_lots, get_active_auction
        )
        channel = _get_announce_channel(self.bot)
        try:
            while True:
                active = get_active_auction()
                if not active or active["status"] != "active" or active["auction_id"] != auction_id:
                    break
                wait = active["ends_at"] - time.time()
                if wait > 0:
                    await asyncio.sleep(wait)
                active = get_active_auction()
                if not active or active["status"] != "active":
                    break
                lot = get_current_lot(auction_id)
                if not lot:
                    break
                result = settle_lot(lot)
                if channel:
                    await self._announce_lot_result(channel, result, auction_id)
                next_lot = advance_lot(auction_id)
                if next_lot:
                    with get_conn() as conn:
                        a = conn.execute("SELECT * FROM wanbao_auctions WHERE auction_id = ?", (auction_id,)).fetchone()
                    lots = get_lots(auction_id)
                    from utils.views.wanbao import build_lot_embed, PublicBidView
                    embed = build_lot_embed(dict(next_lot), a["ends_at"], next_lot["lot_index"], len(lots))
                    if channel:
                        view = PublicBidView(auction_id, next_lot["lot_index"], len(lots))
                        await channel.send(embed=embed, view=view)
                else:
                    if channel:
                        await self._announce_auction_end(channel, auction_id)
                    break
        except asyncio.CancelledError:
            pass
        except Exception as e:
            print(f"[万宝楼] lot timer 异常: {e}")

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
        from utils.views.wanbao import _item_display
        lots = _get_lots(auction_id)
        sold = [l for l in lots if l["status"] == "sold"]
        unsold = [l for l in lots if l["status"] == "unsold"]
        with get_conn() as conn:
            conn.execute("DELETE FROM wanbao_frozen WHERE auction_id = ?", (auction_id,))
            conn.commit()

        embed = discord.Embed(
            title="✦ 万宝楼拍卖会圆满结束 ✦",
            description=f"本次共拍出 **{len(sold)}** 件，流拍 **{len(unsold)}** 件。",
            color=discord.Color.gold(),
        )

        for lot in lots:
            item_str = _item_display(lot)
            if lot["status"] == "sold":
                with get_conn() as conn:
                    p = conn.execute("SELECT name FROM players WHERE discord_id = ?", (lot["bidder_id"],)).fetchone()
                buyer = p["name"] if p else f"<@{lot['bidder_id']}>"
                embed.add_field(
                    name=f"✅ {item_str}",
                    value=f"买家：**{buyer}**　成交价：**{lot['current_bid']} 灵石**　卖家：{seller}",
                    inline=False,
                )
            else:
                embed.add_field(
                    name=f"❌ {item_str}",
                    value="流拍",
                    inline=False,
                )

        embed.set_footer(text="感谢各位道友的参与，下次拍卖会再见！")
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

        from utils.events.public.wanbao import get_active_auction, get_lots, get_last_ended_auction, get_or_create_auction
        from utils.views.wanbao import WanbaoMainView, build_lots_list_embed, _item_display
        auction = get_active_auction()

        if not auction:
            now_mt = _montreal_now()
            today_str = now_mt.strftime("%Y-%m-%d")
            auction = get_or_create_auction(today_str)

        if not auction or auction["status"] == "ended":
            embed = discord.Embed(
                title="✦ 万宝楼大型拍卖会 ✦",
                description=WANBAO_DESC,
                color=discord.Color.gold(),
            )
            embed.add_field(
                name="今日状态",
                value=f"🟡 等待开始　北美东部时间 **{WANBAO_TRIGGER_HOUR}:00** 开始",
                inline=False,
            )

            last = get_last_ended_auction()
            if last:
                last_lots = get_lots(last["auction_id"])
                lines = []
                for lot in last_lots:
                    item_str = _item_display(lot)
                    if lot["status"] == "sold":
                        with get_conn() as conn:
                            p = conn.execute("SELECT name FROM players WHERE discord_id = ?", (lot["bidder_id"],)).fetchone()
                        buyer = p["name"] if p else f"<@{lot['bidder_id']}>"
                        lines.append(f"✅ {item_str}　{buyer} · {lot['current_bid']} 灵石")
                    else:
                        lines.append(f"❌ {item_str}　流拍")
                embed.add_field(
                    name="上次拍卖记录",
                    value="\n".join(lines) if lines else "暂无记录",
                    inline=False,
                )

            view = WanbaoMainView(ctx.author, self)
            return await ctx.send(ctx.author.mention, embed=embed, view=view)

        lots = get_lots(auction["auction_id"])
        status_text = {"pending": "等待开始", "active": "进行中", "ended": "已结束"}.get(auction["status"], "未知")
        embed = discord.Embed(
            title="✦ 万宝楼拍卖会 ✦",
            description=f"状态：**{status_text}**　拍品：**{len(lots)}** 件",
            color=discord.Color.gold(),
        )
        if auction["status"] == "pending":
            embed.add_field(
                name="开始时间",
                value=f"北美东部时间 **{WANBAO_TRIGGER_HOUR}:00**",
                inline=True,
            )
            embed.add_field(
                name="提示",
                value="拍卖开始前可上架物品（每人最多2件），开始后无法继续上架。",
                inline=False,
            )
        view = WanbaoMainView(ctx.author, self)
        await ctx.send(ctx.author.mention, embed=embed, view=view)

    @commands.command(name="开启拍卖", aliases=["kqpm"], hidden=True)
    async def debug_start_auction(self, ctx):
        ALLOWED = {"304758476448595970"}
        if str(ctx.author.id) not in ALLOWED:
            return
        from utils.events.public.wanbao import get_or_create_auction, get_active_auction, start_auction, get_lots
        now_mt = _montreal_now()
        today_str = now_mt.strftime("%Y-%m-%d")
        auction = get_or_create_auction(today_str)
        if auction["status"] == "active":
            return await ctx.send(f"拍卖已在进行中，auction_id: `{auction['auction_id']}`")
        if auction["status"] == "ended":
            return await ctx.send("今日拍卖已结束。")
        first_lot = start_auction(auction["auction_id"])
        if not first_lot:
            return await ctx.send("启动失败，没有拍品。")
        channel = _get_announce_channel(self.bot)
        if channel:
            from utils.views.wanbao import build_lot_embed, PublicBidView
            lots = get_lots(auction["auction_id"])
            with get_conn() as conn:
                a = conn.execute("SELECT * FROM wanbao_auctions WHERE auction_id = ?", (auction["auction_id"],)).fetchone()
            embed = build_lot_embed(dict(first_lot), a["ends_at"], 0, len(lots))
            embed.title = f"🔔 万宝楼拍卖会开始！第 1/{len(lots)} 件"
            view = PublicBidView(auction["auction_id"], 0, len(lots))
            await channel.send(embed=embed, view=view)
        if self._lot_task is None or self._lot_task.done():
            self._lot_task = asyncio.create_task(self._run_lot_timer(auction["auction_id"]))
        await ctx.send(f"拍卖已启动，auction_id: `{auction['auction_id']}`", ephemeral=True)

    @commands.command(name="重启拍卖计时", aliases=["cqpm"], hidden=True)
    async def debug_restart_timer(self, ctx):
        ALLOWED = {"304758476448595970"}
        if str(ctx.author.id) not in ALLOWED:
            return
        from utils.events.public.wanbao import get_active_auction
        active = get_active_auction()
        if not active or active["status"] != "active":
            return await ctx.send("当前没有进行中的拍卖。")
        if self._lot_task and not self._lot_task.done():
            self._lot_task.cancel()
        self._lot_task = asyncio.create_task(self._run_lot_timer(active["auction_id"]))
        await ctx.send(f"已重启 lot timer，auction_id: `{active['auction_id']}`")

    @commands.hybrid_command(name="公共事件", aliases=["ggsj"], description="查看当前或即将发生的世界公共事件")
    async def show_active_event(self, ctx):
        from utils.events.public.wanbao import get_active_auction, get_lots
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
                name="暂无灵雨事件",
                value="下次天降灵雨将于今日 22:00（北美东部时间）触发。",
                inline=False,
            )

        if auction:
            lots = get_lots(auction["auction_id"])
            status_map = {"pending": "🟡 等待开始", "active": "🔴 进行中", "ended": "⚫ 已结束"}
            status_text = status_map.get(auction["status"], auction["status"])
            if auction["status"] == "active":
                remaining_auction = max(0, auction["ends_at"] - time.time())
                detail = f"当前拍品剩余：**{remaining_auction/60:.0f} 分{int(remaining_auction%60):02d}秒**"
            elif auction["status"] == "pending":
                detail = f"北美东部时间 **{WANBAO_TRIGGER_HOUR}:00** 开始"
            else:
                detail = "本次拍卖已结束"
            embed.add_field(
                name=f"✦ 万宝楼大型拍卖会 · {status_text}",
                value=f"拍品共 **{len(lots)}** 件　{detail}\n前往 **万宝楼** 参与竞拍",
                inline=False,
            )
        else:
            embed.add_field(
                name="✦ 万宝楼大型拍卖会",
                value=f"今日拍卖会将于北美东部时间 **{WANBAO_TRIGGER_HOUR}:00** 举行，届时前往 **万宝楼** 参与。",
                inline=False,
            )

        view = PublicEventOverviewView(active, pending, auction, self)
        await ctx.send(ctx.author.mention, embed=embed, view=view)





async def setup(bot: commands.Bot):
    await bot.add_cog(PublicEventsCog(bot))
