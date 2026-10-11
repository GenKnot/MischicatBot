"""玩家与机器人的战斗后果：打劫、废修为、击杀，以及打输了被机器人处置（U1「江湖百态」）。

战斗本身沿用真人 PvP（utils/views/combat.py、utils/combat.roll_combat，只能在秘地打）。这里管赢了之后：

· **打劫**：拿机器人随身灵石的 15%（单次 ≤150）；每个真人每天最多打劫 / 废修为 3 次；声望 -1，被劫的机器人对你好感 -40（变仇视）。
· **废修为**：机器人修为归零；声望 -2，好感 -60；和打劫共用每天 3 次。
· **击杀**：拿机器人随身灵石的 30%（单次 ≤300），钱庄里的钱随人消失；每个真人每天最多 5 次，**全服每天最多 10 个**
  （补员每天只补得起这么多，真人猎杀太快世界会塌陷，见 .gk/ISSUES.md「劫杀」）；声望 -5（天骄 -10）。
· **打输了被擒获**（逃跑没成功）：机器人按性格处置 —— 放走 / 劫你随身 15%（≤150）/ 杀（**总开关 combat.can_kill_humans 默认关**，
  且对方境界低于 kill_protect_below 的永远不杀）。

所有数值在 data/bot_economy.json 的 combat 里。每个动作是一个事务：计数、扣钱、给钱、声望一起提交或一起回滚，
落空（机器人身上没钱、已经死了）不占用当天次数。
"""

import logging
import random

from sqlalchemy import select, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from utils import bot_economy as be
from utils import bot_social, bot_world, rumors
from utils.atomic import grant_stones, spend_stones
from utils.db_async import AsyncSessionLocal, BotPersonality, BotRaid, Player
from utils.realms import get_realm_index

log = logging.getLogger(__name__)


ALL = "__all__"        # bot_raids 里代表「全服」的行：当天被击杀的机器人总数


def today() -> str:
    import time
    return time.strftime("%Y-%m-%d")


async def power_multiplier(player: dict) -> float:
    """机器人的战力加成（按档位的虚拟功法装备）；真人是 1。"""
    if not player.get("is_bot"):
        return 1.0
    async with AsyncSessionLocal() as session:
        tier = await session.scalar(select(BotPersonality.tier).where(BotPersonality.bot_id == player["discord_id"]))
    return 1.0 + be.load_config()["combat"]["power_bonus"].get(tier or "正常", 0.0)


async def _lock(session) -> None:
    await session.execute(update(Player).where(Player.discord_id == "").values(discord_id=""))


async def _claim_raid(session, player_id: str, field: str, limit: int) -> bool:
    """今天的 field（robs / kills）次数没到上限就 +1。在调用方的事务里，落空回滚时一并撤销。"""
    day = today()
    await session.execute(sqlite_insert(BotRaid).values(player_id=player_id, day=day, robs=0, kills=0)
                          .on_conflict_do_nothing())
    col = getattr(BotRaid, field)
    res = await session.execute(update(BotRaid).where(BotRaid.player_id == player_id, BotRaid.day == day, col < limit)
                                .values({field: col + 1}))
    return res.rowcount == 1


async def _check_pair(session, human_id: str, bot_id: str):
    """校验：机器人在世、真人在世、在同一个地方。返回 (human, bot) 或错误文字。"""
    human, bot = await session.get(Player, human_id), await session.get(Player, bot_id)
    if human is None or bot is None or not bot.is_bot or human.is_bot:
        return "对方不存在。"
    if human.is_dead:
        return "你已经坐化了。"
    if bot.is_dead:
        return f"**{bot.name}** 已经坐化了。"
    if human.current_city != bot.current_city:
        return f"**{bot.name}** 已经离开此地。"
    return human, bot


async def _lose_reputation(session, player_id: str, amount: int) -> None:
    await session.execute(update(Player).where(Player.discord_id == player_id)
                          .values(reputation=Player.reputation - amount if amount else Player.reputation))
    await session.execute(update(Player).where(Player.discord_id == player_id, Player.reputation < 0).values(reputation=0))


async def rob_bot(human_id: str, bot_id: str) -> dict:
    cfg = be.load_config()["combat"]
    async with AsyncSessionLocal() as session:
        await _lock(session)
        pair = await _check_pair(session, human_id, bot_id)
        if isinstance(pair, str):
            await session.rollback()
            return {"ok": False, "reason": pair}
        human, bot = pair
        name, hname, city = bot.name, human.name, human.current_city      # 先取出来：回滚之后属性会过期
        if not await _claim_raid(session, human_id, "robs", cfg["rob"]["per_human_per_day"]):
            await session.rollback()
            return {"ok": False, "reason": f"今天已经打劫 / 废人修为 {cfg['rob']['per_human_per_day']} 次了，不能再下手。"}
        amount = min(int(bot.spirit_stones * cfg["rob"]["share"]), cfg["rob"]["cap"])
        if amount <= 0 or not await spend_stones(session, bot_id, amount):
            await session.rollback()
            return {"ok": False, "reason": f"**{name}** 身上已经没什么油水了。"}
        await grant_stones(session, human_id, amount)
        await _lose_reputation(session, human_id, cfg["cost"]["rob"]["reputation"])
        await session.commit()
    favor = await bot_social.adjust_favor(human_id, bot_id, cfg["cost"]["rob"]["favor"])
    await rumors.record_rumor("rob_bot", human_id, hname, target=name, city=city, amount=amount)
    return {"ok": True, "amount": amount, "bot_name": name, "favor": favor}


async def cripple_bot(human_id: str, bot_id: str) -> dict:
    cfg = be.load_config()["combat"]
    async with AsyncSessionLocal() as session:
        await _lock(session)
        pair = await _check_pair(session, human_id, bot_id)
        if isinstance(pair, str):
            await session.rollback()
            return {"ok": False, "reason": pair}
        human, bot = pair
        name, hname, city = bot.name, human.name, human.current_city
        if not await _claim_raid(session, human_id, "robs", cfg["rob"]["per_human_per_day"]):
            await session.rollback()
            return {"ok": False, "reason": f"今天已经打劫 / 废人修为 {cfg['rob']['per_human_per_day']} 次了，不能再下手。"}
        await session.execute(update(Player).where(Player.discord_id == bot_id, Player.is_dead == False)  # noqa: E712
                              .values(cultivation=0))
        await _lose_reputation(session, human_id, cfg["cost"]["cripple"]["reputation"])
        await session.commit()
    favor = await bot_social.adjust_favor(human_id, bot_id, cfg["cost"]["cripple"]["favor"])
    await rumors.record_rumor("cripple_bot", human_id, hname, target=name, city=city)
    return {"ok": True, "bot_name": name, "favor": favor}


async def kill_bot(human_id: str, bot_id: str) -> dict:
    cfg = be.load_config()["combat"]
    async with AsyncSessionLocal() as session:
        await _lock(session)
        pair = await _check_pair(session, human_id, bot_id)
        if isinstance(pair, str):
            await session.rollback()
            return {"ok": False, "reason": pair}
        human, bot = pair
        name, hname, city = bot.name, human.name, human.current_city
        if not await _claim_raid(session, human_id, "kills", cfg["kill"]["per_human_per_day"]):
            await session.rollback()
            return {"ok": False, "reason": f"今天已经击杀 {cfg['kill']['per_human_per_day']} 名修士了，杀孽太重，歇一歇吧。"}
        if not await _claim_raid(session, ALL, "kills", cfg["kill"]["global_per_day"]):
            await session.rollback()                          # 同时撤销上面占的个人次数
            return {"ok": False, "reason": f"今天全服已有 {cfg['kill']['global_per_day']} 名散修被击杀，江湖需要休养生息，明日再来。"}
        tier = await session.scalar(select(BotPersonality.tier).where(BotPersonality.bot_id == bot_id))
        res = await session.execute(update(Player).where(Player.discord_id == bot_id, Player.is_dead == False)  # noqa: E712
                                    .values(is_dead=True, lifespan=0))
        if res.rowcount != 1:
            await session.rollback()
            return {"ok": False, "reason": f"**{name}** 已经坐化了。"}
        reward = min(int(bot.spirit_stones * cfg["kill"]["share"]), cfg["kill"]["cap"])
        if reward > 0 and await spend_stones(session, bot_id, reward):
            await grant_stones(session, human_id, reward)
        else:
            reward = 0
        cost = cfg["cost"]["kill"]
        await _lose_reputation(session, human_id, cost["reputation_tianjiao"] if tier == "天骄" else cost["reputation"])
        await session.commit()
    await bot_world.remove_bots([bot_id])                 # 名下的东西、钱庄、好感记录一起清走；失败了下次结算也会清死掉的机器人
    await rumors.record_rumor("kill_bot", human_id, hname, target=name, city=city, amount=reward)
    return {"ok": True, "amount": reward, "bot_name": name, "tier": tier}


async def handle_captive(bot_id: str, human_id: str, rng: random.Random | None = None) -> dict:
    """真人攻击机器人打输了、又没逃掉：机器人按性格处置。返回 {"outcome": release/rob/kill, "amount", "killed"}。"""
    rng = rng or random.Random()
    cfg = be.load_config()["combat"]
    async with AsyncSessionLocal() as session:
        await _lock(session)
        pair = await _check_pair(session, human_id, bot_id)
        if isinstance(pair, str):
            await session.rollback()
            return {"outcome": "release", "amount": 0, "killed": False}
        human, bot = pair
        hname, bname, city = human.name, bot.name, human.current_city
        persona = await session.get(BotPersonality, bot_id)
        archetype = persona.archetype if persona else "憨直"
        protected = get_realm_index(human.realm) < get_realm_index(cfg["kill_protect_below"])
        can_kill = bool(cfg["can_kill_humans"]) and not protected
        outcome = be.captive_outcome(archetype, be.load_config(), can_kill=can_kill, rng=rng)
        amount = 0
        if outcome in ("rob", "kill"):
            amount = min(int(human.spirit_stones * cfg["captive_rob"]["share"]), cfg["captive_rob"]["cap"])
            if amount > 0 and await spend_stones(session, human_id, amount):
                await grant_stones(session, bot_id, amount)
            else:
                amount = 0
        killed = False
        if outcome == "kill":
            res = await session.execute(update(Player).where(Player.discord_id == human_id, Player.is_dead == False)  # noqa: E712
                                        .values(is_dead=True, lifespan=0))
            killed = res.rowcount == 1
            if killed:
                log.warning("机器人 %s(%s) 击杀了真人 %s", bot.name, bot_id, human_id)
        elif outcome == "rob" and amount == 0:
            outcome = "release"                             # 身上没钱可劫，只好放走
        await session.commit()
    if killed:
        await rumors.record_rumor("bot_kills_human", human_id, hname, target=bname, city=city)
    elif outcome == "rob":
        await rumors.record_rumor("bot_robs_human", human_id, hname, target=bname, city=city, amount=amount)
    return {"outcome": outcome, "amount": amount, "killed": killed}
