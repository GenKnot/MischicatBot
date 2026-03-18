import time
import json
import discord
from sqlalchemy import text
from utils.db_async import AsyncSessionLocal
from utils.market import (
    MARKET_CITIES, MAX_LISTINGS, FEE_RATE,
    get_active_listings, get_my_listings, get_expired_unclaimed,
    list_item, list_equipment, buy_listing, delist,
)
from utils.items import ITEMS

ITEM_TYPE_LABELS = {
    "all": "全部",
    "herb": "草药",
    "material": "矿石",
    "wood": "木材",
    "fish": "鱼类",
    "pill": "丹药",
    "equipment": "装备",
}

PAGE_SIZE = 8


async def _get_player(uid: str) -> dict | None:
    async with AsyncSessionLocal() as session:
        result = await session.execute(text("SELECT * FROM players WHERE discord_id = :uid"), {"uid": uid})
        row = result.fetchone()
        return dict(row._mapping) if row else None


def _listing_line(d: dict, show_seller: bool = True) -> str:
    now = time.time()
    time_left = d["expires_at"] - now
    if time_left <= 0:
        time_tag = "⏰已过期"
    else:
        hours = int(time_left / 3600)
        time_tag = f"{hours}h"
    qty = f"×{d['quantity']}" if d["quantity"] > 1 else ""
    seller = f" · {d.get('seller_name', d['seller_id'][:6])}" if show_seller else ""
    return f"`{d['listing_id']}` **{d['item_name']}**{qty} · {d['price']:,}灵石{seller} · {time_tag}"


def _market_main_embed(player: dict, listings: list[dict], page: int, filter_type: str) -> discord.Embed:
    embed = discord.Embed(
        title="🏪 交易坊",
        description=f"灵石：**{player.get('spirit_stones', 0):,}**　手续费 {int(FEE_RATE*100)}%，上架3天自动下架",
        color=discord.Color.orange(),
    )
    start = page * PAGE_SIZE
    page_items = listings[start:start + PAGE_SIZE]
    total_pages = max(1, (len(listings) + PAGE_SIZE - 1) // PAGE_SIZE)

    if page_items:
        lines = [_listing_line(d) for d in page_items]
        embed.add_field(name=f"在售商品（{ITEM_TYPE_LABELS.get(filter_type, '全部')}）第{page+1}/{total_pages}页", value="\n".join(lines), inline=False)
    else:
        embed.add_field(name="在售商品", value="暂无商品", inline=False)
    return embed


def _my_listings_embed(player: dict, listings: list[dict], expired: list[dict]) -> discord.Embed:
    embed = discord.Embed(
        title="📦 我的摊位",
        description=f"灵石：**{player.get('spirit_stones', 0):,}**　最多 {MAX_LISTINGS} 件同时在售",
        color=discord.Color.orange(),
    )
    active = [d for d in listings if d["status"] == "active"]
    if active:
        lines = [_listing_line(d, show_seller=False) for d in active]
        embed.add_field(name="在售中", value="\n".join(lines), inline=False)
    else:
        embed.add_field(name="在售中", value="暂无", inline=False)

    if expired:
        lines = [f"`{d['listing_id']}` **{d['item_name']}** ×{d['quantity']} · 待领回" for d in expired]
        embed.add_field(name="⏰ 已过期（待领回）", value="\n".join(lines), inline=False)
    return embed


class MarketMainView(discord.ui.View):
    def __init__(self, author, player: dict, listings: list[dict], page: int = 0, filter_type: str = "all", cog=None):
        super().__init__(timeout=120)
        self.author = author
        self.player = player
        self.listings = listings
        self.page = page
        self.filter_type = filter_type
        self.cog = cog
        self.total_pages = max(1, (len(listings) + PAGE_SIZE - 1) // PAGE_SIZE)

        self.add_item(MarketFilterSelect(filter_type))
        if self.page > 0:
            self.add_item(MarketPageButton("◀ 上一页", "prev"))
        if self.page < self.total_pages - 1:
            self.add_item(MarketPageButton("下一页 ▶", "next"))
        self.add_item(MarketBuyButton())
        self.add_item(MarketMyStallButton())
        self.add_item(MarketListButton())
        self.add_item(MarketBackButton())

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user != self.author:
            await interaction.response.send_message("这不是你的面板。", ephemeral=True)
            return False
        return True


class MarketFilterSelect(discord.ui.Select):
    def __init__(self, current: str):
        options = [
            discord.SelectOption(label=v, value=k, default=(k == current))
            for k, v in ITEM_TYPE_LABELS.items()
        ]
        super().__init__(placeholder="筛选类型", options=options, row=0)

    async def callback(self, interaction: discord.Interaction):
        filter_type = self.values[0]
        uid = str(interaction.user.id)
        player = await _get_player(uid)
        listings = await _get_listings_with_names(filter_type)
        await interaction.response.edit_message(
            embed=_market_main_embed(player, listings, 0, filter_type),
            view=MarketMainView(self.view.author, player, listings, 0, filter_type, self.view.cog),
        )


class MarketPageButton(discord.ui.Button):
    def __init__(self, label: str, direction: str):
        super().__init__(label=label, style=discord.ButtonStyle.secondary, row=1)
        self.direction = direction

    async def callback(self, interaction: discord.Interaction):
        v = self.view
        new_page = v.page - 1 if self.direction == "prev" else v.page + 1
        new_page = max(0, min(new_page, v.total_pages - 1))
        uid = str(interaction.user.id)
        player = await _get_player(uid)
        await interaction.response.edit_message(
            embed=_market_main_embed(player, v.listings, new_page, v.filter_type),
            view=MarketMainView(v.author, player, v.listings, new_page, v.filter_type, v.cog),
        )


class MarketBuyButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="💰 购买", style=discord.ButtonStyle.success, row=1)

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.send_modal(BuyModal(self.view.author, self.view.cog))


class MarketMyStallButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="📦 我的摊位", style=discord.ButtonStyle.primary, row=2)

    async def callback(self, interaction: discord.Interaction):
        uid = str(interaction.user.id)
        player = await _get_player(uid)
        listings = await get_my_listings(uid)
        expired = await get_expired_unclaimed(uid)
        await interaction.response.edit_message(
            embed=_my_listings_embed(player, listings, expired),
            view=MyStallView(self.view.author, player, listings, expired, self.view.cog),
        )


class MarketListButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="📤 上架", style=discord.ButtonStyle.success, row=2)

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.edit_message(
            embed=_list_type_embed(),
            view=ListTypeView(self.view.author, self.view.cog),
        )


class MarketBackButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="返回城市", style=discord.ButtonStyle.secondary, row=2)

    async def callback(self, interaction: discord.Interaction):
        await _go_back(interaction, self.view.author, self.view.cog)


class BuyModal(discord.ui.Modal, title="购买商品"):
    listing_id_input = discord.ui.TextInput(label="商品编号", placeholder="输入列表中的编号（如 a1b2c3d4）", min_length=1, max_length=8)

    def __init__(self, author, cog):
        super().__init__()
        self.author = author
        self.cog = cog

    async def on_submit(self, interaction: discord.Interaction):
        uid = str(interaction.user.id)
        listing_id = self.listing_id_input.value.strip()
        result = await buy_listing(uid, listing_id)
        if not result["ok"]:
            await interaction.response.send_message(result["reason"], ephemeral=True)
            return
        await interaction.response.defer()
        player = await _get_player(uid)
        listings = await _get_listings_with_names("all")
        msg = f"✅ 购买 **{result['item_name']}** 成功，花费 {result['price']:,} 灵石（手续费 {result['fee']:,}）。"
        embed = _market_main_embed(player, listings, 0, "all")
        embed.set_footer(text=msg)
        await interaction.edit_original_response(
            embed=embed,
            view=MarketMainView(self.author, player, listings, 0, "all", self.cog),
        )


def _list_type_embed() -> discord.Embed:
    return discord.Embed(
        title="📤 上架商品 · 选择类型",
        description="选择要上架的是背包物品还是装备。",
        color=discord.Color.orange(),
    )


async def _inventory_embed(uid: str) -> discord.Embed:
    from utils.inventory import get_inventory
    inv = await get_inventory(uid)
    embed = discord.Embed(
        title="🌿 背包物品",
        description="选好物品后点「上架物品」，填写物品ID、数量和价格。",
        color=discord.Color.orange(),
    )
    if not inv:
        embed.add_field(name="背包", value="空空如也", inline=False)
        return embed
    lines = []
    for item_id, qty in inv.items():
        item_info = ITEMS.get(item_id, {})
        name = item_info.get("name", item_id)
        lines.append(f"`{item_id}` **{name}** ×{qty}")
    embed.add_field(name="物品列表（复制ID填入上架表单）", value="\n".join(lines[:30]) or "暂无", inline=False)
    if len(inv) > 30:
        embed.set_footer(text=f"共 {len(inv)} 种物品，仅显示前30种")
    return embed


async def _equipment_list_embed(uid: str) -> discord.Embed:
    from utils.equipment_db import get_equipment_list
    from utils.equipment import QUALITY_COLOR, TIER_NAMES, STAT_NAMES
    equips = await get_equipment_list(uid)
    embed = discord.Embed(
        title="⚔️ 装备列表",
        description="选好装备后点「上架装备」，填写装备ID和价格。\n⚠️ 已装备的请先卸下。",
        color=discord.Color.orange(),
    )
    unequipped = [e for e in equips if not e["equipped"]]
    equipped = [e for e in equips if e["equipped"]]
    if unequipped:
        lines = []
        for e in unequipped[:20]:
            icon = QUALITY_COLOR.get(e["quality"], "⬜")
            tier_label = TIER_NAMES[min(e["tier"], len(TIER_NAMES) - 1)]
            stats_str = " ".join(f"{STAT_NAMES.get(k,k)}+{v}" for k, v in list(e["stats"].items())[:3])
            lines.append(f"`{e['equip_id']}` {icon}**{e['name']}**（{e['slot']} · {tier_label}）{stats_str}")
        embed.add_field(name="可上架（复制ID填入上架表单）", value="\n".join(lines), inline=False)
    else:
        embed.add_field(name="可上架", value="暂无未装备的装备", inline=False)
    if equipped:
        lines = [f"🔒 **{e['name']}**（已装备，请先卸下）" for e in equipped]
        embed.add_field(name="已装备（不可上架）", value="\n".join(lines), inline=False)
    return embed


class ListTypeView(discord.ui.View):
    def __init__(self, author, cog=None):
        super().__init__(timeout=120)
        self.author = author
        self.cog = cog

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user != self.author:
            await interaction.response.send_message("这不是你的面板。", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="🌿 查看背包", style=discord.ButtonStyle.success, row=0)
    async def view_inv_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        uid = str(interaction.user.id)
        embed = await _inventory_embed(uid)
        await interaction.response.edit_message(embed=embed, view=ListItemView(self.author, self.cog))

    @discord.ui.button(label="⚔️ 查看装备", style=discord.ButtonStyle.primary, row=0)
    async def view_eq_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        uid = str(interaction.user.id)
        embed = await _equipment_list_embed(uid)
        await interaction.response.edit_message(embed=embed, view=ListEquipView(self.author, self.cog))

    @discord.ui.button(label="返回交易坊", style=discord.ButtonStyle.secondary, row=0)
    async def back_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        uid = str(interaction.user.id)
        player = await _get_player(uid)
        listings = await _get_listings_with_names("all")
        await interaction.response.edit_message(
            embed=_market_main_embed(player, listings, 0, "all"),
            view=MarketMainView(self.author, player, listings, 0, "all", self.cog),
        )


class ListItemView(discord.ui.View):
    def __init__(self, author, cog=None):
        super().__init__(timeout=120)
        self.author = author
        self.cog = cog

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user != self.author:
            await interaction.response.send_message("这不是你的面板。", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="📤 上架物品", style=discord.ButtonStyle.success, row=0)
    async def list_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(ListItemModal(self.author, self.cog))

    @discord.ui.button(label="返回上架选择", style=discord.ButtonStyle.secondary, row=0)
    async def back_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(embed=_list_type_embed(), view=ListTypeView(self.author, self.cog))


class ListEquipView(discord.ui.View):
    def __init__(self, author, cog=None):
        super().__init__(timeout=120)
        self.author = author
        self.cog = cog

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user != self.author:
            await interaction.response.send_message("这不是你的面板。", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="📤 上架装备", style=discord.ButtonStyle.primary, row=0)
    async def list_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(ListEquipModal(self.author, self.cog))

    @discord.ui.button(label="返回上架选择", style=discord.ButtonStyle.secondary, row=0)
    async def back_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(embed=_list_type_embed(), view=ListTypeView(self.author, self.cog))


class ListItemModal(discord.ui.Modal, title="上架背包物品"):
    item_id_input = discord.ui.TextInput(label="物品ID", placeholder="如 herb_lingzhi", min_length=1, max_length=40)
    qty_input = discord.ui.TextInput(label="数量", placeholder="输入数字", min_length=1, max_length=6)
    price_input = discord.ui.TextInput(label="单价（灵石）", placeholder="输入数字", min_length=1, max_length=12)

    def __init__(self, author, cog):
        super().__init__()
        self.author = author
        self.cog = cog

    async def on_submit(self, interaction: discord.Interaction):
        try:
            qty = int(self.qty_input.value.strip())
            price = int(self.price_input.value.replace(",", "").strip())
        except ValueError:
            await interaction.response.send_message("请输入有效数字。", ephemeral=True)
            return
        uid = str(interaction.user.id)
        item_id = self.item_id_input.value.strip()
        result = await list_item(uid, item_id, qty, price)
        if not result["ok"]:
            await interaction.response.send_message(result["reason"], ephemeral=True)
            return
        await interaction.response.defer()
        player = await _get_player(uid)
        listings = await _get_listings_with_names("all")
        embed = _market_main_embed(player, listings, 0, "all")
        embed.set_footer(text=f"✅ 已上架，编号 {result['listing_id']}。")
        await interaction.edit_original_response(
            embed=embed,
            view=MarketMainView(self.author, player, listings, 0, "all", self.cog),
        )


class ListEquipModal(discord.ui.Modal, title="上架装备"):
    equip_id_input = discord.ui.TextInput(label="装备ID", placeholder="从装备列表复制", min_length=1, max_length=40)
    price_input = discord.ui.TextInput(label="价格（灵石）", placeholder="输入数字", min_length=1, max_length=12)

    def __init__(self, author, cog):
        super().__init__()
        self.author = author
        self.cog = cog

    async def on_submit(self, interaction: discord.Interaction):
        try:
            price = int(self.price_input.value.replace(",", "").strip())
        except ValueError:
            await interaction.response.send_message("请输入有效数字。", ephemeral=True)
            return
        uid = str(interaction.user.id)
        equip_id = self.equip_id_input.value.strip()
        result = await list_equipment(uid, equip_id, price)
        if not result["ok"]:
            await interaction.response.send_message(result["reason"], ephemeral=True)
            return
        await interaction.response.defer()
        player = await _get_player(uid)
        listings = await _get_listings_with_names("all")
        embed = _market_main_embed(player, listings, 0, "all")
        embed.set_footer(text=f"✅ 装备已上架，编号 {result['listing_id']}。")
        await interaction.edit_original_response(
            embed=embed,
            view=MarketMainView(self.author, player, listings, 0, "all", self.cog),
        )


class MyStallView(discord.ui.View):
    def __init__(self, author, player: dict, listings: list[dict], expired: list[dict], cog=None):
        super().__init__(timeout=120)
        self.author = author
        self.player = player
        self.listings = listings
        self.expired = expired
        self.cog = cog

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user != self.author:
            await interaction.response.send_message("这不是你的面板。", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="❌ 下架", style=discord.ButtonStyle.danger, row=0)
    async def delist_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(DelistModal(self.author, self.cog))

    @discord.ui.button(label="📥 领回过期商品", style=discord.ButtonStyle.primary, row=0)
    async def claim_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.expired:
            await interaction.response.send_message("没有待领回的商品。", ephemeral=True)
            return
        await interaction.response.send_modal(ClaimModal(self.author, self.cog))

    @discord.ui.button(label="返回交易坊", style=discord.ButtonStyle.secondary, row=0)
    async def back_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        uid = str(interaction.user.id)
        player = await _get_player(uid)
        listings = await _get_listings_with_names("all")
        await interaction.response.edit_message(
            embed=_market_main_embed(player, listings, 0, "all"),
            view=MarketMainView(self.author, player, listings, 0, "all", self.cog),
        )


class DelistModal(discord.ui.Modal, title="下架商品"):
    listing_id_input = discord.ui.TextInput(label="商品编号", placeholder="输入要下架的编号", min_length=1, max_length=8)

    def __init__(self, author, cog):
        super().__init__()
        self.author = author
        self.cog = cog

    async def on_submit(self, interaction: discord.Interaction):
        uid = str(interaction.user.id)
        listing_id = self.listing_id_input.value.strip()
        result = await delist(uid, listing_id)
        if not result["ok"]:
            await interaction.response.send_message(result["reason"], ephemeral=True)
            return
        await interaction.response.defer()
        player = await _get_player(uid)
        listings = await get_my_listings(uid)
        expired = await get_expired_unclaimed(uid)
        embed = _my_listings_embed(player, listings, expired)
        embed.set_footer(text=f"✅ 已下架 **{result['item_name']}**，物品已退回背包。")
        await interaction.edit_original_response(
            embed=embed,
            view=MyStallView(self.author, player, listings, expired, self.cog),
        )


class ClaimModal(discord.ui.Modal, title="领回过期商品"):
    listing_id_input = discord.ui.TextInput(label="商品编号", placeholder="输入要领回的编号", min_length=1, max_length=8)

    def __init__(self, author, cog):
        super().__init__()
        self.author = author
        self.cog = cog

    async def on_submit(self, interaction: discord.Interaction):
        uid = str(interaction.user.id)
        listing_id = self.listing_id_input.value.strip()
        result = await delist(uid, listing_id)
        if not result["ok"]:
            await interaction.response.send_message(result["reason"], ephemeral=True)
            return
        await interaction.response.defer()
        player = await _get_player(uid)
        listings = await get_my_listings(uid)
        expired = await get_expired_unclaimed(uid)
        embed = _my_listings_embed(player, listings, expired)
        embed.set_footer(text=f"✅ 已领回 **{result['item_name']}**。")
        await interaction.edit_original_response(
            embed=embed,
            view=MyStallView(self.author, player, listings, expired, self.cog),
        )


async def _get_listings_with_names(filter_type: str) -> list[dict]:
    if filter_type == "equipment":
        return await get_active_listings("equipment")

    listings = await get_active_listings(None)

    if filter_type == "all":
        return listings

    filtered = []
    for d in listings:
        if d["item_type"] == "item":
            item_info = ITEMS.get(d["item_id"], {})
            if item_info.get("type") == filter_type:
                filtered.append(d)
    return filtered


async def _go_back(interaction: discord.Interaction, author, cog):
    from utils.views.city import CityMenuView, _city_menu_embed
    uid = str(interaction.user.id)
    async with AsyncSessionLocal() as session:
        result = await session.execute(text("SELECT * FROM players WHERE discord_id = :uid"), {"uid": uid})
        p = dict(result.fetchone()._mapping)
    await interaction.response.edit_message(
        embed=await _city_menu_embed(p),
        view=CityMenuView(interaction.user, p, cog),
    )
