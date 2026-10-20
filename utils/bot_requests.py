"""机器人对熟人的请求 / 委托（U1·江湖百态）：借灵石、借物品、送信、陪着采集……

用户 2026-10-13 的想法：熟人机器人会向你开口 —— 缺钱借灵石（以后同城碰面时，隔 1~5 年可能还你，看性格：有的赖账，有的多还）、
借物品、托你去某地给某人送信、要你陪它去采集……**不要卡太死**。所以这里是个**数据驱动的框架**：
· 模板在 `data/bot_requests.json`，每个模板有一个 `kind`（loan_stones / loan_item / errand / companion_gather）——同一种 kind 能写很多模板（只改数据），
  新的玩法类型 = 加一个 kind 的处理函数；
· 提出 → 你答应 / 婉拒（按钮）→ 答应后进入 active（借出去的东西等着还，送信 / 陪采集等着办）→ 在合适的时机（同城碰面、到了收信人的城、开始采集）结算；
· 还钱 / 赖账由性格决定（守序、善良、重义气的按时还，关系好的还会多给；贪财、阴鸷的可能赖账 —— 赖账不动手，记一笔轻仇、好感大降）；
· 台词在条件化文案库（data/bot_chatter/request_*.json），所以不同性格开口的方式、还钱的方式都不一样。

所有写入对其它系统都是旁路：出错只记 warning，不影响到城 / 搭话。
"""

import json
import logging
import random
import time
import uuid
from functools import lru_cache
from pathlib import Path

from sqlalchemy import delete, select, update

from utils import bot_chatter as bc
from utils import bot_economy as be
from utils import bot_grudges, bot_memory
from utils.atomic import consume_item, grant_item, grant_stones, spend_stones
from utils.bots import is_bot_id
from utils.character import years_to_seconds
from utils.db_async import AsyncSessionLocal, BotPersonality, BotRequest, BotTie, Inventory, Player
from utils.items import ITEMS
from utils import settings_hub

log = logging.getLogger(__name__)

_PATH = Path(__file__).resolve().parent.parent / "data" / "bot_requests.json"
KINDS = ("loan_stones", "loan_item", "errand", "companion_gather")
LOAN_KINDS = ("loan_stones", "loan_item")
OPEN = ("offered", "active")
HOUR = 3600


@lru_cache(maxsize=1)
def _load() -> dict:
    return settings_hub.read(_PATH)


def load() -> dict:
    return _load()


def reload() -> None:
    _load.cache_clear()


def validate(cfg: dict, archetypes: list[str] | None = None) -> list[str]:
    errors = []
    ask = cfg.get("ask", {})
    if not 0 <= ask.get("chance", -1) <= 1:
        errors.append("ask.chance 应在 0~1")
    if archetypes is not None and set(ask.get("chance_by_archetype", {})) != set(archetypes):
        errors.append("ask.chance_by_archetype 应覆盖所有原型")
    if ask.get("min_tier") not in ("陌生", "熟识", "至交"):
        errors.append("ask.min_tier 应是 陌生 / 熟识 / 至交")
    for k in ("offer_ttl_hours", "max_open_per_player", "per_bot_cooldown_hours", "max_offers_per_meeting"):
        if ask.get(k, -1) < 0:
            errors.append(f"ask.{k} 不能为负")
    for name, t in cfg.get("templates", {}).items():
        if t.get("kind") not in KINDS:
            errors.append(f"templates.{name}.kind 应是 {KINDS}")
        if t.get("weight", 0) <= 0:
            errors.append(f"templates.{name}.weight 应大于 0")
        lo, hi = t.get("due_years", [1, 0])
        if not 0 < lo <= hi:
            errors.append(f"templates.{name}.due_years 应是 [最小, 最大]")
        if t.get("kind") == "loan_stones" and not (t.get("amounts") and all(a > 0 for a in t["amounts"])):
            errors.append(f"templates.{name}.amounts 应是正数列表")
        if t.get("kind") == "companion_gather" and not t.get("types"):
            errors.append(f"templates.{name}.types 不能为空")
        if t.get("kind") in ("errand", "companion_gather") and not (t.get("reward_stones") and 0 <= t["reward_stones"][0] <= t["reward_stones"][1]):
            errors.append(f"templates.{name}.reward_stones 应是 [最小, 最大]")
        scene = f"request_ask_{name}"
        from utils import bot_chatter_lines as cl
        if scene not in cl.SCENES:
            errors.append(f"模板 {name} 缺少开口台词场景 {scene}（在 bot_chatter_lines.SCENES 加，并写 data/bot_chatter/{scene}.json）")
    pa = cfg.get("player_ask", {})
    if pa.get("min_tier") not in ("陌生", "熟识", "至交") or pa.get("cooldown_hours", -1) < 0 or pa.get("grace_years", -1) < 0:
        errors.append("player_ask: min_tier / cooldown_hours / grace_years 不合法")
    if not (pa.get("amounts") and all(a > 0 for a in pa["amounts"])) or not pa.get("gather_types"):
        errors.append("player_ask.amounts 应是正数列表，gather_types 不能为空")
    for key in ("due_years", "gather_due_years"):
        lo, hi = pa.get(key, [1, 0])
        if not 0 < lo <= hi:
            errors.append(f"player_ask.{key} 应是 [最小, 最大]")
    ac = pa.get("accept", {})
    if set(ac.get("base_by_tier", {})) != {"仇视", "陌生", "熟识", "至交"} or not 0 <= ac.get("min", -1) <= ac.get("max", -1) <= 1:
        errors.append("player_ask.accept: base_by_tier 要覆盖四个档位，0 ≤ min ≤ max ≤ 1")
    if min(ac.get("kindness_div", 0), ac.get("loyalty_div", 0), ac.get("greed_div", 0)) <= 0:
        errors.append("player_ask.accept 的 *_div 应大于 0")
    if pa.get("dun_interval_years", -1) < 0:
        errors.append("player_ask.dun_interval_years 不能为负")
    rp = cfg.get("repay", {})
    for key in ("default_base", "closeness"):
        if archetypes is not None and key == "default_base" and set(rp.get(key, {})) != set(archetypes):
            errors.append("repay.default_base 应覆盖所有原型")
    if archetypes is not None and set(rp.get("gratitude", {}).get("chance_base", {})) != set(archetypes):
        errors.append("repay.gratitude.chance_base 应覆盖所有原型")
    lo, hi = rp.get("gratitude", {}).get("bonus", [1, 0])
    if not 0 <= lo <= hi:
        errors.append("repay.gratitude.bonus 应是 [最小, 最大]")
    if rp.get("max_extends", -1) < 0 or rp.get("item_markup", 0) <= 0:
        errors.append("repay.max_extends / item_markup 不合法")
    return errors


# ---- 还钱的性格决策（纯函数） -----------------------------------------------

def default_probability(archetype: str, lawful: int, kindness: int, greed: int, tier: str, cfg: dict | None = None) -> float:
    """赖账的概率：性格底子 + 不守序 / 贪婪加一点 + 善良 / 交情深减一点。"""
    rp = (cfg or load())["repay"]
    p = rp["default_base"][archetype] + (50 - lawful) / 250 + (greed - 50) / 250 - (kindness - 50) / 300 + rp["closeness"].get(tier, 0.0) * -1
    return max(0.0, min(0.9, p))


def repay_decision(archetype: str, lawful: int, kindness: int, greed: int, tier: str, rng=random, cfg: dict | None = None) -> str:
    """到期了，还不还：default（赖账）/ repay（照还）/ plus（感念旧情，多还一些）。"""
    cfg = cfg or load()
    if rng.random() < default_probability(archetype, lawful, kindness, greed, tier, cfg):
        return "default"
    g = cfg["repay"]["gratitude"]
    p = g["chance_base"][archetype] + (kindness - 50) / 200 + cfg["repay"]["closeness"].get(tier, 0.0)
    return "plus" if rng.random() < max(0.0, min(0.9, p)) else "repay"


def lend_chance(tier: str, relation: str, kindness: int, loyalty: int, greed: int, share: float, gather: bool = False,
                cfg: dict | None = None) -> float:
    """玩家向熟人求助，对方答应的概率：交情档位底子 + 关系加成 + 善意 / 义气加一点、贪婪减一点 − 数额占它身家的比例 × share_penalty（陪采集没有这一项，还有点加成）。"""
    a = (cfg or load())["player_ask"]["accept"]
    p = (a["base_by_tier"].get(tier, 0.0) + a["relation_bonus"].get(relation, 0.0) + (kindness - 50) / a["kindness_div"]
         + (loyalty - 50) / a["loyalty_div"] - (greed - 50) / a["greed_div"])
    p += a["gather_bonus"] if gather else -a["share_penalty"] * min(1.0, max(0.0, share))
    return max(a["min"], min(a["max"], p))


# ---- 读写小工具 -------------------------------------------------------------

def _years(rng, rng_pair) -> float:
    lo, hi = rng_pair
    return years_to_seconds(rng.uniform(lo, hi))


async def _lock(session) -> None:
    await session.execute(update(Player).where(Player.discord_id == "").values(discord_id=""))


async def _bot_state(session, bot_id: str):
    bot, persona = await session.get(Player, bot_id), await session.get(BotPersonality, bot_id)
    if bot is None or persona is None or not bot.is_bot:
        return None
    return bot, persona, (json.loads(persona.profile) if persona.profile else {})


def _row_dict(r: BotRequest) -> dict:
    return {"id": r.id, "bot_id": r.bot_id, "player_id": r.player_id, "template": r.template, "state": r.state,
            "params": json.loads(r.params or "{}"), "created_at": r.created_at, "due_at": r.due_at, "note": r.note}


async def _line(scene: str, player_id: str, bot_id: str, vars: dict | None = None, rng=None) -> str:
    c = await bc.compose(scene, player_id, bot_id, vars, rng=rng)
    return c["line"] if c else ""


def _event(kind: str, bot, line: str, **extra) -> dict:
    return {"kind": kind, "bot_id": bot.discord_id, "bot_name": bot.name, "bot_realm": bot.realm, "line": line, **extra}


# ---- 开口 -------------------------------------------------------------------

async def _feasible(session, tpl_name: str, tpl: dict, player: Player, bot: Player, persona: BotPersonality, rng) -> dict | None:
    """这个模板此刻能不能提：能的话返回 params。"""
    kind = tpl["kind"]
    if kind == "loan_stones":
        if bot.spirit_stones >= tpl["bot_stones_below"]:
            return None
        ok = [a for a in tpl["amounts"] if a <= player.spirit_stones * tpl["amount_max_player_share"]]
        return {"amount": rng.choice(ok)} if ok else None
    if kind == "loan_item":
        likes = (json.loads(persona.likes or "{}")).get("categories", [])
        from utils.bot_social import category_of
        inv = (await session.execute(select(Inventory.item_id).where(Inventory.discord_id == player.discord_id, Inventory.quantity >= 1))).scalars().all()
        pool = [i for i in inv if i in ITEMS and 0 < be.item_value(i) <= tpl["item_value_max"]]
        liked = [i for i in pool if category_of(i) in likes]
        pick = rng.choice(liked or pool) if (liked or pool) else None
        return {"item": pick, "qty": 1, "value": be.item_value(pick)} if pick else None
    if kind == "errand":
        ties = (await session.execute(select(BotTie).where((BotTie.a_id == bot.discord_id) | (BotTie.b_id == bot.discord_id),
                                                           BotTie.kind.in_(["结拜", "同门", "朋友", "相识"])))).scalars().all()
        others = [t.b_id if t.a_id == bot.discord_id else t.a_id for t in ties]
        rows = (await session.execute(select(Player, BotPersonality.home_city).join(BotPersonality, BotPersonality.bot_id == Player.discord_id).where(
            Player.discord_id.in_(others or [""]), Player.is_bot == True, Player.is_dead == False))).all()      # noqa: E712
        far = [(p, home) for p, home in rows if home and home != player.current_city and home != bot.current_city]
        if not far:
            return None
        p, home = rng.choice(far)
        return {"target": p.discord_id, "target_name": p.name, "city": home}
    if kind == "companion_gather":
        from utils.world import get_region
        if get_region(bot.current_city):                    # 它在秘地就不约采集了
            return None
        return {"what": rng.choice(tpl["types"])}
    return None


async def maybe_ask(player_id: str, bot_id: str, rng=None, now: float | None = None) -> dict | None:
    """熟人机器人此刻会不会向玩家开口：返回提出的请求（已入库，state=offered）和开口台词，没有返回 None。旁路。"""
    rng, now, cfg = rng or random.Random(), now or time.time(), load()
    ask = cfg["ask"]
    try:
        ctx = await bc.build_context(player_id, bot_id)
        if ctx is None or ctx["tier"] == "仇视" or ctx["relation"] == "仇敌":
            return None
        if not (ctx["tier"] in ("熟识", "至交") or ctx["relation"] in ask["bonded_relations"]):
            return None
        if rng.random() >= ask["chance"] * ask["chance_by_archetype"].get(ctx["archetype"], 1.0):
            return None
        if await bc.gate(player_id, bot_id, now):
            return None
        async with AsyncSessionLocal() as session:
            await _lock(session)
            rows = (await session.execute(select(BotRequest).where(BotRequest.player_id == player_id))).scalars().all()
            if sum(1 for r in rows if r.state in OPEN) >= ask["max_open_per_player"]:
                return None
            mine = [r for r in rows if r.bot_id == bot_id]
            if any(r.state in OPEN for r in mine) or any(now - r.created_at < ask["per_bot_cooldown_hours"] * HOUR for r in mine):
                return None
            state = await _bot_state(session, bot_id)
            player = await session.get(Player, player_id)
            if state is None or state[0].is_dead or player is None:
                await session.rollback()
                return None
            bot, persona, _prof = state
            options = []
            for name, tpl in cfg["templates"].items():
                params = await _feasible(session, name, tpl, player, bot, persona, rng)
                if params is not None:
                    options.append((name, tpl, params))
            if not options:
                await session.rollback()
                return None
            name, tpl, params = rng.choices(options, weights=[o[1]["weight"] for o in options])[0]
            rid = uuid.uuid4().hex[:16]
            session.add(BotRequest(id=rid, bot_id=bot_id, player_id=player_id, template=name, state="offered", params=json.dumps(params, ensure_ascii=False),
                                   created_at=now, due_at=now + ask["offer_ttl_hours"] * HOUR, updated_at=now))
            await session.commit()
            bname, brealm = bot.name, bot.realm
        vars_ = {**params, "target": params.get("target_name", params.get("target", ""))}      # 台词里的 {target} 是名字不是 ID
        line = await _line(f"request_ask_{name}", player_id, bot_id, vars_, rng)
        if not line:
            await set_state(rid, "expired", now, "没有台词")
            return None
        await bc.record(player_id, bot_id, now)
        return {"id": rid, "bot_id": bot_id, "bot_name": bname, "bot_realm": brealm, "template": name, "kind": tpl["kind"], "params": params,
                "line": line, "expires_at": now + ask["offer_ttl_hours"] * HOUR}
    except Exception:
        log.warning("机器人开口失败：%s %s", player_id, bot_id, exc_info=True)
        return None


async def set_state(rid: str, state: str, now: float, note: str = "") -> None:
    async with AsyncSessionLocal() as session:
        await session.execute(update(BotRequest).where(BotRequest.id == rid).values(state=state, updated_at=now, note=note))
        await session.commit()


# ---- 答应 / 婉拒 ------------------------------------------------------------

async def accept(rid: str, rng=None, now: float | None = None) -> dict:
    """玩家答应：借灵石 / 借物品当场转给对方，进入 active（约定归还时间）；送信 / 陪采集进入 active 等着办。"""
    rng, now, cfg = rng or random.Random(), now or time.time(), load()
    async with AsyncSessionLocal() as session:
        await _lock(session)
        row = await session.get(BotRequest, rid)
        if row is None or row.state != "offered":
            await session.rollback()
            return {"ok": False, "reason": "这个请求已经处理过了。"}
        if now > row.due_at:                                    # 提出后 offer_ttl 内有效
            row.state, row.updated_at, row.note = "expired", now, "超时"
            await session.commit()
            return {"ok": False, "reason": "对方已经另想办法了（请求过期）。"}
        tpl = cfg["templates"][row.template]
        params, pid, bid = json.loads(row.params), row.player_id, row.bot_id
        bot = await session.get(Player, bid)
        if bot is None or bot.is_dead:
            row.state, row.updated_at, row.note = "expired", now, "对方不在了"
            await session.commit()
            return {"ok": False, "reason": "对方已不在人世。"}
        bname = bot.name
        if tpl["kind"] == "loan_stones":
            if not await spend_stones(session, pid, params["amount"]):
                await session.rollback()
                return {"ok": False, "reason": "你的灵石不够。"}
            await grant_stones(session, bid, params["amount"])
        elif tpl["kind"] == "loan_item":
            if not await consume_item(session, pid, params["item"], params["qty"]):
                await session.rollback()
                return {"ok": False, "reason": f"你已经没有 {params['item']} 了。"}
            await grant_item(session, bid, params["item"], params["qty"])
        params["accepted_at"] = now
        row.state, row.updated_at, row.params = "active", now, json.dumps(params, ensure_ascii=False)
        row.due_at = now + _years(rng, tpl["due_years"])
        await session.commit()
        due = row.due_at
    line = await _line("request_thanks", pid, bid, rng=rng)
    return {"ok": True, "bot_name": bname, "line": line, "due_at": due, "template": row.template}


async def decline(rid: str, rng=None, now: float | None = None) -> dict:
    rng, now, cfg = rng or random.Random(), now or time.time(), load()
    async with AsyncSessionLocal() as session:
        await _lock(session)
        row = await session.get(BotRequest, rid)
        if row is None or row.state != "offered":
            await session.rollback()
            return {"ok": False, "reason": "这个请求已经处理过了。"}
        row.state, row.updated_at, row.note = "declined", now, "婉拒"
        pid, bid = row.player_id, row.bot_id
        await session.commit()
    return {"ok": True, "line": await _line("request_declined", pid, bid, rng=rng)}


# ---- 碰面时结算 + 开口 ------------------------------------------------------

async def on_meet(player_id: str, present_ids: list[str], rng=None, now: float | None = None) -> dict:
    """玩家和一群机器人碰面了（到城 / 点『搭话』）：① 结算（到期的借款还不还、送信送到了没有）② 熟人里可能有一位向你开口。
    返回 {"events": [结算结果...], "offer": 开口 or None}。旁路。"""
    rng, now, cfg = rng or random.Random(), now or time.time(), load()
    out = {"events": [], "offer": None}
    try:
        present = set(present_ids)
        async with AsyncSessionLocal() as session:
            rows = (await session.execute(select(BotRequest).where(BotRequest.player_id == player_id, BotRequest.state == "active"))).scalars().all()
            actives = [_row_dict(r) for r in rows]
        for r in actives:
            tpl = cfg["templates"].get(r["template"])
            if tpl is None:
                continue
            if r["params"].get("dir") == "player":               # 玩家求来的账：到期它来催，宽限之后翻脸
                if tpl["kind"] in LOAN_KINDS and r["bot_id"] in present and now >= r["due_at"]:
                    out["events"] += await _dun_or_default(r, rng, now, cfg)
                continue
            if tpl["kind"] in LOAN_KINDS and r["bot_id"] in present and now >= r["due_at"]:
                out["events"] += await _settle_loan(r, tpl, rng, now, cfg)
            elif tpl["kind"] == "errand" and r["params"].get("target") in present:
                out["events"] += await _finish_errand(r, tpl, rng, now)
        fam = await bc.familiars(player_id)
        candidates = [b for b in present_ids if b in fam]
        rng.shuffle(candidates)
        for bot_id in candidates[:max(cfg["ask"]["max_offers_per_meeting"], 0) * 3]:       # 最多试几位，找到一位开口的就停
            offer = await maybe_ask(player_id, bot_id, rng, now)
            if offer:
                out["offer"] = offer
                break
    except Exception:
        log.warning("碰面结算 / 开口失败：%s", player_id, exc_info=True)
    return out


async def on_gather(player_id: str, city: str, rng=None, now: float | None = None) -> list[dict]:
    """玩家开始采集：约好陪采集、而且此刻在同一座城的机器人，这次就一起去了。"""
    rng, now, cfg = rng or random.Random(), now or time.time(), load()
    events = []
    try:
        async with AsyncSessionLocal() as session:
            rows = (await session.execute(select(BotRequest).where(BotRequest.player_id == player_id, BotRequest.state == "active"))).scalars().all()
            todo = [_row_dict(r) for r in rows if cfg["templates"].get(r.template, {}).get("kind") == "companion_gather"]
            here = set((await session.execute(select(Player.discord_id).where(
                Player.discord_id.in_([r["bot_id"] for r in todo] or [""]), Player.is_bot == True, Player.is_dead == False,
                Player.current_city == city))).scalars())          # noqa: E712
        for r in todo:
            if r["bot_id"] in here:
                if r["params"].get("dir") == "player":
                    events += await _finish_player_gather(r, rng, now, cfg)
                else:
                    events += await _finish_gather(r, cfg["templates"][r["template"]], rng, now)
    except Exception:
        log.warning("陪采集结算失败：%s", player_id, exc_info=True)
    return events


async def _pay(session, from_id: str, to_id: str, amount: int) -> int:
    """从 from 转给 to 最多 amount 灵石（对方有多少转多少），返回实际转了多少。"""
    have = await session.scalar(select(Player.spirit_stones).where(Player.discord_id == from_id)) or 0
    pay = max(0, min(amount, have))
    if pay and await spend_stones(session, from_id, pay):
        await grant_stones(session, to_id, pay)
        return pay
    return 0


async def _settle_loan(r: dict, tpl: dict, rng, now: float, cfg: dict) -> list[dict]:
    """到期的借款：按性格决定赖账 / 照还 / 多还；手头不够就先还一部分、宽限几年，宽限用完还不上算赖账。"""
    rp = cfg["repay"]
    pid, bid, params = r["player_id"], r["bot_id"], r["params"]
    ctx = await bc.build_context(pid, bid)
    if ctx is None:
        return []
    prof = ctx["_profile"] or {}
    decision = repay_decision(ctx["archetype"], prof.get("lawful", 50), ctx["_kindness"], ctx["_greed"], ctx["tier"], rng, cfg)
    events = []
    async with AsyncSessionLocal() as session:
        await _lock(session)
        row = await session.get(BotRequest, r["id"])
        if row is None or row.state != "active":
            await session.rollback()
            return []
        bot = await session.get(Player, bid)
        if bot is None or bot.is_dead:
            row.state, row.updated_at, row.note = "failed", now, "对方不在了"
            await session.commit()
            return []
        bname, brealm = bot.name, bot.realm
        paid_item = None
        if decision != "default":
            if tpl["kind"] == "loan_item":
                item, qty = params["item"], params["qty"]
                if await consume_item(session, bid, item, qty):                  # 手里还有这件东西：原物奉还
                    await grant_item(session, pid, item, qty)
                    paid_item = item
                else:                                                            # 没有了：折成灵石
                    params["owed"] = int(be.item_value(item) * qty * rp["item_markup"])
            owed = int(params.get("owed", params.get("amount", 0)))
            bonus = rng.uniform(*rp["gratitude"]["bonus"]) if decision == "plus" and paid_item is None else 0.0
            total = int(owed * (1 + bonus)) if paid_item is None else 0
            paid = await _pay(session, bid, pid, total) if paid_item is None else 0
        if decision == "default":
            row.state, row.updated_at, row.note = "defaulted", now, "赖账"
            await session.commit()
            kind = "default"
        elif paid_item is not None:
            row.state, row.updated_at, row.note = "done", now, "原物奉还"
            await session.commit()
            kind = "repay_item"
        elif paid >= total:
            row.state, row.updated_at, row.note = "done", now, "已还"
            await session.commit()
            kind = "repay_plus" if bonus else "repay"
        else:                                                                  # 手头不够
            params["owed"] = total - paid
            params["extends"] = params.get("extends", 0) + 1
            if params["extends"] > rp["max_extends"]:
                row.state, row.note = "defaulted", "还不上"
                kind = "default"
            else:
                row.due_at = now + _years(rng, rp["extend_years"])
                kind = "short"
            row.updated_at, row.params = now, json.dumps(params, ensure_ascii=False)
            await session.commit()
    scene = {"repay": "request_repay", "repay_plus": "request_repay_plus", "repay_item": "request_repay_item", "short": "request_short", "default": "request_default"}[kind]
    amount = paid if kind in ("repay", "repay_plus") else params.get("owed", 0)
    line = await _line(scene, pid, bid, {"amount": amount, "item": params.get("item", "")}, rng)
    from utils import bot_social
    ev = {"kind": kind, "bot_id": bid, "bot_name": bname, "bot_realm": brealm, "line": line, "amount": amount, "item": paid_item or ""}
    if kind == "default":
        await bot_grudges.on_offense(bid, pid, "debt")
        await bot_memory.remember(pid, bid, "debt", "", str(params.get("amount", "")))
        await bot_social.adjust_favor(pid, bid, cfg["default"]["favor"])
    elif kind in ("repay", "repay_plus", "repay_item"):
        await bot_memory.remember(pid, bid, "repaid", "", kind)
    events.append(ev)
    return events


async def _finish_errand(r: dict, tpl: dict, rng, now: float) -> list[dict]:
    """信送到了：收信人道谢，托信的人从自己身上出一份酬劳（有多少给多少，不凭空造钱），双方好感都涨。"""
    from utils import bot_social
    pid, asker, target = r["player_id"], r["bot_id"], r["params"]["target"]
    reward = rng.randint(*tpl["reward_stones"])
    async with AsyncSessionLocal() as session:
        await _lock(session)
        row = await session.get(BotRequest, r["id"])
        if row is None or row.state != "active":
            await session.rollback()
            return []
        t = await session.get(Player, target)
        if t is None or t.is_dead:
            await session.rollback()
            return []
        paid = await _pay(session, asker, pid, reward)
        row.state, row.updated_at, row.note = "done", now, "信已送到"
        await session.commit()
        tname, trealm = t.name, t.realm
    async with AsyncSessionLocal() as session:
        aname = await session.scalar(select(Player.name).where(Player.discord_id == asker)) or "故人"
    line = await _line("request_errand_arrive", pid, target, {"asker": aname}, rng)
    await bot_social.adjust_favor(pid, asker, tpl["favor"])
    await bot_social.adjust_favor(pid, target, max(1, tpl["favor"] // 2))
    await bot_memory.remember(pid, asker, "errand", "", "done")
    return [{"kind": "errand_done", "bot_id": target, "bot_name": tname, "bot_realm": trealm, "line": line, "amount": paid, "asker": aname}]


async def _finish_gather(r: dict, tpl: dict, rng, now: float) -> list[dict]:
    from utils import bot_social
    pid, bid = r["player_id"], r["bot_id"]
    reward = rng.randint(*tpl["reward_stones"])
    async with AsyncSessionLocal() as session:
        await _lock(session)
        row = await session.get(BotRequest, r["id"])
        if row is None or row.state != "active":
            await session.rollback()
            return []
        bot = await session.get(Player, bid)
        paid = await _pay(session, bid, pid, reward)
        row.state, row.updated_at, row.note = "done", now, "一起采集"
        await session.commit()
        bname, brealm = bot.name, bot.realm
    line = await _line("request_gather_done", pid, bid, {"what": r["params"].get("what", "采集")}, rng)
    await bot_social.adjust_favor(pid, bid, tpl["favor"])
    await bot_memory.remember(pid, bid, "gather", "", "done")
    return [{"kind": "gather_done", "bot_id": bid, "bot_name": bname, "bot_realm": brealm, "line": line, "amount": paid}]


# ---- 玩家主动求助 -----------------------------------------------------------

KIND_TEMPLATE = {"loan_stones": "borrow_stones", "loan_item": "borrow_item", "companion_gather": "gather_together"}


def _debt_label(params: dict) -> dict:
    """催债 / 还清台词里的 {amount} {item}。"""
    return {"amount": params.get("owed", params.get("amount", 0)), "item": params.get("item", "")}


async def player_ask(player_id: str, bot_id: str, kind: str, params: dict, rng=None, now: float | None = None) -> dict:
    """玩家当面向一位机器人求助：借灵石（amount）/ 借物品（item）/ 陪着采集（what）。
    答应与否按 `lend_chance`（交情、关系、它的善意 / 义气 / 贪婪、数额占身家的比例）掷骰；答应了借的当场转给你，约定 1~5 游戏年归还。
    返回 {"ok", "accepted", "reason", "line", "bot_name"}。每对（玩家，机器人）有冷却，婉拒也算一次。"""
    rng, now, cfg = rng or random.Random(), now or time.time(), load()
    pa = cfg["player_ask"]
    if kind not in KIND_TEMPLATE:
        return {"ok": False, "accepted": False, "reason": "不知道这种求助。", "line": "", "bot_name": ""}
    ctx = await bc.build_context(player_id, bot_id)
    if ctx is None:
        return {"ok": False, "accepted": False, "reason": "对方不存在。", "line": "", "bot_name": ""}
    async with AsyncSessionLocal() as session:
        await _lock(session)
        player, bot = await session.get(Player, player_id), await session.get(Player, bot_id)
        if player is None or player.is_dead or bot is None or not bot.is_bot or bot.is_dead:
            await session.rollback()
            return {"ok": False, "accepted": False, "reason": "对方已不在人世。", "line": "", "bot_name": ""}
        bname = bot.name
        if bot.current_city != player.current_city:
            await session.rollback()
            return {"ok": False, "accepted": False, "reason": f"**{bname}** 已经离开此地。", "line": "", "bot_name": bname}
        mine = [r for r in (await session.execute(select(BotRequest).where(BotRequest.player_id == player_id, BotRequest.bot_id == bot_id))).scalars()
                if json.loads(r.params or "{}").get("dir") == "player"]
        if any(now - r.created_at < pa["cooldown_hours"] * HOUR for r in mine):
            await session.rollback()
            return {"ok": False, "accepted": False, "reason": f"刚向 **{bname}** 求过助，过些日子再开口吧。", "line": "", "bot_name": bname}
        if kind != "companion_gather" and any(r.state == "active" and r.template == KIND_TEMPLATE[kind] for r in mine):
            await session.rollback()
            return {"ok": False, "accepted": False, "reason": f"你上回向 **{bname}** 借的还没还。", "line": "", "bot_name": bname}
        # 参数校验（不合规的直接拒绝，不占冷却）
        stones, value, p = bot.spirit_stones, 0, dict(params)
        if kind == "loan_stones":
            if p.get("amount") not in pa["amounts"]:
                await session.rollback()
                return {"ok": False, "accepted": False, "reason": "借的数目不对。", "line": "", "bot_name": bname}
            value = p["amount"]
        elif kind == "loan_item":
            item = p.get("item")
            value = be.item_value(item) if item in ITEMS else 0
            if not item or item not in ITEMS or not 0 < value <= pa["item_value_max"]:
                await session.rollback()
                return {"ok": False, "accepted": False, "reason": "这件东西不能借（不存在，或太贵重）。", "line": "", "bot_name": bname}
            have = await session.scalar(select(Inventory.quantity).where(Inventory.discord_id == bot_id, Inventory.item_id == item)) or 0
            if have < 1:
                await session.rollback()
                return {"ok": False, "accepted": False, "reason": f"**{bname}** 手上没有 {item}。", "line": "", "bot_name": bname}
            p["qty"], p["value"] = 1, value
        else:
            from utils.world import get_region
            if p.get("what") not in pa["gather_types"] or get_region(bot.current_city):
                await session.rollback()
                return {"ok": False, "accepted": False, "reason": "这里没法一起采集。", "line": "", "bot_name": bname}
        p["dir"] = "player"
        rid = uuid.uuid4().hex[:16]
        known = ctx["tier"] != "仇视" and ctx["relation"] != "仇敌" and (ctx["tier"] in ("熟识", "至交") or ctx["relation"] in pa["bonded_relations"])
        broke = kind == "loan_stones" and stones < value
        prof = ctx["_profile"] or {}
        chance = 0.0 if (not known or broke) else lend_chance(
            ctx["tier"], ctx["relation"], ctx["_kindness"], prof.get("loyalty", 50), ctx["_greed"], value / max(stones, 1) if kind != "companion_gather" else 0.0,
            kind == "companion_gather", cfg)
        accepted = known and not broke and rng.random() < chance
        if accepted and kind == "loan_stones":
            accepted = await spend_stones(session, bot_id, value)
            if accepted:
                await grant_stones(session, player_id, value)
        elif accepted and kind == "loan_item":
            accepted = await consume_item(session, bot_id, p["item"], 1)
            if accepted:
                await grant_item(session, player_id, p["item"], 1)
        due = now + _years(rng, pa["gather_due_years" if kind == "companion_gather" else "due_years"])
        session.add(BotRequest(id=rid, bot_id=bot_id, player_id=player_id, template=KIND_TEMPLATE[kind], state="active" if accepted else "refused",
                               params=json.dumps(p, ensure_ascii=False), created_at=now, due_at=due if accepted else now, updated_at=now,
                               note="" if accepted else ("手头紧" if broke else "婉拒")))
        await session.commit()
    vars_ = {"amount": p.get("amount", ""), "item": p.get("item", ""), "what": p.get("what", "")}
    line = await _line("request_lend_accept" if accepted else "request_lend_refuse", player_id, bot_id, vars_, rng)
    reason = "" if accepted else (f"**{bname}** 手头也紧。" if broke else "")
    return {"ok": True, "accepted": accepted, "reason": reason, "line": line, "bot_name": bname, "due_at": due if accepted else 0, "request_id": rid}


async def repay_debt(player_id: str, bot_id: str, now: float | None = None) -> dict:
    """玩家还这个机器人的账（借的灵石 / 物品）：灵石有多少还多少，物品优先还原物，没有就折成灵石（加价 item_markup）。"""
    now, cfg = now or time.time(), load()
    pa, rp = cfg["player_ask"], cfg["repay"]
    paid_total, cleared, items = 0, [], []
    async with AsyncSessionLocal() as session:
        await _lock(session)
        rows = [r for r in (await session.execute(select(BotRequest).where(
            BotRequest.player_id == player_id, BotRequest.bot_id == bot_id, BotRequest.state == "active"))).scalars()
            if json.loads(r.params or "{}").get("dir") == "player" and cfg["templates"].get(r.template, {}).get("kind") in LOAN_KINDS]
        if not rows:
            await session.rollback()
            return {"ok": False, "reason": "你没有欠它的账。", "cleared": 0, "paid": 0, "left": 0, "line": ""}
        left = 0
        for r in rows:
            params = json.loads(r.params)
            if r.template == "borrow_item" and not params.get("as_stones"):
                if await consume_item(session, player_id, params["item"], params["qty"]):          # 原物奉还
                    await grant_item(session, bot_id, params["item"], params["qty"])
                    items.append(params["item"])
                    r.state, r.updated_at, r.note = "done", now, "原物奉还"
                    cleared.append(params)
                    continue
                params["as_stones"], params["owed"] = True, int(params["value"] * params["qty"] * rp["item_markup"])
            owed = int(params.get("owed", params.get("amount", 0)))
            paid = await _pay(session, player_id, bot_id, owed)
            paid_total += paid
            if paid >= owed:
                r.state, r.updated_at, r.note = "done", now, "已还"
                cleared.append(params)
            else:
                params["owed"] = owed - paid
                r.params, r.updated_at = json.dumps(params, ensure_ascii=False), now
                left += owed - paid
        await session.commit()
    line = ""
    if cleared:
        from utils import bot_social
        line = await _line("request_debt_cleared", player_id, bot_id, _debt_label(cleared[-1]))
        await bot_social.adjust_favor(player_id, bot_id, pa["cleared_favor"])
        await bot_memory.remember(player_id, bot_id, "repaid_by_player", "", "")
    if not cleared and not paid_total:
        return {"ok": False, "reason": "你的灵石不够，一分钱也还不了。", "cleared": 0, "paid": 0, "left": left, "line": ""}
    return {"ok": True, "reason": "", "cleared": len(cleared), "paid": paid_total, "left": left, "line": line, "items": items}


async def _dun_or_default(r: dict, rng, now: float, cfg: dict) -> list[dict]:
    """玩家欠的账到期了、债主在场：宽限期内催一催（隔一阵才再催），宽限期过了翻脸 —— 记仇、好感大降。"""
    from utils import bot_social
    pa, pid, bid, params = cfg["player_ask"], r["player_id"], r["bot_id"], r["params"]
    async with AsyncSessionLocal() as session:
        bot = await session.get(Player, bid)
        if bot is None or bot.is_dead:
            return []
        bname, brealm = bot.name, bot.realm
    if now < r["due_at"] + years_to_seconds(pa["grace_years"]):
        last = params.get("dunned_at", 0)
        if last and now - last < years_to_seconds(pa["dun_interval_years"]):
            return []
        params["dunned_at"] = now
        async with AsyncSessionLocal() as session:
            await session.execute(update(BotRequest).where(BotRequest.id == r["id"], BotRequest.state == "active").values(
                params=json.dumps(params, ensure_ascii=False), updated_at=now))
            await session.commit()
        await bot_social.adjust_favor(pid, bid, pa["dun_favor"])
        return [_event("dun", bot, await _line("request_dun", pid, bid, _debt_label(params), rng), amount=_debt_label(params)["amount"], item=params.get("item", ""))]
    async with AsyncSessionLocal() as session:
        res = await session.execute(update(BotRequest).where(BotRequest.id == r["id"], BotRequest.state == "active").values(
            state="defaulted", updated_at=now, note="玩家赖账"))
        await session.commit()
    if res.rowcount != 1:
        return []
    await bot_grudges.on_offense(pid, bid, "debt")                      # 反过来：它记你的账（actor 是玩家，受害者是它）
    await bot_memory.remember(pid, bid, "debt_by_player", "", "")
    await bot_social.adjust_favor(pid, bid, pa["default_favor"])
    return [_event("player_default", bot, await _line("request_player_default", pid, bid, rng=rng))]


async def _finish_player_gather(r: dict, rng, now: float, cfg: dict) -> list[dict]:
    """玩家求来的陪采集：它在同城就一起去了。没有酬劳，双方好感涨、记进记忆。"""
    from utils import bot_social
    pid, bid = r["player_id"], r["bot_id"]
    async with AsyncSessionLocal() as session:
        res = await session.execute(update(BotRequest).where(BotRequest.id == r["id"], BotRequest.state == "active").values(
            state="done", updated_at=now, note="一起采集"))
        bot = await session.get(Player, bid)
        await session.commit()
    if res.rowcount != 1 or bot is None:
        return []
    line = await _line("request_gather_done", pid, bid, {"what": r["params"].get("what", "采集")}, rng)
    await bot_social.adjust_favor(pid, bid, cfg["player_ask"]["gather_favor"])
    await bot_memory.remember(pid, bid, "gather", "", "done")
    return [_event("gather_done", bot, line, amount=0)]


# ---- 过期 / 查询 / 清理 -----------------------------------------------------

async def expire(now: float | None = None) -> int:
    """提出后没答复的过期；答应了的送信 / 陪采集过了期限算没办成（好感小降）。借款不过期（到期后等着碰面再还 / 赖）。"""
    from utils import bot_social
    now, cfg = now or time.time(), load()
    n = 0
    async with AsyncSessionLocal() as session:
        await _lock(session)
        rows = (await session.execute(select(BotRequest).where(BotRequest.state.in_(OPEN), BotRequest.due_at < now))).scalars().all()
        failed = []
        for r in rows:
            kind = cfg["templates"].get(r.template, {}).get("kind")
            if r.state == "offered":
                r.state, r.note = "expired", "没有答复"
            elif kind == "companion_gather" and json.loads(r.params or "{}").get("dir") == "player":
                r.state, r.note = "expired", "没去成"                 # 玩家求来的陪采集，过期了就算了，不扣好感
            elif kind in ("errand", "companion_gather"):
                r.state, r.note = "failed", "没办成"
                failed.append((r.player_id, r.bot_id))
            else:
                continue
            r.updated_at = now
            n += 1
        await session.commit()
    for pid, bid in failed:
        await bot_social.adjust_favor(pid, bid, cfg["fail"]["favor"])
    return n


def describe(r: dict, bot_name: str, now: float | None = None) -> str:
    """给玩家看的一行。"""
    from utils.character import seconds_to_years
    now, p = now or time.time(), r["params"]
    left = f"，约定 {seconds_to_years(max(0, r['due_at'] - now)):.1f} 年后" if r["state"] == "active" else ""
    t = load()["templates"].get(r["template"], {}).get("kind")
    if p.get("dir") == "player":
        if t == "loan_stones":
            return f"你欠 **{bot_name}** {p.get('owed', p['amount'])} 灵石{left}还"
        if t == "loan_item":
            return f"你借了 **{bot_name}** 的 {p['item']}{left}还"
        if t == "companion_gather":
            return f"**{bot_name}** 答应陪你{p['what']}（还剩约 {seconds_to_years(max(0, r['due_at'] - now)):.1f} 年，在同城开始采集即可）"
    if r["state"] == "offered":
        return f"【待答复】**{bot_name}** 有事相求"
    if t == "loan_stones":
        return f"借给 **{bot_name}** {p.get('owed', p['amount'])} 灵石{left}还"
    if t == "loan_item":
        return f"借给 **{bot_name}** {p['item']}{left}还"
    if t == "errand":
        return f"替 **{bot_name}** 给 {p['city']} 的 **{p['target_name']}** 送信（还剩约 {seconds_to_years(max(0, r['due_at'] - now)):.1f} 年）"
    if t == "companion_gather":
        return f"陪 **{bot_name}** {p['what']}（还剩约 {seconds_to_years(max(0, r['due_at'] - now)):.1f} 年，到时在同城开始采集即可）"
    return f"**{bot_name}** 的请求"


async def list_for(player_id: str, now: float | None = None) -> list[str]:
    """玩家当前所有未了结的请求，每条一行文字。"""
    async with AsyncSessionLocal() as session:
        rows = (await session.execute(select(BotRequest).where(BotRequest.player_id == player_id, BotRequest.state.in_(OPEN))
                                      .order_by(BotRequest.created_at))).scalars().all()
        names = dict((await session.execute(select(Player.discord_id, Player.name).where(Player.discord_id.in_([r.bot_id for r in rows] or [""])))).all())
    return [describe(_row_dict(r), names.get(r.bot_id, "故人"), now) for r in rows]


async def forget_player(session, player_id: str) -> None:
    """玩家转世：旧角色的请求（欠账、委托）作废。"""
    await session.execute(delete(BotRequest).where(BotRequest.player_id == player_id))
