"""机器人的每日结算（U1「江湖百态」）。

每天对每个在世的机器人做一遍：**收入 → 修炼与寿元 → 日常开销 → 打工材料 → 突破 → 死亡清理**，最后补员。
参数在 data/bot_economy.json（来源与校准见 .gk/ISSUES.md「经济参数」「模拟结果」），公式在 utils/bot_economy.py，
离线模拟（scripts/sim_bots.py）用的是同一份，所以模拟里看到的就是这里会发生的。

**每天只结一次、崩了能续**：每个机器人在 `bot_personality.settled_day` 记着自己最后结算的日期。
一个机器人的『收入 / 修炼 / 开销 / 材料』是一个事务，事务里**先认领**（条件 UPDATE 把 settled_day 改成今天）——
认领和结算同生共死，中途出错整体回滚，下一轮自然再来；重复跑（两个循环、手动结算）只会有一个认领到。
突破**直接调用游戏里的突破逻辑**（do_single_breakthrough / handle_*_breakthrough），不另抄一份；
三道大关先从机器人账上扣丹药钱、发一颗丹，再走真人同样的流程。突破单独一个事务，出错只影响这一次突破。

一个机器人出错只记日志、不影响别的机器人（和闭关 / 采集结算同样的隔离，B24）。
"""

import json
import logging
import random
import time
from collections import Counter

from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from utils import bot_economy as be
from utils import bot_world, rumors
from utils import bot_grudges, bot_profile, bot_ties, bot_traits
from utils.bot_legends import make_legend
from utils.atomic import grant_item, increment_player, spend_stones
from utils.breakthrough_logic import (do_single_breakthrough, handle_huaying_breakthrough,
                                      handle_ningdan_breakthrough, handle_zhuji_breakthrough,
                                      load_breakthrough_state)
from utils.db_async import AsyncSessionLocal, BankAccount, BotPersonality, BotRaid, Equipment, Inventory, Player
from utils.inventory import get_inventory
from utils.realms import cultivation_needed, get_realm_index, next_realm

log = logging.getLogger(__name__)

PILL_HANDLERS = {"筑基丹": handle_zhuji_breakthrough, "凝丹丹": handle_ningdan_breakthrough,
                 "化婴丹": handle_huaying_breakthrough}
SUMMARY_KEYS = ("bots", "settled", "skipped", "errors", "income", "upkeep", "pills", "materials_value",
                "breakthroughs", "bt_failures", "gate_wait", "capped", "deaths", "ascended", "refilled", "wild_trips", "cleaned")
RAID_KEEP_DAYS = 3                                           # 打劫 / 击杀次数的记录只留最近几天


def today() -> str:
    return time.strftime("%Y-%m-%d")


async def _lock(session) -> None:
    """先做一次空写入拿写锁，之后的读 → 改 → 写才不会被并发打断。"""
    await session.execute(update(Player).where(Player.discord_id == "").values(discord_id=""))


async def _pay_from_wealth(session, bot_id: str, price: int) -> int | None:
    """先扣随身、不够的从钱庄扣。成功返回从随身扣了多少（退款用），钱不够返回 None（什么都没扣）。"""
    stones = await session.scalar(select(Player.spirit_stones).where(Player.discord_id == bot_id)) or 0
    bank = await session.scalar(select(BankAccount.demand_balance).where(BankAccount.discord_id == bot_id)) or 0
    from_carry = min(stones, price)
    from_bank = price - from_carry
    if from_bank > bank:
        return None
    if from_carry and not await spend_stones(session, bot_id, from_carry):
        return None
    if from_bank:
        res = await session.execute(
            update(BankAccount)
            .where(BankAccount.discord_id == bot_id, BankAccount.demand_balance >= from_bank)
            .values(demand_balance=BankAccount.demand_balance - from_bank))
        if res.rowcount != 1:
            await session.rollback()
            return None
    return from_carry


async def _settle_economy(bot_id: str, tier: str, archetype: str, day: str, force: bool, cfg: dict, scale: float,
                          rng: random.Random, budget: dict, sm: Counter) -> bool | None:
    """收入 / 修炼 / 寿元 / 开销 / 材料，一个事务。返回 True = 这个机器人今天寿元耗尽，None = 没认领到（已结过 / 不存在）。"""
    async with AsyncSessionLocal() as session:
        await _lock(session)
        claim = update(BotPersonality).where(BotPersonality.bot_id == bot_id).values(settled_day=day)
        if not force:
            claim = claim.where(BotPersonality.settled_day != day)
        if (await session.execute(claim)).rowcount != 1:
            await session.rollback()
            return None
        player = await session.get(Player, bot_id)
        if player is None or player.is_dead or not player.is_bot:
            await session.rollback()
            return None

        # 收入：按全服上限缩放，随身 / 钱庄按性格分成（钱庄无利息，机器人不走钱庄的取款逻辑）
        paid = int(round(be.daily_income(tier, cfg, rng) * scale))
        carry_part, bank_part = be.split_income(paid, archetype, cfg, rng)
        if carry_part:
            await increment_player(session, bot_id, spirit_stones=carry_part)
        if bank_part:
            await session.execute(
                sqlite_insert(BankAccount)
                .values(discord_id=bot_id, demand_balance=bank_part, demand_deposited_at=time.time())
                .on_conflict_do_update(index_elements=["discord_id"],
                                       set_={"demand_balance": BankAccount.demand_balance + bank_part}))
        sm["income"] += paid

        # 修炼：只在『活跃』的游戏年里涨修为、耗寿元
        years = be.active_years(tier, cfg, rng)
        need = cultivation_needed(player.realm)
        stats = {"comprehension": player.comprehension, "spirit_root_type": player.spirit_root_type}
        player.cultivation = max(player.cultivation, min(player.cultivation + be.cultivation_gain(years, stats), need * 2))
        player.lifespan = player.lifespan - years

        # 日常开销：随身灵石的一部分，花掉就消失
        carry_now = await session.scalar(select(Player.spirit_stones).where(Player.discord_id == bot_id)) or 0
        spend = be.spend_amount(carry_now, archetype, cfg)
        if spend and await spend_stones(session, bot_id, spend):
            sm["upkeep"] += spend

        # 材料：打工掉落（打折），受全服每日价值上限约束；每种材料只留 keep_per_item 件，多的当作用掉
        for name in be.material_roll(player.realm, cfg, rng):
            value = be.item_value(name)
            if value > budget["left"]:
                continue
            budget["left"] -= value
            sm["materials_value"] += value
            await grant_item(session, bot_id, name, 1)
        keep = cfg["materials"]["keep_per_item"]
        await session.execute(update(Inventory).where(Inventory.discord_id == bot_id, Inventory.quantity > keep)
                              .values(quantity=keep))
        # 装备：守城 / 拍卖会给机器人发装备，机器人不穿，只留最好的 keep_equipment 件（按品阶），多的当作卖掉了
        keep_eq = cfg["materials"]["keep_equipment"]
        eq_ids = list((await session.execute(select(Equipment.equip_id).where(Equipment.discord_id == bot_id)
                                              .order_by(Equipment.tier.desc(), Equipment.equip_id))).scalars())
        if len(eq_ids) > keep_eq:
            await session.execute(delete(Equipment).where(Equipment.equip_id.in_(eq_ids[keep_eq:])))
        dead = player.lifespan <= 0

        # 位置：去秘地历练一天（让玩家有机会在秘地遇到它们），第二天回常驻城市
        persona = await session.get(BotPersonality, bot_id)
        if not persona.home_city and player.current_city not in be.WILD_NAMES:
            persona.home_city = player.current_city          # 老机器人补上常驻城市
        if not persona.traits:                               # 老机器人补上说话特质（按 id 做种子，可复现）
            persona.traits = json.dumps(bot_traits.roll_traits(archetype, persona.talk, random.Random(f"{bot_id}:traits")),
                                        ensure_ascii=False)
        if not persona.profile:                              # 老机器人补上行为画像（同样按 id 做种子）
            origin = (json.loads(persona.traits) if persona.traits else {}).get("origin")
            persona.profile = json.dumps(bot_profile.roll_profile(archetype, origin, random.Random(f"{bot_id}:profile")))
        if tier == "天骄" and not persona.epithet:           # 老天骄补上称号和背景
            persona.epithet, persona.backstory = make_legend(archetype, persona.home_city or player.current_city,
                                                             random.Random(bot_id))
        if player.current_city in be.WILD_NAMES:
            player.current_city = persona.home_city or player.current_city
        elif not dead and not (player.cultivating_until and player.cultivating_until > time.time()):
            if (region := be.pick_wild_trip(player.realm, cfg, rng)):
                player.current_city = region
                sm["wild_trips"] += 1
        await session.commit()
    return dead


async def _set_capped_days(bot_id: str, days: int | None) -> int:
    """天骄『顶在天花板上』的连续天数：None = 清零，否则 +1。返回新的天数。"""
    async with AsyncSessionLocal() as session:
        await _lock(session)
        value = BotPersonality.capped_days + 1 if days is not None else 0
        await session.execute(update(BotPersonality).where(BotPersonality.bot_id == bot_id).values(capped_days=value))
        n = await session.scalar(select(BotPersonality.capped_days).where(BotPersonality.bot_id == bot_id))
        await session.commit()
    return n or 0


async def _try_ascend(bot_id: str, tier: str, player: dict, cfg: dict, rng: random.Random) -> bool:
    """天骄顶在天花板上够了日子，每天有一定几率飞升。飞升的传闻在这里记（人还在，查得到称号）。"""
    if tier != "天骄":
        return False
    days = await _set_capped_days(bot_id, 1)
    tj = cfg["tianjiao"]
    if days < tj["ascend_after_days"] or rng.random() >= tj["ascend_chance"]:
        return False
    epithet = await rumors.tianjiao_epithet(bot_id)
    await rumors.record_player_rumor("tianjiao_ascend", bot_id, epithet=epithet or player["name"], realm=player["realm"])
    return True


async def _breakthrough(bot_id: str, tier: str, cfg: dict, ceiling_idx: int, rng: random.Random, sm: Counter) -> str | None:
    """尝试一次突破。返回 "dead"（死了）/ "ascended"（天骄飞升）/ None。"""
    can_bt, player = await load_breakthrough_state(bot_id)
    if not can_bt or not player:
        if tier == "天骄":
            await _set_capped_days(bot_id, None)
        return None
    nxt = next_realm(player["realm"])
    if not nxt or get_realm_index(nxt) > ceiling_idx:
        sm["capped"] += 1                                    # 到了天花板：攒着修为等真人先走一步
        return "ascended" if await _try_ascend(bot_id, tier, player, cfg, rng) else None
    if tier == "天骄":
        await _set_capped_days(bot_id, None)
    if player.get("cultivating_until") and player["cultivating_until"] > time.time():
        return None                                          # 正在闭关 / 双修，不打扰

    gate = be.gate_price(player["realm"], cfg)
    refund = None
    if gate:
        pill, price = gate
        async with AsyncSessionLocal() as session:
            await _lock(session)
            refund = await _pay_from_wealth(session, bot_id, price)
            if refund is None:
                await session.rollback()
                sm["gate_wait"] += 1                         # 买不起丹，继续等
                return None
            await grant_item(session, bot_id, pill, 1)
            await session.commit()
        result = await PILL_HANDLERS[pill](bot_id, True)
        if (await get_inventory(bot_id)).get(pill, 0) > 0:   # 没走到消耗丹药那一步（状态变了）：丹和钱都退回
            async with AsyncSessionLocal() as session:
                await _lock(session)
                await session.execute(update(Inventory).where(Inventory.discord_id == bot_id, Inventory.item_id == pill)
                                      .values(quantity=Inventory.quantity - 1))
                await session.execute(delete(Inventory).where(Inventory.discord_id == bot_id, Inventory.quantity <= 0))
                await increment_player(session, bot_id, spirit_stones=refund)
                if price - refund:
                    await session.execute(update(BankAccount).where(BankAccount.discord_id == bot_id)
                                          .values(demand_balance=BankAccount.demand_balance + price - refund))
                await session.commit()
        else:
            sm["pills"] += price
    else:
        result = await do_single_breakthrough(bot_id, player)

    if not result.get("success"):
        log.info("机器人 %s 突破未能进行：%s", bot_id, result.get("message"))
        return None
    if result.get("breakthrough"):
        sm["breakthroughs"] += 1
        return None
    sm["bt_failures"] += 1
    return "dead" if result.get("is_dead") else None


async def _settle_bot(bot_id: str, tier: str, archetype: str, day: str, force: bool, cfg: dict, scale: float,
                      ceiling_idx: int, rng: random.Random, budget: dict, sm: Counter) -> None:
    dead = await _settle_economy(bot_id, tier, archetype, day, force, cfg, scale, rng, budget, sm)
    if dead is None:
        sm["skipped"] += 1
        return
    sm["settled"] += 1
    fate = None
    if dead:
        await rumors.on_bot_old_age(bot_id)                  # 寿元耗尽（突破致死的传闻在突破逻辑里记）；天骄用专门的种类
        fate = "dead"
    else:
        fate = await _breakthrough(bot_id, tier, cfg, ceiling_idx, rng, sm)
    if fate:
        await bot_world.remove_bots([bot_id])                # 遗产随人消失；天骄离场会留一个空缺，补员时补新秀
        sm["ascended" if fate == "ascended" else "deaths"] += 1


async def _cleanup(day: str) -> int:
    """被玩家击杀的机器人（标了坐化、但清理没做完）补清；顺手删掉过期的打劫次数记录。返回清走几个。"""
    async with AsyncSessionLocal() as session:
        ids = list((await session.execute(select(Player.discord_id).where(Player.is_bot == True, Player.is_dead == True))).scalars())  # noqa: E712
        t = time.mktime(time.strptime(day, "%Y-%m-%d")) - RAID_KEEP_DAYS * 86400
        await session.execute(delete(BotRaid).where(BotRaid.day < time.strftime("%Y-%m-%d", time.localtime(t))))
        await session.commit()
    return (await bot_world.remove_bots(ids))["removed"] if ids else 0


async def _refill(day: str, force: bool, cfg: dict, rng: random.Random, sm: Counter) -> None:
    """补员：在世人数低于目标时补新人，每天最多补目标的 refill_rate（至少 1 人）；每天只补一次。"""
    async with AsyncSessionLocal() as session:
        await _lock(session)
        target = int(await bot_world.get_state(session, "target", "0") or 0)
        alive = await session.scalar(select(func.count()).select_from(Player)
                                     .where(Player.is_bot == True, Player.is_dead == False))  # noqa: E712
        if target <= alive or (not force and await bot_world.get_state(session, "refill_day") == day):
            await session.rollback()
            return
        count = min(target - alive, be.refill_cap(target, cfg))
        await bot_world.set_state(session, "refill_day", day)
        await session.commit()
    res = await bot_world.generate_bots(count, rng, track_target=False, fill_vacancies=True)
    if res["ok"]:
        sm["refilled"] += len(res["created"])
    else:
        log.warning("机器人补员失败：%s", res["reason"])


async def run_settlement(*, force: bool = False, rng: random.Random | None = None) -> dict:
    """做一次每日结算，返回汇总。没有要结的就是空操作。

    `force`：已经结过的也再结一遍（会再发一次收入 / 再过一天），只给管理员手动用。
    """
    cfg, rng, day = be.load_config(), rng or random.Random(), today()
    sm = Counter({k: 0 for k in SUMMARY_KEYS})
    sm["cleaned"] = await _cleanup(day)
    async with AsyncSessionLocal() as session:
        ceiling_idx = await bot_world.current_ceiling_index(session)
        rows = (await session.execute(
            select(Player.discord_id, BotPersonality.tier, BotPersonality.archetype, BotPersonality.settled_day)
            .join(BotPersonality, BotPersonality.bot_id == Player.discord_id)
            .where(Player.is_bot == True, Player.is_dead == False)       # noqa: E712
            .order_by(Player.discord_id))).all()
    due = [(i, t, a) for i, t, a, d in rows if force or d != day]
    sm["bots"] = len(due)
    scale = be.income_scale([t for _, t, _ in due], cfg)
    budget = {"left": cfg["materials"]["daily_cap_value_per_bot"] * len(due)}
    for bot_id, tier, archetype in due:
        try:
            await _settle_bot(bot_id, tier, archetype, day, force, cfg, scale, ceiling_idx, rng, budget, sm)
        except Exception:
            sm["errors"] += 1
            log.exception("机器人每日结算失败：%s", bot_id)
    try:
        await _refill(day, force, cfg, rng, sm)
    except Exception:
        sm["errors"] += 1
        log.exception("机器人补员失败")
    out = dict(sm)
    out["social"] = await bot_ties.social_day(day, rng, force=force)
    out["grudges"] = await bot_grudges.grudge_day(day, rng, force=force)         # 仇恨：续期 / 潜伏 / 淡去        # 一天的社交：碰面、反目、和解、结拜
    out["ceiling_index"] = ceiling_idx
    if sm["settled"] or sm["refilled"] or sm["errors"]:
        log.info("机器人每日结算：%s", out)
    return out
