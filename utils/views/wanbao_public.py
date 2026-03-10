import time

import discord

from utils.db import get_conn

WANBAO_DESC = (
    "每日北美东部时间 **20:00**，万宝楼将举办大型拍卖会。\n\n"
    "**官方拍品**\n"
    "· 每次官方出 **8 件**：2件功法、2件丹药、2件灵材、2件装备\n"
    "· 按稀有度权重随机生成，偶有珍稀之物\n\n"
    "**玩家上架**\n"
    "· 每位道友最多上架 **2 件**，全场上限 **20 件**\n"
    "· 上架需支付 **300 灵石** 手续费\n"
    "· 流拍需额外支付 **300 灵石** 取回费\n"
    "· 拍卖开始后无法继续上架，请提前到场\n\n"
    "**竞拍规则**\n"
    "· 每件拍品竞拍时间 **2 分钟**，按顺序逐件进行\n"
    "· 出价按钮：+10 / +100 / +200 / +500 / +1000\n"
    "· 出价时灵石自动冻结，被超越后立即解冻\n"
    "· 成交后万宝楼收取 **8%** 手续费，卖家实收 92%\n"
    "· 功法得标后进入背包，可学习或留作交易\n"
    "· 装备得标后直接入库\n\n"
    "**注意事项**\n"
    "· 拍卖期间在万宝楼内无法闭关、采集、探险\n"
    "· 茶馆暂停营业\n"
    "· 18:00 起公告频道发布预告，附前往按钮\n\n"
    "**触发时间**：每日 20:00（北美东部时间），18:00 起预告"
)

WANBAO_TRIGGER_HOUR = 20


class _WanbaoEventButton(discord.ui.Button):
    def __init__(self, pe_cog=None):
        super().__init__(label="万宝楼拍卖会", style=discord.ButtonStyle.primary)
        self.pe_cog = pe_cog

    async def callback(self, interaction: discord.Interaction):
        from utils.events.public.wanbao import get_active_auction, get_lots
        auction = get_active_auction()

        embed = discord.Embed(title="✦ 万宝楼大型拍卖会 ✦", description=WANBAO_DESC, color=discord.Color.gold())

        if auction:
            lots = get_lots(auction["auction_id"])
            status_map = {"pending": "🟡 等待开始", "active": "🔴 进行中", "ended": "⚫ 已结束"}
            status_text = status_map.get(auction["status"], auction["status"])
            if auction["status"] == "active":
                remaining = max(0, auction["ends_at"] - time.time())
                detail = f"当前拍品剩余 **{int(remaining//60)}分{int(remaining%60):02d}秒**"
            elif auction["status"] == "pending":
                detail = f"北美东部时间 **{WANBAO_TRIGGER_HOUR}:00** 开始"
            else:
                detail = "本次拍卖已结束"
            embed.add_field(name="今日状态", value=f"{status_text}　{detail}", inline=False)
            embed.add_field(name="拍品数量", value=f"**{len(lots)}** 件", inline=True)
        else:
            embed.add_field(name="今日状态", value=f"🟡 等待开始　北美东部时间 **{WANBAO_TRIGGER_HOUR}:00** 开始", inline=False)

        view = _WanbaoDetailView(interaction.user, self.pe_cog, auction)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)


class _WanbaoDetailView(discord.ui.View):
    def __init__(self, author, pe_cog=None, auction=None):
        super().__init__(timeout=120)
        self.author = author
        self.pe_cog = pe_cog
        self.auction = auction

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user != self.author:
            await interaction.response.send_message("这不是你的面板。", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="前往万宝楼", style=discord.ButtonStyle.success)
    async def travel(self, interaction: discord.Interaction, button: discord.ui.Button):
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

    @discord.ui.button(label="进入拍卖", style=discord.ButtonStyle.primary)
    async def enter_auction(self, interaction: discord.Interaction, button: discord.ui.Button):
        uid = str(interaction.user.id)
        with get_conn() as conn:
            row = conn.execute("SELECT current_city FROM players WHERE discord_id = ?", (uid,)).fetchone()
        if not row:
            return await interaction.response.send_message("尚未创建角色。", ephemeral=True)
        if row["current_city"] != "万宝楼":
            return await interaction.response.send_message("需先前往 **万宝楼** 方可进入拍卖。", ephemeral=True)
        if not self.pe_cog:
            return await interaction.response.send_message("系统暂时不可用。", ephemeral=True)
        await interaction.response.defer(ephemeral=True)
        from utils.events.public.wanbao import get_active_auction, get_lots, get_last_ended_auction, get_or_create_auction
        from utils.views.wanbao import WanbaoMainView, build_lots_list_embed, _item_display
        from utils.views.wanbao_public import WANBAO_DESC, WANBAO_TRIGGER_HOUR
        auction = get_active_auction()
        if not auction:
            from datetime import datetime
            from zoneinfo import ZoneInfo
            today_str = datetime.now(ZoneInfo("America/Montreal")).strftime("%Y-%m-%d")
            auction = get_or_create_auction(today_str)
        if not auction or auction["status"] == "ended":
            embed = discord.Embed(title="✦ 万宝楼大型拍卖会 ✦", description=WANBAO_DESC, color=discord.Color.gold())
            embed.add_field(name="今日状态", value=f"🟡 等待开始　北美东部时间 **{WANBAO_TRIGGER_HOUR}:00** 开始", inline=False)
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
                embed.add_field(name="上次拍卖记录", value="\n".join(lines) if lines else "暂无记录", inline=False)
            view = WanbaoMainView(interaction.user, self.pe_cog)
            return await interaction.followup.send(embed=embed, view=view, ephemeral=True)
        lots = get_lots(auction["auction_id"])
        status_text = {"pending": "等待开始", "active": "进行中", "ended": "已结束"}.get(auction["status"], "未知")
        embed = discord.Embed(title="✦ 万宝楼拍卖会 ✦", description=f"状态：**{status_text}**　拍品：**{len(lots)}** 件", color=discord.Color.gold())
        if auction["status"] == "pending":
            embed.add_field(name="开始时间", value=f"北美东部时间 **{WANBAO_TRIGGER_HOUR}:00**", inline=True)
            embed.add_field(name="提示", value="拍卖开始前可上架物品（每人最多2件），开始后无法继续上架。", inline=False)
        view = WanbaoMainView(interaction.user, self.pe_cog)
        await interaction.followup.send(embed=embed, view=view, ephemeral=True)

    @discord.ui.button(label="返回", style=discord.ButtonStyle.secondary)
    async def back(self, interaction: discord.Interaction, button: discord.ui.Button):
        from utils.events.public.wanbao import get_active_auction
        from utils.views.public_event_overview import PublicEventOverviewView
        from utils.views.spirit_rain import _get_active_event, _get_pending_event
        auction = get_active_auction()
        active = _get_active_event()
        pending = _get_pending_event() if not active else None
        view = PublicEventOverviewView(active, pending, auction, self.pe_cog)
        await interaction.response.edit_message(content=None, view=view)


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
