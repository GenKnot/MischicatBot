"""机器人主动搭话（U1·江湖百态 P5）：在有『小契机』的时候，熟人机器人 @ 玩家说一句。

用户 2026-10-12 的设计 / 我的默认：
· 不凭空骚扰，每次都要有契机 —— ① 玩家到了有熟人的城市（概率）② 玩家突破大境界（真心 / 酸 / 不服 / 觊觎四种态度）
  ③ 公共事件开始 / 结束 ④ 玩家打劫 / 废修为之后几分钟，当事机器人和替它出头的朋友放话、还有劝架的。
· **每人每天最多 3 条**，同一个机器人对同一个玩家有冷却；很久没上线的玩家不打扰；玩家可以一键**屏蔽**（只屏蔽搭话，仇恨和拦路照常）。
· 玩家用按钮回应（热情 / 客气 / 淡淡 / 冷淡），好感随之小幅变化，机器人再回一句。
· 台词来自条件化文案库（utils/bot_chatter_lines.py）：按 性格 / 好感 / 关系 / 阵营标签 / 出身 / 星座 / 内向外向 / 境界差 / 态度 / 事件 挑，再过一遍说话特质改写。

即时的搭话（到城）走调用方的 send；延迟的（道贺、事件、冲突）先入队 `chatter_queue`，由 cogs/chatter.py 到点发到传闻频道。
所有入队 / 判定都是旁路：出错只记 warning，不影响主流程。
"""

import json
import logging
import random
import time
import uuid
from functools import lru_cache
from pathlib import Path

from sqlalchemy import select, update

from utils import bot_dialogue as bd
from utils import bot_chatter_lines as lines
from utils import bot_profile, bot_ties, bot_voice
from utils.bots import is_bot_id
from utils.db_async import (AsyncSessionLocal, BotPersonality, BotRelation, BotTie, ChatterPair, ChatterQueue, ChatterState,
                            Player, PublicEventParticipant)
from utils.realms import REALMS, major_realm
from utils import settings_hub

log = logging.getLogger(__name__)

_PATH = Path(__file__).resolve().parent.parent / "data" / "bot_chatter_config.json"
MAJORS = list(dict.fromkeys(major_realm(r) for r in REALMS))
REPLY_SCENES = {"warm": "reply_warm", "ok": "reply_ok", "neutral": "reply_neutral", "cold": "reply_cold"}
HOUR = 3600


@lru_cache(maxsize=1)
def _load() -> dict:
    return settings_hub.read(_PATH)


def load() -> dict:
    return _load()


def reload() -> None:
    _load.cache_clear()


def validate(cfg: dict) -> list[str]:
    errors = []
    if cfg.get("daily_cap", 0) < 1:
        errors.append("daily_cap 至少 1")
    for k in ("pair_cooldown_hours", "active_within_hours"):
        if cfg.get(k, -1) < 0:
            errors.append(f"{k} 不能为负")
    a = cfg.get("arrive", {})
    if set(a.get("chance_by_relation", {})) != set(lines.RELATIONS) or not all(0 <= v <= 1 for v in a.get("chance_by_relation", {}).values()):
        errors.append("arrive.chance_by_relation 应覆盖所有关系，概率在 0~1")
    if set(a.get("chance_by_tier", {})) != set(bd.TIERS) or not all(0 <= v <= 1 for v in a.get("chance_by_tier", {}).values()):
        errors.append("arrive.chance_by_tier 应覆盖所有好感档位，概率在 0~1")
    c = cfg.get("congrats", {})
    if set(c.get("relation_chance", {})) != set(lines.RELATIONS) or not all(0 <= v <= 1 for v in c.get("relation_chance", {}).values()):
        errors.append("congrats.relation_chance 应覆盖所有关系，概率在 0~1")
    if not 0 <= c.get("stranger_chance", -1) <= 1 or not (c.get("stranger_max") is None or c.get("stranger_max", -1) >= 0):
        errors.append("congrats.stranger_chance 0~1；stranger_max 非负或 null")
    for k in ("congrats", "event"):
        lo, hi = cfg.get(k, {}).get("delay_seconds", [1, 0])
        if not 0 <= lo <= hi:
            errors.append(f"{k}.delay_seconds 应是 [最小, 最大]")
    cf = cfg.get("conflict", {})
    lo, hi = cf.get("delay_minutes", [1, 0])
    if not 0 <= lo <= hi:
        errors.append("conflict.delay_minutes 应是 [最小, 最大]")
    for k in ("max_messages", "mediators_max"):
        if k not in cf or not (cf[k] is None or cf[k] >= 0):
            errors.append(f"conflict.{k} 应是 null（不限）或非负整数")
    for section in ("arrive", "congrats", "conflict"):
        if cfg.get(section, {}).get("max_lines", 0) < 1:
            errors.append(f"{section}.max_lines 至少 1")
    if cfg.get("hostile_favor", 1) > 0 or set(cfg.get("familiar_weight", {})) != {"strength_div", "favor_div", "hostile_factor"}:
        errors.append("hostile_favor 应 ≤ 0；familiar_weight 要有 strength_div / favor_div / hostile_factor")
    if set(cfg.get("mediator", {})) != {"kindness_min", "lawful_min", "extra_delay_seconds"}:
        errors.append("mediator 要有 kindness_min / lawful_min / extra_delay_seconds")
    q = cfg.get("queue", {})
    if q.get("claim_limit", 0) < 1 or q.get("keep_days", -1) < 0:
        errors.append("queue.claim_limit 应 ≥ 1，keep_days 不能为负")
    if set(cfg.get("reply", {})) != set(REPLY_SCENES):
        errors.append(f"reply 应有 {sorted(REPLY_SCENES)}")
    return errors


def day_of(now: float | None = None) -> str:
    return time.strftime("%Y-%m-%d", time.localtime(now or time.time()))


def major_index(realm: str) -> int:
    return MAJORS.index(major_realm(realm))


def realm_gap(bot_realm: str, player_realm: str) -> str:
    d = major_index(bot_realm) - major_index(player_realm)
    return "higher" if d > 0 else "lower" if d < 0 else "equal"


# ---- 态度（道贺） -----------------------------------------------------------

def attitude_weights(kindness: int, pride: int, greed: int, vengeful: int, tier: str, relation: str, gap: str,
                     cfg: dict | None = None) -> dict[str, float]:
    """道贺时四种态度的权重：真心（善良、交情深、有结拜 / 朋友）/ 酸（好胜、对头、境界不比你高）/ 不服（好胜、记仇、境界不低于你）/ 觊觎（贪婪、不熟的人）。"""
    a = (cfg or load())["attitude"]
    close = tier in ("熟识", "至交")
    bonded = relation in ("结拜", "同门", "朋友")
    return {
        "真心": a["sincere_base"] + a["sincere_kindness"] * kindness / 50 + (a["sincere_close_tier"] if close else 0) + (a["sincere_bond"] if bonded else 0),
        "酸": a["sour_pride"] * pride / 50 * (1.0 if gap in ("lower", "equal") else a["sour_gap_other"]) + (a["sour_hostile"] if tier == "仇视" else 0),
        "不服": a["defiant_pride"] * pride / 50 * (1.0 if gap in ("equal", "higher") else a["defiant_gap_other"]) + a["defiant_vengeful"] * vengeful / 50,
        "觊觎": a["covet_greed"] * greed / 50 + (a["covet_stranger"] if tier in ("陌生", "仇视") else 0) * (a["covet_bonded_factor"] if bonded else 1.0),
    }


# ---- 状态：屏蔽 / 每日上限 / 冷却 -------------------------------------------

async def is_muted(player_id: str) -> bool:
    async with AsyncSessionLocal() as session:
        row = await session.get(ChatterState, player_id)
        return bool(row and row.muted)


async def set_muted(player_id: str, muted: bool) -> None:
    async with AsyncSessionLocal() as session:
        await session.execute(update(Player).where(Player.discord_id == "").values(discord_id=""))
        row = await session.get(ChatterState, player_id)
        if row is None:
            session.add(ChatterState(player_id=player_id, day="", count=0, muted=muted))
        else:
            row.muted = muted
        await session.commit()


async def gate(player_id: str, bot_id: str | None, now: float, cfg: dict | None = None) -> str | None:
    """不该搭话的原因（None = 可以）：muted / cap / pair / inactive / player。"""
    cfg = cfg or load()
    async with AsyncSessionLocal() as session:
        p = await session.get(Player, player_id)
        if p is None or p.is_bot or p.is_dead:
            return "player"
        if now - p.last_active > cfg["active_within_hours"] * HOUR:
            return "inactive"
        st = await session.get(ChatterState, player_id)
        if st is not None:
            if st.muted:
                return "muted"
            if st.day == day_of(now) and st.count >= cfg["daily_cap"]:
                return "cap"
        if bot_id:
            pair = await session.get(ChatterPair, (player_id, bot_id))
            if pair is not None and now - pair.last_at < cfg["pair_cooldown_hours"] * HOUR:
                return "pair"
    return None


async def record(player_id: str, bot_ids, now: float) -> None:
    """记一次已送达（一次搭话事件，不管几个人同时说话）：今日计数 +1，每个说话的机器人和这个玩家的冷却从现在开始。"""
    ids = [bot_ids] if isinstance(bot_ids, str) else list(bot_ids)
    day = day_of(now)
    async with AsyncSessionLocal() as session:
        await session.execute(update(Player).where(Player.discord_id == "").values(discord_id=""))
        st = await session.get(ChatterState, player_id)
        if st is None:
            session.add(ChatterState(player_id=player_id, day=day, count=1, muted=False))
        elif st.day != day:
            st.day, st.count = day, 1
        else:
            st.count += 1
        for bot_id in ids:
            pair = await session.get(ChatterPair, (player_id, bot_id))
            if pair is None:
                session.add(ChatterPair(player_id=player_id, bot_id=bot_id, last_at=now))
            else:
                pair.last_at = now
        await session.commit()


# ---- 上下文与台词 -----------------------------------------------------------

async def build_context(player_id: str, bot_id: str, extra: dict | None = None) -> dict | None:
    """挑台词用的上下文：机器人的性格 / 特质 / 画像标签 + 它和这个玩家的好感档位 / 关系 / 境界差。机器人或玩家不存在返回 None。"""
    from utils.bot_social import favor_tier
    async with AsyncSessionLocal() as session:
        bot, player = await session.get(Player, bot_id), await session.get(Player, player_id)
        persona = await session.get(BotPersonality, bot_id)
        rel = await session.get(BotRelation, (player_id, bot_id))
        a, b = bot_ties.pair(player_id, bot_id)
        tie = await session.get(BotTie, (a, b))
    if bot is None or player is None or persona is None:
        return None
    traits = json.loads(persona.traits) if persona.traits else {}
    profile = json.loads(persona.profile) if persona.profile else None
    ctx = {"archetype": persona.archetype, "tier": favor_tier(rel.favor if rel else 0), "relation": tie.kind if tie else "无",
           "tags": bot_profile.tags(persona.kindness, profile), "origin": traits.get("origin"), "zodiac": traits.get("zodiac"),
           "introversion": traits.get("introversion"), "realm_gap": realm_gap(bot.realm, player.realm),
           "_bot_name": bot.name, "_bot_realm": bot.realm, "_player_name": player.name, "_traits": traits or None,
           "_kindness": persona.kindness, "_pride": persona.pride, "_greed": persona.greed, "_profile": profile}
    ctx.update(extra or {})
    return ctx


def render(scene: str, ctx: dict, fmt: dict | None = None, rng=None) -> str | None:
    """挑一句、过一遍说话特质、填占位符。库里没有匹配的返回 None。"""
    rng = rng or random.Random()
    template = lines.pick(scene, ctx, rng)
    if template is None:
        return None
    if ctx.get("_traits"):
        template = bot_voice.style(template, ctx["_traits"], scene, ctx["tier"], rng)
    return bd.fill(template, player=ctx["_player_name"], bot=ctx["_bot_name"], **(fmt or {}))


async def compose(scene: str, player_id: str, bot_id: str, fmt: dict | None = None, extra_ctx: dict | None = None, rng=None) -> dict | None:
    ctx = await build_context(player_id, bot_id, extra_ctx)
    if ctx is None:
        return None
    line = render(scene, ctx, fmt, rng)
    if not line:
        return None
    return {"scene": scene, "line": line, "bot_id": bot_id, "bot_name": ctx["_bot_name"], "bot_realm": ctx["_bot_realm"],
            "player_id": player_id, "tier": ctx["tier"]}


# ---- 熟人 -------------------------------------------------------------------

async def familiars(player_id: str) -> dict[str, dict]:
    """玩家的熟人机器人 {bot_id: {"relation", "strength", "favor"}}：有关系网上的关系、或有过好感记录的。"""
    out: dict[str, dict] = {}
    for t in await bot_ties.ties_of(player_id):
        if is_bot_id(t["other"]):
            out[t["other"]] = {"relation": t["kind"], "strength": t["strength"], "favor": 0}
    async with AsyncSessionLocal() as session:
        for r in (await session.execute(select(BotRelation).where(BotRelation.player_id == player_id))).scalars():
            d = out.setdefault(r.bot_id, {"relation": "无", "strength": 0, "favor": 0})
            d["favor"] = r.favor
    return out


def familiar_weight(info: dict, cfg: dict | None = None) -> float:
    cfg = cfg or load()
    fw = cfg["familiar_weight"]
    w = 1 + info["strength"] / fw["strength_div"] + max(info["favor"], 0) / fw["favor_div"]
    return w * (fw["hostile_factor"] if info["favor"] <= cfg["hostile_favor"] else 1.0)


# ---- 一次搭话事件里的多个说话人 ---------------------------------------------

def group_payload(entries: list[dict], max_lines: int) -> dict | None:
    """把同一次事件里的多个说话人合并成一条消息：第一位是『主说话人』（回应按钮、化解按钮都对它），最多展示 max_lines 行，其余写『另有 N 位』。"""
    if not entries:
        return None
    primary = entries[0]
    shown = entries[:max_lines]
    return {**primary, "entries": [{k: e[k] for k in ("bot_id", "bot_name", "bot_realm", "line")} for e in shown],
            "more": len(entries) - len(shown), "all_bot_ids": [e["bot_id"] for e in entries]}


def arrive_chance(relation: str, favor: int, cfg: dict) -> float:
    """到城时一个熟人迎上来的概率：取『关系』和『好感档位』里较大的一个 —— 很熟的几乎必来，不熟的才可能不理你。"""
    from utils.bot_social import favor_tier
    a = cfg["arrive"]
    return max(a["chance_by_relation"].get(relation, 0.0), a["chance_by_tier"].get(favor_tier(favor), 0.0))


async def bots_in_city(city: str) -> list[str]:
    """某座城里在世的机器人 ID。"""
    async with AsyncSessionLocal() as session:
        return list((await session.execute(select(Player.discord_id).where(
            Player.is_bot == True, Player.is_dead == False, Player.current_city == city))).scalars())      # noqa: E712


# ---- 到城（即时） -----------------------------------------------------------

async def maybe_arrive(player_id: str, city: str, rng=None, now: float | None = None) -> dict | None:
    """玩家到了 city：那里的每个熟人各自按熟悉程度掷骰，来的一起说话（合并成一条消息）。返回已生成的台词（还没记账），没有人说话返回 None。旁路。"""
    rng, now, cfg = rng or random.Random(), now or time.time(), load()
    try:
        if await gate(player_id, None, now, cfg):
            return None
        fam = await familiars(player_id)
        if not fam:
            return None
        async with AsyncSessionLocal() as session:
            here = set((await session.execute(select(Player.discord_id).where(
                Player.discord_id.in_(list(fam)), Player.is_bot == True, Player.is_dead == False, Player.current_city == city))).scalars())   # noqa: E712
        speakers = [b for b in here if await gate(player_id, b, now, cfg) is None
                    and rng.random() < arrive_chance(fam[b]["relation"], fam[b]["favor"], cfg)]
        speakers.sort(key=lambda b: -familiar_weight(fam[b]))
        entries = []
        for b in speakers:
            e = await compose("chatter_arrive", player_id, b, {"city": city}, rng=rng)
            if e:
                entries.append(e)
        return group_payload(entries, cfg["arrive"]["max_lines"])
    except Exception:
        log.warning("到城搭话失败：%s %s", player_id, city, exc_info=True)
        return None


# ---- 入队（延迟发送） -------------------------------------------------------

async def enqueue(player_id: str, speaker_id: str, scene: str, vars: dict | None, ctx: dict | None, delay: float,
                  now: float | None = None, group: str | None = None) -> str:
    """排一条延迟发送的搭话。`group` 相同（且玩家、场景相同、同时到点）的会合并成一条消息，多个人一起说话。"""
    now = now or time.time()
    qid = uuid.uuid4().hex[:16]
    async with AsyncSessionLocal() as session:
        session.add(ChatterQueue(id=qid, player_id=player_id, speaker_id=speaker_id, scene=scene,
                                 fmt=json.dumps({"vars": vars or {}, "ctx": ctx or {}, "group": group or ""}, ensure_ascii=False), due_at=now + delay))
        await session.commit()
    return qid


async def alive_bots(ids) -> dict[str, Player]:
    ids = list(ids)
    if not ids:
        return {}
    async with AsyncSessionLocal() as session:
        return {r.discord_id: r for r in (await session.execute(select(Player).where(
            Player.discord_id.in_(ids), Player.is_bot == True, Player.is_dead == False))).scalars()}      # noqa: E712


async def on_breakthrough(player: dict, result: dict, rng=None, now: float | None = None) -> int:
    """玩家刚突破（player 是突破前的字典）：大境界成功的话——认识你的人基本都会来道贺（按关系概率，态度由性格决定：真心 / 酸 / 不服 / 觊觎），
    人数不设上限；不认识的人最多 stranger_max 个。同一次突破的道贺合并成一条消息。返回入队条数。旁路。"""
    rng, now, cfg = rng or random.Random(), now or time.time(), load()
    try:
        if not result.get("breakthrough") or major_realm(result["new_realm"]) == major_realm(result["old_realm"]):
            return 0
        pid, city = player["discord_id"], player.get("current_city", "")
        ccfg = cfg["congrats"]
        fam = await familiars(pid)
        alive = await alive_bots(fam)
        group, delay, n = uuid.uuid4().hex[:8], rng.uniform(*ccfg["delay_seconds"]), 0
        speakers = []
        for bot_id in sorted(fam, key=lambda b: -familiar_weight(fam[b])):
            info = fam[bot_id]
            if bot_id not in alive:
                continue
            if alive[bot_id].current_city != city and info["relation"] not in ("结拜", "同门"):      # 兄弟不在同城也会捎话
                continue
            p = ccfg["relation_chance"][info["relation"]]
            if info["favor"] <= cfg["hostile_favor"] and info["relation"] == "无":
                p = ccfg["relation_chance"]["仇敌"]
            if rng.random() < p:
                speakers.append(bot_id)
        if ccfg["stranger_max"] != 0:                              # 不认识你的人：同城里零星几个
            async with AsyncSessionLocal() as session:
                crowd = [r for r in (await session.execute(select(Player.discord_id).where(
                    Player.is_bot == True, Player.is_dead == False, Player.current_city == city))).scalars() if r not in fam]   # noqa: E712
            rng.shuffle(crowd)
            strangers = [b for b in crowd if rng.random() < ccfg["stranger_chance"]]
            speakers += strangers[:ccfg["stranger_max"]] if ccfg["stranger_max"] is not None else strangers
        for bot_id in speakers:
            ctx = await build_context(pid, bot_id)
            if ctx is None:
                continue
            w = attitude_weights(ctx["_kindness"], ctx["_pride"], ctx["_greed"], (ctx["_profile"] or {}).get("vengeful", 50),
                                 ctx["tier"], ctx["relation"], ctx["realm_gap"], cfg)
            attitude = rng.choices(list(w), weights=list(w.values()))[0]
            await enqueue(pid, bot_id, "chatter_congrats", {"realm": result["new_realm"]}, {"attitude": attitude}, delay, now, group)
            n += 1
        return n
    except Exception:
        log.warning("道贺入队失败", exc_info=True)
        return 0


async def queue_event(event_id: str, city: str, when: str, beast_tide: bool, rng=None, now: float | None = None) -> int:
    """公共事件（灵雨，可能带兽潮）开始 / 结束：在场的机器人和参与的熟人玩家配几对，各说一句。when：before / after。"""
    rng, now, cfg = rng or random.Random(), now or time.time(), load()
    try:
        ecfg = cfg["event"]
        if rng.random() >= ecfg[f"{when}_chance"]:
            return 0
        async with AsyncSessionLocal() as session:
            if when == "after":                                    # 结束后：事件里出过力的玩家；开始时：还没人报名，用城里在场的玩家
                humans = list((await session.execute(select(PublicEventParticipant.discord_id).distinct().join(
                    Player, Player.discord_id == PublicEventParticipant.discord_id).where(
                    PublicEventParticipant.event_id == event_id, Player.is_bot == False))).scalars())     # noqa: E712
            else:
                humans = list((await session.execute(select(Player.discord_id).where(
                    Player.is_bot == False, Player.is_dead == False, Player.current_city == city))).scalars())  # noqa: E712
            bots = list((await session.execute(select(Player.discord_id).where(
                Player.is_bot == True, Player.is_dead == False, Player.current_city == city))).scalars())  # noqa: E712
        if not humans or not bots:
            return 0
        pairs = []
        for h in humans:
            fam = await familiars(h)
            for b in bots:
                if b in fam:
                    pairs.append((h, b, familiar_weight(fam[b])))
        rng.shuffle(pairs)
        pairs.sort(key=lambda t: -t[2] * rng.random())
        used_h, used_b, n = set(), set(), 0
        for h, b, _w in pairs:
            if ecfg["max_pairs"] is not None and n >= ecfg["max_pairs"]:
                break
            if h in used_h or b in used_b:
                continue
            used_h.add(h)
            used_b.add(b)
            await enqueue(h, b, f"chatter_event_{when}", {"event": "兽潮" if beast_tide else "灵雨", "city": city},
                          {"event": "兽潮" if beast_tide else "灵雨"}, rng.uniform(*ecfg["delay_seconds"]), now)
            n += 1
        return n
    except Exception:
        log.warning("事件搭话入队失败", exc_info=True)
        return 0


async def queue_conflict(actor_id: str, victim_id: str, kind: str, holders: list[dict], rng=None, now: float | None = None) -> int:
    """玩家打劫 / 废修为 / 击杀了机器人：几分钟后，当事机器人（还活着的话）放话；替它出头的朋友们（人数不设上限，用户定）稍后一起出来；
    还可能有善良或守序的朋友来劝架。朋友们的话合并成一条消息。"""
    rng, now, cfg = rng or random.Random(), now or time.time(), load()
    try:
        ccfg = cfg["conflict"]
        async with AsyncSessionLocal() as session:
            victim = await session.get(Player, victim_id)
            vname = victim.name if victim else "故人"
        lo, hi = ccfg["delay_minutes"]
        base = rng.uniform(lo, hi) * 60
        friend_delay = base + rng.uniform(*ccfg["friend_extra_minutes"]) * 60
        limit = ccfg["max_messages"]
        ties = {t["other"]: t["kind"] for t in await bot_ties.ties_of(victim_id)}
        group, n, spoke = uuid.uuid4().hex[:8], 0, set()
        for h in holders:
            if limit is not None and n >= limit:
                break
            hid = h["holder"]
            if hid == victim_id:
                if kind == "kill":
                    continue                                         # 死人不会说话
                await enqueue(actor_id, hid, "chatter_conflict_self", {"victim": "我"}, {"kind": kind}, base, now)
            else:
                await enqueue(actor_id, hid, "chatter_conflict_friend", {"victim": vname}, {"kind": kind, "bond": ties.get(hid, "相识")},
                              friend_delay, now, group)
            spoke.add(hid)
            n += 1
        mediators, cap, mcfg = 0, ccfg["mediators_max"], cfg["mediator"]
        if rng.random() < ccfg["mediator_chance"]:
            for t in await bot_ties.ties_of(victim_id, ("朋友", "结拜", "同门")):
                if cap is not None and mediators >= cap:
                    break
                if (limit is not None and n >= limit) or t["other"] in spoke or not is_bot_id(t["other"]) or t["other"] == actor_id:
                    continue
                ctx = await build_context(actor_id, t["other"])
                if ctx and (ctx["_kindness"] >= mcfg["kindness_min"] or (ctx["_profile"] or {}).get("lawful", 0) >= mcfg["lawful_min"]):
                    await enqueue(actor_id, t["other"], "chatter_mediate", {"victim": vname}, {"kind": kind}, friend_delay + mcfg["extra_delay_seconds"], now)
                    mediators += 1
                    n += 1
        return n
    except Exception:
        log.warning("冲突放话入队失败", exc_info=True)
        return 0


# ---- 到点发送 ---------------------------------------------------------------

async def claim(qid: str, now: float) -> bool:
    """认领一条队列记录：条件更新（还没发过才改），并发时只有一个调用者拿到。"""
    async with AsyncSessionLocal() as session:
        res = await session.execute(update(ChatterQueue).where(ChatterQueue.id == qid, ChatterQueue.sent_at == 0).values(sent_at=now))
        await session.commit()
    return res.rowcount == 1


async def _set_outcome(qids: list[str], outcome: str) -> None:
    async with AsyncSessionLocal() as session:
        await session.execute(update(ChatterQueue).where(ChatterQueue.id.in_(qids)).values(outcome=outcome))
        await session.commit()


async def claim_due(now: float | None = None, limit: int | None = None, rng=None) -> list[dict]:
    """取出到点的搭话（条件更新认领，不会重复发）。同一玩家、同一场景、同一个 group 的合并成一条消息（多个人一起说话）。
    被屏蔽 / 超上限 / 冷却中 / 台词挑不出的丢弃（记在 outcome 里）。每条消息算一次搭话事件（今日计数 +1）。
    返回 [{"queue_ids", "payload": group_payload 的结果, "scene"}]，由后台循环发到频道。"""
    now, cfg = now or time.time(), load()
    async with AsyncSessionLocal() as session:
        rows = (await session.execute(select(ChatterQueue).where(ChatterQueue.sent_at == 0, ChatterQueue.due_at <= now)
                                      .order_by(ChatterQueue.due_at).limit(cfg["queue"]["claim_limit"] if limit is None else limit))).scalars().all()
        todo = [(r.id, r.player_id, r.speaker_id, r.scene, json.loads(r.fmt or "{}")) for r in rows]
    groups: dict[tuple, list] = {}
    for qid, pid, sid, scene, fmt in todo:
        if not await claim(qid, now):
            continue
        key = (pid, scene, fmt.get("group") or qid)
        groups.setdefault(key, []).append((qid, sid, fmt))
    out = []
    for (pid, scene, _g), members in groups.items():
        qids = [m[0] for m in members]
        reason = await gate(pid, None, now, cfg)
        if reason:
            await _set_outcome(qids, reason)
            continue
        entries, dropped = [], []
        for qid, sid, fmt in members:
            r = await gate(pid, sid, now, cfg)
            e = None if r else await compose(scene, pid, sid, fmt.get("vars"), fmt.get("ctx"), rng)
            if e:
                entries.append(e)
                await _set_outcome([qid], "sent")
            else:
                await _set_outcome([qid], r or "nolines")
        if entries:
            payload = group_payload(entries, cfg["conflict" if scene.startswith("chatter_conflict") else "congrats"]["max_lines"])
            await record(pid, payload["all_bot_ids"], now)
            out.append({"queue_ids": qids, "payload": payload, "scene": scene})
    return out


async def purge_old(now: float | None = None, keep_days: float | None = None) -> int:
    """清掉已处理的旧队列记录。"""
    from sqlalchemy import delete
    now = now or time.time()
    keep_days = load()["queue"]["keep_days"] if keep_days is None else keep_days
    async with AsyncSessionLocal() as session:
        res = await session.execute(delete(ChatterQueue).where(ChatterQueue.sent_at > 0, ChatterQueue.sent_at < now - keep_days * 86400))
        await session.commit()
    return res.rowcount


# ---- 玩家的回应 -------------------------------------------------------------

async def respond(player_id: str, bot_id: str, attitude: str, rng=None) -> dict:
    """玩家点了回应按钮（warm / ok / neutral / cold）：好感小幅变化，机器人回一句。"""
    from utils import bot_social
    delta = load()["reply"].get(attitude)
    if delta is None:
        return {"ok": False, "reason": "不知道这种回应。"}
    favor = await bot_social.adjust_favor(player_id, bot_id, delta) if delta else await bot_social.get_favor(player_id, bot_id)
    reply = await compose(REPLY_SCENES[attitude], player_id, bot_id, rng=rng)
    return {"ok": True, "delta": delta, "favor": favor, "line": reply["line"] if reply else ""}


# ---- 清理 -------------------------------------------------------------------

async def remove_for(session, ids: list[str]) -> int:
    """机器人被清理：它没发的搭话、和玩家的冷却记录一并删掉。"""
    from sqlalchemy import delete
    a = await session.execute(delete(ChatterQueue).where(ChatterQueue.speaker_id.in_(ids)))
    b = await session.execute(delete(ChatterPair).where(ChatterPair.bot_id.in_(ids)))
    return a.rowcount + b.rowcount


async def forget_player(session, player_id: str) -> None:
    """玩家转世：给旧角色排的搭话作废、冷却清掉；屏蔽的选择保留（那是玩家本人的偏好）。"""
    from sqlalchemy import delete
    await session.execute(delete(ChatterQueue).where(ChatterQueue.player_id == player_id, ChatterQueue.sent_at == 0))
    await session.execute(delete(ChatterPair).where(ChatterPair.player_id == player_id))
