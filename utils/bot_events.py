"""机器人参与公共事件（U1「江湖百态」）：天降灵雨、兽潮守城、万宝楼拍卖。

用户 2026-10-11 的决定：
· **灵雨活动**：机器人参与，奖励和真人一样（和真人共用 `spirit_rain.grant_activity`，不另抄一份）；每人最多 2 次；
  不过给一道保险丝：每场事件机器人从『灵晶』拿到的灵石总量有上限（`activity_reward_budget_per_event`）；
· **兽潮守城**：机器人守城，**和真人一起排名领奖**（战力含机器人的档位加成）；
· **迁徙**：灵雨降临时 25% 的机器人赶往事件城，事件结束后回常驻城市；
· **万宝楼**：机器人按偏好和钱包竞拍，只用随身灵石、出价不超过起拍价的 3 倍、每场最多得 1 件。

所有数值在 data/bot_economy.json 的 public_events。机器人没有 Discord 账号，所以不发交互、直接在逻辑层行动；
整个模块出任何错都只记日志，绝不影响公共事件本身（调用方也各包了一层）。
"""

import asyncio
import json
import logging
import random
import time

from sqlalchemy import func, select, text, update

from utils import bot_economy as be
from utils import bot_chatter, bot_social, bot_ties
from utils.db_async import AsyncSessionLocal, BotPersonality, Player

log = logging.getLogger(__name__)

RAIN_ACTIVITIES = ("crystal", "enlighten", "temper")
MAX_RAIN_ACTIVITIES = 2                    # 和真人一样：每场最多 2 次非守城活动


async def _alive_bots(session, *, in_city: str | None = None, not_in_city: str | None = None) -> list[Player]:
    now = time.time()
    q = select(Player).where(Player.is_bot == True, Player.is_dead == False)       # noqa: E712
    rows = list((await session.execute(q.order_by(Player.discord_id))).scalars())
    out = []
    for p in rows:
        if p.cultivating_until and p.cultivating_until > now:
            continue                                         # 闭关 / 双修中的不打扰
        if in_city is not None and p.current_city != in_city:
            continue
        if not_in_city is not None and (p.current_city == not_in_city or p.current_city in be.WILD_NAMES):
            continue                                         # 在秘地历练的不被叫走
        out.append(p)
    return out


async def migrate_to_city(city: str, rng: random.Random | None = None) -> int:
    """事件降临：`migrate_share` 的机器人（在世、没在闭关、不在秘地）赶往事件城。返回迁走几个。"""
    rng, cfg = rng or random.Random(), be.load_config()["public_events"]
    async with AsyncSessionLocal() as session:
        total = await session.scalar(select(func.count()).select_from(Player)
                                     .where(Player.is_bot == True, Player.is_dead == False))  # noqa: E712
        movers = await _alive_bots(session, not_in_city=city)
        k = min(len(movers), int(round((total or 0) * cfg["migrate_share"])))
        chosen = [p.discord_id for p in rng.sample(movers, k)]
        if chosen:
            await session.execute(update(Player).where(Player.discord_id.in_(chosen)).values(current_city=city))
            await session.commit()
    return len(chosen)


STAT_COLUMNS = ("comprehension", "physique", "fortune", "bone", "soul")


def stat_cap(tier: str, cfg: dict) -> int:
    """机器人靠公共事件长属性点的上限：该档位生成时属性上限 + stat_cap_over_tier。
    灵雨每天一次，+1 属性点的机率累积下来会把机器人越养越强，破坏『用心真人对正常机器人战力比 ≥ 1.35』的校准。"""
    from utils.bot_world import TIER_SPECS
    return TIER_SPECS[tier]["stats"][1] + cfg["public_events"]["stat_cap_over_tier"]


async def _clamp_stats(uid: str, cap: int) -> None:
    async with AsyncSessionLocal() as session:
        await session.execute(text(
            "UPDATE players SET " + ", ".join(f"{c} = MIN({c}, :cap)" for c in STAT_COLUMNS) + " WHERE discord_id = :uid"),
            {"cap": cap, "uid": uid})
        await session.commit()


async def _join(event_id: str, uid: str, activity: str, joined_at: float) -> bool:
    """写参与记录。同一个 (事件, 人, 活动) 只会有一条。"""
    async with AsyncSessionLocal() as session:
        res = await session.execute(text(
            "INSERT OR IGNORE INTO public_event_participants (event_id, discord_id, joined_at, contribution, activity) "
            "VALUES (:eid, :uid, :now, 0, :act)"), {"eid": event_id, "uid": uid, "now": joined_at, "act": activity})
        await session.commit()
    return res.rowcount == 1


async def join_spirit_rain(event_id: str, city: str, beast_tide: bool, rng: random.Random | None = None) -> dict:
    """事件城里的机器人参与灵雨活动（和真人同一套奖励）；有兽潮的话一部分去守城。"""
    from utils.events.public.spirit_rain import grant_activity
    rng, cfg = rng or random.Random(), be.load_config()["public_events"]
    out = {"joined": 0, "activities": 0, "defenders": 0, "stones": 0, "skipped_budget": 0}
    budget = cfg["activity_reward_budget_per_event"]
    now = time.time()
    present = []                                              # 这场活动里碰了面的机器人（共同经历，会互相认识）
    async with AsyncSessionLocal() as session:
        bots = [{c.key: getattr(p, c.key) for c in p.__table__.columns} for p in await _alive_bots(session, in_city=city)]
        tiers = dict((await session.execute(select(BotPersonality.bot_id, BotPersonality.tier))).all())
    full = be.load_config()
    for bot in bots:
        uid = bot["discord_id"]
        try:
            took_part = False
            if rng.random() < cfg["join_chance"]:
                pool = [a for a in RAIN_ACTIVITIES if not (a == "temper" and bot["physique"] < 7)]
                for n, activity in enumerate(rng.sample(pool, min(MAX_RAIN_ACTIVITIES, len(pool)))):
                    if activity == "crystal" and budget <= 0:
                        out["skipped_budget"] += 1
                        continue
                    if not await _join(event_id, uid, activity, now + n):
                        continue
                    _, stones = await grant_activity(uid, activity, bot, event_id)
                    budget -= stones
                    out["stones"] += stones
                    out["activities"] += 1
                    took_part = True
            if beast_tide and rng.random() < cfg["defense_chance"]:
                if await _join(event_id, uid, "defense", now):
                    await grant_activity(uid, "defense", bot, event_id)
                    out["defenders"] += 1
                    took_part = True
            if took_part:
                await _clamp_stats(uid, stat_cap(tiers.get(uid) or "正常", full))
            out["joined"] += took_part
            if took_part:
                present.append(uid)
        except Exception:
            log.exception("机器人参与灵雨失败：%s", uid)
    await bot_ties.meet_group(present, "公共事件", rng, max_pairs=cfg.get("meet_pairs_per_event", 40))
    return out


async def on_spirit_rain_start(event_id: str, city: str, beast_tide: bool, rng: random.Random | None = None) -> dict:
    """灵雨降临：先迁徙，再让事件城里的机器人参与。出任何错都只记日志。"""
    try:
        moved = await migrate_to_city(city, rng)
        out = await join_spirit_rain(event_id, city, beast_tide, rng)
        out["migrated"] = moved
        await bot_chatter.queue_event(event_id, city, "before", beast_tide, rng)           # 在场的熟人说两句
        log.info("机器人参与灵雨 %s：%s", event_id, out)
        return out
    except Exception:
        log.exception("机器人参与灵雨失败：%s", event_id)
        return {}


async def send_home(event_id: str, city: str) -> int:
    """事件结束：参与过的机器人回常驻城市（本来就住在事件城的留下）。返回回家几个。"""
    async with AsyncSessionLocal() as session:
        ids = list((await session.execute(text(
            "SELECT DISTINCT ep.discord_id FROM public_event_participants ep JOIN players p ON ep.discord_id = p.discord_id "
            "WHERE ep.event_id = :eid AND p.is_bot = 1 AND p.current_city = :city"), {"eid": event_id, "city": city})).scalars())
        n = 0
        for uid in ids:
            home = await session.scalar(select(BotPersonality.home_city).where(BotPersonality.bot_id == uid))
            if home and home != city:
                await session.execute(update(Player).where(Player.discord_id == uid).values(current_city=home))
                n += 1
        await session.commit()
    return n


async def on_spirit_rain_end(event: dict) -> int:
    try:
        data = json.loads(event.get("data") or "{}")
        await bot_chatter.queue_event(event["event_id"], data.get("city", ""), "after", bool(data.get("beast_tide")))
        return await send_home(event["event_id"], data.get("city", ""))
    except Exception:
        log.exception("机器人回城失败：%s", event.get("event_id"))
        return 0


# ---- 万宝楼拍卖 -------------------------------------------------------------

def wants_lot(persona: dict | None, lot: dict, cfg: dict) -> bool:
    """这个机器人想不想要这件拍品：物品按喜好（类别 / 具体物品，讨厌的绝不拍）；装备 / 功法按性格原型。"""
    if persona is None:
        return False
    interest = cfg["public_events"]["auction"]["interest"]
    if lot["item_type"] == "equipment":
        return persona["archetype"] in interest["equipment"]
    if lot["item_type"] == "technique":
        return persona["archetype"] in interest["technique"]
    name, cat = lot["item_name"], bot_social.category_of(lot["item_name"])
    likes, dislikes = persona.get("likes", {}), persona.get("dislikes", {})
    if name in dislikes.get("items", []) or cat in dislikes.get("categories", []):
        return False
    return name in likes.get("items", []) or cat in likes.get("categories", [])


async def auction_candidates(auction_id: str, lot: dict, rng: random.Random) -> list[tuple[str, int]]:
    """愿意且出得起的机器人 [(id, 出价上限)]，随机取 bidders_per_lot 个；这场已经得标过的不再拍。"""
    cfg = be.load_config()
    au = cfg["public_events"]["auction"]
    async with AsyncSessionLocal() as session:
        rows = (await session.execute(
            select(Player.discord_id, Player.spirit_stones, BotPersonality)
            .join(BotPersonality, BotPersonality.bot_id == Player.discord_id)
            .where(Player.is_bot == True, Player.is_dead == False))).all()           # noqa: E712
        winners = set((await session.execute(text(
            "SELECT bidder_id FROM wanbao_lots WHERE auction_id = :aid AND status = 'sold'"), {"aid": auction_id})).scalars())
    out = []
    for uid, stones, pers in rows:
        if uid in winners or stones < au["min_carry"]:
            continue
        persona = {"archetype": pers.archetype, "likes": json.loads(pers.likes or "{}"),
                   "dislikes": json.loads(pers.dislikes or "{}")}
        if not wants_lot(persona, lot, cfg):
            continue
        max_bid = int(min(stones * au["carry_share"], lot["start_price"] * au["max_multiple"]))
        if max_bid >= lot["start_price"]:
            out.append((uid, max_bid))
    return rng.sample(out, min(len(out), au["bidders_per_lot"]))


async def _bot_bids(auction_id: str, lot_id: str, uid: str, max_bid: int, delays: list[float], sleep, rng) -> int:
    """一个机器人在这件拍品上按预定的时间点出价；返回成功出价几次。"""
    from utils.events.public.wanbao import get_current_lot, place_bid
    au = be.load_config()["public_events"]["auction"]
    done, last = 0, 0.0
    for at in delays:
        await sleep(max(0.0, at - last))
        last = at
        lot = await get_current_lot(auction_id)
        if not lot or lot["lot_id"] != lot_id:
            break                                            # 这件已经落槌
        if lot["bidder_id"] == uid:
            continue                                         # 现在领先的就是自己
        cur = lot["current_bid"] or 0
        amount = lot["start_price"] if not cur else max(cur + 1, int(cur * (1 + au["increment_pct"])))
        if amount > max_bid:
            break                                            # 超过自己的上限，认输
        ok, _ = await place_bid(auction_id, uid, amount)
        done += ok
    return done


async def auction_round(auction_id: str, lot: dict, window_secs: float, rng: random.Random | None = None,
                        sleep=asyncio.sleep) -> dict:
    """一件拍品开拍：挑几个愿意且出得起的机器人，各自在拍卖窗口里随机的时间点出价。
    调用方把它当后台任务发出去（`window_secs` = 这件拍品还剩多少秒）。出错只记日志。"""
    rng, au = rng or random.Random(), be.load_config()["public_events"]["auction"]
    try:
        bidders = await auction_candidates(auction_id, lot, rng)
        lo, hi = au["bid_window"]
        tasks = []
        for uid, max_bid in bidders:
            n = rng.randint(1, au["max_bids_per_lot"])
            delays = sorted(rng.uniform(lo, hi) * window_secs for _ in range(n))
            tasks.append(_bot_bids(auction_id, lot["lot_id"], uid, max_bid, delays, sleep, rng))
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for r in results:
            if isinstance(r, Exception):
                log.error("机器人竞拍出错", exc_info=r)
        return {"bidders": len(bidders), "bids": sum(r for r in results if isinstance(r, int))}
    except asyncio.CancelledError:
        raise
    except Exception:
        log.exception("机器人竞拍失败：%s", auction_id)
        return {"bidders": 0, "bids": 0}
