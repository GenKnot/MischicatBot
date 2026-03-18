import time
import uuid
import json

from sqlalchemy import select
from utils.db_async import AsyncSessionLocal, Player, Inventory, Equipment, MarketListing

MARKET_CITIES = ["灵虚城", "丹阁", "落云城", "碧波城", "天工城"]
MAX_LISTINGS = 5
FEE_RATE = 0.08
LISTING_TTL = 3 * 24 * 3600


async def get_active_listings(item_type: str = None) -> list[dict]:
    async with AsyncSessionLocal() as session:
        q = select(MarketListing).where(MarketListing.status == "active")
        if item_type:
            q = q.where(MarketListing.item_type == item_type)
        q = q.order_by(MarketListing.listed_at.desc())
        result = await session.execute(q)
        return [_to_dict(r) for r in result.scalars()]


async def get_my_listings(discord_id: str) -> list[dict]:
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(MarketListing).where(MarketListing.seller_id == discord_id)
            .order_by(MarketListing.listed_at.desc())
        )
        return [_to_dict(r) for r in result.scalars()]


async def get_expired_unclaimed(discord_id: str) -> list[dict]:
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(MarketListing).where(
                MarketListing.seller_id == discord_id,
                MarketListing.status == "expired",
            )
        )
        return [_to_dict(r) for r in result.scalars()]


async def list_item(discord_id: str, item_id: str, quantity: int, price: int) -> dict:
    from utils.items import ITEMS
    async with AsyncSessionLocal() as session:
        active_result = await session.execute(
            select(MarketListing).where(
                MarketListing.seller_id == discord_id,
                MarketListing.status == "active",
            )
        )
        if len(active_result.scalars().all()) >= MAX_LISTINGS:
            return {"ok": False, "reason": f"最多同时上架 {MAX_LISTINGS} 件。"}

        row = await session.get(Inventory, (discord_id, item_id))
        if not row or row.quantity < quantity:
            return {"ok": False, "reason": "背包物品不足。"}
        if price <= 0:
            return {"ok": False, "reason": "价格必须大于 0。"}

        item_info = ITEMS.get(item_id, {})
        item_name = item_info.get("name", item_id)

        row.quantity -= quantity
        if row.quantity <= 0:
            await session.delete(row)

        listing_id = str(uuid.uuid4())[:8]
        session.add(MarketListing(
            listing_id=listing_id,
            seller_id=discord_id,
            item_type="item",
            item_id=item_id,
            item_name=item_name,
            quantity=quantity,
            price=price,
            listed_at=time.time(),
            expires_at=time.time() + LISTING_TTL,
            status="active",
            eq_data=None,
        ))
        await session.commit()
        return {"ok": True, "listing_id": listing_id}


async def list_equipment(discord_id: str, equip_id: str, price: int) -> dict:
    async with AsyncSessionLocal() as session:
        active_result = await session.execute(
            select(MarketListing).where(
                MarketListing.seller_id == discord_id,
                MarketListing.status == "active",
            )
        )
        if len(active_result.scalars().all()) >= MAX_LISTINGS:
            return {"ok": False, "reason": f"最多同时上架 {MAX_LISTINGS} 件。"}

        eq = await session.get(Equipment, equip_id)
        if not eq or eq.discord_id != discord_id:
            return {"ok": False, "reason": "装备不存在。"}
        if eq.equipped:
            return {"ok": False, "reason": "请先卸下装备再上架。"}
        if price <= 0:
            return {"ok": False, "reason": "价格必须大于 0。"}

        eq_data = json.dumps({
            "equip_id": eq.equip_id,
            "name": eq.name,
            "slot": eq.slot,
            "quality": eq.quality,
            "tier": eq.tier,
            "tier_req": eq.tier_req,
            "stats": json.loads(eq.stats or "{}"),
            "flavor": eq.flavor,
        }, ensure_ascii=False)

        listing_id = str(uuid.uuid4())[:8]
        session.add(MarketListing(
            listing_id=listing_id,
            seller_id=discord_id,
            item_type="equipment",
            item_id=equip_id,
            item_name=eq.name,
            quantity=1,
            price=price,
            listed_at=time.time(),
            expires_at=time.time() + LISTING_TTL,
            status="active",
            eq_data=eq_data,
        ))
        await session.delete(eq)
        await session.commit()
        return {"ok": True, "listing_id": listing_id}


async def buy_listing(discord_id: str, listing_id: str) -> dict:
    async with AsyncSessionLocal() as session:
        listing = await session.get(MarketListing, listing_id)
        if not listing or listing.status != "active":
            return {"ok": False, "reason": "该商品已下架或不存在。"}
        if listing.seller_id == discord_id:
            return {"ok": False, "reason": "不能购买自己的商品。"}

        now = time.time()
        if now >= listing.expires_at:
            listing.status = "expired"
            await session.commit()
            return {"ok": False, "reason": "该商品已过期。"}

        buyer = await session.get(Player, discord_id)
        if not buyer:
            return {"ok": False, "reason": "角色不存在。"}
        if buyer.spirit_stones < listing.price:
            return {"ok": False, "reason": f"灵石不足，需要 {listing.price:,}。"}

        fee = max(1, int(listing.price * FEE_RATE))
        seller_gets = listing.price - fee

        buyer.spirit_stones -= listing.price
        seller = await session.get(Player, listing.seller_id)
        if seller:
            seller.spirit_stones += seller_gets

        if listing.item_type == "item":
            inv = await session.get(Inventory, (discord_id, listing.item_id))
            if inv:
                inv.quantity += listing.quantity
            else:
                session.add(Inventory(discord_id=discord_id, item_id=listing.item_id, quantity=listing.quantity))
        else:
            eq_info = json.loads(listing.eq_data)
            session.add(Equipment(
                equip_id=eq_info["equip_id"],
                discord_id=discord_id,
                name=eq_info["name"],
                slot=eq_info["slot"],
                quality=eq_info["quality"],
                tier=eq_info["tier"],
                tier_req=eq_info["tier_req"],
                stats=json.dumps(eq_info["stats"], ensure_ascii=False),
                flavor=eq_info["flavor"],
                equipped=False,
            ))

        listing.status = "sold"
        await session.commit()
        return {"ok": True, "item_name": listing.item_name, "price": listing.price, "fee": fee}


async def delist(discord_id: str, listing_id: str) -> dict:
    async with AsyncSessionLocal() as session:
        listing = await session.get(MarketListing, listing_id)
        if not listing or listing.seller_id != discord_id:
            return {"ok": False, "reason": "上架记录不存在。"}
        if listing.status not in ("active", "expired"):
            return {"ok": False, "reason": "该商品已售出。"}

        if listing.item_type == "item":
            inv = await session.get(Inventory, (discord_id, listing.item_id))
            if inv:
                inv.quantity += listing.quantity
            else:
                session.add(Inventory(discord_id=discord_id, item_id=listing.item_id, quantity=listing.quantity))
        else:
            eq_info = json.loads(listing.eq_data)
            session.add(Equipment(
                equip_id=eq_info["equip_id"],
                discord_id=discord_id,
                name=eq_info["name"],
                slot=eq_info["slot"],
                quality=eq_info["quality"],
                tier=eq_info["tier"],
                tier_req=eq_info["tier_req"],
                stats=json.dumps(eq_info["stats"], ensure_ascii=False),
                flavor=eq_info["flavor"],
                equipped=False,
            ))

        listing.status = "delisted"
        await session.commit()
        return {"ok": True, "item_name": listing.item_name}


async def expire_old_listings():
    async with AsyncSessionLocal() as session:
        now = time.time()
        result = await session.execute(
            select(MarketListing).where(
                MarketListing.status == "active",
                MarketListing.expires_at <= now,
            )
        )
        for listing in result.scalars():
            listing.status = "expired"
        await session.commit()


def _to_dict(r: "MarketListing") -> dict:
    return {c.name: getattr(r, c.name) for c in r.__table__.columns}
