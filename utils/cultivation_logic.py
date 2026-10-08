import time
from sqlalchemy import select
from utils.db_async import AsyncSessionLocal, Player
from utils.character import (
    calc_cultivation_gain, years_to_seconds, seconds_to_years,
    get_cultivation_bonus, get_effective_lifespan_max
)
from utils.realms import cultivation_needed


async def get_player_data(discord_id: str) -> dict | None:
    async with AsyncSessionLocal() as session:
        player = await session.get(Player, discord_id)
        if not player:
            return None
        
        return {c.key: getattr(player, c.key) for c in player.__table__.columns}


async def check_cultivation_status(discord_id: str) -> dict:
    async with AsyncSessionLocal() as session:
        player = await session.get(Player, discord_id)
        if not player:
            return {"exists": False}
        
        now = time.time()
        
        is_cultivating = bool(player.cultivating_until and now < player.cultivating_until)
        is_gathering = bool(player.gathering_until and now < player.gathering_until)
        
        status = "空闲"
        if is_cultivating:
            remaining = seconds_to_years(player.cultivating_until - now)
            status = f"闭关中（还剩 {remaining:.1f} 年）"
        elif is_gathering:
            remaining = seconds_to_years(player.gathering_until - now)
            gtype = player.gathering_type or "采集"
            status = f"{gtype}中（还剩 {remaining:.1f} 年）"
        
        return {
            "exists": True,
            "is_cultivating": is_cultivating,
            "is_gathering": is_gathering,
            "status": status,
            "player_dict": {c.key: getattr(player, c.key) for c in player.__table__.columns}
        }


async def start_cultivation(discord_id: str, years: int) -> dict:
    async with AsyncSessionLocal() as session:
        player = await session.get(Player, discord_id)
        if not player:
            return {"success": False, "message": "角色不存在"}
        
        if player.lifespan < years:
            return {"success": False, "message": f"寿元不足，剩余 {player.lifespan} 年"}
        
        now = time.time()
        
        if player.cultivating_until and now < player.cultivating_until:
            remaining = seconds_to_years(player.cultivating_until - now)
            return {"success": False, "message": f"正在闭关，还剩 {remaining:.1f} 年"}
        
        if player.gathering_until and now < player.gathering_until:
            return {"success": False, "message": "正在采集中，无法修炼"}
        
        cultivating_until = now + years_to_seconds(years)
        bonus = await get_cultivation_bonus(discord_id, player.current_city, player.cave)
        
        from utils.buffs import get_cultivation_speed_bonus
        speed_bonus = get_cultivation_speed_bonus({c.key: getattr(player, c.key) for c in player.__table__.columns})
        if speed_bonus > 0:
            bonus += speed_bonus
        
        gain = int(calc_cultivation_gain(years, player.comprehension, player.spirit_root_type) * (1 + bonus))
        
        player.cultivating_until = cultivating_until
        player.cultivating_years = years
        player.last_active = now
        
        await session.commit()
        
        needed = cultivation_needed(player.realm)
        
        return {
            "success": True,
            "years": years,
            "gain": gain,
            "cultivation": player.cultivation,
            "needed": needed,
            "speed_bonus": speed_bonus,
            "name": player.name
        }


async def stop_cultivation(discord_id: str) -> dict:
    async with AsyncSessionLocal() as session:
        player = await session.get(Player, discord_id)
        if not player:
            return {"success": False, "message": "角色不存在"}
        
        now = time.time()
        
        if not player.cultivating_until or now >= player.cultivating_until:
            return {"success": False, "message": "当前并未在闭关"}
        
        partner_id = (player.dual_partner_id or "").strip()
        is_dual = bool(partner_id)
        
        partner = None
        if is_dual:
            partner = await session.get(Player, partner_id)
        
        partner_active = bool(
            partner
            and partner.cultivating_until
            and now < partner.cultivating_until
            and str(partner.dual_partner_id or "") == discord_id
        )
        
        async def _calc_stop(p, is_dual_mode: bool):
            elapsed_years = seconds_to_years(now - (p.last_active or now))
            total_years = p.cultivating_years or 0
            actual_years = min(int(elapsed_years), int(total_years or 0))
            overflow = p.cultivation_overflow or 0
            
            if overflow > 0:
                gain = int(overflow * actual_years / max(int(total_years or 1), 1))
            else:
                bonus = await get_cultivation_bonus(str(p.discord_id), p.current_city, p.cave)
                from utils.buffs import get_cultivation_speed_bonus
                speed_bonus = get_cultivation_speed_bonus({c.key: getattr(p, c.key) for c in p.__table__.columns})
                if speed_bonus > 0:
                    bonus += speed_bonus
                gain = int(calc_cultivation_gain(actual_years, p.comprehension, p.spirit_root_type) * (1 + bonus))
            
            new_cultivation = (p.cultivation or 0) + gain
            
            if is_dual_mode:
                new_lifespan = (p.lifespan or 0) + (int(total_years or 0) - actual_years)
                player_dict = {c.key: getattr(p, c.key) for c in p.__table__.columns}
                new_lifespan = min(new_lifespan, get_effective_lifespan_max(player_dict))
            else:
                new_lifespan = (p.lifespan or 0) - actual_years
            
            return actual_years, gain, new_cultivation, new_lifespan
        
        if not is_dual or not partner_active:
            actual_years, gain, new_cultivation, new_lifespan = await _calc_stop(player, is_dual_mode=False)
            
            player.cultivation = new_cultivation
            player.lifespan = new_lifespan
            player.cultivation_overflow = 0
            player.cultivating_until = None
            player.cultivating_years = None
            player.dual_partner_id = None
            player.last_active = now
            
            await session.commit()
            
            needed = cultivation_needed(player.realm)
            
            return {
                "success": True,
                "is_dual": False,
                "name": player.name,
                "actual_years": actual_years,
                "gain": gain,
                "cultivation": new_cultivation,
                "needed": needed,
                "lifespan": new_lifespan
            }
        
        a_years, a_gain, a_cult, a_life = await _calc_stop(player, is_dual_mode=True)
        b_years, b_gain, b_cult, b_life = await _calc_stop(partner, is_dual_mode=True)
        
        player.cultivation = a_cult
        player.lifespan = a_life
        player.cultivation_overflow = 0
        player.cultivating_until = None
        player.cultivating_years = None
        player.dual_partner_id = None
        player.last_active = now
        
        partner.cultivation = b_cult
        partner.lifespan = b_life
        partner.cultivation_overflow = 0
        partner.cultivating_until = None
        partner.cultivating_years = None
        partner.dual_partner_id = None
        partner.last_active = now
        
        await session.commit()
        
        needed_a = cultivation_needed(player.realm)
        needed_b = cultivation_needed(partner.realm)
        
        return {
            "success": True,
            "is_dual": True,
            "name": player.name,
            "partner_name": partner.name,
            "partner_id": partner_id,
            "actual_years": a_years,
            "gain": a_gain,
            "cultivation": a_cult,
            "needed": needed_a,
            "lifespan": a_life,
            "partner_years": b_years,
            "partner_gain": b_gain,
            "partner_cultivation": b_cult,
            "partner_needed": needed_b,
            "partner_lifespan": b_life
        }
