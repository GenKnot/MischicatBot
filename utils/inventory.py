from sqlalchemy import select

from utils.atomic import consume_item, grant_item
from utils.db_async import AsyncSessionLocal, Inventory


async def get_inventory(discord_id: str) -> dict:
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Inventory).where(Inventory.discord_id == discord_id)
        )
        return {r.item_id: r.quantity for r in result.scalars()}


async def has_item(discord_id: str, item_id: str) -> bool:
    async with AsyncSessionLocal() as session:
        row = await session.get(Inventory, (discord_id, item_id))
        return row is not None and row.quantity > 0


async def add_item(discord_id: str, item_id: str, quantity: int = 1):
    async with AsyncSessionLocal() as session:
        await grant_item(session, discord_id, item_id, quantity)
        await session.commit()


async def remove_item(discord_id: str, item_id: str, quantity: int = 1) -> bool:
    """扣减物品。数量不足返回 False，且不会扣掉任何东西。"""
    async with AsyncSessionLocal() as session:
        ok = await consume_item(session, discord_id, item_id, quantity)
        if ok:
            await session.commit()
        return ok
