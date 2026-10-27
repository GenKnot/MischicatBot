"""仇恨账本（U1·江湖百态 P3）：谁恨谁、为了谁、为什么，以及这份仇恨会蹲多久。

用户 2026-10-12 的设计：
· 冒犯（打劫、打劫失败、废修为、击杀）会让受害者本人、以及关系网里的朋友 / 结拜 / 同门（按交情、性格、事件轻重掷骰）记仇；不是人人都出头。
· 仇恨有具体原因（『王某杀害了你的结拜兄弟李某』），玩家的仇人列表看得到；连环复仇：杀了小的，小的的朋友来；复仇者必须是关系网里真实存在的人。
· 蹲守窗口按性格定年数（游戏年，1 年 = 现实 2 小时）；到期没蹲到**不等于放下**：按性格有概率续期，不续就转为『潜伏』（仇恨还在，新事件或相遇会重新激活）。
  少数『执着』的人窗口特别长。复仇方式（直接 / 隐忍 / 等待时机）由行为画像决定。
· 受害者没名气时，朋友要过一阵才得知（甚至不知道）；有名气的一出事全服都知道（utils/fame.py）。
· 玩家可以化解：赔灵石、诚心道歉、送礼；杀掉仇敌不等于仇恨结束（它的朋友会继续）。
· 玩家转世：机器人不再记得新的他，但玩家自己保留前世仇人的记录（`player_enemies`）。

本模块只管『记账』和『谁现在可以来蹲你』（`candidates_against`），真正的拦路在 P4。全部写入都是旁路：出错只记 warning。
"""

import json
import logging
import random
import time
from functools import lru_cache
from pathlib import Path

from sqlalchemy import delete, func, or_, select, update

from utils import bot_profile, fame
from utils.atomic import spend_stones
from utils.bots import is_bot_id
from utils.character import years_to_seconds
from utils.db_async import (AsyncSessionLocal, BotGrudge, BotPersonality, BotTie, BotWorldState, Player, PlayerEnemy)
from utils.realms import REALMS, major_realm
from utils import settings_hub

log = logging.getLogger(__name__)

_PATH = Path(__file__).resolve().parent.parent / "data" / "bot_grudges.json"
MAJORS = list(dict.fromkeys(major_realm(r) for r in REALMS))
GRUDGE_KEY = "grudge_day"
STYLES = bot_profile.STYLES


@lru_cache(maxsize=1)
def _load() -> dict:
    return settings_hub.read(_PATH)


def load() -> dict:
    return _load()


def reload() -> None:
    _load.cache_clear()


def validate(cfg: dict, archetypes: list[str] | None = None) -> list[str]:
    errors = []
    for kind, k in cfg.get("kinds", {}).items():
        if not 1 <= k.get("severity", 0) <= 100:
            errors.append(f"kinds.{kind}.severity 应在 1~100")
        for key, needs in (("self", ["{actor}"]), ("third", ["{actor}", "{rel}", "{victim}"])):
            if not all(n in k.get(key, "") for n in needs):
                errors.append(f"kinds.{kind}.{key} 缺少 {needs}")
    for rel, v in cfg.get("relation", {}).items():
        if not 0 < v <= 1:
            errors.append(f"relation.{rel} 应在 (0, 1]")
    if "self" not in cfg.get("relation", {}):
        errors.append("relation 里要有 self")
    for rel in cfg.get("relation", {}):
        if rel != "self" and rel not in cfg.get("relation_names", {}):
            errors.append(f"relation_names 缺 {rel}")
    for name in ("windows", "renew"):
        table = cfg.get(name, {})
        if archetypes is not None and not set(archetypes) <= set(table):
            errors.append(f"{name} 缺原型：{sorted(set(archetypes) - set(table))}")
    for arche, years in cfg.get("windows", {}).items():
        if not years > 0:
            errors.append(f"windows.{arche} 应大于 0")
    for arche in archetypes or []:
        if not 0 <= cfg.get("renew", {}).get(arche, -1) <= 1:
            errors.append(f"renew.{arche} 应在 0~1")
    mx = cfg.get("renew", {}).get("max_renewals")
    if mx is not None and not (isinstance(mx, int) and mx >= 0):
        errors.append("renew.max_renewals 应是 null（不限）或非负整数")
    st = cfg.get("stubborn", {})
    if not (0 <= st.get("share", -1) <= 1 and st.get("mult", 0) >= 1):
        errors.append("stubborn: share 0~1，mult ≥ 1")
    if set(cfg.get("ready", {})) != set(STYLES):
        errors.append(f"ready 应覆盖 {STYLES}")
    if cfg.get("third_party_scale", 0) <= 0:
        errors.append("third_party_scale 应大于 0")
    ap = cfg.get("appease", {})
    if ap.get("stones_per_point", 0) <= 0 or not 0 <= ap.get("apology", {}).get("base", -1) <= 1 or not 0 <= ap.get("apology", {}).get("chance_cap", -1) <= 1:
        errors.append("appease 配置不合法（apology.base / chance_cap 在 0~1，stones_per_point > 0）")
    f = cfg.get("formula", {})
    if f.get("stat_base", -1) < 0 or f.get("strength_base", -1) < 0 or not 0 <= f.get("third_cap", -1) <= 1 or not 0 <= f.get("renew_cap", -1) <= 1:
        errors.append("formula: stat_base / strength_base ≥ 0，third_cap / renew_cap 在 0~1")
    return errors


# ---- 小工具 -----------------------------------------------------------------

def stronger(kind_a: str, kind_b: str, cfg: dict | None = None) -> str:
    cfg = cfg or load()
    return kind_a if cfg["kinds"][kind_a]["severity"] >= cfg["kinds"][kind_b]["severity"] else kind_b


def is_ready(style: str, holder_realm: str, target_realm: str, cfg: dict | None = None) -> bool:
    """这个人现在敢不敢动手：直接的随时敢；谨慎的要等自己的大境界不比对方低太多（P4 拦路用）。"""
    cfg = cfg or load()
    gap = MAJORS.index(major_realm(target_realm)) - MAJORS.index(major_realm(holder_realm))
    return gap <= cfg["ready"].get(style or "等待时机", 1)


def _persona(row: BotPersonality | None) -> tuple[str, dict]:
    if row is None:
        return "憨直", {}
    return row.archetype, (json.loads(row.profile) if row.profile else {})


def window_years(archetype: str, rel: str, stubborn: bool, cfg: dict | None = None) -> float:
    cfg = cfg or load()
    years = cfg["windows"][archetype]
    if rel == "结拜":
        years *= cfg["sworn_window_mult"]
    if stubborn:
        years *= cfg["stubborn"]["mult"]
    return years


# ---- 记账 -------------------------------------------------------------------

async def _upsert_grudge(session, holder_id: str, actor_id: str, victim_id: str, kind: str, reason: str, eff: float, rel: str,
                         arche: str | None, prof: dict, known: float, now: float, rng, cfg: dict) -> BotGrudge:
    """记一笔（或加重已有的一笔）仇：窗口、复仇方式、执着与否都在这里定。在调用方的事务里，不 commit。"""
    row = await session.get(BotGrudge, (holder_id, actor_id, victim_id))
    stubborn = bool(row.stubborn) if row else (
        bool(prof) and prof.get("loyalty", 0) >= cfg["stubborn"]["loyalty_min"] and rng.random() < cfg["stubborn"]["share"])
    until = known + years_to_seconds(window_years(arche, rel, stubborn, cfg)) if arche else 0.0
    style = (row.style if row and row.style else bot_profile.revenge_style(prof or None, rng)) if arche else ""
    sev = int(round(eff))
    if row is None:
        row = BotGrudge(holder_id=holder_id, target_id=actor_id, victim_id=victim_id, kind=kind, reason=reason,
                        severity=min(100, max(1, sev)), events=1, state="active", style=style, stubborn=stubborn,
                        created_at=now, known_at=known, window_until=until)
        session.add(row)
    else:
        if stronger(kind, row.kind, cfg) == kind:
            row.kind, row.reason = kind, reason
        row.severity, row.events = min(100, row.severity + max(1, sev)), row.events + 1
        row.state, row.window_until = "active", max(row.window_until, until)
        row.known_at = min(row.known_at, known) if row.known_at else known
    # 这个人对 actor 的其它旧账也重新激活（新仇勾起旧恨）
    await session.execute(update(BotGrudge).where(BotGrudge.holder_id == holder_id, BotGrudge.target_id == actor_id,
                                                  BotGrudge.state == "dormant").values(state="active", window_until=until))
    return row


async def add_known(holder_id: str, actor_id: str, victim_id: str, kind: str, reason: str, severity: int, rel: str,
                    rng=None, now: float | None = None) -> bool:
    """查清楚了：holder 现在知道是 actor 干的（调查结案用）。已死的 holder 不记。返回有没有记上。旁路。"""
    rng, now, cfg = rng or random.Random(), now or time.time(), load()
    try:
        async with AsyncSessionLocal() as session:
            await session.execute(update(Player).where(Player.discord_id == "").values(discord_id=""))
            holder = await session.get(Player, holder_id)
            if holder is None or holder.is_dead:
                await session.rollback()
                return False
            persona = await session.get(BotPersonality, holder_id)
            arche, prof = _persona(persona) if is_bot_id(holder_id) else (None, {})
            await _upsert_grudge(session, holder_id, actor_id, victim_id, kind, reason, float(severity), rel, arche, prof, now, now, rng, cfg)
            await session.commit()
        return True
    except Exception:
        log.warning("调查结案记仇失败：%s → %s", holder_id, actor_id, exc_info=True)
        return False


async def on_offense(actor_id: str, victim_id: str, kind: str, *, rng=None, now: float | None = None) -> list[dict]:
    """actor 对 victim 做了 kind（rob_fail / rob / cripple / kill）：受害者本人和关系网里的人按概率记仇。
    返回新记 / 加重的仇恨 [{holder, target, victim, kind, reason, severity, known_at}]。旁路：出错只记 warning。"""
    rng, now, cfg = rng or random.Random(), now or time.time(), load()
    k = cfg["kinds"][kind]
    out, pending = [], []
    try:
        async with AsyncSessionLocal() as session:
            await session.execute(update(Player).where(Player.discord_id == "").values(discord_id=""))      # 先拿写锁
            actor, victim = await session.get(Player, actor_id), await session.get(Player, victim_id)
            if actor is None or victim is None or actor_id == victim_id:
                await session.rollback()
                return []
            aname, vname, vfame, vcity = actor.name, victim.name, victim.fame, victim.current_city
            holders = []                                          # (holder_id, rel, 交情)
            if kind != "kill":
                holders.append((victim_id, "self", 100))
            ties = (await session.execute(select(BotTie).where(
                or_(BotTie.a_id == victim_id, BotTie.b_id == victim_id), BotTie.kind.in_(["结拜", "同门", "朋友", "相识"])))).scalars().all()
            for t in ties:
                other = t.b_id if t.a_id == victim_id else t.a_id
                if other != actor_id:
                    holders.append((other, t.kind, t.strength))
            ids = [h[0] for h in holders]
            players = {p.discord_id: p for p in (await session.execute(select(Player).where(Player.discord_id.in_(ids)))).scalars()} if ids else {}
            personas = {r.bot_id: r for r in (await session.execute(
                select(BotPersonality).where(BotPersonality.bot_id.in_([i for i in ids if is_bot_id(i)])))).scalars()} if ids else {}
            if not is_bot_id(victim_id) and kind == "kill":      # 玩家被杀：记进前世仇人（转世后还在）
                await session.merge(PlayerEnemy(player_id=victim_id, enemy_id=actor_id, life=int(victim.created_at), enemy_name=aname,
                                                reason=k["self"].format(actor=aname), since=now))
            reach = fame.reach(vfame)
            for holder_id, rel, strength in holders:
                p = players.get(holder_id)
                if p is None or p.is_dead:
                    continue
                arche, prof = _persona(personas.get(holder_id)) if is_bot_id(holder_id) else (None, {})
                eff = k["severity"] * cfg["relation"][rel]
                if prof:
                    eff *= cfg["formula"]["stat_base"] + (prof.get("vengeful", 50) if rel == "self" else prof.get("loyalty", 50)) / 100
                if rel != "self":
                    eff *= cfg["formula"]["strength_base"] + strength / 100
                    if eff < cfg["min_severity"] or rng.random() >= min(cfg["formula"]["third_cap"], eff / cfg["third_party_scale"]):
                        continue
                delay, investigate = 0.0, False
                if rel != "self" and reach != "server":
                    if reach == "city" and p.current_city != vcity:
                        delay = cfg["reach_delay_years"]["city_other"]
                    elif reach == "none":
                        if is_bot_id(holder_id):
                            investigate = True                   # 机器人朋友：自己去打听（可能向玩家问话），查到了才记仇
                        else:
                            if rng.random() >= cfg["reach_delay_years"]["none_learn_chance"]:
                                continue                          # 真人朋友：没听说
                            delay = rng.uniform(*cfg["reach_delay_years"]["none"])
                known = now + years_to_seconds(delay)
                reason = (k["self"] if rel == "self" else k["third"]).format(
                    actor=aname, victim=vname, rel=cfg["relation_names"].get(rel, ""))
                if investigate:                                   # 无名小卒出事：机器人朋友不会立刻知道，要自己去查（utils/bot_investigation.py）
                    pending.append({"seeker": holder_id, "missing": victim_id, "missing_name": vname, "culprit": actor_id, "culprit_name": aname,
                                    "kind": kind, "rel": rel, "severity": int(round(eff)), "reason": reason, "city": vcity})
                    continue
                row = await _upsert_grudge(session, holder_id, actor_id, victim_id, kind, reason, eff, rel, arche, prof, known, now, rng, cfg)
                out.append({"holder": holder_id, "target": actor_id, "victim": victim_id, "kind": kind, "reason": reason,
                            "severity": row.severity, "known_at": known})
            await session.commit()
    except Exception:
        log.warning("记仇失败：%s → %s %s", actor_id, victim_id, kind, exc_info=True)
        return []
    if pending:
        from utils import bot_investigation
        await bot_investigation.start(pending, rng, now)
    return out


# ---- 每日：续期 / 潜伏 / 淡去 ------------------------------------------------

async def grudge_day(day: str, rng=None, force: bool = False, now: float | None = None) -> dict:
    """每日处理（按日认领，幂等）：窗口到期的按性格掷骰续期，不续转潜伏；潜伏的仇恨缓慢淡去；死掉 / 消失的机器人名下的账清掉。"""
    rng, now, cfg = rng or random.Random(), now or time.time(), load()
    sm = {"renewed": 0, "dormant": 0, "faded": 0, "orphans": 0}
    try:
        async with AsyncSessionLocal() as session:
            await session.execute(update(Player).where(Player.discord_id == "").values(discord_id=""))
            claimed = await session.get(BotWorldState, GRUDGE_KEY)
            if claimed is not None and claimed.value == day and not force:
                await session.rollback()
                return {}
            await session.merge(BotWorldState(key=GRUDGE_KEY, value=day))
            alive = set((await session.execute(select(Player.discord_id).where(Player.is_bot == True, Player.is_dead == False))).scalars())  # noqa: E712
            holders = set((await session.execute(select(BotGrudge.holder_id).distinct())).scalars())
            gone = [h for h in holders if is_bot_id(h) and h not in alive]
            if gone:
                sm["orphans"] = (await session.execute(delete(BotGrudge).where(BotGrudge.holder_id.in_(gone)))).rowcount
            personas = {r.bot_id: r for r in (await session.execute(select(BotPersonality))).scalars()}
            due = (await session.execute(select(BotGrudge).where(BotGrudge.state == "active", BotGrudge.window_until > 0,
                                                                BotGrudge.known_at <= now, BotGrudge.window_until < now))).scalars().all()
            for g in due:
                arche, _prof = _persona(personas.get(g.holder_id))
                mx = cfg["renew"]["max_renewals"]
                p = min(cfg["formula"]["renew_cap"], cfg["renew"][arche] + g.severity / 100 * cfg["renew"]["severity_bonus_per_100"])
                if (mx is None or g.renewals < mx) and rng.random() < p:
                    g.window_until = now + years_to_seconds(window_years(arche, "self", g.stubborn, cfg))
                    g.renewals += 1
                    sm["renewed"] += 1
                else:
                    g.state = "dormant"
                    sm["dormant"] += 1
            decay = cfg["decay"]["dormant_per_day"]
            if decay:
                whole, frac = int(decay), decay - int(decay)
                for g in (await session.execute(select(BotGrudge).where(BotGrudge.state == "dormant"))).scalars().all():
                    g.severity -= whole + (1 if rng.random() < frac else 0)          # 小数部分按概率扣一点
                    if g.severity <= 0:
                        await session.delete(g)
                        sm["faded"] += 1
            await session.commit()
    except Exception:
        log.warning("仇恨每日处理失败", exc_info=True)
        return {}
    return sm


# ---- 查询 -------------------------------------------------------------------

def _row(g: BotGrudge) -> dict:
    return {"holder": g.holder_id, "target": g.target_id, "victim": g.victim_id, "kind": g.kind, "reason": g.reason,
            "severity": g.severity, "events": g.events, "state": g.state, "style": g.style, "stubborn": g.stubborn,
            "known_at": g.known_at, "window_until": g.window_until, "renewals": g.renewals, "last_ambush_at": g.last_ambush_at}


async def grudges_of(holder_id: str) -> list[dict]:
    """某人的仇人列表（带原因），按仇恨轻重排序。"""
    async with AsyncSessionLocal() as session:
        rows = (await session.execute(select(BotGrudge).where(BotGrudge.holder_id == holder_id).order_by(BotGrudge.severity.desc()))).scalars().all()
    return [_row(g) for g in rows]


async def grudges_against(target_id: str) -> list[dict]:
    async with AsyncSessionLocal() as session:
        rows = (await session.execute(select(BotGrudge).where(BotGrudge.target_id == target_id).order_by(BotGrudge.severity.desc()))).scalars().all()
    return [_row(g) for g in rows]


async def previous_enemies(player_id: str) -> list[dict]:
    async with AsyncSessionLocal() as session:
        rows = (await session.execute(select(PlayerEnemy).where(PlayerEnemy.player_id == player_id).order_by(PlayerEnemy.since.desc()))).scalars().all()
    return [{"enemy": r.enemy_id, "name": r.enemy_name, "reason": r.reason, "since": r.since, "life": r.life} for r in rows]


async def candidates_against(target_id: str, now: float | None = None) -> list[dict]:
    """现在有资格来蹲 target 的机器人（P4 拦路用）：窗口开着、已得知、人还活着，附上复仇方式、境界和『敢不敢』。"""
    now, cfg = now or time.time(), load()
    async with AsyncSessionLocal() as session:
        target = await session.get(Player, target_id)
        if target is None or target.is_dead:
            return []
        rows = (await session.execute(
            select(BotGrudge, Player.realm, Player.current_city)
            .join(Player, Player.discord_id == BotGrudge.holder_id)
            .where(BotGrudge.target_id == target_id, BotGrudge.state == "active", BotGrudge.known_at <= now,
                   BotGrudge.window_until >= now, Player.is_bot == True, Player.is_dead == False))).all()   # noqa: E712
    out = []
    for g, realm, city in rows:
        d = _row(g)
        d.update(holder_realm=realm, holder_city=city, ready=is_ready(g.style, realm, target.realm, cfg))
        out.append(d)
    return sorted(out, key=lambda d: -d["severity"])


async def format_list(player_id: str, limit: int = 10) -> str:
    """玩家的『仇人』文字：现世的在前，前世的在后。"""
    cur, prev = await grudges_of(player_id), await previous_enemies(player_id)
    if not cur and not prev:
        return ""
    lines = []
    async with AsyncSessionLocal() as session:
        names = dict((await session.execute(select(Player.discord_id, Player.name).where(
            Player.discord_id.in_([g["target"] for g in cur] or [""])))).all())
    for g in cur[:limit]:
        lines.append(f"• **{names.get(g['target'], '？')}**：{g['reason']}")
    if prev:
        lines.append("—— 前世的仇 ——")
        for e in prev[:limit]:
            lines.append(f"• **{e['name']}**：{e['reason']}")
    return "\n".join(lines)


# ---- 化解 -------------------------------------------------------------------

async def _reduce(session, holder_id: str, target_id: str, points: int) -> tuple[int, int]:
    """把 holder 对 target 的仇恨整体减 points（从最重的开始）。返回 (剩余总仇恨, 消除了几笔)。"""
    rows = (await session.execute(select(BotGrudge).where(BotGrudge.holder_id == holder_id, BotGrudge.target_id == target_id)
                                  .order_by(BotGrudge.severity.desc()))).scalars().all()
    removed = 0
    for g in rows:
        take = min(points, g.severity)
        g.severity -= take
        points -= take
        if g.severity <= 0:
            await session.delete(g)
            removed += 1
        if points <= 0:
            break
    return sum(g.severity for g in rows if g.severity > 0), removed


async def appease(player_id: str, holder_id: str, method: str, amount: int = 0, rng=None, now: float | None = None) -> dict:
    """玩家化解 holder 对自己的仇恨。method：stones（赔灵石，amount）/ apology（诚心道歉，看对方性格，有冷却）。
    返回 {"ok", "reason", "left"}。"""
    rng, now, cfg = rng or random.Random(), now or time.time(), load()["appease"]
    async with AsyncSessionLocal() as session:
        await session.execute(update(Player).where(Player.discord_id == "").values(discord_id=""))
        holder = await session.get(Player, holder_id)
        if holder is None or not holder.is_bot or holder.is_dead:
            await session.rollback()
            return {"ok": False, "reason": "对方已不在人世。", "left": 0}
        name = holder.name
        grudges = (await session.execute(select(BotGrudge).where(BotGrudge.holder_id == holder_id, BotGrudge.target_id == player_id))).scalars().all()
        total = sum(g.severity for g in grudges)                  # 回滚会让属性过期，先算好
        if not grudges:
            await session.rollback()
            return {"ok": False, "reason": f"**{name}** 并没有记恨你。", "left": 0}
        if method == "stones":
            amount = min(int(amount), cfg["max_stones"])
            if amount <= 0:
                await session.rollback()
                return {"ok": False, "reason": "赔礼的灵石数要大于 0。", "left": total}
            if not await spend_stones(session, player_id, amount):
                await session.rollback()
                return {"ok": False, "reason": "你的灵石不够。", "left": total}
            points = max(1, amount // cfg["stones_per_point"])
            left, removed = await _reduce(session, holder_id, player_id, points)
            await session.commit()
            text = f"**{name}** 收下了 {amount} 灵石的赔礼，" + ("多年的旧怨一笔勾销。" if not left else "怒意消了几分，但心结还在。")
            return {"ok": True, "reason": text, "left": left}
        if method == "apology":
            ap = cfg["apology"]
            last = max(g.last_apology for g in grudges)
            if now - last < ap["cooldown_hours"] * 3600:
                await session.rollback()
                return {"ok": False, "reason": f"**{name}** 刚听过你的道歉，过些时候再说吧。", "left": total}
            persona = await session.get(BotPersonality, holder_id)
            prof = json.loads(persona.profile) if persona and persona.profile else {}
            chance = min(ap["chance_cap"], ap["base"] + persona.kindness / 100 * ap["kind_weight"] + (100 - prof.get("vengeful", 50)) / 100 * ap["vengeful_weight"]) if persona else ap["base"]
            for g in grudges:
                g.last_apology = now
            if rng.random() < chance:
                left, removed = await _reduce(session, holder_id, player_id, ap["reduce"])
                await session.commit()
                return {"ok": True, "reason": f"**{name}** 沉默良久，叹了口气：「罢了，这笔账先放下一些。」", "left": left}
            for g in grudges:
                g.severity = min(100, g.severity + ap["backfire"])
            total = sum(g.severity for g in grudges)
            await session.commit()
            return {"ok": False, "reason": f"**{name}** 冷笑一声：「现在才来认错？晚了。」", "left": total}
        await session.rollback()
        return {"ok": False, "reason": "不知道这种赔礼方式。", "left": 0}


async def on_gift(player_id: str, holder_id: str, delta: int) -> int:
    """送礼让对方消气：好感加了 delta（>0）就减同样 gift_factor 倍的仇恨。返回消去的点数（旁路，出错只记 warning）。"""
    if delta <= 0:
        return 0
    try:
        points = max(1, int(delta * load()["appease"]["gift_factor"]))
        async with AsyncSessionLocal() as session:
            exists = await session.scalar(select(func.count()).select_from(BotGrudge).where(BotGrudge.holder_id == holder_id, BotGrudge.target_id == player_id))
            if not exists:
                return 0
            await _reduce(session, holder_id, player_id, points)
            await session.commit()
        return points
    except Exception:
        log.warning("送礼化解仇恨失败：%s %s", player_id, holder_id, exc_info=True)
        return 0


# ---- 清理 -------------------------------------------------------------------

async def remove_for(session, ids: list[str]) -> int:
    """机器人被清理：它恨的、恨它的账一并删掉。"""
    res = await session.execute(delete(BotGrudge).where(or_(BotGrudge.holder_id.in_(ids), BotGrudge.target_id.in_(ids))))
    return res.rowcount


async def archive_player(session, player_id: str, life: int) -> None:
    """玩家转世：机器人不再恨『新的他』（删掉以他为目标的账）；他自己的仇人列表存进前世记录（life = 上一世的编号，即旧角色的创建时间），现世的清掉。"""
    mine = (await session.execute(select(BotGrudge).where(BotGrudge.holder_id == player_id))).scalars().all()
    for g in mine:
        tname = await session.scalar(select(Player.name).where(Player.discord_id == g.target_id)) or "？"
        if await session.get(PlayerEnemy, (player_id, g.target_id, life)) is None:
            session.add(PlayerEnemy(player_id=player_id, enemy_id=g.target_id, life=life, enemy_name=tname, reason=g.reason, since=g.created_at))
    await session.execute(delete(BotGrudge).where(or_(BotGrudge.holder_id == player_id, BotGrudge.target_id == player_id)))
