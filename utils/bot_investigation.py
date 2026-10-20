"""失踪调查（U1·江湖百态）：没名气的机器人被杀，它的朋友不会立刻知道是谁干的，要自己去查。

用户 2026-10-12 的设计（A5 / K3）：普通机器人的死亡不该毫无痕迹，也不该无缘无故成为全服新闻；它的朋友会发现『这个人最近怎么不见了』，
于是开始找 —— 在城里遇到玩家就问『你最近有没有见过某某』，玩家用按钮回答（见过 / 没见过 / 不想说）。影响多大取决于名望、关系网和传播过程。

做法：
· `bot_grudges.on_offense` 发现受害者没名气（`fame.reach == "none"`）、替它出头的是机器人朋友时，不再『随机几年后知道 / 根本没听说』，而是开一份调查（`bot_missing`）；
· 调查有进度 0~100：每天自己涨一点（谨慎的涨得快），碰到玩家时问话，回答改变进度 ——
  凶手本人被问到：说『见过』等于露馅（+60）、『不想说』让它起疑（+25）、『没见过』是撒谎，有一定概率被识破（+40）；
  旁人被问到：和失踪者 / 凶手打过交道（有记忆）而回答『见过』是真线索（+12，它记你的情，好感 +3）；没打过交道却说『见过』是假线索，让它走了弯路（−3）；
· 到 100 就查清了：它记仇（进仇恨账，之后可以组团找凶手 —— P4）；拖得太久（默认 40 天）就放弃，只留下悲伤。
所有写入对其它系统都是旁路：出错只记 warning。
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
from utils import bot_grudges, bot_memory
from utils.db_async import AsyncSessionLocal, BotMissing, BotPersonality, BotWorldState, Player
from utils import settings_hub

log = logging.getLogger(__name__)

_PATH = Path(__file__).resolve().parent.parent / "data" / "bot_investigation.json"
DAY_KEY = "investigation_day"
HOUR = 3600
CHOICES = ("seen", "unseen", "silent")


@lru_cache(maxsize=1)
def _load() -> dict:
    return settings_hub.read(_PATH)


def load() -> dict:
    return _load()


def reload() -> None:
    _load.cache_clear()


def validate(cfg: dict) -> list[str]:
    errors = []
    a = cfg.get("ask", {})
    if not 0 <= a.get("chance", -1) <= 1 or a.get("per_player_cooldown_hours", -1) < 0:
        errors.append("ask: chance 0~1，per_player_cooldown_hours ≥ 0")
    p = cfg.get("progress", {})
    if p.get("daily_base", -1) < 0 or p.get("cautious_weight", -1) < 0 or p.get("give_up_days", 0) <= 0:
        errors.append("progress: daily_base / cautious_weight ≥ 0，give_up_days > 0")
    ans = cfg.get("answer", {})
    for k in ("killer_confess", "killer_slip_gain", "killer_silent", "witness_gain"):
        if not 0 <= ans.get(k, -1) <= 100:
            errors.append(f"answer.{k} 应在 0~100")
    if not 0 <= ans.get("killer_slip_chance", -1) <= 1:
        errors.append("answer.killer_slip_chance 应在 0~1")
    if ans.get("false_lead", 1) > 0:
        errors.append("answer.false_lead 应 ≤ 0（假线索让它走弯路）")
    return errors


def progress_delta(is_culprit: bool, choice: str, has_evidence: bool, slipped: bool, cfg: dict | None = None) -> int:
    """玩家的一次回答让调查进度变多少（纯函数）。slipped：凶手撒谎时有没有被识破。"""
    a = (cfg or load())["answer"]
    if is_culprit:
        return {"seen": a["killer_confess"], "silent": a["killer_silent"], "unseen": a["killer_slip_gain"] if slipped else 0}[choice]
    if choice == "seen":
        return a["witness_gain"] if has_evidence else a["false_lead"]
    return 0


def daily_gain(impulse: int, cfg: dict | None = None) -> int:
    """每天自己查能涨多少：基础 + 谨慎（冲动低）的人更有耐心。"""
    p = (cfg or load())["progress"]
    return max(0, int(round(p["daily_base"] + p["cautious_weight"] * (50 - impulse) / 50)))


# ---- 开案 -------------------------------------------------------------------

async def start(items: list[dict], rng=None, now: float | None = None) -> int:
    """开调查。items：bot_grudges.on_offense 给的 [{seeker, missing, missing_name, culprit, culprit_name, kind, rel, severity, reason, city}]。
    同一个 (seeker, missing, culprit) 只开一份。返回新开了几份。旁路。"""
    now = now or time.time()
    n = 0
    try:
        async with AsyncSessionLocal() as session:
            await session.execute(update(Player).where(Player.discord_id == "").values(discord_id=""))
            for it in items:
                exists = await session.scalar(select(BotMissing.id).where(
                    BotMissing.seeker_id == it["seeker"], BotMissing.missing_id == it["missing"],
                    BotMissing.culprit_id == it["culprit"], BotMissing.state == "active"))
                if exists:
                    continue
                session.add(BotMissing(id=uuid.uuid4().hex[:16], seeker_id=it["seeker"], missing_id=it["missing"], missing_name=it["missing_name"],
                                       culprit_id=it["culprit"], culprit_name=it["culprit_name"], kind=it["kind"], rel=it["rel"],
                                       severity=it["severity"], reason=it["reason"], city=it["city"], started_at=now, progress=0, state="active", asked="{}"))
                n += 1
            await session.commit()
    except Exception:
        log.warning("开失踪调查失败", exc_info=True)
        return 0
    return n


# ---- 问话 -------------------------------------------------------------------

async def maybe_question(player_id: str, present_ids: list[str], rng=None, now: float | None = None) -> dict | None:
    """玩家碰到了几个机器人：其中有人在找失踪的朋友，就可能问玩家『见过某某吗』。返回问话摘要（还没记账），没有返回 None。旁路。"""
    rng, now, cfg = rng or random.Random(), now or time.time(), load()
    try:
        present = set(present_ids)
        async with AsyncSessionLocal() as session:
            rows = (await session.execute(select(BotMissing).where(BotMissing.state == "active", BotMissing.seeker_id.in_(list(present) or [""])))).scalars().all()
            cands = []
            for r in rows:
                asked = json.loads(r.asked or "{}")
                if now - asked.get(player_id, 0) < cfg["ask"]["per_player_cooldown_hours"] * HOUR:
                    continue
                cands.append((r.id, r.seeker_id, r.missing_name))
        rng.shuffle(cands)
        for rid, seeker, mname in cands:
            if rng.random() >= cfg["ask"]["chance"] or await bc.gate(player_id, seeker, now):
                continue
            async with AsyncSessionLocal() as session:
                await session.execute(update(Player).where(Player.discord_id == "").values(discord_id=""))
                row = await session.get(BotMissing, rid)
                if row is None or row.state != "active":
                    await session.rollback()
                    continue
                asked = json.loads(row.asked or "{}")
                asked[player_id] = now
                row.asked = json.dumps(asked)
                bot = await session.get(Player, seeker)
                await session.commit()
            c = await bc.compose("investigation_ask", player_id, seeker, {"missing": mname}, rng=rng)
            if not c:
                continue
            await bc.record(player_id, seeker, now)
            return {"id": rid, "seeker_id": seeker, "seeker_name": bot.name, "seeker_realm": bot.realm, "missing_name": mname, "line": c["line"]}
    except Exception:
        log.warning("失踪调查问话失败：%s", player_id, exc_info=True)
    return None


async def answer(rid: str, player_id: str, choice: str, rng=None, now: float | None = None) -> dict:
    """玩家回答：seen（见过）/ unseen（没见过）/ silent（不想说）。返回 {"ok", "line", "delta", "progress", "resolved", "kind"}。"""
    rng, now, cfg = rng or random.Random(), now or time.time(), load()
    if choice not in CHOICES:
        return {"ok": False, "reason": "不知道这种回答。"}
    async with AsyncSessionLocal() as session:
        await session.execute(update(Player).where(Player.discord_id == "").values(discord_id=""))
        row = await session.get(BotMissing, rid)
        if row is None or row.state != "active":
            await session.rollback()
            return {"ok": False, "reason": "这件事已经有结果了。"}
        data = {"seeker": row.seeker_id, "missing": row.missing_id, "mname": row.missing_name, "culprit": row.culprit_id, "progress": row.progress}
    is_culprit = data["culprit"] == player_id
    mem_missing, mem_culprit = await bot_memory.recall(player_id, data["missing"]), await bot_memory.recall(player_id, data["culprit"])
    evidence = bool(mem_missing) or bool(mem_culprit)
    slipped = is_culprit and choice == "unseen" and rng.random() < cfg["answer"]["killer_slip_chance"]
    delta = progress_delta(is_culprit, choice, evidence and not is_culprit, slipped, cfg)
    progress = max(0, min(100, data["progress"] + delta))
    resolved = progress >= 100
    async with AsyncSessionLocal() as session:
        await session.execute(update(BotMissing).where(BotMissing.id == rid, BotMissing.state == "active").values(
            progress=progress, state="resolved" if resolved else "active"))
        await session.commit()
        row = await session.get(BotMissing, rid)
        info = {"kind": row.kind, "rel": row.rel, "severity": row.severity, "reason": row.reason, "missing": row.missing_id, "culprit": row.culprit_id,
                "seeker": row.seeker_id}
    if resolved:
        await bot_grudges.add_known(info["seeker"], info["culprit"], info["missing"], info["kind"], info["reason"], info["severity"], info["rel"], rng, now)
    from utils import bot_social
    helped = (not is_culprit) and choice == "seen" and evidence
    if helped:
        await bot_social.adjust_favor(player_id, data["seeker"], cfg["answer"]["helped_favor"])
    elif choice == "silent" and not is_culprit:
        await bot_social.adjust_favor(player_id, data["seeker"], cfg["answer"]["silent_favor"])
    scene = "investigation_found" if (resolved and is_culprit) else "investigation_thanks" if helped else "investigation_ack"
    c = await bc.compose(scene, player_id, data["seeker"], {"missing": data["mname"]}, rng=rng)
    return {"ok": True, "line": c["line"] if c else "", "delta": delta, "progress": progress, "resolved": resolved, "exposed": resolved and is_culprit,
            "bot_name": c["bot_name"] if c else ""}


# ---- 每天 -------------------------------------------------------------------

async def investigation_day(day: str, rng=None, force: bool = False, now: float | None = None) -> dict:
    """每日处理（按日认领，幂等）：每份调查自己涨一点进度；查清了记仇；拖太久 / 找的人没了就放弃。"""
    rng, now, cfg = rng or random.Random(), now or time.time(), load()
    sm = {"progressed": 0, "resolved": 0, "gave_up": 0}
    resolved = []
    try:
        async with AsyncSessionLocal() as session:
            await session.execute(update(Player).where(Player.discord_id == "").values(discord_id=""))
            claimed = await session.get(BotWorldState, DAY_KEY)
            if claimed is not None and claimed.value == day and not force:
                await session.rollback()
                return {}
            await session.merge(BotWorldState(key=DAY_KEY, value=day))
            alive = set((await session.execute(select(Player.discord_id).where(Player.is_bot == True, Player.is_dead == False))).scalars())   # noqa: E712
            personas = {r.bot_id: r for r in (await session.execute(select(BotPersonality))).scalars()}
            for r in (await session.execute(select(BotMissing).where(BotMissing.state == "active"))).scalars().all():
                if r.seeker_id not in alive or now - r.started_at > cfg["progress"]["give_up_days"] * 86400:
                    r.state = "gave_up"
                    sm["gave_up"] += 1
                    continue
                persona = personas.get(r.seeker_id)
                impulse = (json.loads(persona.profile) if persona and persona.profile else {}).get("impulse", 50)
                r.progress = min(100, r.progress + daily_gain(impulse, cfg))
                sm["progressed"] += 1
                if r.progress >= 100:
                    r.state = "resolved"
                    sm["resolved"] += 1
                    resolved.append((r.seeker_id, r.culprit_id, r.missing_id, r.kind, r.reason, r.severity, r.rel))
            await session.commit()
        for seeker, culprit, missing, kind, reason, severity, rel in resolved:
            await bot_grudges.add_known(seeker, culprit, missing, kind, reason, severity, rel, rng, now)
    except Exception:
        log.warning("失踪调查每日处理失败", exc_info=True)
        return {}
    return sm


async def active_for_culprit(culprit_id: str) -> int:
    """有几份调查在找这个人（调试 / 以后给玩家『有人在打听你』的线索用）。"""
    async with AsyncSessionLocal() as session:
        rows = (await session.execute(select(BotMissing.id).where(BotMissing.culprit_id == culprit_id, BotMissing.state == "active"))).scalars().all()
    return len(rows)


async def forget_player(session, player_id: str) -> None:
    """玩家转世：针对旧角色的调查作废（机器人不认识新的他）。"""
    await session.execute(delete(BotMissing).where(BotMissing.culprit_id == player_id))
