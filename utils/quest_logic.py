import logging
import time
import random
import json
from sqlalchemy import select
from utils.atomic import grant_item, increment_player
from utils.db_async import AsyncSessionLocal, Player, Inventory, Equipment
from utils.combat import calc_power
from utils.equipment import generate_equipment
from utils.character import years_to_seconds, seconds_to_years
from utils.realms import get_realm_index

log = logging.getLogger(__name__)


async def get_active_quest(discord_id: str) -> dict | None:
    async with AsyncSessionLocal() as session:
        player = await session.get(Player, discord_id)
        if not player or not player.active_quest:
            return None
        
        try:
            quest_data = json.loads(player.active_quest)
            return {
                "quest": quest_data,
                "due": player.quest_due,
                "player_dict": {c.key: getattr(player, c.key) for c in player.__table__.columns}
            }
        except Exception:
            # active_quest 存的不是合法 JSON
            log.warning("任务数据解析失败 uid=%s", discord_id)
            return None


async def start_quest(discord_id: str, quest: dict, tier: str) -> dict:
    async with AsyncSessionLocal() as session:
        player = await session.get(Player, discord_id)
        if not player:
            return {"success": False, "message": "角色不存在"}
        
        if player.active_quest:
            return {"success": False, "message": "已有进行中的任务"}
        
        now = time.time()
        
        if player.cultivating_until and now < player.cultivating_until:
            return {"success": False, "message": "闭关中无法接取任务"}
        
        if player.gathering_until and now < player.gathering_until:
            return {"success": False, "message": "采集中无法接取任务"}
        
        from sqlalchemy import text as _text
        defense_row = (await session.execute(
            _text(
                "SELECT 1 FROM public_event_participants ep "
                "JOIN public_events e ON ep.event_id = e.event_id "
                "WHERE ep.discord_id = :uid AND ep.activity = 'defense' AND e.status = 'active'"
            ),
            {"uid": discord_id}
        )).fetchone()
        if defense_row:
            return {"success": False, "message": "守城期间无法接取任务"}
        
        party_id = player.party_id
        party_size = 1
        if party_id:
            party_rows = await session.execute(
                select(Player).where(Player.party_id == party_id, Player.is_dead == 0)
            )
            party_members = list(party_rows.scalars())
            party_size = len(party_members)
            
            for member in party_members:
                if member.active_quest:
                    return {"success": False, "message": f"队员 {member.name} 已有任务在进行"}
                if member.cultivating_until and now < member.cultivating_until:
                    return {"success": False, "message": f"队员 {member.name} 正在闭关"}
                if member.gathering_until and now < member.gathering_until:
                    return {"success": False, "message": f"队员 {member.name} 正在采集"}
        
        quest_duration_map = {"普通": 1, "精英": 1, "传说": 1}
        gather_duration_map = {"普通": 2, "精英": 2, "传说": 2}
        
        if quest["type"] == "gather":
            duration = gather_duration_map.get(tier, 2)
        else:
            duration = quest_duration_map.get(tier, 1)
        
        quest_due = now + years_to_seconds(duration)
        
        quest_data = {
            "id": quest["id"],
            "title": quest["title"],
            "tier": tier,
            "type": quest["type"],
            "duration": duration,
            "enemy": quest.get("enemy", {}),
            "location": quest.get("location", ""),
            "rewards": quest.get("rewards", {})
        }
        
        if party_id:
            party_rows = await session.execute(
                select(Player).where(Player.party_id == party_id, Player.is_dead == 0)
            )
            party_members = list(party_rows.scalars())
            
            for member in party_members:
                member.active_quest = json.dumps(quest_data, ensure_ascii=False)
                member.quest_due = quest_due
        else:
            player.active_quest = json.dumps(quest_data, ensure_ascii=False)
            player.quest_due = quest_due
        
        await session.commit()
        
        return {
            "success": True,
            "quest_name": quest["title"],
            "duration": duration,
            "party_size": party_size if party_id else None
        }


async def resolve_quest(discord_id: str) -> dict:
    async with AsyncSessionLocal() as session:
        player = await session.get(Player, discord_id)
        if not player or not player.active_quest:
            return {"success": False, "message": "没有进行中的任务"}
        
        now = time.time()
        if player.quest_due and now < player.quest_due:
            return {"success": False, "message": "任务尚未完成"}
        
        try:
            quest_data = json.loads(player.active_quest)
        except:
            return {"success": False, "message": "任务数据异常"}
        
        quest_type = quest_data.get("type", "combat")
        
        if quest_type == "combat":
            result = await _resolve_combat_quest(discord_id, player, quest_data)
        else:
            result = await _resolve_gather_quest(discord_id, player, quest_data)
        
        return result


async def _resolve_combat_quest(discord_id: str, player: Player, quest_data: dict) -> dict:
    player_dict = {c.key: getattr(player, c.key) for c in player.__table__.columns}
    
    party_id = player.party_id
    if party_id:
        async with AsyncSessionLocal() as session:
            party_rows = await session.execute(
                select(Player).where(Player.party_id == party_id, Player.is_dead == 0)
            )
            party_members = list(party_rows.scalars())
            powers = [await calc_power({c.key: getattr(m, c.key) for c in m.__table__.columns}) for m in party_members]
            total_power = sum(powers) * random.uniform(0.85, 1.15)
    else:
        total_power = (await calc_power(player_dict)) * random.uniform(0.85, 1.15)
    
    enemy = quest_data.get("enemy", {})
    enemy_power = enemy.get("power", 100) * random.uniform(0.85, 1.15)
    
    won = total_power > enemy_power
    
    if won:
        rewards = quest_data.get("rewards", {})
        
        equipment_drop = None
        tier = quest_data.get("tier", "普通")
        
        if tier == "普通":
            if random.random() < 0.3:
                from utils.equipment import get_player_tier
                realm_idx = get_player_tier(player.realm)
                quality_pool = ["普通", "精良"]
                quality_weights = [70, 30]
                quality = random.choices(quality_pool, weights=quality_weights, k=1)[0]
                equipment_drop = generate_equipment(tier=realm_idx, quality=quality)
        elif tier == "精英":
            from utils.equipment import get_player_tier
            realm_idx = get_player_tier(player.realm)
            quality_pool = ["精良", "稀有"]
            quality_weights = [60, 40]
            quality = random.choices(quality_pool, weights=quality_weights, k=1)[0]
            equipment_drop = generate_equipment(tier=realm_idx, quality=quality)
        elif tier == "传说":
            from utils.equipment import get_player_tier
            realm_idx = get_player_tier(player.realm)
            quality_pool = ["稀有", "史诗", "传说"]
            quality_weights = [50, 35, 15]
            quality = random.choices(quality_pool, weights=quality_weights, k=1)[0]
            equipment_drop = generate_equipment(tier=realm_idx, quality=quality)
        
        await _apply_quest_rewards(discord_id, rewards, player_dict, equipment_drop, party_id)
        
        return {
            "success": True,
            "victory": True,
            "rewards": rewards,
            "equipment": equipment_drop,
            "quest_name": quest_data.get("title", "任务"),
            "is_party": bool(party_id)
        }
    else:
        from utils.combat import roll_escape
        escaped, escape_pct = await roll_escape(player_dict)
        
        if escaped:
            tier = quest_data.get("tier", "普通")
            lifespan_loss = {"普通": 2, "精英": 5, "传说": 10}.get(tier, 2)
            
            async with AsyncSessionLocal() as session:
                p = await session.get(Player, discord_id)
                if p:
                    p.lifespan = max(0, p.lifespan - lifespan_loss)
                    p.active_quest = None
                    p.quest_due = None
                    if p.lifespan <= 0:
                        p.is_dead = True
                    await session.commit()
            
            return {
                "success": True,
                "victory": False,
                "escaped": True,
                "lifespan_loss": lifespan_loss,
                "quest_name": quest_data.get("title", "任务")
            }
        else:
            power_gap = max(0, enemy_power - total_power)
            death_chance = min(0.6, 0.1 + power_gap / (enemy.get("power", 100) * 2))
            
            if random.random() < death_chance:
                async with AsyncSessionLocal() as session:
                    p = await session.get(Player, discord_id)
                    if p:
                        p.is_dead = True
                        p.lifespan = 0
                        p.active_quest = None
                        p.quest_due = None
                        await session.commit()
                
                return {
                    "success": True,
                    "victory": False,
                    "escaped": False,
                    "fatal": True,
                    "quest_name": quest_data.get("title", "任务")
                }
            else:
                lifespan_loss = random.randint(10, 30)
                async with AsyncSessionLocal() as session:
                    p = await session.get(Player, discord_id)
                    if p:
                        p.lifespan = max(1, p.lifespan - lifespan_loss)
                        p.active_quest = None
                        p.quest_due = None
                        await session.commit()
                
                return {
                    "success": True,
                    "victory": False,
                    "escaped": False,
                    "fatal": False,
                    "lifespan_loss": lifespan_loss,
                    "quest_name": quest_data.get("title", "任务")
                }


async def _resolve_gather_quest(discord_id: str, player: Player, quest_data: dict) -> dict:
    events = [
        {"desc": "一路顺风，采集顺利完成。", "bonus": 1.0},
        {"desc": "途中遭遇妖兽袭击，奋力击退，有惊无险。", "bonus": 1.0},
        {"desc": "意外发现一处隐秘洞穴，内有前人遗留的修炼心得。", "bonus": 1.2},
        {"desc": "采集途中踩中灵脉节点，灵气涌入体内。", "bonus": 1.1},
        {"desc": "遭遇同行修士争抢，双方交手，你略占上风。", "bonus": 1.0},
        {"desc": "发现一株罕见灵药，顺手带回。", "bonus": 1.5}
    ]
    
    event = random.choice(events)
    rewards = quest_data.get("rewards", {})
    
    adjusted_rewards = {}
    for key, value in rewards.items():
        if key in ["spirit_stones", "cultivation", "reputation"]:
            adjusted_rewards[key] = int(value * event["bonus"])
        else:
            adjusted_rewards[key] = value
    
    party_id = player.party_id
    await _apply_quest_rewards(discord_id, adjusted_rewards, None, None, party_id)
    
    return {
        "success": True,
        "event_desc": event["desc"],
        "rewards": adjusted_rewards,
        "quest_name": quest_data.get("title", "任务"),
        "is_party": bool(party_id)
    }


async def _apply_quest_rewards(discord_id: str, rewards: dict, player_dict: dict | None, equipment_drop: dict | None, party_id: str | None):
    if party_id:
        async with AsyncSessionLocal() as session:
            party_rows = await session.execute(
                select(Player).where(Player.party_id == party_id)
            )
            party_members = list(party_rows.scalars())
            
            roll_results = []
            if equipment_drop:
                for member in party_members:
                    roll = random.randint(1, 100)
                    roll_results.append((member, roll))
                roll_results.sort(key=lambda x: x[1], reverse=True)
                winner = roll_results[0][0]
                from utils.equipment_db import new_equipment_row
                session.add(new_equipment_row(winner.discord_id, equipment_drop))

            for member in party_members:
                member_id = member.discord_id

                # 原子累加，且与队友的发放共处同一事务：
                # 逐个 `+=` 时并发结算会互相覆盖，队伍里有人拿不到奖励。
                await increment_player(
                    session, member_id,
                    spirit_stones=rewards.get("spirit_stones") or 0,
                    cultivation=rewards.get("cultivation") or 0,
                    reputation=rewards.get("reputation") or 0,
                )

                for item_name in rewards.get("items") or []:
                    await grant_item(session, member_id, item_name, 1)

                member.active_quest = None
                member.quest_due = None

            await session.commit()

        if equipment_drop and roll_results:
            roll_lines = "\n".join(
                f"{'🎖️' if i == 0 else '·'} **{m.name}** 掷出 **{r}**{'（获得装备）' if i == 0 else ''}"
                for i, (m, r) in enumerate(roll_results)
            )
            rewards["_equip_roll_result"] = roll_lines
            rewards["_equip_winner"] = roll_results[0][0].name
    else:
        async with AsyncSessionLocal() as session:
            player = await session.get(Player, discord_id)
            if not player:
                return
            
            await increment_player(
                session, discord_id,
                spirit_stones=rewards.get("spirit_stones") or 0,
                cultivation=rewards.get("cultivation") or 0,
                reputation=rewards.get("reputation") or 0,
            )

            for item_name in rewards.get("items") or []:
                await grant_item(session, discord_id, item_name, 1)

            if equipment_drop:
                from utils.equipment_db import new_equipment_row
                session.add(new_equipment_row(discord_id, equipment_drop))

            player.active_quest = None
            player.quest_due = None
            
            await session.commit()


async def _clear_quest(discord_id: str, party_id: str | None):
    if party_id:
        async with AsyncSessionLocal() as session:
            party_rows = await session.execute(
                select(Player).where(Player.party_id == party_id)
            )
            party_members = list(party_rows.scalars())
            
            for member in party_members:
                member.active_quest = None
                member.quest_due = None
            
            await session.commit()
    else:
        async with AsyncSessionLocal() as session:
            player = await session.get(Player, discord_id)
            if player:
                player.active_quest = None
                player.quest_due = None
                await session.commit()


async def cancel_quest(discord_id: str) -> dict:
    async with AsyncSessionLocal() as session:
        player = await session.get(Player, discord_id)
        if not player or not player.active_quest:
            return {"success": False, "message": "没有进行中的任务"}
        
        party_id = player.party_id
        await _clear_quest(discord_id, party_id)
        
        return {"success": True, "is_party": bool(party_id)}
