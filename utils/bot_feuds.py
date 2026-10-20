"""机器人之间的恩怨（U1·江湖百态 F）：仇敌互相找茬、有仇的替朋友出头，打输的丢钱 / 丢修为 / 丢命。

之前机器人之间只有关系、不打也不聊；这里每天结算一次：
· 候选对子来自两处：`bot_ties` 里的『仇敌』关系，和 `bot_grudges` 里有效的仇恨账（持有者与目标都是机器人，也就是替朋友出头的复仇）；
· 每对按记仇度、仇恨轻重、是否同城掷骰，谨慎的人（grudges.ready）等自己境界够了才动手；
· 动手后比境界加随机，胜者按性格原型挑结果：口角 / 劫财 / 废修为 / 击杀；败者的朋友再记一笔仇（`bot_grudges.on_offense`），冤冤相报；
· 击杀每天全服有上限（补员补不过来世界会塌陷），整体可关；有看头的结果进江湖传闻（`rumors`），关系演变里的反目 / 结拜也会进传闻。
数值全在 data/bot_feuds.json。每个动作一个事务；出错只记 warning，不影响每日结算。
"""

import logging
import random
import time
from functools import lru_cache
from pathlib import Path

from sqlalchemy import select, update

from utils import bot_grudges, bot_ties, bot_world, rumors
from utils.atomic import grant_stones, spend_stones
from utils.db_async import AsyncSessionLocal, BotGrudge, BotPersonality, BotTie, BotWorldState, Player
from utils import settings_hub

log = logging.getLogger(__name__)

_PATH = Path(__file__).resolve().parent.parent / "data" / "bot_feuds.json"
DAY_KEY = "feud_day"
OUTCOMES = ("口角", "劫财", "废修为", "击杀")
KIND_OF = {"劫财": "rob", "废修为": "cripple", "击杀": "kill"}          # 对应 bot_grudges.kinds


@lru_cache(maxsize=1)
def _load() -> dict:
    return settings_hub.read(_PATH)


def load() -> dict:
    return _load()


def reload() -> None:
    _load.cache_clear()


def validate(cfg: dict, archetypes: list[str] | None = None) -> list[str]:
    errors = []
    for k in ("tie_chance", "grudge_chance", "cross_city_mult"):
        if not 0 <= cfg.get(k, -1) <= 1:
            errors.append(f"{k} 应在 0~1")
    if cfg.get("max_clashes_per_day", -1) < 0 or cfg.get("kills_per_day", -1) < 0 or cfg.get("grudge_kill_bonus", -1) < 0:
        errors.append("max_clashes_per_day / kills_per_day / grudge_kill_bonus 不能为负")
    if cfg.get("power", {}).get("realm_step", 0) <= 0 or cfg.get("power", {}).get("noise", -1) < 0:
        errors.append("power: realm_step > 0，noise ≥ 0")
    tables = {"default": cfg.get("outcomes", {}).get("default")} | dict(cfg.get("outcomes", {}).get("by_archetype", {}))
    for name, t in tables.items():
        if not isinstance(t, dict) or set(t) != set(OUTCOMES) or any(v < 0 for v in t.values()) or sum(t.values()) <= 0:
            errors.append(f"outcomes.{name}: 必须正好有 {OUTCOMES}，权重非负且总和 > 0")
    for a in archetypes or []:
        if a not in cfg.get("outcomes", {}).get("by_archetype", {}):
            errors.append(f"outcomes.by_archetype 缺性格原型 {a}")
    for k in ("rob", "kill"):
        s = cfg.get(k, {})
        if not 0 <= s.get("share", -1) <= 1 or s.get("cap", -1) < 0:
            errors.append(f"{k}: share 0~1，cap ≥ 0")
    if set(cfg.get("rumor", {})) != {"劫财", "废修为", "击杀"} or any(not 0 <= v <= 1 for v in cfg.get("rumor", {}).values()):
        errors.append("rumor: 需要 劫财 / 废修为 / 击杀，概率 0~1")
    s = cfg.get("social_rumors", {})
    if s.get("max_per_day", -1) < 0 or not 0 <= s.get("quarrel_chance", -1) <= 1 or not 0 <= s.get("sworn_chance", -1) <= 1:
        errors.append("social_rumors: max_per_day ≥ 0，两个概率 0~1")
    return errors


# ---- 纯逻辑：选对子、比胜负、挑结果 ------------------------------------------

def clash_chance(source: str, a: dict, b: dict, same_city: bool, severity: int = 0, cfg: dict | None = None) -> float:
    """一对仇家今天动手的概率。source：tie（仇敌关系，双方都可能先动手，取记仇度之和）/ grudge（a 是持仇的人，b 是目标）。"""
    cfg = cfg or load()
    if source == "tie":
        p = cfg["tie_chance"] * (a["vengeful"] + b["vengeful"]) / 100
    else:
        p = cfg["grudge_chance"] * (0.5 + severity / 100) * (0.5 + a["vengeful"] / 100)
    return min(1.0, p * (1 if same_city else cfg["cross_city_mult"]))


def ready(style: str, holder_realm: int, target_realm: int, grudge_cfg: dict | None = None) -> bool:
    """谨慎的等自己境界够了才动手（和拦路同一套 ready 配置）。"""
    return target_realm - holder_realm <= (grudge_cfg or bot_grudges.load())["ready"].get(style or "等待时机", 1)


def fight(attacker: dict, defender: dict, rng, cfg: dict | None = None) -> tuple[str, str]:
    """比胜负，返回 (胜者 id, 败者 id)。"""
    p = (cfg or load())["power"]
    score = lambda x: x["realm"] * p["realm_step"] + rng.uniform(0, p["noise"])           # noqa: E731
    sa, sd = score(attacker), score(defender)
    return (attacker["id"], defender["id"]) if sa >= sd else (defender["id"], attacker["id"])


def pick_outcome(archetype: str, kindness: int, grudge_severity: int, grudge_kind: str | None, rng, cfg: dict | None = None,
                 kills_left: int = 1) -> str:
    cfg = cfg or load()
    w = dict(cfg["outcomes"]["by_archetype"].get(archetype) or cfg["outcomes"]["default"])
    w["击杀"] *= max(0.0, 1.5 - kindness / 100)
    if grudge_kind == "kill":
        w["击杀"] *= 1 + grudge_severity / 100 * cfg["grudge_kill_bonus"]
    if not cfg["kill_enabled"] or kills_left <= 0:
        w["击杀"] = 0
    total = sum(w.values())
    if total <= 0:
        return "口角"
    r = rng.uniform(0, total)
    for name in OUTCOMES:
        r -= w[name]
        if r < 0 and w[name] > 0:
            return name
    return "口角"


# ---- 一场冲突 ---------------------------------------------------------------

async def _clash(winner: str, loser: str, outcome: str, cfg: dict) -> dict | None:
    """落地：一个事务里改钱 / 修为 / 生死。胜负双方有人已经不在了返回 None。"""
    async with AsyncSessionLocal() as session:
        await session.execute(update(Player).where(Player.discord_id == "").values(discord_id=""))
        w, l = await session.get(Player, winner), await session.get(Player, loser)
        if w is None or l is None or w.is_dead or l.is_dead or not w.is_bot or not l.is_bot:
            await session.rollback()
            return None
        wname, lname, city, lstones = w.name, l.name, l.current_city, l.spirit_stones
        amount = 0
        if outcome in ("劫财", "击杀"):
            s = cfg["rob" if outcome == "劫财" else "kill"]
            amount = min(int(lstones * s["share"]), s["cap"])
            if amount > 0 and await spend_stones(session, loser, amount):
                await grant_stones(session, winner, amount)
            else:
                amount = 0
        if outcome == "劫财" and amount == 0:
            outcome = "口角"                                    # 对方身上没油水
        elif outcome == "废修为":
            await session.execute(update(Player).where(Player.discord_id == loser).values(cultivation=0))
        elif outcome == "击杀":
            res = await session.execute(update(Player).where(Player.discord_id == loser, Player.is_dead == False)  # noqa: E712
                                        .values(is_dead=True, lifespan=0))
            if res.rowcount != 1:
                await session.rollback()
                return None
        await session.commit()
    return {"winner": winner, "loser": loser, "outcome": outcome, "amount": amount, "winner_name": wname, "loser_name": lname, "city": city}


async def _after(res: dict, rng, cfg: dict) -> None:
    """善后：败者的朋友记仇（击杀要在清理前做，关系网还在），进传闻，击杀的清走。"""
    out, win, lose = res["outcome"], res["winner"], res["loser"]
    if out in KIND_OF:
        await bot_grudges.on_offense(win, lose, KIND_OF[out], rng=rng)
    if out != "口角" and rng.random() < cfg["rumor"][out]:
        if out == "劫财":
            await rumors.record_rumor("bot_feud_rob", win, res["winner_name"], target=res["loser_name"], city=res["city"], amount=res["amount"])
        elif out == "废修为":
            await rumors.record_rumor("bot_feud_cripple", win, res["winner_name"], target=res["loser_name"], city=res["city"])
        else:
            await rumors.record_rumor("bot_feud_kill", win, res["winner_name"], target=res["loser_name"], city=res["city"])
    if out == "击杀":
        await bot_world.remove_bots([lose])


# ---- 每日 -------------------------------------------------------------------

async def feud_day(day: str, rng=None, force: bool = False, now: float | None = None) -> dict:
    """每日恩怨（按日认领，幂等）。返回汇总 {candidates, clashes, 口角, 劫财, 废修为, 击杀}。出错只记 warning。"""
    rng, now, cfg = rng or random.Random(), now or time.time(), load()
    sm = {"candidates": 0, "clashes": 0, **{o: 0 for o in OUTCOMES}}
    try:
        async with AsyncSessionLocal() as session:
            await session.execute(update(Player).where(Player.discord_id == "").values(discord_id=""))
            claimed = await session.get(BotWorldState, DAY_KEY)
            if claimed is not None and claimed.value == day and not force:
                await session.rollback()
                return {}
            await session.merge(BotWorldState(key=DAY_KEY, value=day))
            infos = await bot_ties._load_infos(session)
            ties = (await session.execute(select(BotTie).where(BotTie.kind == "仇敌"))).scalars().all()
            grudges = (await session.execute(select(BotGrudge).where(BotGrudge.state == "active", BotGrudge.known_at <= now))).scalars().all()
            cand = [("tie", t.a_id, t.b_id, 0, None, "") for t in ties if t.a_id in infos and t.b_id in infos]
            cand += [("grudge", g.holder_id, g.target_id, g.severity, g.kind, g.style) for g in grudges if g.holder_id in infos and g.target_id in infos]
            await session.commit()
        sm["candidates"] = len(cand)
        rng.shuffle(cand)
        gcfg, kills_left = bot_grudges.load(), cfg["kills_per_day"]
        for source, x, y, sev, gkind, style in cand:
            if sm["clashes"] >= cfg["max_clashes_per_day"]:
                break
            a, b = infos[x], infos[y]
            if source == "tie" and rng.random() < 0.5:
                a, b = b, a                                               # 仇敌关系里谁先动手随机
            if source == "grudge" and not ready(style, a["realm"], b["realm"], gcfg):
                continue
            if rng.random() >= clash_chance(source, a, b, a["city"] == b["city"], sev, cfg):
                continue
            win, lose = fight(a, b, rng, cfg)
            w = infos[win]
            async with AsyncSessionLocal() as session:
                kind_ = (await session.get(BotPersonality, win)).kindness
            outcome = pick_outcome(w["arche"], kind_, sev if win == a["id"] else 0, gkind if win == a["id"] else None, rng, cfg, kills_left)
            res = await _clash(win, lose, outcome, cfg)
            if res is None:
                continue
            sm["clashes"] += 1
            sm[res["outcome"]] += 1
            if res["outcome"] == "击杀":
                kills_left -= 1
            await _after(res, rng, cfg)
            for gone in ([lose] if res["outcome"] == "击杀" else []):
                infos.pop(gone, None)
    except Exception:
        log.warning("机器人每日恩怨失败", exc_info=True)
    return sm


async def social_gossip(events: list[tuple], infos: dict, rng=None) -> int:
    """关系演变里的反目 / 结拜进传闻（events：[("quarrel", a, b) | ("sworn", [成员…])]），每天有上限。返回记了几条。"""
    rng, cfg = rng or random.Random(), load()["social_rumors"]
    n = 0
    for ev in events:
        if n >= cfg["max_per_day"]:
            break
        kind, members = ev[0], list(ev[1:]) if ev[0] == "quarrel" else list(ev[1])
        if len(members) < 2 or any(m not in infos for m in members[:2]):
            continue
        if rng.random() >= cfg["quarrel_chance" if kind == "quarrel" else "sworn_chance"]:
            continue
        async with AsyncSessionLocal() as session:
            rows = {pid: (name, city) for pid, name, city in (await session.execute(
                select(Player.discord_id, Player.name, Player.current_city).where(Player.discord_id.in_(members[:2])))).all()}
        if len(rows) < 2:
            continue
        (an, city), (bn, _) = rows[members[0]], rows[members[1]]
        if kind == "quarrel":
            rid = await rumors.record_rumor("bot_quarrel", members[0], an, target=bn, city=city)
        else:
            rid = await rumors.record_rumor("bot_sworn", members[0], an, target=bn, city=city)
        n += 1 if rid else 0
    return n
