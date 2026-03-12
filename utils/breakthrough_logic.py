import time
from sqlalchemy import select
from utils.db_async import AsyncSessionLocal, Player
from utils.realms import (
    cultivation_needed, lifespan_max_for_realm, next_realm,
    roll_breakthrough, apply_failure
)


async def can_breakthrough(discord_id: str) -> tuple[bool, dict | None]:
    async with AsyncSessionLocal() as session:
        player = await session.get(Player, discord_id)
        if not player:
            return False, None
        
        needed = cultivation_needed(player.realm)
        can_bt = player.cultivation >= needed
        
        player_dict = {c.key: getattr(player, c.key) for c in player.__table__.columns}
        
        return can_bt, player_dict


async def do_single_breakthrough(discord_id: str, player_dict: dict) -> dict:
    realm = player_dict["realm"]
    nxt = next_realm(realm)
    
    if not nxt:
        return {"success": False, "message": "已至大道巅峰"}
    
    success, outcome = roll_breakthrough(
        realm,
        player_dict["physique"],
        player_dict["bone"],
        player_dict["cultivation"]
    )
    
    now = time.time()
    
    if success:
        needed = cultivation_needed(realm)
        overflow = max(0, player_dict["cultivation"] - needed)
        new_lifespan_max = lifespan_max_for_realm(nxt)
        lifespan_gain = max(0, new_lifespan_max - player_dict["lifespan_max"])
        new_lifespan = player_dict["lifespan"] + lifespan_gain
        
        async with AsyncSessionLocal() as session:
            player = await session.get(Player, discord_id)
            if not player:
                return {"success": False, "message": "角色不存在"}
            
            player.realm = nxt
            player.lifespan = new_lifespan
            player.lifespan_max = new_lifespan_max
            player.cultivation = overflow
            player.last_active = now
            
            await session.commit()
        
        return {
            "success": True,
            "breakthrough": True,
            "old_realm": realm,
            "new_realm": nxt,
            "lifespan": new_lifespan,
            "lifespan_max": new_lifespan_max,
            "lifespan_gain": lifespan_gain
        }
    else:
        new_cultivation, new_lifespan, fail_msg = apply_failure(
            player_dict["cultivation"],
            player_dict["lifespan"],
            outcome
        )
        
        async with AsyncSessionLocal() as session:
            player = await session.get(Player, discord_id)
            if not player:
                return {"success": False, "message": "角色不存在"}
            
            player.cultivation = new_cultivation
            player.lifespan = new_lifespan
            player.last_active = now
            
            if new_lifespan <= 0:
                player.is_dead = True
            
            await session.commit()
        
        needed = cultivation_needed(realm)
        
        return {
            "success": True,
            "breakthrough": False,
            "fail_msg": fail_msg,
            "cultivation": new_cultivation,
            "lifespan": new_lifespan,
            "needed": needed,
            "is_dead": new_lifespan <= 0
        }


async def do_breakthrough_chain(discord_id: str) -> dict:
    chain = []
    
    can_bt, player_dict = await can_breakthrough(discord_id)
    if not can_bt or not player_dict:
        return {"success": False, "message": "修为未圆满"}
    
    while True:
        result = await do_single_breakthrough(discord_id, player_dict)
        
        if not result["success"]:
            chain.append(result["message"])
            break
        
        if result["breakthrough"]:
            lifespan_line = (
                f"寿元上限→{result['lifespan_max']}年"
                if result["lifespan_gain"] > 0
                else f"寿元{result['lifespan']}年"
            )
            chain.append(f"**{result['old_realm']}** ➜ **{result['new_realm']}**（{lifespan_line}）")
            
            can_bt, player_dict = await can_breakthrough(discord_id)
            if not can_bt:
                break
        else:
            if result["is_dead"]:
                chain.append(f"突破失败，{result['fail_msg']}寿元耗尽，魂归天道。")
            else:
                chain.append(
                    f"突破失败，{result['fail_msg']}"
                    f"修为：{result['cultivation']}/{result['needed']}　"
                    f"寿元：{result['lifespan']}年"
                )
            break
    
    successes = [c for c in chain if "➜" in c]
    fail_line = next((c for c in chain if "➜" not in c), "")
    
    return {
        "success": True,
        "chain": chain,
        "successes": successes,
        "fail_line": fail_line
    }


async def handle_zhuji_breakthrough(discord_id: str, use_pill: bool) -> dict:
    from utils.items import calc_zhuji_breakthrough_rate
    from utils.db import has_item, remove_item
    
    async with AsyncSessionLocal() as session:
        player = await session.get(Player, discord_id)
        if not player:
            return {"success": False, "message": "角色不存在"}
        
        player_dict = {c.key: getattr(player, c.key) for c in player.__table__.columns}
    
    if use_pill and not has_item(discord_id, "筑基丹"):
        return {"success": False, "message": "背包中无筑基丹"}
    
    rate = calc_zhuji_breakthrough_rate(player_dict, use_pill=use_pill)
    
    import random
    success = random.random() * 100 < rate
    
    if use_pill:
        remove_item(discord_id, "筑基丹", 1)
    
    if success:
        needed = cultivation_needed(player_dict["realm"])
        overflow = max(0, player_dict["cultivation"] - needed)
        nxt = "筑基期1层"
        new_lifespan_max = lifespan_max_for_realm(nxt)
        lifespan_gain = max(0, new_lifespan_max - player_dict["lifespan_max"])
        new_lifespan = player_dict["lifespan"] + lifespan_gain
        
        now = time.time()
        
        async with AsyncSessionLocal() as session:
            player = await session.get(Player, discord_id)
            if not player:
                return {"success": False, "message": "角色不存在"}
            
            player.realm = nxt
            player.lifespan = new_lifespan
            player.lifespan_max = new_lifespan_max
            player.cultivation = overflow
            player.last_active = now
            
            await session.commit()
        
        return {
            "success": True,
            "breakthrough": True,
            "new_realm": nxt,
            "lifespan": new_lifespan,
            "lifespan_max": new_lifespan_max
        }
    else:
        new_cultivation = player_dict["cultivation"] // 2
        loss = max(1, player_dict["lifespan"] // 10)
        new_lifespan = max(0, player_dict["lifespan"] - loss)
        
        now = time.time()
        
        async with AsyncSessionLocal() as session:
            player = await session.get(Player, discord_id)
            if not player:
                return {"success": False, "message": "角色不存在"}
            
            player.cultivation = new_cultivation
            player.lifespan = new_lifespan
            player.last_active = now
            
            if new_lifespan <= 0:
                player.is_dead = True
            
            await session.commit()
        
        needed = cultivation_needed(player_dict["realm"])
        
        return {
            "success": True,
            "breakthrough": False,
            "cultivation": new_cultivation,
            "lifespan": new_lifespan,
            "needed": needed,
            "is_dead": new_lifespan <= 0
        }


async def handle_ningdan_breakthrough(discord_id: str, use_pill: bool) -> dict:
    from utils.items.breakthrough import calc_ningdan_breakthrough_rate
    from utils.db import has_item, remove_item
    
    async with AsyncSessionLocal() as session:
        player = await session.get(Player, discord_id)
        if not player:
            return {"success": False, "message": "角色不存在"}
        
        player_dict = {c.key: getattr(player, c.key) for c in player.__table__.columns}
    
    if use_pill and not has_item(discord_id, "凝丹丹"):
        return {"success": False, "message": "背包中无凝丹丹"}
    
    rate = calc_ningdan_breakthrough_rate(player_dict, use_pill=use_pill)
    
    import random
    success = random.random() * 100 < rate
    
    if use_pill:
        remove_item(discord_id, "凝丹丹", 1)
    if success:
        needed = cultivation_needed(player_dict["realm"])
        overflow = max(0, player_dict["cultivation"] - needed)
        nxt = "结丹期初期"
        new_lifespan_max = lifespan_max_for_realm(nxt)
        lifespan_gain = max(0, new_lifespan_max - player_dict["lifespan_max"])
        new_lifespan = player_dict["lifespan"] + lifespan_gain
        
        now = time.time()
        
        async with AsyncSessionLocal() as session:
            player = await session.get(Player, discord_id)
            if not player:
                return {"success": False, "message": "角色不存在"}
            
            player.realm = nxt
            player.lifespan = new_lifespan
            player.lifespan_max = new_lifespan_max
            player.cultivation = overflow
            player.last_active = now
            
            await session.commit()
        
        return {
            "success": True,
            "breakthrough": True,
            "new_realm": nxt,
            "lifespan": new_lifespan,
            "lifespan_max": new_lifespan_max
        }
    else:
        new_cultivation = player_dict["cultivation"] // 2
        loss = max(1, player_dict["lifespan"] // 8)
        new_lifespan = max(0, player_dict["lifespan"] - loss)
        
        now = time.time()
        
        async with AsyncSessionLocal() as session:
            player = await session.get(Player, discord_id)
            if not player:
                return {"success": False, "message": "角色不存在"}
            
            player.cultivation = new_cultivation
            player.lifespan = new_lifespan
            player.last_active = now
            
            if new_lifespan <= 0:
                player.is_dead = True
            
            await session.commit()
        
        needed = cultivation_needed(player_dict["realm"])
        
        return {
            "success": True,
            "breakthrough": False,
            "cultivation": new_cultivation,
            "lifespan": new_lifespan,
            "needed": needed,
            "is_dead": new_lifespan <= 0
        }


async def handle_huaying_breakthrough(discord_id: str, use_pill: bool) -> dict:
    from utils.items.breakthrough import calc_huaying_breakthrough_rate
    from utils.db import has_item, remove_item
    
    async with AsyncSessionLocal() as session:
        player = await session.get(Player, discord_id)
        if not player:
            return {"success": False, "message": "角色不存在"}
        
        player_dict = {c.key: getattr(player, c.key) for c in player.__table__.columns}
    
    if use_pill and not has_item(discord_id, "化婴丹"):
        return {"success": False, "message": "背包中无化婴丹"}
    
    rate = calc_huaying_breakthrough_rate(player_dict, use_pill=use_pill)
    
    import random
    success = random.random() * 100 < rate
    
    if use_pill:
        remove_item(discord_id, "化婴丹", 1)
    
    if success:
        needed = cultivation_needed(player_dict["realm"])
        overflow = max(0, player_dict["cultivation"] - needed)
        nxt = "元婴期初期"
        new_lifespan_max = lifespan_max_for_realm(nxt)
        lifespan_gain = max(0, new_lifespan_max - player_dict["lifespan_max"])
        new_lifespan = player_dict["lifespan"] + lifespan_gain
        
        now = time.time()
        
        async with AsyncSessionLocal() as session:
            player = await session.get(Player, discord_id)
            if not player:
                return {"success": False, "message": "角色不存在"}
            
            player.realm = nxt
            player.lifespan = new_lifespan
            player.lifespan_max = new_lifespan_max
            player.cultivation = overflow
            player.last_active = now
            
            await session.commit()
        
        return {
            "success": True,
            "breakthrough": True,
            "new_realm": nxt,
            "lifespan": new_lifespan,
            "lifespan_max": new_lifespan_max
        }
    else:
        new_cultivation = player_dict["cultivation"] // 2
        loss = max(1, player_dict["lifespan"] // 6)
        new_lifespan = max(0, player_dict["lifespan"] - loss)
        
        now = time.time()
        
        async with AsyncSessionLocal() as session:
            player = await session.get(Player, discord_id)
            if not player:
                return {"success": False, "message": "角色不存在"}
            
            player.cultivation = new_cultivation
            player.lifespan = new_lifespan
            player.last_active = now
            
            if new_lifespan <= 0:
                player.is_dead = True
            
            await session.commit()
        
        needed = cultivation_needed(player_dict["realm"])
        
        return {
            "success": True,
            "breakthrough": False,
            "cultivation": new_cultivation,
            "lifespan": new_lifespan,
            "needed": needed,
            "is_dead": new_lifespan <= 0
        }
