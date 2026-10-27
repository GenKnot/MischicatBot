"""关系网（U1·江湖百态 P2）：机器人之间、真人与机器人之间的『认识的人』。

用户 2026-10-12 的设计：
· 种类：相识 / 朋友 / 结拜（支持多人）/ 同门 / 仇敌；一个人认识多少人有上限（`capacity`，0~50，按性格随机，见 bot_profile）。
· 怎么认识：生成时就有一部分；同城的人慢慢结识；共同经历（组队、公共事件）认识。**一切都是概率**：性格相合（affinity）、同城、
  境界相近只提高概率，不保证；合不来的人也可能因共同经历成了朋友。
· 关系会变：朋友可能反目成仇，仇人可能和解，交情深的会结拜。
· 复仇者必须是关系网里真实存在的人（P3 用 `mourners` 找谁会替死者出头）。
· 真人 × 机器人：好感到了线自动成朋友 / 仇敌，好感够高可以结拜（`propose_bond`）。

存储：`bot_ties`，一对人一行（a_id < b_id）。每日社交在每日结算之后跑一次（`social_day`，按日认领，幂等），整个世界一次读进内存、
算完一次写回，2 万个机器人也只是几秒。配置在 data/bot_ties.json。
"""

import json
import logging
import random
import time
import uuid
from collections import Counter, defaultdict
from functools import lru_cache
from pathlib import Path

from sqlalchemy import delete, func, or_, select, update

from utils import bot_profile
from utils.bots import is_bot_id
from utils.db_async import AsyncSessionLocal, BotPersonality, BotTie, BotWorldState, Player
from utils.realms import REALMS, major_realm
from utils import settings_hub

log = logging.getLogger(__name__)

_PATH = Path(__file__).resolve().parent.parent / "data" / "bot_ties.json"
KINDS = ("相识", "朋友", "结拜", "同门", "仇敌")
FRIENDLY = ("朋友", "结拜", "同门")                       # 会替你出头的关系（mourners 用）
MAJORS = list(dict.fromkeys(major_realm(r) for r in REALMS))
SOCIAL_KEY = "social_day"


@lru_cache(maxsize=1)
def _load() -> dict:
    return settings_hub.read(_PATH)


def load() -> dict:
    return _load()


def reload() -> None:
    _load.cache_clear()


def validate(cfg: dict, archetypes: list[str] | None = None) -> list[str]:
    errors = []
    aff = cfg.get("affinity", {})
    if not (0 < aff.get("min", 0) <= aff.get("default", 0) <= 1):
        errors.append("affinity: 0 < min ≤ default ≤ 1")
    seen = set()
    for row in aff.get("pairs", []):
        if len(row) != 3 or not (0 <= row[2] <= 1):
            errors.append(f"affinity.pairs 每项应是 [原型, 原型, 0~1]：{row}")
            continue
        key = tuple(sorted(row[:2]))
        if key in seen:
            errors.append(f"affinity.pairs 重复：{key}")
        seen.add(key)
        if archetypes is not None and (row[0] not in archetypes or row[1] not in archetypes):
            errors.append(f"affinity.pairs 里有未知原型：{row}")
    for kind, r in cfg.get("start_strength", {}).items():
        if kind not in KINDS or not (0 <= r[0] <= r[1] <= 100):
            errors.append(f"start_strength.{kind} 应是 [最小, 最大]，0~100")
    if set(cfg.get("start_strength", {})) != set(KINDS):
        errors.append("start_strength 应覆盖所有关系种类")
    for key in ("meet_chance", "befriend_chance", "quarrel_base", "reconcile_base", "sworn_chance", "bond_extend_chance"):
        if not 0 <= cfg.get("daily", {}).get(key, -1) <= 1:
            errors.append(f"daily.{key} 应在 0~1")
    if not 2 <= cfg.get("daily", {}).get("bond_max", 0) <= 8:
        errors.append("daily.bond_max 应在 2~8")
    if cfg.get("daily", {}).get("quarrel_aff_base", -1) < 1 or cfg.get("daily", {}).get("party_meet_pairs", -1) < 0:
        errors.append("daily.quarrel_aff_base 应 ≥ 1（亲和度最高 1），party_meet_pairs 应 ≥ 0")
    if cfg.get("player", {}).get("enemy_recover_margin", -1) < 0:
        errors.append("player.enemy_recover_margin 不能为负")
    for key in ("same", "other"):
        if not 0 < cfg.get("city", {}).get(key, 0) <= 1:
            errors.append(f"city.{key} 应在 (0, 1]")
    k = cfg.get("knowing", {})
    if not (0 < k.get("base", 0) <= 1 and 0 < k.get("cap", 0) <= 1 and 0 <= k.get("friend_first_sight", -1) <= 1 and 0 <= k.get("enemy_first_sight", -1) <= 1):
        errors.append("knowing: base / cap 在 (0, 1]，first_sight 在 0~1")
    pl = cfg.get("player", {})
    if not (0 <= pl.get("accept_base", -1) <= 1 and 0 <= pl.get("accept_per_loyalty", -1) <= 0.01):
        errors.append("player.accept_base 0~1；accept_per_loyalty 0~0.01")
    return errors


def pair(a: str, b: str) -> tuple[str, str]:
    return (a, b) if a < b else (b, a)


# ---- 概率 -------------------------------------------------------------------

def affinity(arche_a: str, arche_b: str, cfg: dict | None = None) -> float:
    """两种性格有多合得来（0~1，对称）。"""
    cfg = cfg or load()
    a = cfg["affinity"]
    key = tuple(sorted((arche_a, arche_b)))
    for x, y, v in a["pairs"]:
        if tuple(sorted((x, y))) == key:
            return max(a["min"], v)
    return max(a["min"], a["default"])


def form_chance(a: dict, b: dict, context: str, cfg: dict | None = None) -> float:
    """两个人这次『认识』的概率：亲和度 × 同城 × 境界相近 × 事由。"""
    cfg = cfg or load()
    aff = affinity(a["arche"], b["arche"], cfg)
    city = cfg["city"]["same" if a["city"] == b["city"] else "other"]
    realm = max(cfg["realm"]["min"], 1 - abs(a["realm"] - b["realm"]) * cfg["realm"]["per_major_gap"])
    k = cfg["knowing"]
    return min(k["cap"], k["base"] * aff * city * realm * cfg["context"].get(context, 1.0))


def roll_kind(a: dict, b: dict, rng, cfg: dict | None = None) -> str:
    """刚认识时就是什么关系：多数只是相识，合得来的可能一见如故，合不来又记仇的可能一见就有梁子。"""
    cfg = cfg or load()
    aff = affinity(a["arche"], b["arche"], cfg)
    r, k = rng.random(), cfg["knowing"]
    if r < aff * k["friend_first_sight"]:
        return "朋友"
    if r > 1 - (1 - aff) * k["enemy_first_sight"] * (a["vengeful"] + b["vengeful"]) / 100:
        return "仇敌"
    return "相识"


# ---- 内存里的关系簿 ---------------------------------------------------------

class TieBook:
    """整个世界的关系，读进内存算完再一次写回。"""

    def __init__(self, infos: dict, ties: dict):
        self.infos, self.ties = infos, ties                    # ties: {(a, b): {kind, strength, bond_id, note}}
        self.count = Counter()
        for (a, b) in ties:
            self.count[a] += 1
            self.count[b] += 1
        self.new, self.changed = {}, set()
        self.events = []                                         # 当天的大事 [("quarrel", a, b) | ("sworn", [成员…])]，给传闻用

    def room(self, uid: str) -> bool:
        info = self.infos.get(uid)
        return info is None or self.count[uid] < info["cap"]          # 真人没有上限

    def add(self, a: str, b: str, kind: str, rng, cfg: dict, note: str = "", bond_id: str = "") -> bool:
        key = pair(a, b)
        if key in self.ties or a == b or not (self.room(a) and self.room(b)):
            return False
        row = {"kind": kind, "strength": rng.randint(*cfg["start_strength"][kind]), "bond_id": bond_id, "note": note}
        self.ties[key] = self.new[key] = row
        self.count[a] += 1
        self.count[b] += 1
        return True

    def set(self, key: tuple, **changes) -> None:
        self.ties[key].update(changes)
        if key not in self.new:
            self.changed.add(key)


async def _load_infos(session, ids=None) -> dict:
    q = (select(Player.discord_id, Player.realm, Player.current_city, BotPersonality.archetype, BotPersonality.home_city,
                BotPersonality.kindness, BotPersonality.pride, BotPersonality.profile)
         .join(BotPersonality, BotPersonality.bot_id == Player.discord_id)
         .where(Player.is_bot == True, Player.is_dead == False))                  # noqa: E712
    if ids is not None:
        q = q.where(Player.discord_id.in_(list(ids)))
    infos = {}
    for uid, realm, city, arche, home, kind, pride, profile in (await session.execute(q)).all():
        prof = json.loads(profile) if profile else {}
        infos[uid] = {"id": uid, "arche": arche, "city": home or city, "realm": MAJORS.index(major_realm(realm)),
                      "cap": prof.get("capacity", 10), "loyalty": prof.get("loyalty", 50), "vengeful": prof.get("vengeful", 50),
                      "lawful": prof.get("lawful", 50), "pride": pride, "kindness": kind}
    return infos


async def _load_ties(session, ids=None) -> dict:
    q = select(BotTie)
    if ids is not None:
        q = q.where(or_(BotTie.a_id.in_(list(ids)), BotTie.b_id.in_(list(ids))))
    return {(t.a_id, t.b_id): {"kind": t.kind, "strength": t.strength, "bond_id": t.bond_id, "note": t.note}
            for t in (await session.execute(q)).scalars()}


async def _persist(session, book: TieBook, now: float) -> None:
    for (a, b), row in book.new.items():
        session.add(BotTie(a_id=a, b_id=b, kind=row["kind"], strength=row["strength"], since=now, last_event=now,
                           bond_id=row["bond_id"], note=row["note"]))
    for (a, b) in book.changed:
        row = book.ties[(a, b)]
        await session.execute(update(BotTie).where(BotTie.a_id == a, BotTie.b_id == b).values(
            kind=row["kind"], strength=row["strength"], bond_id=row["bond_id"], note=row["note"], last_event=now))


# ---- 生成时：初始关系网 -----------------------------------------------------

def seed_book(book: TieBook, new_ids: list[str], rng, cfg: dict | None = None) -> None:
    """给新生成的机器人建初始关系：每人认识的人数 ≈ 容量的 15%~50%，多数在同城；另有一部分人属于一个同门小团体。"""
    cfg = cfg or load()
    seed = cfg["seed"]
    infos = book.infos
    alive = list(infos)
    by_city = defaultdict(list)
    for uid in alive:
        by_city[infos[uid]["city"]].append(uid)
    for uid in new_ids:
        me = infos.get(uid)
        if me is None:
            continue
        want = round(me["cap"] * rng.uniform(*seed["fraction_of_capacity"])) - book.count[uid]
        tries = seed["candidates"]
        while want > 0 and tries > 0 and len(alive) > 1:
            tries -= 1
            pool = by_city[me["city"]] if rng.random() < seed["same_city_share"] and len(by_city[me["city"]]) > 1 else alive
            other = rng.choice(pool)
            if other == uid or pair(uid, other) in book.ties:
                continue
            you = infos[other]
            if rng.random() < form_chance(me, you, "出生", cfg) and book.add(uid, other, roll_kind(me, you, rng, cfg), rng, cfg, "出生"):
                want -= 1
    # 同门小团体：同城的几个新人拜入同一个师门
    pool = [u for u in new_ids if u in infos]
    rng.shuffle(pool)
    n_members = int(len(pool) * seed["sect_group_share"])
    cities = defaultdict(list)
    for uid in pool[:n_members * 2]:
        cities[infos[uid]["city"]].append(uid)
    for members in cities.values():
        size = rng.randint(*seed["sect_group_size"])
        while len(members) >= 2 and n_members > 0:
            group, members = members[:size], members[size:]
            n_members -= len(group)
            form_group(book, group, "同门", rng, cfg, note="同门")
    # 出生就有的结拜兄弟：重义气的同城新人里，一小部分早就结拜了
    loyal = [u for u in new_ids if u in infos and infos[u]["loyalty"] >= cfg["daily"]["sworn_loyalty"]]
    rng.shuffle(loyal)
    cities = defaultdict(list)
    for uid in loyal[:int(len(new_ids) * seed["sworn_share"])]:
        cities[infos[uid]["city"]].append(uid)
    for members in cities.values():
        while len(members) >= 2:
            size = rng.randint(*seed["sworn_size"])
            group, members = members[:size], members[size:]
            if len(group) >= 2:
                form_group(book, group, "结拜", rng, cfg, note="结拜")


def form_group(book: TieBook, members: list[str], kind: str, rng, cfg: dict, note: str = "") -> str:
    """一群人结成 结拜 / 同门：两两之间都成为这种关系，共用一个团体编号。已有的相识 / 朋友 / 仇敌关系会被升级。"""
    bond = uuid.UUID(int=rng.getrandbits(128)).hex[:12]
    for i, a in enumerate(members):
        for b in members[i + 1:]:
            key = pair(a, b)
            if key in book.ties:
                book.set(key, kind=kind, bond_id=bond, note=note or book.ties[key]["note"],
                         strength=max(book.ties[key]["strength"], cfg["start_strength"][kind][0]))
            else:
                # 团体关系不受容量限制（已经说好的兄弟）
                row = {"kind": kind, "strength": rng.randint(*cfg["start_strength"][kind]), "bond_id": bond, "note": note}
                book.ties[key] = book.new[key] = row
                book.count[a] += 1
                book.count[b] += 1
    return bond


async def seed_new(new_ids: list[str], rng=None) -> int:
    """给刚生成的机器人建初始关系网（best effort，出错只记 warning）。返回新增的关系条数。"""
    rng = rng or random.Random()
    try:
        async with AsyncSessionLocal() as session:
            infos = await _load_infos(session)
            book = TieBook(infos, await _load_ties(session))
            seed_book(book, new_ids, rng)
            await _persist(session, book, time.time())
            await session.commit()
        return len(book.new)
    except Exception:
        log.warning("建立初始关系网失败", exc_info=True)
        return 0


# ---- 每日社交 ---------------------------------------------------------------

def social_book(book: TieBook, rng, cfg: dict | None = None) -> Counter:
    """一天的社交：同城碰面（认识 / 加深）→ 关系演变（反目 / 和解 / 结拜）。返回汇总。"""
    cfg = cfg or load()
    d = cfg["daily"]
    infos, sm = book.infos, Counter()
    by_city = defaultdict(list)
    for uid, info in infos.items():
        by_city[info["city"]].append(uid)
    for uid in list(infos):
        city = by_city[infos[uid]["city"]]
        if len(city) < 2 or rng.random() >= d["meet_chance"]:
            continue
        other = rng.choice(city)
        if other == uid:
            continue
        a, b, key = infos[uid], infos[other], pair(uid, other)
        aff = affinity(a["arche"], b["arche"], cfg)
        if key in book.ties:
            row = book.ties[key]
            if row["kind"] in ("相识", "朋友"):
                gain = int(rng.randint(*d["strength_gain"]) * (0.5 + aff))
                book.set(key, strength=min(100, row["strength"] + gain))
                if row["kind"] == "相识" and row["strength"] >= d["befriend_strength"] and rng.random() < d["befriend_chance"] * min(1, aff * 2):
                    book.set(key, kind="朋友")
                    sm["befriended"] += 1
        elif rng.random() < form_chance(a, b, "同城", cfg) and book.add(uid, other, roll_kind(a, b, rng, cfg), rng, cfg, "同城"):
            sm["met"] += 1
    friends_of = defaultdict(set)
    for (x, y), row in book.ties.items():
        if row["kind"] == "朋友":
            friends_of[x].add(y)
            friends_of[y].add(x)
    in_bond = {u for (x, y), r in book.ties.items() if r["kind"] == "结拜" for u in (x, y)}
    for key in list(book.ties):
        row = book.ties[key]
        a, b = infos.get(key[0]), infos.get(key[1])
        if a is None or b is None:                                         # 有真人的关系不在这里演变
            continue
        aff = affinity(a["arche"], b["arche"], cfg)
        if row["kind"] == "朋友":
            if rng.random() < d["quarrel_base"] * (d["quarrel_aff_base"] - aff) * (a["vengeful"] + b["vengeful"]) / 100:
                book.set(key, kind="仇敌", strength=rng.randint(*cfg["start_strength"]["仇敌"]), note="反目", bond_id="")
                book.events.append(("quarrel", key[0], key[1]))
                sm["quarrels"] += 1
            elif (row["strength"] >= d["sworn_strength"] and min(a["loyalty"], b["loyalty"]) >= d["sworn_loyalty"]
                  and key[0] not in in_bond and key[1] not in in_bond and rng.random() < d["sworn_chance"]):
                members = [key[0], key[1]]
                mutual = sorted((friends_of[key[0]] & friends_of[key[1]]) - in_bond)
                rng.shuffle(mutual)
                for m in mutual:
                    info = infos.get(m)
                    if len(members) >= d["bond_max"] or info is None or info["loyalty"] < d["sworn_loyalty"]:
                        continue
                    if rng.random() < d["bond_extend_chance"]:
                        members.append(m)
                form_group(book, members, "结拜", rng, cfg, note="结拜")
                book.events.append(("sworn", members))
                in_bond.update(members)
                sm["sworn"] += 1
        elif row["kind"] == "仇敌":
            if rng.random() < d["reconcile_base"] * (200 - a["vengeful"] - b["vengeful"]) / 100:
                book.set(key, kind="相识", strength=rng.randint(*cfg["start_strength"]["相识"]), note="和解")
                sm["reconciled"] += 1
    return sm


async def social_day(day: str, rng=None, force: bool = False) -> dict:
    """每日社交，一天只跑一次（按日认领，和每日结算一样幂等）。出错只记 warning。"""
    rng = rng or random.Random()
    try:
        async with AsyncSessionLocal() as session:
            await session.execute(update(Player).where(Player.discord_id == "").values(discord_id=""))      # 先拿写锁
            claimed = await session.get(BotWorldState, SOCIAL_KEY)
            if claimed is not None and claimed.value == day and not force:
                await session.rollback()
                return {}
            await session.merge(BotWorldState(key=SOCIAL_KEY, value=day))
            book = TieBook(await _load_infos(session), await _load_ties(session))
            sm = social_book(book, rng)
            await _persist(session, book, time.time())
            await session.commit()
        from utils import bot_feuds                                # 延迟导入：bot_feuds 反过来用到这里的 _load_infos
        sm["gossip"] = await bot_feuds.social_gossip(book.events, book.infos, rng)
        return {**sm, "new_ties": len(book.new)}
    except Exception:
        log.warning("机器人每日社交失败", exc_info=True)
        return {}


# ---- 共同经历 ---------------------------------------------------------------

async def meet_group(ids: list[str], context: str, rng=None, max_pairs: int | None = None) -> int:
    """一群机器人共同经历了一件事（组队 / 公共事件）：随机抽几对，按概率认识 / 加深。返回新认识的对数。出错只记 warning。"""
    rng = rng or random.Random()
    bots = [i for i in dict.fromkeys(ids) if is_bot_id(i)]
    if len(bots) < 2:
        return 0
    try:
        cfg = load()
        max_pairs = cfg["daily"]["party_meet_pairs"] if max_pairs is None else max_pairs
        async with AsyncSessionLocal() as session:
            await session.execute(update(Player).where(Player.discord_id == "").values(discord_id=""))
            book = TieBook(await _load_infos(session, bots), await _load_ties(session, bots))
            pairs = [(a, b) for i, a in enumerate(bots) for b in bots[i + 1:] if a in book.infos and b in book.infos]
            rng.shuffle(pairs)
            for a, b in pairs[:max_pairs]:
                key, ia, ib = pair(a, b), book.infos[a], book.infos[b]
                if key in book.ties:
                    row = book.ties[key]
                    if row["kind"] in ("相识", "朋友"):
                        book.set(key, strength=min(100, row["strength"] + rng.randint(*cfg["daily"]["strength_gain"])))
                elif rng.random() < form_chance(ia, ib, context, cfg):
                    book.add(a, b, roll_kind(ia, ib, rng, cfg), rng, cfg, context)
            await _persist(session, book, time.time())
            await session.commit()
        return len(book.new)
    except Exception:
        log.warning("共同经历建立关系失败：%s", context, exc_info=True)
        return 0


# ---- 查询 / 清理 ------------------------------------------------------------

async def ties_of(uid: str, kinds: tuple | None = None) -> list[dict]:
    """某人的全部关系 [{other, kind, strength, bond_id, note}]，按交情深浅排序。"""
    async with AsyncSessionLocal() as session:
        q = select(BotTie).where(or_(BotTie.a_id == uid, BotTie.b_id == uid))
        if kinds:
            q = q.where(BotTie.kind.in_(kinds))
        rows = (await session.execute(q)).scalars().all()
    out = [{"other": t.b_id if t.a_id == uid else t.a_id, "kind": t.kind, "strength": t.strength, "bond_id": t.bond_id, "note": t.note}
           for t in rows]
    return sorted(out, key=lambda r: -r["strength"])


async def mourners(uid: str) -> list[dict]:
    """某人死了，谁会替他出头：朋友 / 结拜 / 同门（仅限仍在世的机器人 + 真人），按交情深浅。P3 立仇用。"""
    return [t for t in await ties_of(uid, FRIENDLY)]


async def describe(uid: str, limit: int = 3) -> str:
    """资料页的一行：『关系：朋友 N · 结拜：甲、乙 · 同门 K · 仇家 M』。没有关系返回空串。"""
    ties = await ties_of(uid)
    if not ties:
        return ""
    names = {}
    async with AsyncSessionLocal() as session:
        ids = [t["other"] for t in ties if t["kind"] in ("结拜", "同门")][:limit]
        if ids:
            names = dict((await session.execute(select(Player.discord_id, Player.name).where(Player.discord_id.in_(ids)))).all())
    n = Counter(t["kind"] for t in ties)
    parts = []
    sworn = [names.get(t["other"], "?") for t in ties if t["kind"] == "结拜"][:limit]
    if sworn:
        parts.append(f"结拜兄弟：{'、'.join(sworn)}")
    if n["同门"]:
        parts.append(f"同门 {n['同门']} 人")
    if n["朋友"]:
        parts.append(f"朋友 {n['朋友']} 人")
    if n["仇敌"]:
        parts.append(f"仇家 {n['仇敌']} 人")
    if n["相识"]:
        parts.append(f"相识 {n['相识']} 人")
    return "关系：" + " · ".join(parts)


async def remove_for(session, ids: list[str]) -> int:
    """机器人被清理：它的所有关系一并删掉。"""
    res = await session.execute(delete(BotTie).where(or_(BotTie.a_id.in_(ids), BotTie.b_id.in_(ids))))
    return res.rowcount


async def forget_player(session, player_id: str) -> None:
    """玩家转世：和机器人的关系清掉（机器人默认不认识新的他）。"""
    await session.execute(delete(BotTie).where(or_(BotTie.a_id == player_id, BotTie.b_id == player_id)))


# ---- 真人 × 机器人 ----------------------------------------------------------

async def sync_player_tie(player_id: str, bot_id: str, favor: int) -> None:
    """好感变了：按线升级 / 降级真人与机器人的关系。相识 → 朋友（好感 ≥ friend_favor）；好感 ≤ enemy_favor 成仇敌；
    结拜之后好感掉到 betray_favor（-10）以下视为背义，反目成仇。出错只记 warning。"""
    try:
        cfg = load()["player"]
        a, b = pair(player_id, bot_id)
        now = time.time()
        async with AsyncSessionLocal() as session:
            row = await session.get(BotTie, (a, b))
            kind = row.kind if row else None
            if favor <= cfg["enemy_favor"]:
                want = "仇敌" if kind != "仇敌" else None
            elif kind == "结拜":
                want = "仇敌" if favor <= cfg["betray_favor"] else None
            elif favor >= cfg["friend_favor"]:
                want = "朋友" if kind in (None, "相识", "仇敌") else None
            else:
                want = "相识" if kind is None else ("相识" if kind == "仇敌" and favor > cfg["enemy_favor"] + cfg["enemy_recover_margin"] else None)
            if want is None:
                return
            if row is None:
                session.add(BotTie(a_id=a, b_id=b, kind=want, strength=favor if favor > 0 else 0, since=now, last_event=now, note="交往"))
            else:
                row.kind, row.last_event, row.bond_id = want, now, ""
            await session.commit()
    except Exception:
        log.warning("同步真人与机器人的关系失败：%s %s", player_id, bot_id, exc_info=True)


async def propose_bond(player_id: str, bot_id: str, favor: int, rng=None, now: float | None = None) -> dict:
    """真人向机器人提出结拜。条件：已是朋友、好感 ≥ sworn_favor；成不成看机器人的义气（40%~90%）；被拒绝后有冷却。
    返回 {"ok": bool, "reason": str}。"""
    rng, now, cfg = rng or random.Random(), now or time.time(), load()["player"]
    a, b = pair(player_id, bot_id)
    async with AsyncSessionLocal() as session:
        await session.execute(update(Player).where(Player.discord_id == "").values(discord_id=""))
        row = await session.get(BotTie, (a, b))
        bot = await session.get(Player, bot_id)
        if bot is None or not bot.is_bot or bot.is_dead:
            await session.rollback()
            return {"ok": False, "reason": "对方已不在人世。"}
        name = bot.name
        if row is not None and row.kind == "结拜":
            await session.rollback()
            return {"ok": False, "reason": f"你与 **{name}** 早已结为异姓兄弟。"}
        if row is None or row.kind != "朋友" or favor < cfg["sworn_favor"]:
            await session.rollback()
            return {"ok": False, "reason": f"**{name}** 与你的交情还不到结拜的地步（需要先成为朋友，且好感达到 {cfg['sworn_favor']}）。"}
        if row.note == "拒绝结拜" and now - row.last_event < cfg["refuse_cooldown_hours"] * 3600:
            await session.rollback()
            return {"ok": False, "reason": f"**{name}** 刚拒绝过你，过些日子再提吧。"}
        persona = await session.get(BotPersonality, bot_id)
        loyalty = (json.loads(persona.profile) if persona and persona.profile else {}).get("loyalty", 50)
        if rng.random() >= cfg["accept_base"] + loyalty * cfg["accept_per_loyalty"]:
            row.note, row.last_event = "拒绝结拜", now
            await session.commit()
            return {"ok": False, "reason": f"**{name}** 沉吟片刻，婉拒了：「结拜是大事，容我再想想。」"}
        row.kind, row.note, row.last_event = "结拜", "结拜", now
        row.bond_id = uuid.UUID(int=rng.getrandbits(128)).hex[:12]
        row.strength = max(row.strength, load()["start_strength"]["结拜"][0])
        await session.commit()
        return {"ok": True, "reason": f"你与 **{name}** 焚香结拜，从此以兄弟相称。"}
