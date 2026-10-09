import json
from sqlalchemy import delete, select, update
from utils.db_async import AsyncSessionLocal, Equipment


def _row_to_dict(row: Equipment) -> dict:
    d = {c.name: getattr(row, c.name) for c in row.__table__.columns}
    d["stats"] = json.loads(d["stats"] or "{}")
    return d


def new_equipment_row(discord_id: str, eq: dict) -> Equipment:
    """构造一条装备记录，由调用方的 session 落库。

    调用方已经开着 session 时用这个，不要再调 `give_equipment` ——
    嵌套开 session 在外层已有未提交写入的情况下会互相等锁。
    """
    return Equipment(
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
    )


async def give_equipment(discord_id: str, eq: dict):
    async with AsyncSessionLocal() as session:
        session.add(new_equipment_row(discord_id, eq))
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
    # 先在独立的会话里做只读校验：同一个会话里先读后写，另一个写事务提交后这边升级写锁会报快照过期
    async with AsyncSessionLocal() as session:
        row = await session.get(Equipment, equip_id)
        if not row or row.discord_id != discord_id:
            return False, "装备不存在。"
        if player_tier < row.tier_req:
            req_name = TIER_NAMES[min(row.tier_req, len(TIER_NAMES) - 1)]
            return False, f"需要达到 **{req_name}期** 才能装备此物。"
        slot, name = row.slot, row.name

    # 卸下同槽位已穿的 + 穿上目标，是同一个事务里的两条 UPDATE：并发穿同槽位的两件装备时，
    # 事务串行执行，最后只剩一件（B49）。卸下用 UPDATE 而不是先查再改，所以旧版本留下的
    # 『同槽位两件已穿』也会一并收敛。
    async with AsyncSessionLocal() as session:
        await session.execute(
            update(Equipment)
            .where(Equipment.discord_id == discord_id, Equipment.slot == slot,
                   Equipment.equipped == True, Equipment.equip_id != equip_id)  # noqa: E712
            .values(equipped=False)
        )
        done = await session.execute(
            update(Equipment)
            .where(Equipment.equip_id == equip_id, Equipment.discord_id == discord_id)
            .values(equipped=True)
        )
        if done.rowcount != 1:
            await session.rollback()
            return False, "装备不存在。"
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

    # 带条件的原子 DELETE：重复点击 / 刚被别处穿上、上架、卖掉时删不到，如实回复（B50）
    async with AsyncSessionLocal() as session:
        res = await session.execute(
            delete(Equipment).where(Equipment.equip_id == equip_id, Equipment.discord_id == discord_id,
                                    Equipment.equipped == False)  # noqa: E712
        )
        await session.commit()
        if res.rowcount != 1:
            return False, "装备不存在或已被穿上，未能丢弃。"
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
