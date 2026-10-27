"""拦路遭遇（U1·江湖百态 P4）：记仇的机器人在野外找上玩家。

用户 2026-10-12 的设计 / 我的默认：
· 只在玩家**在线**、做野外动作（探险 / 前往秘地 / 采集）的当下判定一次；离线不触发；公共事件进行中不触发；管理员『拦路开关』关了不触发；
  幸福模式不拦路，正常模式最重废修为，**真实模式才可能杀人**（还要过 combat.can_kill_humans 和新手保护）。
· 谁来：`bot_grudges.candidates_against` 里窗口开着、敢动手的蹲守者；概率按大境界差（比你强 65% / 同阶 40% / 比你弱 20%），几个人一起找你时叠加；
  对同一个玩家两次被拦至少隔 3 游戏年（用户定），同一个蹲守者对同一个玩家至少隔 1 游戏年。重义气的会叫上结拜 / 朋友（≤2 人）。
· 你的结拜兄弟 / 朋友碰巧在同城，可能赶来：比拦路者强或一样强，拦路者悻悻而去；稍弱则帮你（逃跑 +20%、战力 +20%）。
· 玩家选 **逃跑 / 迎战**，1 分钟不选算逃跑。逃跑成功率 = 现有逃跑率 − 境界差 × 8%（− 同伴）；迎战按双方战力。
  赢了：不杀不劫由玩家决定（战后面板）；输了或逃跑失败：进入**交涉**，机器人先要个交代，玩家回应（诚恳道歉 / 敷衍认错 / 拒绝道歉 / 继续挑衅）或花钱买命，1 分钟不回应算拒绝。
· 最后处置按它的性格权重 × 仇恨轻重 × 行为画像 × 玩家的回应：放走 / 劫财 / 废修为（送到安全的城）/ 杀。被废或被杀后有保护期（默认 1 天，管理员可改）。

状态存在 `bot_encounters`，重启后由后台循环收尾（`process_expired`），不会让玩家卡在半路。逻辑层只返回字典，Discord 界面在 utils/views/ambush.py。
"""

import json
import logging
import random
import time
import uuid
from functools import lru_cache
from pathlib import Path

from sqlalchemy import delete, func, or_, select, update

from utils import bot_economy as be
from utils import bot_grudges, bot_memory, bot_profile, bot_ties, rumors, world_settings
from utils.atomic import grant_stones, spend_stones
from utils.bots import is_bot_id
from utils.character import years_to_seconds
from utils.db_async import (AsyncSessionLocal, BotEncounter, BotGrudge, BotPersonality, Player, PlayerAmbush)
from utils.realms import REALMS, get_realm_index, major_realm
from utils.world import CITIES
from utils import settings_hub

log = logging.getLogger(__name__)

_PATH = Path(__file__).resolve().parent.parent / "data" / "bot_ambush.json"
MAJORS = list(dict.fromkeys(major_realm(r) for r in REALMS))
OUTCOMES = ("release", "rob", "cripple", "kill")
DAY = 86400


@lru_cache(maxsize=1)
def _load() -> dict:
    return settings_hub.read(_PATH)


def load() -> dict:
    return _load()


def reload() -> None:
    _load.cache_clear()


def validate(cfg: dict, archetypes: list[str] | None = None) -> list[str]:
    errors = []
    for k in ("stronger", "equal", "weaker", "multi_cap", "other_city_factor"):
        if not 0 <= cfg.get("chance", {}).get(k, -1) <= 1:
            errors.append(f"chance.{k} 应在 0~1")
    if set(cfg.get("modes", [])) - {"幸福", "正常", "真实"}:
        errors.append("modes 里有未知模式")
    if cfg.get("global_cooldown_years", -1) < 0 or cfg.get("per_pair_years", -1) < 0:
        errors.append("冷却年数不能为负")
    for k in ("choose_seconds", "bargain_seconds"):
        if cfg.get("timeouts", {}).get(k, 0) < 5:
            errors.append(f"timeouts.{k} 至少 5 秒")
    table = cfg.get("outcome", {})
    if archetypes is not None and set(table) != set(archetypes):
        errors.append(f"outcome 应覆盖所有原型，差异：{sorted(set(table) ^ set(archetypes))}")
    for arche, w in table.items():
        if set(w) - set(OUTCOMES) or "release" not in w or not all(v >= 0 for v in w.values()) or sum(w.values()) <= 0:
            errors.append(f"outcome.{arche} 不合法（要有 release，只能用 {OUTCOMES}，权重非负）")
    if set(cfg.get("responses", {})) != {"apologize", "perfunctory", "refuse", "provoke"}:
        errors.append("responses 应是 apologize / perfunctory / refuse / provoke")
    for name, r in cfg.get("responses", {}).items():
        if not set(OUTCOMES) <= set(r) or not r.get("label"):
            errors.append(f"responses.{name} 要给每种处置一个倍数和 label")
    if archetypes is not None and set(cfg.get("buyout", {}).get("accept", {})) != set(archetypes):
        errors.append("buyout.accept 应覆盖所有原型")
    for k in ("rob", "buyout"):
        if not 0 < cfg.get(k, {}).get("share", 0) <= 1 or cfg.get(k, {}).get("cap", 0) <= 0:
            errors.append(f"{k}: share 0~1，cap > 0")
    if not 0 <= cfg.get("flee", {}).get("min", -1) <= cfg.get("flee", {}).get("max", -1) <= 1:
        errors.append("flee: 0 ≤ min ≤ max ≤ 1")
    sw = cfg.get("severity_weight", {})
    if sw.get("base", -1) < 0 or sw.get("release_div", 0) <= 0 or cfg.get("buyout", {}).get("severity_div", 0) <= 0:
        errors.append("severity_weight.base ≥ 0，severity_weight.release_div / buyout.severity_div > 0")
    n = cfg.get("fight", {}).get("noise", [])
    if not (isinstance(n, list) and len(n) == 2 and 0 < n[0] <= n[1]):
        errors.append("fight.noise 应是 [最小, 最大]，0 < 最小 ≤ 最大")
    if cfg.get("stuck_seconds", -1) < 0:
        errors.append("stuck_seconds 不能为负")
    return errors


def year_seconds(years: float) -> float:
    return years_to_seconds(years)


def major_index(realm: str) -> int:
    return MAJORS.index(major_realm(realm))


# ---- 纯函数：概率与权重 -----------------------------------------------------

def encounter_chance(holder_realm: str, player_realm: str, same_city: bool, cfg: dict | None = None) -> float:
    """单个蹲守者这次找上门的概率：比你强 / 同阶 / 比你弱，不在同城再打折。"""
    cfg = cfg or load()
    gap = major_index(holder_realm) - major_index(player_realm)
    base = cfg["chance"]["stronger" if gap > 0 else "equal" if gap == 0 else "weaker"]
    return base * (1.0 if same_city else cfg["chance"]["other_city_factor"])


def combine_chances(chances: list[float], context: str = "explore", cfg: dict | None = None) -> float:
    """几个人一起找你：至少一个找上门的概率，封顶 multi_cap，再乘动作类型系数。"""
    cfg = cfg or load()
    miss = 1.0
    for p in chances:
        miss *= 1 - p
    return min(cfg["chance"]["multi_cap"], (1 - miss) * cfg["contexts"].get(context, 1.0))


def companion_multiplier(n: int, cfg: dict | None = None) -> float:
    """同伴带来的战力倍数：人越多每多一个人的加成越小（幂递减），10 个人不会是 3.5 倍。"""
    c = (cfg or load())["companions"]
    return 1 + c["power_bonus"] * n ** c["power_exponent"]


def flee_rate(base_rate: float, leader_realm: str, player_realm: str, companions: int = 0, rescued: bool = False,
              cfg: dict | None = None) -> float:
    """逃跑成功率：玩家自己的逃跑率，被更强的人盯上更难逃，同伴越多越难逃，朋友赶来帮忙则容易些。"""
    cfg = cfg or load()
    gap = major_index(leader_realm) - major_index(player_realm)
    rate = base_rate - gap * cfg["flee"]["gap_per_major"] - cfg["companions"]["flee_penalty"] * companions ** cfg["companions"]["flee_exponent"] \
        + (cfg["rescue"]["flee_bonus"] if rescued else 0)
    return max(cfg["flee"]["min"], min(cfg["flee"]["max"], rate))


def outcome_weights(archetype: str, severity: int, grudge_kind: str, kindness: int, profile: dict | None, response: str,
                    can_kill: bool, rng=random, cfg: dict | None = None) -> dict[str, float]:
    """赢了之后的处置权重：性格底子 × 仇恨轻重 × 行为画像（善恶 / 守序 / 偶尔反常）× 玩家的回应；不能杀时杀并入废修为。"""
    cfg = cfg or load()
    w = {k: float(v) for k, v in cfg["outcome"][archetype].items()}
    sw = cfg["severity_weight"]
    for k in ("cripple", "kill"):
        if k in w:
            w[k] *= (sw["base"] + severity / 100) * sw[k]
    if "release" in w:
        w["release"] *= max(sw["release_floor"], 1 - severity / sw["release_div"])
    if grudge_kind == "kill" and "kill" in w:
        w["kill"] *= cfg["kill_grudge_bonus"]
    for k, f in bot_profile.captive_shift(kindness, profile, rng).items():
        if k in w:
            w[k] *= f
    for k, f in cfg["responses"][response].items():
        if k in w:
            w[k] *= f
    if not can_kill and "kill" in w:
        w["cripple"] = w.get("cripple", 0) + w.pop("kill")
    return w


def buyout_chance(archetype: str, severity: int, cfg: dict | None = None) -> float:
    cfg = cfg or load()
    return max(0.0, cfg["buyout"]["accept"][archetype] * (1 - severity / cfg["buyout"]["severity_div"]))


# ---- 门槛 -------------------------------------------------------------------

async def _in_public_event(session, player_id: str, now: float) -> bool:
    from utils.db_async import PublicEvent, PublicEventParticipant
    n = await session.scalar(select(func.count()).select_from(PublicEventParticipant)
                             .join(PublicEvent, PublicEvent.event_id == PublicEventParticipant.event_id)
                             .where(PublicEventParticipant.discord_id == player_id, PublicEvent.status == "active", PublicEvent.ends_at > now))
    return bool(n)


async def active_encounter(session, player_id: str) -> BotEncounter | None:
    return (await session.execute(select(BotEncounter).where(BotEncounter.target_id == player_id,
                                                              BotEncounter.stage.in_(["choose", "resolving", "bargain"])))).scalars().first()


async def blocked(player_id: str, now: float, cfg: dict) -> str | None:
    """不该拦路的原因（None = 可以）。"""
    settings = await world_settings.get_all()
    if settings["mode"] not in cfg["modes"]:
        return "mode"
    if not settings["ambush_enabled"]:
        return "switch"
    async with AsyncSessionLocal() as session:
        p = await session.get(Player, player_id)
        if p is None or p.is_bot or p.is_dead:
            return "player"
        if await active_encounter(session, player_id) is not None:
            return "busy"
        st = await session.get(PlayerAmbush, player_id)
        if st is not None and (st.protect_until > now or now - st.last_at < year_seconds(cfg["global_cooldown_years"])):
            return "cooldown"
        if await _in_public_event(session, player_id, now):
            return "public_event"
    return None


# ---- 触发 -------------------------------------------------------------------

async def maybe_ambush(player_id: str, context: str = "explore", rng=None, now: float | None = None) -> dict | None:
    """玩家刚做了一个野外动作：这次有没有人找上门？有就建好一次遭遇并返回摘要，没有返回 None。
    旁路：出错只记 warning（拦路坏了不能让探险跟着坏）。"""
    rng, now, cfg = rng or random.Random(), now or time.time(), load()
    try:
        if await blocked(player_id, now, cfg) is not None:
            return None
        cands = await bot_grudges.candidates_against(player_id, now)
        pair_gap = year_seconds(cfg["per_pair_years"])
        cands = [c for c in cands if c["ready"] and now - c["last_ambush_at"] >= pair_gap]
        if not cands:
            return None
        async with AsyncSessionLocal() as session:
            player = await session.get(Player, player_id)
            pcity, prealm = player.current_city, player.realm
            busy = set((await session.execute(select(BotEncounter.leader_id).where(BotEncounter.stage.in_(["choose", "resolving", "bargain"])))).scalars())
        cands = [c for c in cands if c["holder"] not in busy]
        if not cands:
            return None
        chances = [encounter_chance(c["holder_realm"], prealm, c["holder_city"] == pcity, cfg) for c in cands]
        if rng.random() >= combine_chances(chances, context, cfg):
            return None
        leader = cands[0]                                         # candidates_against 已按仇恨轻重排序
        lid = leader["holder"]
        companions = await _pick_companions(lid, player_id, pcity, rng, cfg, cands[1:])
        rescuer = await _pick_rescuer(player_id, pcity, rng, cfg)
        info = await _names(lid, leader["victim"], companions, rescuer)
        if rescuer and major_index(info["rescuer_realm"]) >= major_index(leader["holder_realm"]):
            await _mark(player_id, lid, now)                       # 朋友赶到，拦路者悻悻而去：这次也算被拦过（冷却照走）
            return {"aborted": True, "leader": info["leader"], "rescuer": info["rescuer"], "reason": leader["reason"]}
        enc_id = uuid.uuid4().hex[:16]
        async with AsyncSessionLocal() as session:
            await session.execute(update(Player).where(Player.discord_id == "").values(discord_id=""))
            if await active_encounter(session, player_id) is not None:
                await session.rollback()
                return None
            session.add(BotEncounter(id=enc_id, target_id=player_id, leader_id=lid, companions=json.dumps(companions), rescuer_id=rescuer or "",
                                     victim_id=leader["victim"], reason=leader["reason"], severity=leader["severity"], context=context,
                                     stage="choose", created_at=now, expires_at=now + cfg["timeouts"]["choose_seconds"]))
            await session.execute(update(Player).where(Player.discord_id.in_([lid, *companions])).values(current_city=pcity))   # 他们『赶到』了
            await session.commit()
        await _mark(player_id, lid, now)
        taunt = await _say("ambush_appear", player_id, lid, victim=info["victim_name"])
        return {"aborted": False, "id": enc_id, "leader": info["leader"], "companions": info["companions"], "rescuer": info["rescuer"],
                "reason": leader["reason"], "severity": leader["severity"], "taunt": taunt, "expires_at": now + cfg["timeouts"]["choose_seconds"],
                "victim": info["victim_name"], "context": context}
    except Exception:
        log.warning("拦路判定失败：%s %s", player_id, context, exc_info=True)
        return None


async def _mark(player_id: str, holder_id: str, now: float) -> None:
    async with AsyncSessionLocal() as session:
        await session.execute(update(Player).where(Player.discord_id == "").values(discord_id=""))
        st = await session.get(PlayerAmbush, player_id)
        if st is None:
            session.add(PlayerAmbush(player_id=player_id, last_at=now, protect_until=0, count=1))
        else:
            st.last_at, st.count = now, st.count + 1
        await session.execute(update(BotGrudge).where(BotGrudge.holder_id == holder_id, BotGrudge.target_id == player_id)
                              .values(last_ambush_at=now))
        await session.commit()


async def _pick_companions(leader_id: str, player_id: str, city: str, rng, cfg: dict, others: list[dict] | None = None) -> list[str]:
    """谁跟着一起来（人数不设上限，用户定）：① 拦路者的结拜 / 同门 / 朋友——按关系、各自的义气，不在同城打折；
    ② 城里爱打抱不平的路人；③ 同样记恨这个玩家的其它蹲守者（`others`，窗口开着、敢动手的）。都是掷骰，所以多数时候是三五个人，偶尔十来个。"""
    c = cfg["companions"]
    others = others or []
    ties = await bot_ties.ties_of(leader_id, ("结拜", "同门", "朋友"))
    async with AsyncSessionLocal() as session:
        busy = set((await session.execute(select(BotEncounter.leader_id).where(BotEncounter.stage.in_(["choose", "resolving", "bargain"])))).scalars())
        busy |= {x for e in (await session.execute(select(BotEncounter.companions).where(BotEncounter.stage.in_(["choose", "resolving", "bargain"])))).scalars()
                 for x in json.loads(e or "[]")}
        tie_ids = [t["other"] for t in ties]
        rows = {r.discord_id: r for r in (await session.execute(select(Player).where(
            Player.is_bot == True, Player.is_dead == False,                                         # noqa: E712
            or_(Player.current_city == city, Player.discord_id.in_(tie_ids or [""]))))).scalars()}   # 同城的路人 + 拦路者的亲友
        personas = {r.bot_id: r for r in (await session.execute(select(BotPersonality).where(BotPersonality.bot_id.in_(list(rows) or [""])))).scalars()}
    out, seen = [], {leader_id, player_id} | busy
    def add(uid):
        if uid not in seen and uid in rows:
            seen.add(uid)
            out.append(uid)
    def full():
        return c["max"] is not None and len(out) >= c["max"]
    def loyalty(uid):
        p = personas.get(uid)
        return (json.loads(p.profile) if p and p.profile else {}).get("loyalty", 50)
    for t in ties:
        if full():
            break
        uid = t["other"]
        if uid in rows and uid not in seen:
            p = c["join_chance"] * c["relation_weight"].get(t["kind"], 0.5) * (0.5 + loyalty(uid) / 100) * (1.0 if rows[uid].current_city == city else c["other_city_factor"])
            if rng.random() < p:
                add(uid)
    for o in others:                                               # 同样记恨你的蹲守者
        if full():
            break
        if o["holder"] not in seen and rng.random() < c["grudge_holder_chance"]:
            add(o["holder"])
    for uid, row in rows.items():                                  # 城里爱打抱不平的路人
        if full():
            break
        if uid in seen or row.current_city != city:
            continue
        p = personas.get(uid)
        prof = json.loads(p.profile) if p and p.profile else None
        if p and bot_profile.is_righteous(p.kindness, prof) and rng.random() < c["bystander_chance"]:
            add(uid)
    return out


async def _pick_rescuer(player_id: str, city: str, rng, cfg: dict) -> str:
    """玩家的结拜 / 朋友（机器人）碰巧在同城，可能赶来。返回机器人 ID，没有返回空串。"""
    ties = await bot_ties.ties_of(player_id, ("结拜", "朋友"))
    if not ties:
        return ""
    async with AsyncSessionLocal() as session:
        rows = (await session.execute(select(Player.discord_id, Player.current_city, BotPersonality.profile)
                                      .join(BotPersonality, BotPersonality.bot_id == Player.discord_id)
                                      .where(Player.discord_id.in_([t["other"] for t in ties]), Player.is_bot == True,
                                             Player.is_dead == False))).all()           # noqa: E712
    here = {uid: (json.loads(profile) if profile else {}).get("loyalty", 50) for uid, c, profile in rows if c == city}
    for t in ties:
        loyalty = here.get(t["other"])
        if loyalty is None:
            continue
        p = cfg["rescue"]["sworn" if t["kind"] == "结拜" else "friend"] * (cfg["rescue"]["loyalty_base"] + loyalty / 100)
        if rng.random() < min(cfg["rescue"]["cap"], p):
            return t["other"]
    return ""


async def _names(leader_id: str, victim_id: str, companions: list[str], rescuer: str) -> dict:
    ids = [i for i in {leader_id, victim_id, rescuer, *companions} if i]
    async with AsyncSessionLocal() as session:
        rows = {r.discord_id: r for r in (await session.execute(select(Player).where(Player.discord_id.in_(ids)))).scalars()}
    lead = rows[leader_id]
    victim = "我" if victim_id == leader_id else (rows[victim_id].name if victim_id in rows else "故人")
    out = {"leader": {"id": leader_id, "name": lead.name, "realm": lead.realm},
           "companions": [{"id": c, "name": rows[c].name, "realm": rows[c].realm} for c in companions if c in rows],
           "victim_name": victim, "rescuer": None, "rescuer_realm": ""}
    if rescuer and rescuer in rows:
        out["rescuer"] = {"id": rescuer, "name": rows[rescuer].name, "realm": rows[rescuer].realm}
        out["rescuer_realm"] = rows[rescuer].realm
    return out


async def _say(scene: str, player_id: str, bot_id: str, **fmt) -> str:
    from utils import bot_social
    try:
        return await bot_social.say(scene, player_id, bot_id, **fmt)
    except Exception:
        log.warning("取拦路台词失败：%s", scene, exc_info=True)
        return ""


# ---- 状态流转 ---------------------------------------------------------------

async def _claim(session, enc_id: str, old: str, new: str) -> BotEncounter | None:
    """把遭遇从 old 阶段推进到 new：条件 UPDATE，并发时只有一个调用者拿到。"""
    res = await session.execute(update(BotEncounter).where(BotEncounter.id == enc_id, BotEncounter.stage == old).values(stage=new))
    if res.rowcount != 1:
        return None
    return await session.get(BotEncounter, enc_id)


async def get_encounter(enc_id: str) -> dict | None:
    async with AsyncSessionLocal() as session:
        e = await session.get(BotEncounter, enc_id)
        if e is None:
            return None
        return {"id": e.id, "target": e.target_id, "leader": e.leader_id, "companions": json.loads(e.companions or "[]"),
                "rescuer": e.rescuer_id, "stage": e.stage, "price": e.price, "expires_at": e.expires_at, "reason": e.reason,
                "severity": e.severity, "channel_id": e.channel_id, "message_id": e.message_id, "result": e.result, "victim": e.victim_id}


async def set_message(enc_id: str, channel_id, message_id) -> None:
    async with AsyncSessionLocal() as session:
        await session.execute(update(BotEncounter).where(BotEncounter.id == enc_id).values(channel_id=str(channel_id), message_id=str(message_id)))
        await session.commit()


async def _finish(enc_id: str, result: str) -> None:
    async with AsyncSessionLocal() as session:
        await session.execute(update(BotEncounter).where(BotEncounter.id == enc_id).values(stage="done", result=result))
        await session.commit()


async def _load_sides(enc: BotEncounter | dict) -> tuple[dict, dict | None]:
    from utils.player import get_player
    target, leader = enc.target_id if hasattr(enc, "target_id") else enc["target"], enc.leader_id if hasattr(enc, "leader_id") else enc["leader"]
    return await get_player(target), await get_player(leader)


async def choose_flee(enc_id: str, rng=None, now: float | None = None) -> dict:
    """玩家选逃跑（或超时）。成功脱身；失败进入交涉。"""
    from utils.combat import calc_escape_rate
    rng, now, cfg = rng or random.Random(), now or time.time(), load()
    async with AsyncSessionLocal() as session:
        await session.execute(update(Player).where(Player.discord_id == "").values(discord_id=""))
        enc = await _claim(session, enc_id, "choose", "resolving")
        if enc is None:
            await session.rollback()
            return {"stage": "gone"}
        await session.commit()
        data = {"target": enc.target_id, "leader": enc.leader_id, "companions": json.loads(enc.companions or "[]"), "rescuer": enc.rescuer_id}
    player, leader = await _load_sides({"target": data["target"], "leader": data["leader"]})
    if player is None or leader is None or leader["is_dead"] or player["is_dead"]:
        await _finish(enc_id, "gone")
        return {"stage": "gone"}
    rate = flee_rate(await calc_escape_rate(player), leader["realm"], player["realm"], len(data["companions"]), bool(data["rescuer"]), cfg)
    if rng.random() < rate:
        await _finish(enc_id, "escaped")
        line = await _say("captive_release", data["target"], data["leader"])
        return {"stage": "escaped", "rate": rate, "line": line}
    return await _to_bargain(enc_id, data, player, leader, rate, rng, cfg, now)


async def choose_fight(enc_id: str, rng=None, now: float | None = None) -> dict:
    """玩家选迎战：比战力（同伴 / 朋友各有加成）。赢了结束（战后由玩家决定）；输了进入交涉。"""
    from utils.combat import calc_power
    from utils.bot_combat import power_multiplier
    rng, now, cfg = rng or random.Random(), now or time.time(), load()
    async with AsyncSessionLocal() as session:
        await session.execute(update(Player).where(Player.discord_id == "").values(discord_id=""))
        enc = await _claim(session, enc_id, "choose", "resolving")
        if enc is None:
            await session.rollback()
            return {"stage": "gone"}
        await session.commit()
        data = {"target": enc.target_id, "leader": enc.leader_id, "companions": json.loads(enc.companions or "[]"), "rescuer": enc.rescuer_id}
    player, leader = await _load_sides({"target": data["target"], "leader": data["leader"]})
    if player is None or leader is None or leader["is_dead"] or player["is_dead"]:
        await _finish(enc_id, "gone")
        return {"stage": "gone"}
    mine = await calc_power(player) * (1 + (cfg["rescue"]["power_bonus"] if data["rescuer"] else 0)) * rng.uniform(*cfg["fight"]["noise"])
    theirs = (await calc_power(leader)) * (await power_multiplier(leader)) * companion_multiplier(len(data["companions"]), cfg) * rng.uniform(*cfg["fight"]["noise"])
    if mine > theirs:
        await _finish(enc_id, "won")
        return {"stage": "won", "mine": round(mine, 1), "theirs": round(theirs, 1), "leader": leader["discord_id"]}
    return await _to_bargain(enc_id, data, player, leader, None, rng, cfg, now, powers=(round(mine, 1), round(theirs, 1)))


async def _to_bargain(enc_id, data, player, leader, rate, rng, cfg, now, powers=None) -> dict:
    price = min(int(player["spirit_stones"] * cfg["buyout"]["share"]), cfg["buyout"]["cap"])
    async with AsyncSessionLocal() as session:
        await session.execute(update(BotEncounter).where(BotEncounter.id == enc_id).values(
            stage="bargain", price=price, expires_at=now + cfg["timeouts"]["bargain_seconds"]))
        await session.commit()
        e = await session.get(BotEncounter, enc_id)
        victim_id = e.victim_id
    victim = await _victim_name(victim_id, leader["discord_id"])
    demand = await _say("ambush_demand", data["target"], data["leader"], victim=victim)
    return {"stage": "bargain", "rate": rate, "powers": powers, "demand": demand, "price": price,
            "expires_at": now + cfg["timeouts"]["bargain_seconds"], "leader": leader["discord_id"]}


async def _victim_name(victim_id: str, leader_id: str) -> str:
    if victim_id == leader_id:
        return "我"
    async with AsyncSessionLocal() as session:
        return (await session.scalar(select(Player.name).where(Player.discord_id == victim_id))) or "故人"


async def respond(enc_id: str, response: str, rng=None, now: float | None = None) -> dict:
    """交涉：apologize / perfunctory / refuse / provoke / buyout。返回最终处置 {"stage": "done", "outcome", ...}。"""
    rng, now, cfg = rng or random.Random(), now or time.time(), load()
    if response != "buyout" and response not in cfg["responses"]:
        return {"stage": "error", "reason": "不知道这种回应。"}
    async with AsyncSessionLocal() as session:
        await session.execute(update(Player).where(Player.discord_id == "").values(discord_id=""))
        enc = await _claim(session, enc_id, "bargain", "resolving")
        if enc is None:
            await session.rollback()
            return {"stage": "gone"}
        await session.commit()
        e = {"target": enc.target_id, "leader": enc.leader_id, "price": enc.price, "severity": enc.severity, "victim": enc.victim_id}
    player, leader = await _load_sides(e)
    if player is None or leader is None or leader["is_dead"] or player["is_dead"]:
        await _finish(enc_id, "gone")
        return {"stage": "gone"}
    async with AsyncSessionLocal() as session:
        persona = await session.get(BotPersonality, e["leader"])
        grudge = await session.get(BotGrudge, (e["leader"], e["target"], e["victim"]))
        arche = persona.archetype if persona else "憨直"
        kindness = persona.kindness if persona else 50
        profile = json.loads(persona.profile) if persona and persona.profile else None
        gkind = grudge.kind if grudge else ""
    bought = False
    if response == "buyout":
        if e["price"] <= 0 or player["spirit_stones"] < e["price"]:
            await _restore_bargain(enc_id, now, cfg)
            return {"stage": "bargain", "error": "灵石不够买命。"}
        if rng.random() < buyout_chance(arche, e["severity"], cfg):
            bought = True
        response = "perfunctory"                                 # 买命被拒：当作敷衍
    if bought:
        outcome, amount = "release", e["price"]
        async with AsyncSessionLocal() as session:
            await session.execute(update(Player).where(Player.discord_id == "").values(discord_id=""))
            if not await spend_stones(session, e["target"], amount):
                await session.rollback()
                await _finish(enc_id, "gone")
                return {"stage": "gone"}
            await grant_stones(session, e["leader"], amount)
            await session.commit()
        return await _conclude(enc_id, e, player, leader, outcome, amount, bought=True, now=now)
    can_kill = await _can_kill(player, cfg)
    weights = outcome_weights(arche, e["severity"], gkind, kindness, profile, response, can_kill, rng, cfg)
    names = list(weights)
    outcome = rng.choices(names, weights=[weights[n] for n in names])[0]
    return await _conclude(enc_id, e, player, leader, outcome, 0, bought=False, now=now)


async def _restore_bargain(enc_id: str, now: float, cfg: dict) -> None:
    async with AsyncSessionLocal() as session:
        await session.execute(update(BotEncounter).where(BotEncounter.id == enc_id, BotEncounter.stage == "resolving")
                              .values(stage="bargain"))
        await session.commit()


async def _can_kill(player: dict, cfg: dict) -> bool:
    ccfg = be.load_config()["combat"]
    if not (await world_settings.bots_can_kill_humans() and ccfg["can_kill_humans"]):
        return False
    return get_realm_index(player["realm"]) >= get_realm_index(ccfg["kill_protect_below"])


async def _conclude(enc_id: str, e: dict, player: dict, leader: dict, outcome: str, amount: int, *, bought: bool, now: float) -> dict:
    """落实处置：劫财 / 废修为 / 杀，记账、传闻、保护期。"""
    cfg, uid, lid = load(), e["target"], e["leader"]
    killed, new_city = False, ""
    settings = await world_settings.get_all()
    async with AsyncSessionLocal() as session:
        await session.execute(update(Player).where(Player.discord_id == "").values(discord_id=""))
        if outcome in ("rob", "kill") and not bought:
            amount = min(int(player["spirit_stones"] * cfg["rob"]["share"]), cfg["rob"]["cap"])
            if amount > 0 and await spend_stones(session, uid, amount):
                await grant_stones(session, lid, amount)
            else:
                amount = 0
                if outcome == "rob":
                    outcome = "release"                        # 身上没钱可劫，只好放走
        if outcome == "cripple":
            new_city = _safe_city(player["current_city"])
            await session.execute(update(Player).where(Player.discord_id == uid, Player.is_dead == False)       # noqa: E712
                                  .values(cultivation=0, current_city=new_city))
        elif outcome == "kill":
            res = await session.execute(update(Player).where(Player.discord_id == uid, Player.is_dead == False)    # noqa: E712
                                        .values(is_dead=True, lifespan=0))
            killed = res.rowcount == 1
        if outcome in cfg["safe_city_after"] or killed:
            st = await session.get(PlayerAmbush, uid)
            until = now + settings["death_protect_days"] * DAY
            if st is None:
                session.add(PlayerAmbush(player_id=uid, last_at=now, protect_until=until, count=1))
            else:
                st.protect_until = max(st.protect_until, until)
        await session.execute(update(BotEncounter).where(BotEncounter.id == enc_id).values(stage="done", result=outcome))
        await session.commit()
    if not killed:
        await bot_memory.remember(uid, lid, "defeated", "", "buyout" if bought else outcome)
    if killed:
        log.warning("机器人 %s 在拦路中击杀了真人 %s", lid, uid)
        await bot_grudges.on_offense(lid, uid, "kill")
        await rumors.record_rumor("bot_kills_human", uid, player["name"], target=leader["name"], city=player["current_city"])
    elif outcome == "rob":
        await bot_grudges.on_offense(lid, uid, "rob")
        await rumors.record_rumor("bot_robs_human", uid, player["name"], target=leader["name"], city=player["current_city"], amount=amount)
    elif outcome == "cripple":
        await bot_grudges.on_offense(lid, uid, "cripple")
    scene = {"release": "captive_release", "rob": "captive_rob", "cripple": "ambush_cripple", "kill": "captive_kill"}[outcome]
    line = await _say(scene, uid, lid, victim=await _victim_name(e["victim"], lid))
    return {"stage": "done", "outcome": outcome, "amount": amount, "killed": killed, "bought": bought, "line": line,
            "new_city": new_city, "leader": lid}


def _safe_city(current: str) -> str:
    choices = [c["name"] for c in CITIES if c["name"] != current]
    return random.choice(choices) if choices else current


# ---- 收尾 / 清理 ------------------------------------------------------------

async def process_expired(now: float | None = None, rng=None) -> list[dict]:
    """超时的遭遇收尾：选择阶段超时算逃跑，交涉阶段超时算拒绝。返回 [{encounter, result}]，供后台循环发消息。"""
    now = now or time.time()
    async with AsyncSessionLocal() as session:
        rows = (await session.execute(select(BotEncounter).where(BotEncounter.stage.in_(["choose", "bargain"]),
                                                                  BotEncounter.expires_at <= now))).scalars().all()
        todo = [(e.id, e.stage) for e in rows]
    out = []
    for enc_id, stage in todo:
        try:
            enc = await get_encounter(enc_id)
            result = await (choose_flee(enc_id, rng, now) if stage == "choose" else respond(enc_id, "refuse", rng, now))
            out.append({"encounter": enc, "result": result, "timed_out": True})
        except Exception:
            log.warning("拦路收尾失败：%s", enc_id, exc_info=True)
    return out


async def sweep_stuck(now: float | None = None, older_than: float | None = None) -> int:
    """卡在 resolving（处理到一半 bot 重启）超过 older_than 秒的遭遇直接结案，免得玩家一直被『有遭遇』挡着。"""
    now = now or time.time()
    older_than = load()["stuck_seconds"] if older_than is None else older_than
    async with AsyncSessionLocal() as session:
        res = await session.execute(update(BotEncounter).where(BotEncounter.stage == "resolving", BotEncounter.expires_at < now - older_than)
                                    .values(stage="done", result="stuck"))
        await session.commit()
    return res.rowcount


async def remove_for(session, ids: list[str]) -> int:
    """机器人被清理：以它为拦路者 / 救援者的遭遇删掉（选择中的玩家下次点按钮会得到『已结束』）。"""
    res = await session.execute(delete(BotEncounter).where(or_(BotEncounter.leader_id.in_(ids), BotEncounter.rescuer_id.in_(ids))))
    return res.rowcount


async def forget_player(session, player_id: str) -> None:
    """玩家转世：进行中的遭遇作废。保护期（player_ambush）保留 —— 刚被杀的新角色也受保护。"""
    await session.execute(delete(BotEncounter).where(BotEncounter.target_id == player_id))
