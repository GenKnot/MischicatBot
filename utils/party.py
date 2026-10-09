import uuid
import time
from sqlalchemy import exists, func, select, update
from utils.db_async import AsyncSessionLocal, Party, Player


async def get_party(party_id: str) -> dict | None:
    async with AsyncSessionLocal() as session:
        party = await session.get(Party, party_id)
        if not party:
            return None
        return {"party_id": party.party_id, "leader_id": party.leader_id, "city": party.city, "created_at": party.created_at}


async def get_party_members(party_id: str) -> list[dict]:
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Player).where(Player.party_id == party_id)
        )
        return [
            {c.key: getattr(p, c.key) for c in Player.__table__.columns}
            for p in result.scalars()
        ]


async def create_party(leader_id: str, city: str) -> str:
    party_id = str(uuid.uuid4())[:8]
    async with AsyncSessionLocal() as session:
        session.add(Party(party_id=party_id, leader_id=leader_id, city=city, created_at=time.time()))
        leader = await session.get(Player, leader_id)
        if leader:
            leader.party_id = party_id
        await session.commit()
    return party_id


MAX_PARTY_SIZE = 4


async def add_to_party(party_id: str, uid: str) -> bool:
    """把玩家加入队伍。一条带条件的 UPDATE：队伍存在、人数不足 4、玩家活着且还没有队伍。

    以前是『先数人数、再无条件写 party_id』：并发时能超过 4 人；玩家已在别的队伍时会被悄悄带走（B67）。
    """
    async with AsyncSessionLocal() as session:
        members = select(func.count()).select_from(Player).where(Player.party_id == party_id).scalar_subquery()
        res = await session.execute(
            update(Player)
            .where(Player.discord_id == uid, Player.party_id.is_(None), Player.is_dead == False,  # noqa: E712
                   exists().where(Party.party_id == party_id), members < MAX_PARTY_SIZE)
            .values(party_id=party_id)
        )
        await session.commit()
    return res.rowcount == 1


async def accept_invite(inviter_id: str, target_id: str) -> dict:
    """接受组队邀请：邀请者没有队伍就先建队，再把被邀请者放进去 —— 一个事务。

    先做一次空写入拿到写锁，之后的校验与写入才不会被并发的另一个接受打断（B67）：
    两个人同时接受同一个无队伍邀请者，不会各建一个队；同时接受也不会超过 4 人；
    被邀请者在邀请发出后已经加入别的队伍的，拒绝而不是悄悄带走。
    """
    if inviter_id == target_id:
        return {"ok": False, "reason": "不能邀请自己。"}
    async with AsyncSessionLocal() as session:
        await session.execute(
            update(Player).where(Player.discord_id.in_([inviter_id, target_id])).values(party_id=Player.party_id)
        )
        inv = await session.get(Player, inviter_id)
        tgt = await session.get(Player, target_id)
        if not inv or not tgt:
            return {"ok": False, "reason": "玩家数据异常，组队失败。"}
        if inv.is_dead or tgt.is_dead:
            return {"ok": False, "reason": "有人已坐化，组队失败。"}
        if inv.current_city != tgt.current_city:
            return {"ok": False, "reason": "邀请者已离开原城市，组队失败。"}
        if tgt.party_id:
            reason = "你已经在这个队伍里了。" if tgt.party_id == inv.party_id else "你已在其他队伍中，请先退出再接受邀请。"
            return {"ok": False, "reason": reason}
        party_id = inv.party_id
        if party_id is None:
            party_id = str(uuid.uuid4())[:8]
            session.add(Party(party_id=party_id, leader_id=inviter_id, city=inv.current_city, created_at=time.time()))
            await session.flush()
            inv.party_id = party_id
        else:
            count = await session.scalar(select(func.count()).select_from(Player).where(Player.party_id == party_id))
            if count >= MAX_PARTY_SIZE:
                return {"ok": False, "reason": "队伍已满，无法加入。"}
        tgt.party_id = party_id
        await session.commit()
    return {"ok": True, "party_id": party_id}


async def remove_from_party(uid: str) -> str:
    async with AsyncSessionLocal() as session:
        player = await session.get(Player, uid)
        if not player or not player.party_id:
            return "你不在任何队伍中。"
        party_id = player.party_id
        party = await session.get(Party, party_id)
        player.party_id = None
        await session.flush()
        if not party:
            await session.commit()
            return "已退出队伍。"
        result = await session.execute(
            select(Player).where(Player.party_id == party_id)
        )
        remaining = result.scalars().all()
        if not remaining:
            await session.delete(party)
        elif uid == party.leader_id and remaining:
            party.leader_id = remaining[0].discord_id
        await session.commit()
    return "已退出队伍。"


async def disband_party(uid: str) -> tuple[str, list[str]]:
    async with AsyncSessionLocal() as session:
        player = await session.get(Player, uid)
        if not player or not player.party_id:
            return "你不在任何队伍中。", []
        party_id = player.party_id
        party = await session.get(Party, party_id)
        if not party or party.leader_id != uid:
            return "只有队长才能解散队伍。", []
        result = await session.execute(
            select(Player).where(Player.party_id == party_id)
        )
        members = result.scalars().all()
        member_ids = [m.discord_id for m in members]
        for m in members:
            m.party_id = None
        await session.delete(party)
        await session.commit()
    return "队伍已解散，所有成员已退出。", member_ids
