import time
import uuid
import json

from sqlalchemy import delete, select, update

from utils.atomic import consume_item, grant_item, grant_stones, spend_stones
from utils.db_async import AsyncSessionLocal, Equipment, MarketListing

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

        if price <= 0:
            return {"ok": False, "reason": "价格必须大于 0。"}
        if quantity <= 0:
            return {"ok": False, "reason": "数量必须大于 0。"}
        # 先原子扣背包再建挂单：并发上架同一批物品时只有一次能扣到
        if not await consume_item(session, discord_id, item_id, quantity):
            return {"ok": False, "reason": "背包物品不足。"}

        item_info = ITEMS.get(item_id, {})
        item_name = item_info.get("name", item_id)

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
        # 原子占用装备：并发上架同一件时只有一次能删掉，另一次挂单被回滚
        removed = await session.execute(
            delete(Equipment).where(
                Equipment.equip_id == equip_id,
                Equipment.discord_id == discord_id,
                Equipment.equipped == False,  # noqa: E712 — SQL 比较，不能用 `is not`
            )
        )
        if removed.rowcount != 1:
            await session.rollback()
            return {"ok": False, "reason": "装备不存在。"}
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

        # 原子占单：只有把 active 改成 sold 的那一次点击才算买到，
        # 并发的第二次点击 rowcount 为 0，不会重复发货。
        claimed = await session.execute(
            update(MarketListing)
            .where(MarketListing.listing_id == listing_id,
                   MarketListing.status == "active")
            .values(status="sold")
        )
        if claimed.rowcount != 1:
            return {"ok": False, "reason": "该商品已下架或不存在。"}

        # rollback 会让 ORM 对象过期，之后再读属性会触发同步 IO，
        # 所以这里先把要用到的值取成普通变量。
        price, seller_id = listing.price, listing.seller_id
        item_type, item_id, quantity = listing.item_type, listing.item_id, listing.quantity
        item_name, eq_data = listing.item_name, listing.eq_data
        fee = max(1, int(price * FEE_RATE))
        seller_gets = price - fee

        if not await spend_stones(session, discord_id, price):
            await session.rollback()          # 连带撤销上面的占单
            return {"ok": False, "reason": f"灵石不足，需要 {price:,}。"}
        await grant_stones(session, seller_id, seller_gets)

        if item_type == "item":
            await grant_item(session, discord_id, item_id, quantity)
        else:
            eq_info = json.loads(eq_data)
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

        await session.commit()
        return {"ok": True, "item_name": item_name, "price": price, "fee": fee}


async def delist(discord_id: str, listing_id: str) -> dict:
    async with AsyncSessionLocal() as session:
        listing = await session.get(MarketListing, listing_id)
        if not listing or listing.seller_id != discord_id:
            return {"ok": False, "reason": "上架记录不存在。"}
        if listing.status not in ("active", "expired"):
            return {"ok": False, "reason": "该商品已售出。"}

        if listing.item_type == "item":
            await grant_item(session, discord_id, listing.item_id, listing.quantity)
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
