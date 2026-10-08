import random
import time
import json
from sqlalchemy import select
from utils.db_async import AsyncSessionLocal, Player
from utils.character import calc_cultivation_gain, years_to_seconds, get_cultivation_bonus
from utils.realms import cultivation_needed


async def has_dual_technique(discord_id: str) -> bool:
    async with AsyncSessionLocal() as session:
        player = await session.get(Player, discord_id)
        if not player:
            return False
        
        data = json.loads(player.techniques or "[]")
        for t in data:
            name = t if isinstance(t, str) else t.get("name", "")
            if name == "双修功法":
                return True
        return False


async def check_dual_requirements(inviter_id: str, target_id: str) -> dict:
    async with AsyncSessionLocal() as session:
        inviter = await session.get(Player, inviter_id)
        target = await session.get(Player, target_id)
        
        if not inviter or inviter.is_dead:
            return {"success": False, "message": "发起者角色不存在或已坐化"}
        
        if not target or target.is_dead:
            return {"success": False, "message": "对方角色不存在或已坐化"}
        
        inv_has_dual = await has_dual_technique(inviter_id)
        tgt_has_dual = await has_dual_technique(target_id)
        
        if not inv_has_dual and not tgt_has_dual:
            return {"success": False, "message": "双方均未习得「双修功法」"}
        
        if inviter.current_city != target.current_city:
            return {"success": False, "message": "双修需在同一城市"}
        
        now = time.time()
        cooldown_secs = years_to_seconds(2)
        
        if inviter.last_dual_cultivate and now - inviter.last_dual_cultivate < cooldown_secs:
            from utils.character import seconds_to_years
            remaining = seconds_to_years(cooldown_secs - (now - inviter.last_dual_cultivate))
            return {"success": False, "message": f"发起者冷却中，还需 {remaining:.1f} 游戏年"}
        
        if target.last_dual_cultivate and now - target.last_dual_cultivate < cooldown_secs:
            from utils.character import seconds_to_years
            remaining = seconds_to_years(cooldown_secs - (now - target.last_dual_cultivate))
            return {"success": False, "message": f"对方冷却中，还需 {remaining:.1f} 游戏年"}
        
        if inviter.cultivating_until and now < inviter.cultivating_until:
            return {"success": False, "message": "发起者正在闭关"}
        
        if target.cultivating_until and now < target.cultivating_until:
            return {"success": False, "message": "对方正在闭关"}
        
        if inviter.lifespan < 1:
            return {"success": False, "message": "发起者寿元不足"}
        
        if target.lifespan < 1:
            return {"success": False, "message": "对方寿元不足"}
        
        inv_virgin = bool(inviter.is_virgin)
        tgt_virgin = bool(target.is_virgin)
        
        return {
            "success": True,
            "inviter_virgin": inv_virgin,
            "target_virgin": tgt_virgin,
            "inviter_name": inviter.name,
            "target_name": target.name
        }


def _multiplier_range(inviter_virgin: bool, target_virgin: bool) -> tuple[float, float]:
    """双修倍率的**唯一**规则：双方清白 10~20 倍（随机）；一方清白 5 倍；都不是 1.2 倍。"""
    if inviter_virgin and target_virgin:
        return 10, 20
    if inviter_virgin or target_virgin:
        return 5.0, 5.0
    return 1.2, 1.2


def calculate_dual_multiplier(inviter_virgin: bool, target_virgin: bool) -> tuple[float, str]:
    """掷出一个倍率及其描述。发邀请时调用一次，展示给对方；对方接受时该倍率原样结算。"""
    lo, hi = _multiplier_range(inviter_virgin, target_virgin)
    multiplier = random.uniform(lo, hi) if lo != hi else lo

    if inviter_virgin and target_virgin:
        desc = f"双方皆为清白之身，阴阳交融，修为暴涨（**{multiplier:.1f}倍**）"
    elif inviter_virgin or target_virgin:
        desc = "一方清白之身，修为大增（**5倍**）"
    else:
        desc = "双修加持，修为略有提升（**1.2倍**）"

    return multiplier, desc


async def start_dual_cultivation(inviter_id: str, target_id: str, multiplier: float | None = None) -> dict:
    """开始双修。

    `multiplier` 是邀请面板上展示给对方的倍率：传了就**按它结算**，所见即所得。
    但它只在结算时仍然适用才生效 —— 邀请发出到被接受之间，清白身可能已经被别的双修用掉；
    若仍按旧的高倍率结算，同一份清白身就能兑现多次。所以倍率必须落在当前清白身状态对应的
    区间内，否则拒绝，请对方重新发起邀请。不传则由这里现掷（没有展示过的场合）。
    """
    now = time.time()
    
    async with AsyncSessionLocal() as session:
        inviter = await session.get(Player, inviter_id)
        target = await session.get(Player, target_id)
        
        if not inviter or not target:
            return {"success": False, "message": "角色数据异常"}
        
        cooldown_secs = years_to_seconds(2)
        
        if inviter.lifespan < 1:
            return {"success": False, "message": f"**{inviter.name}** 寿元不足"}
        
        if target.lifespan < 1:
            return {"success": False, "message": f"**{target.name}** 寿元不足"}
        
        if inviter.last_dual_cultivate and now - inviter.last_dual_cultivate < cooldown_secs:
            return {"success": False, "message": f"**{inviter.name}** 冷却未结束"}
        
        if target.last_dual_cultivate and now - target.last_dual_cultivate < cooldown_secs:
            return {"success": False, "message": f"**{target.name}** 冷却未结束"}
        
        if inviter.cultivating_until and now < inviter.cultivating_until:
            return {"success": False, "message": f"**{inviter.name}** 正在闭关"}
        
        if target.cultivating_until and now < target.cultivating_until:
            return {"success": False, "message": f"**{target.name}** 正在闭关"}
        
        inv_virgin = bool(inviter.is_virgin)
        tgt_virgin = bool(target.is_virgin)
        both_virgin = inv_virgin and tgt_virgin

        lo, hi = _multiplier_range(inv_virgin, tgt_virgin)
        if multiplier is None:
            multiplier = random.uniform(lo, hi) if lo != hi else lo
        elif not (lo - 1e-9 <= multiplier <= hi + 1e-9):
            return {"success": False, "message": "双方状态已变化，邀请上的倍率已不适用，请重新发起邀请"}

        years = 1
        cultivating_until = now + years_to_seconds(years)
        
        inv_base = calc_cultivation_gain(years, inviter.comprehension, inviter.spirit_root_type)
        inv_bonus = await get_cultivation_bonus(inviter_id, inviter.current_city, inviter.cave)
        inv_gain = int(inv_base * (1 + inv_bonus) * multiplier)
        
        tgt_base = calc_cultivation_gain(years, target.comprehension, target.spirit_root_type)
        tgt_bonus = await get_cultivation_bonus(target_id, target.current_city, target.cave)
        tgt_gain = int(tgt_base * (1 + tgt_bonus) * multiplier)
        
        inviter.lifespan -= years
        inviter.cultivation_overflow = inv_gain
        inviter.cultivating_until = cultivating_until
        inviter.cultivating_years = years
        inviter.last_dual_cultivate = now
        inviter.dual_partner_id = target_id
        inviter.is_virgin = False
        inviter.last_active = now
        
        target.lifespan -= years
        target.cultivation_overflow = tgt_gain
        target.cultivating_until = cultivating_until
        target.cultivating_years = years
        target.last_dual_cultivate = now
        target.dual_partner_id = inviter_id
        target.is_virgin = False
        target.last_active = now
        
        await session.commit()
        
        inv_needed = cultivation_needed(inviter.realm)
        tgt_needed = cultivation_needed(target.realm)
        
        if both_virgin:
            inv_gender = inviter.gender
            tgt_gender = target.gender
            gender_word_inviter = "处男" if inv_virgin and inv_gender == "男" else "处女"
            gender_word_target = "处男" if tgt_virgin and tgt_gender == "男" else "处女"
            flavor = (
                "灵气缠绵，呼吸交织，两道身影在朦胧的灵雾中渐渐靠近……\n"
                "初尝禁果，羞意难掩，却又欲罢不能。\n"
                "阴阳之力在体内激荡翻涌，如决堤之水，修为暴涨。\n\n"
                f"💮 **{inviter.name}** 失去了{gender_word_inviter}状态\n"
                f"💮 **{target.name}** 失去了{gender_word_target}状态\n\n"
                f"修为暴涨（**{multiplier:.1f}倍**）"
            )
        elif inv_virgin or tgt_virgin:
            virgin_one = inviter.name if inv_virgin else target.name
            virgin_player = inviter if inv_virgin else target
            gender_word = "处男" if virgin_player.gender == "男" else "处女"
            flavor = (
                "灵气流转，肌肤相触，一股陌生而炽热的感觉涌遍全身……\n"
                "懵懂与悸动交织，那道防线悄然崩塌。\n"
                "阴阳之力借此契机奔涌而出，修为大幅提升。\n\n"
                f"💮 **{virgin_one}** 失去了{gender_word}状态\n\n"
                "修为大增（**5倍**）"
            )
        else:
            flavor = (
                "两道灵识相互感应，阴阳之气缓缓流转交融。\n"
                "虽无初次的惊涛骇浪，却也有一番绵绵细水的滋味。\n\n"
                "修为略有提升（**1.2倍**）"
            )
        
        return {
            "success": True,
            "flavor": flavor,
            "inviter_name": inviter.name,
            "target_name": target.name,
            "inviter_gain": inv_gain,
            "target_gain": tgt_gain,
            "inviter_cultivation": inviter.cultivation,
            "target_cultivation": target.cultivation,
            "inviter_needed": inv_needed,
            "target_needed": tgt_needed
        }
