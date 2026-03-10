import discord
import time
from utils.db import get_conn
from utils.events.public.wanbao import (
    get_active_auction, get_lots, get_current_lot,
    place_bid, list_item, can_list_item,
    WANBAO_CITY, LISTING_FEE, MAX_PLAYER_LOTS, LOT_DURATION,
)


def _get_player(uid: str) -> dict | None:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM players WHERE discord_id = ?", (uid,)).fetchone()
    return dict(row) if row else None


def _item_display(lot: dict) -> str:
    qty = f" ×{lot['quantity']}" if lot["quantity"] > 1 else ""
    if lot["item_type"] == "technique":
        tag = "📜"
    elif lot["item_type"] == "equipment":
        tag = "⚔️"
    else:
        tag = "📦"
    return f"{tag} {lot['item_name']}{qty}"


STAT_CN = {
    "comprehension": "悟性", "physique": "体魄", "bone": "根骨",
    "soul": "神识", "fortune": "气运", "cultivation_speed": "修炼速度",
    "cultivation_speed_bonus": "修炼速度", "lifespan_bonus": "寿元上限",
    "lifespan_restore": "寿元回复", "lifespan_extend": "延寿",
    "lifespan": "寿元回复", "breakthrough_bonus": "突破加成",
    "escape_rate": "逃跑成功率",
}

SLOT_CN = {
    "weapon": "武器", "armor": "护甲", "helmet": "头盔",
    "boots": "靴子", "accessory": "饰品", "ring": "戒指",
}

RARITY_CN = {"普通": "⚪普通", "稀有": "🔵稀有", "珍贵": "🟣珍贵", "绝世": "🟡绝世"}
QUALITY_CN = {"普通": "⚪普通", "精良": "🟢精良", "稀有": "🔵稀有", "史诗": "🟣史诗", "传说": "🟡传说"}


def _fmt_stat_bonus(stat_bonus: dict) -> str:
    parts = []
    for k, v in stat_bonus.items():
        label = STAT_CN.get(k, k)
        if isinstance(v, float):
            parts.append(f"{label} +{v*100:.0f}%")
        else:
            parts.append(f"{label} +{v}")
    return "　".join(parts) if parts else "无"


def build_lot_embed(lot: dict, auction_ends_at: float, lot_index: int, total_lots: int) -> discord.Embed:
    from utils.items import ITEMS
    from utils.sects import TECHNIQUES

    remaining = max(0, auction_ends_at - time.time())
    mins = int(remaining // 60)
    secs = int(remaining % 60)

    embed = discord.Embed(
        title=f"✦ 第 {lot_index + 1}/{total_lots} 件 · {_item_display(lot)} ✦",
        color=discord.Color.gold(),
    )

    if lot["item_type"] == "technique":
        info = TECHNIQUES.get(lot["item_name"], {})
        embed.description = info.get("desc", "")
        embed.add_field(name="品级", value=info.get("grade", "未知"), inline=True)
        embed.add_field(name="类型", value=info.get("type", "未知"), inline=True)
        bonus_str = _fmt_stat_bonus(info.get("stat_bonus", {}))
        embed.add_field(name="装备加成", value=bonus_str, inline=False)

    elif lot["item_type"] == "equipment":
        import json as _json
        eq_raw = lot.get("eq_data")
        eq = _json.loads(eq_raw) if eq_raw else {}
        embed.description = eq.get("flavor", "")
        embed.add_field(name="品质", value=QUALITY_CN.get(eq.get("quality", ""), eq.get("quality", "")), inline=True)
        embed.add_field(name="部位", value=eq.get("slot", ""), inline=True)
        stats_str = "　".join(
            f"{STAT_CN.get(k, k)} +{v}" for k, v in eq.get("stats", {}).items()
        )
        embed.add_field(name="属性", value=stats_str or "无", inline=False)

    else:
        info = ITEMS.get(lot["item_name"], {})
        embed.description = info.get("desc", "")
        rarity = info.get("rarity", "")
        embed.add_field(name="稀有度", value=RARITY_CN.get(rarity, rarity), inline=True)
        embed.add_field(name="类型", value=info.get("type", ""), inline=True)
        effect = info.get("effect", {})
        if effect:
            eff_str = "　".join(
                f"{STAT_CN.get(k, k)} +{v*100:.0f}%" if isinstance(v, float) else f"{STAT_CN.get(k, k)} +{v}"
                for k, v in effect.items()
            )
            embed.add_field(name="效果", value=eff_str, inline=False)

    seller = "万宝楼" if not lot["seller_id"] else f"<@{lot['seller_id']}>"
    current = lot["current_bid"] if lot["current_bid"] > 0 else lot["start_price"]
    bidder = f"<@{lot['bidder_id']}>" if lot["bidder_id"] else "暂无出价"

    embed.add_field(name="起拍价", value=f"{lot['start_price']} 灵石", inline=True)
    embed.add_field(name="当前出价", value=f"**{current} 灵石**", inline=True)
    embed.add_field(name="出价者", value=bidder, inline=True)
    embed.add_field(name="卖家", value=seller, inline=True)
    embed.add_field(name="剩余时间", value=f"{mins}分{secs:02d}秒", inline=True)
    return embed


def build_lots_list_embed(auction: dict, lots: list[dict]) -> discord.Embed:
    embed = discord.Embed(
        title="✦ 本次万宝楼拍卖 · 拍品一览 ✦",
        color=discord.Color.gold(),
    )
    current_idx = auction["current_lot"]
    for lot in lots:
        idx = lot["lot_index"]
        if lot["status"] == "sold":
            status = f"✅ 已成交 {lot['current_bid']} 灵石"
        elif lot["status"] == "unsold":
            status = "❌ 流拍"
        elif lot["status"] == "active":
            status = f"🔴 竞拍中 · 当前 {lot['current_bid'] or lot['start_price']} 灵石"
        elif idx < current_idx:
            status = "已结束"
        else:
            status = f"起拍 {lot['start_price']} 灵石"
        seller = "万宝楼" if not lot["seller_id"] else "玩家上架"
        embed.add_field(
            name=f"第{idx + 1}件　{_item_display(lot)}",
            value=f"{status}　{seller}",
            inline=False,
        )
    return embed


class WanbaoMainView(discord.ui.View):
    def __init__(self, author: discord.User, pe_cog=None):
        super().__init__(timeout=120)
        self.author = author
        self.pe_cog = pe_cog

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user != self.author:
            await interaction.response.send_message("这不是你的面板。", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="查看拍品", style=discord.ButtonStyle.primary)
    async def view_lots(self, interaction: discord.Interaction, button: discord.ui.Button):
        auction = get_active_auction()
        if not auction:
            return await interaction.response.send_message("当前没有进行中的拍卖。", ephemeral=True)
        lots = get_lots(auction["auction_id"])
        embed = build_lots_list_embed(auction, lots)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @discord.ui.button(label="当前拍品出价", style=discord.ButtonStyle.success)
    async def bid_current(self, interaction: discord.Interaction, button: discord.ui.Button):
        uid = str(interaction.user.id)
        player = _get_player(uid)
        if not player:
            return await interaction.response.send_message("尚未创建角色。", ephemeral=True)
        if player["current_city"] != WANBAO_CITY:
            return await interaction.response.send_message("需在万宝楼城内方可参与竞拍。", ephemeral=True)

        auction = get_active_auction()
        if not auction or auction["status"] != "active":
            return await interaction.response.send_message("拍卖尚未开始。", ephemeral=True)

        lot = get_current_lot(auction["auction_id"])
        if not lot:
            return await interaction.response.send_message("当前无进行中的拍品。", ephemeral=True)

        lots = get_lots(auction["auction_id"])
        total = len(lots)
        embed = build_lot_embed(lot, auction["ends_at"], lot["lot_index"], total)
        view = BidView(self.author, auction["auction_id"], lot, auction["ends_at"], lot["lot_index"], total, self.pe_cog)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    @discord.ui.button(label="上架物品", style=discord.ButtonStyle.secondary)
    async def list_item_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        uid = str(interaction.user.id)
        player = _get_player(uid)
        if not player:
            return await interaction.response.send_message("尚未创建角色。", ephemeral=True)
        if player["current_city"] != WANBAO_CITY:
            return await interaction.response.send_message("需在万宝楼城内方可上架物品。", ephemeral=True)

        auction = get_active_auction()
        if not auction:
            return await interaction.response.send_message("当前没有拍卖活动。", ephemeral=True)
        if auction["status"] == "active":
            return await interaction.response.send_message("拍卖已开始，无法继续上架。", ephemeral=True)

        ok, msg = can_list_item(uid, auction["auction_id"])
        if not ok:
            return await interaction.response.send_message(msg, ephemeral=True)

        await interaction.response.send_modal(ListItemModal(auction["auction_id"]))

    @discord.ui.button(label="返回主菜单", style=discord.ButtonStyle.danger)
    async def back_menu(self, interaction: discord.Interaction, button: discord.ui.Button):
        from utils.views.world import _send_main_menu
        cog = self.pe_cog.bot.cogs.get("Cultivation") if self.pe_cog else None
        if not cog:
            return await interaction.response.send_message("无法返回。", ephemeral=True)
        await interaction.response.defer()
        await _send_main_menu(interaction, cog)


class PublicBidView(discord.ui.View):
    def __init__(self, auction_id: str, lot_index: int, total: int):
        super().__init__(timeout=LOT_DURATION + 10)
        self.auction_id = auction_id
        self.lot_index = lot_index
        self.total = total

    async def _do_bid(self, interaction: discord.Interaction, increment: int):
        uid = str(interaction.user.id)
        player = _get_player(uid)
        if not player:
            return await interaction.response.send_message("尚未创建角色。", ephemeral=True)
        if player["current_city"] != WANBAO_CITY:
            return await interaction.response.send_message("需在万宝楼城内方可参与竞拍。", ephemeral=True)

        with get_conn() as conn:
            lot_row = conn.execute(
                "SELECT * FROM wanbao_lots WHERE auction_id = ? AND lot_index = ? AND status = 'active'",
                (self.auction_id, self.lot_index)
            ).fetchone()
        if not lot_row:
            return await interaction.response.send_message("此拍品已结束。", ephemeral=True)

        lot = dict(lot_row)
        current = lot["current_bid"] if lot["current_bid"] > 0 else lot["start_price"]
        new_bid = current + increment

        ok, msg = place_bid(self.auction_id, uid, new_bid)
        if not ok:
            return await interaction.response.send_message(msg, ephemeral=True)

        with get_conn() as conn:
            auction = conn.execute("SELECT * FROM wanbao_auctions WHERE auction_id = ?", (self.auction_id,)).fetchone()
            lot_row = conn.execute(
                "SELECT * FROM wanbao_lots WHERE auction_id = ? AND lot_index = ?",
                (self.auction_id, self.lot_index)
            ).fetchone()
        lot = dict(lot_row)
        embed = build_lot_embed(lot, auction["ends_at"], self.lot_index, self.total)
        name = player["name"] if player else str(interaction.user)
        embed.add_field(name="最新出价", value=f"**{name}** 出价 **{new_bid} 灵石**", inline=False)
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="+10", style=discord.ButtonStyle.secondary)
    async def bid_10(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._do_bid(interaction, 10)

    @discord.ui.button(label="+100", style=discord.ButtonStyle.secondary)
    async def bid_100(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._do_bid(interaction, 100)

    @discord.ui.button(label="+200", style=discord.ButtonStyle.secondary)
    async def bid_200(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._do_bid(interaction, 200)

    @discord.ui.button(label="+500", style=discord.ButtonStyle.primary)
    async def bid_500(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._do_bid(interaction, 500)

    @discord.ui.button(label="+1000", style=discord.ButtonStyle.primary)
    async def bid_1000(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._do_bid(interaction, 1000)


class BidView(discord.ui.View):
    def __init__(self, author, auction_id: str, lot: dict, ends_at: float, lot_index: int, total: int, pe_cog=None):
        super().__init__(timeout=LOT_DURATION + 10)
        self.author = author
        self.auction_id = auction_id
        self.lot = lot
        self.ends_at = ends_at
        self.lot_index = lot_index
        self.total = total
        self.pe_cog = pe_cog

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user != self.author:
            await interaction.response.send_message("这不是你的面板。", ephemeral=True)
            return False
        return True

    async def _do_bid(self, interaction: discord.Interaction, increment: int):
        uid = str(interaction.user.id)
        with get_conn() as conn:
            lot_row = conn.execute(
                "SELECT * FROM wanbao_lots WHERE auction_id = ? AND lot_index = ? AND status = 'active'",
                (self.auction_id, self.lot_index)
            ).fetchone()
        if not lot_row:
            return await interaction.response.send_message("此拍品已结束。", ephemeral=True)
        lot = dict(lot_row)
        current = lot["current_bid"] if lot["current_bid"] > 0 else lot["start_price"]
        new_bid = current + increment
        ok, msg = place_bid(self.auction_id, uid, new_bid)
        if not ok:
            return await interaction.response.send_message(msg, ephemeral=True)

        with get_conn() as conn:
            auction = conn.execute("SELECT * FROM wanbao_auctions WHERE auction_id = ?", (self.auction_id,)).fetchone()
            lot_row = conn.execute(
                "SELECT * FROM wanbao_lots WHERE auction_id = ? AND lot_index = ?",
                (self.auction_id, self.lot_index)
            ).fetchone()
        lot = dict(lot_row)
        embed = build_lot_embed(lot, auction["ends_at"], self.lot_index, self.total)
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="+10", style=discord.ButtonStyle.secondary)
    async def bid_10(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._do_bid(interaction, 10)

    @discord.ui.button(label="+100", style=discord.ButtonStyle.secondary)
    async def bid_100(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._do_bid(interaction, 100)

    @discord.ui.button(label="+200", style=discord.ButtonStyle.secondary)
    async def bid_200(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._do_bid(interaction, 200)

    @discord.ui.button(label="+500", style=discord.ButtonStyle.primary)
    async def bid_500(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._do_bid(interaction, 500)

    @discord.ui.button(label="+1000", style=discord.ButtonStyle.primary)
    async def bid_1000(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._do_bid(interaction, 1000)


class ListItemModal(discord.ui.Modal, title="上架拍品"):
    item_name = discord.ui.TextInput(label="物品名称", placeholder="例：雷云芝", max_length=30)
    quantity = discord.ui.TextInput(label="数量", placeholder="例：20", max_length=5)
    start_price = discord.ui.TextInput(label="起拍价（灵石）", placeholder="例：2000", max_length=10)

    def __init__(self, auction_id: str):
        super().__init__()
        self.auction_id = auction_id

    async def on_submit(self, interaction: discord.Interaction):
        uid = str(interaction.user.id)
        try:
            qty = int(self.quantity.value)
            price = int(self.start_price.value)
        except ValueError:
            return await interaction.response.send_message("数量和起拍价必须是整数。", ephemeral=True)
        if qty <= 0 or price <= 0:
            return await interaction.response.send_message("数量和起拍价必须大于0。", ephemeral=True)

        ok, msg = list_item(self.auction_id, uid, self.item_name.value.strip(), qty, price)
        if ok:
            await interaction.response.send_message(
                f"{msg}\n上架手续费 **{LISTING_FEE} 灵石** 已扣除。流拍时需额外支付 {LISTING_FEE} 灵石取回费。",
                ephemeral=True
            )
        else:
            await interaction.response.send_message(msg, ephemeral=True)
