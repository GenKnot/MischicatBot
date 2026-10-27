import random
import time
from sqlalchemy import select, update
from utils.db_async import AsyncSessionLocal, Player
from utils import rules
from utils.character import realm_lifespan
from utils.world import CITIES


def calculate_rebirth_bonus(player: dict) -> dict:
    rebirth_count = player.get("rebirth_count", 0)
    c = rules.section("rebirth")
    mult = 1 + rebirth_count * c["mult_step"]
    return {stat: max(0, int((player.get(stat, 5) - 5) * c["stat_keep"] * mult))
            for stat in ("comprehension", "physique", "fortune", "bone", "soul")}


async def check_death(discord_id: str) -> tuple[bool, dict | None]:
    async with AsyncSessionLocal() as session:
        player = await session.get(Player, discord_id)
        if not player:
            return False, None
        
        player_dict = {c.key: getattr(player, c.key) for c in player.__table__.columns}
        
        if player.lifespan <= 0 or player.is_dead:
            return True, player_dict
        
        return False, player_dict


async def handle_rebirth(discord_id: str, player_dict: dict) -> dict:
    bonus = calculate_rebirth_bonus(player_dict)
    new_rebirth = player_dict.get("rebirth_count", 0) + 1
    lifespan = realm_lifespan("炼气期")
    now = time.time()
    starting_city = random.choice(CITIES)["name"]
    
    async with AsyncSessionLocal() as session:
        player = await session.get(Player, discord_id)
        if not player:
            return {"success": False, "message": "角色不存在"}
        
        player.realm = "炼气期1层"
        player.cultivation = 0
        player.lifespan = lifespan
        player.lifespan_max = lifespan
        player.spirit_stones = rules.section("rebirth")["start_stones"]
        player.is_dead = False
        player.is_virgin = True
        player.sect = None
        player.sect_rank = None
        player.cultivating_until = None
        player.cultivating_years = None
        player.active_quest = None
        player.quest_due = None
        player.gathering_until = None
        player.gathering_type = None
        player.explore_count = 0
        player.explore_reset_year = 0
        player.current_city = starting_city
        player.last_active = now
        player.rebirth_count = new_rebirth
        player.comprehension += bonus["comprehension"]
        player.physique += bonus["physique"]
        player.fortune += bonus["fortune"]
        player.bone += bonus["bone"]
        player.soul += bonus["soul"]
        
        await session.commit()
    
    sect = player_dict.get("sect") or ""
    is_xianzang = sect == "仙葬谷"
    reason = "仙葬谷轮回传承" if is_xianzang else "阴阳奇遇感应"
    
    return {
        "success": True,
        "rebirth_count": new_rebirth,
        "reason": reason,
        "bonus": bonus,
        "name": player_dict["name"]
    }


async def handle_death(discord_id: str) -> dict:
    async with AsyncSessionLocal() as session:
        player = await session.get(Player, discord_id)
        if not player:
            return {"success": False, "message": "角色不存在"}
        
        player.is_dead = True
        await session.commit()
        
        return {
            "success": True,
            "name": player.name
        }


async def can_rebirth(discord_id: str) -> tuple[bool, dict | None]:
    async with AsyncSessionLocal() as session:
        player = await session.get(Player, discord_id)
        if not player:
            return False, None
        
        sect = player.sect or ""
        has_bahongchen = player.has_bahongchen
        is_xianzang = sect == "仙葬谷"
        can_rebirth = is_xianzang or bool(has_bahongchen)
        
        player_dict = {c.key: getattr(player, c.key) for c in player.__table__.columns}
        
        return can_rebirth, player_dict


def should_trigger_yinyang(player_dict: dict) -> bool:
    if player_dict.get("has_bahongchen") or player_dict.get("rebirth_count", 0) > 0:
        return False
    return random.random() <= rules.section("rebirth")["yinyang_chance"]


async def mark_yinyang_triggered(discord_id: str):
    async with AsyncSessionLocal() as session:
        player = await session.get(Player, discord_id)
        if player:
            player.has_bahongchen = True
            await session.commit()
