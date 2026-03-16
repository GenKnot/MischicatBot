import json
from sqlalchemy import select
from utils.db_async import AsyncSessionLocal, Equipment


def _row_to_dict(row: Equipment) -> dict:
    d = {c.name: getattr(row, c.name) for c in row.__table__.columns}
    d["stats"] = json.loads(d["stats"] or "{}")
    return d


async def give_equipment(discord_id: str, eq: dict):
    async with AsyncSessionLocal() as session:
        session.add(Equipment(
            equip_id=eq["equip_id"],
            discord_id=discord_id,
            name=eq["name"],
            slot=eq["slot"],
            quality=eq["quality"],
            tier=eq["tier"],
            tier_req=eq["tier_req"],
            stats=json.dumps(eq["stats"], ensure_ascii=False),
            flavor=eq["flavor"],
            equipped=False,
        ))
        await session.commit()


async def get_equipment_list(discord_id: str) -> list[dict]:
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Equipment)
            .where(Equipment.discord_id == discord_id)
            .order_by(Equipment.equipped.desc(), Equipment.tier.desc())
        )
        return [_row_to_dict(r) for r in result.scalars()]


async def get_equipped(discord_id: str) -> list[dict]:
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Equipment).where(
                Equipment.discord_id == discord_id,
                Equipment.equipped == True,
            )
        )
        return [_row_to_dict(r) for r in result.scalars()]


async def equip_item(discord_id: str, equip_id: str, player_tier: int) -> tuple[bool, str]:
    from utils.equipment import TIER_NAMES
    async with AsyncSessionLocal() as session:
        row = await session.get(Equipment, equip_id)
        if not row or row.discord_id != discord_id:
            return False, "装备不存在。"
        if player_tier < row.tier_req:
            req_name = TIER_NAMES[min(row.tier_req, len(TIER_NAMES) - 1)]
            return False, f"需要达到 **{req_name}期** 才能装备此物。"
        result = await session.execute(
            select(Equipment).where(
                Equipment.discord_id == discord_id,
                Equipment.slot == row.slot,
                Equipment.equipped == True,
            )
        )
        existing = result.scalar_one_or_none()
        if existing:
            existing.equipped = False
        row.equipped = True
        name = row.name
        await session.commit()
    return True, f"已装备 **{name}**。"


async def unequip_item(discord_id: str, equip_id: str) -> tuple[bool, str]:
    async with AsyncSessionLocal() as session:
        row = await session.get(Equipment, equip_id)
        if not row or row.discord_id != discord_id or not row.equipped:
            return False, "该装备未装备或不存在。"
        row.equipped = False
        name = row.name
        await session.commit()
    return True, f"已卸下 **{name}**。"


async def discard_equipment(discord_id: str, equip_id: str) -> tuple[bool, str]:
    async with AsyncSessionLocal() as session:
        row = await session.get(Equipment, equip_id)
        if not row or row.discord_id != discord_id:
            return False, "装备不存在。"
        if row.equipped:
            return False, "请先卸下装备再丢弃。"
        name = row.name
        await session.delete(row)
        await session.commit()
    return True, f"已丢弃 **{name}**。"


async def get_equipment_by_id(equip_id: str, discord_id: str) -> dict | None:
    async with AsyncSessionLocal() as session:
        row = await session.get(Equipment, equip_id)
        if not row or row.discord_id != discord_id:
            return None
        return _row_to_dict(row)


async def update_equipment_stats(equip_id: str, new_name: str, new_stats: dict, new_flavor: str):
    async with AsyncSessionLocal() as session:
        row = await session.get(Equipment, equip_id)
        if row:
            row.name = new_name
            row.stats = json.dumps(new_stats, ensure_ascii=False)
            row.flavor = new_flavor
            await session.commit()
