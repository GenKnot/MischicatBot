"""机器人修士的生成与清除（U1「江湖百态」）。

机器人是 `players` 里 `is_bot = 1` 的行（见 utils/bots.py），性格与偏好在 `bot_personality`（见 utils/bot_social.py）。
这里只管「放进世界」和「整批清走」：

· 档位：炮灰 60% / 正常 35% / 天骄 5%，决定境界、属性与随身灵石（`TIER_SPECS`）。本批只放低境界，
  每日结算（成长、打工、突破）还没做，所以不让他们高到碾压真人。
· 一次生成是**一个事务**：要么全进、要么全不进；数量与总量都有上限。
· 清除要把机器人名下的东西一起清干净（背包、装备、钱庄……），哪些表要清登记在 `CLEANUP`，
  有静态棘轮：新增带玩家 ID 的表却没登记，测试会红。
"""

import json
import random
import time
from pathlib import Path

from sqlalchemy import delete, func, select, update

from utils import bot_economy as be, rumors
from utils import bot_ambush, bot_chatter, bot_grudges, bot_profile, bot_ties, bot_traits
from utils.bot_legends import make_legend
from utils.bot_social import generate_personality
from utils.bots import BOT_ID_PREFIX
from utils.character import REALM_LIFESPAN, roll_spirit_root
from utils.db_async import (AdventureProgress, AlchemyMastery, AsyncSessionLocal, BankAccount, BankDeposit,
                            BotMemory, BotPersonality, BotRelation, BotRequest, BotWorldState, Equipment, Inventory, KnownRecipe, MarketListing,
                            Player, PublicEventParticipant, Residence, WanbaoFrozen)
from utils.realms import REALMS, cultivation_needed, get_realm_index, major_realm
from utils.world import CITIES

_NAMES = Path(__file__).resolve().parent.parent / "data" / "bot_names.json"

MAX_PER_BATCH = 2000
MAX_BOTS = 20000          # 目标上限；性能见 scripts/bench_bots.py 的压测结论（.gk/ISSUES.md）
DEFAULT_COUNT = 2000

TIER_WEIGHTS = {"炮灰": 60, "正常": 35, "天骄": 5}
# 境界范围（含）、五项属性范围、随身灵石范围
TIER_SPECS = {
    "炮灰": {"realms": ("炼气期1层", "炼气期5层"), "stats": (3, 6), "stones": (0, 100)},
    "正常": {"realms": ("炼气期4层", "筑基期3层"), "stats": (4, 8), "stones": (50, 400)},
    "天骄": {"realms": ("筑基期3层", "结丹期初期"), "stats": (7, 11), "stones": (300, 1500)},
}
_STAT_COLUMNS = ("comprehension", "physique", "fortune", "bone", "soul")


# ---- 道号 -------------------------------------------------------------------

def load_names() -> dict:
    return json.loads(_NAMES.read_text(encoding="utf-8"))


def _roll_name(rng: random.Random, names: dict) -> str:
    given = rng.choice(names["given_single"]) if rng.random() < 0.5 else (
        rng.choice(names["given_first"]) + rng.choice(names["given_second"]))
    return rng.choice(names["surnames"]) + given


def unique_name(rng: random.Random, names: dict, taken: set) -> str:
    """不与已有玩家 / 本批重名；词库抽干了就在名字后面加序号。"""
    for _ in range(200):
        name = _roll_name(rng, names)
        if name not in taken:
            return name
    base = _roll_name(rng, names)
    n = 2
    while f"{base}{n}" in taken:
        n += 1
    return f"{base}{n}"


# ---- 生成 -------------------------------------------------------------------

def _realms_between(lo: str, hi: str) -> list[str]:
    return REALMS[REALMS.index(lo):REALMS.index(hi) + 1]


def roll_tier(rng: random.Random) -> str:
    return rng.choices(list(TIER_WEIGHTS), weights=list(TIER_WEIGHTS.values()))[0]


def roll_player_fields(rng: random.Random, tier: str, bot_id: str, name: str, now: float,
                       ceiling_idx: int | None = None) -> dict:
    """`ceiling_idx`：机器人不能超过的境界下标（最高真人所在大境的末层）；出生就不能高过它。"""
    spec = TIER_SPECS[tier]
    realms = _realms_between(*spec["realms"])
    if ceiling_idx is not None:
        realms = be.realm_at_most(realms, ceiling_idx)
    realm = rng.choice(realms)
    lifespan_max = REALM_LIFESPAN[major_realm(realm)]
    spirit_root, root_type = roll_spirit_root(rng)
    return {
        "discord_id": bot_id, "name": name, "gender": rng.choice(["男", "女"]),
        "spirit_root": spirit_root, "spirit_root_type": root_type,
        **{k: rng.randint(*spec["stats"]) for k in _STAT_COLUMNS},
        "realm": realm, "cultivation": int(cultivation_needed(realm) * rng.uniform(0, 0.8)),
        "lifespan_max": lifespan_max, "lifespan": max(10, int(lifespan_max * rng.uniform(0.6, 1.0))),
        "spirit_stones": rng.randint(*spec["stones"]), "current_city": rng.choice(CITIES)["name"],
        "created_at": now, "last_active": now, "is_bot": True,
    }


async def get_state(session, key: str, default: str = "") -> str:
    row = await session.get(BotWorldState, key)
    return row.value if row else default


async def set_state(session, key: str, value: str) -> None:
    await session.merge(BotWorldState(key=key, value=value))


async def current_ceiling_index(session) -> int:
    """机器人当前不能超过的境界下标：最高在世真人所在的大境（见 bot_economy.ceiling_index）。"""
    realms = list((await session.execute(
        select(Player.realm).where(Player.is_bot == False, Player.is_dead == False))).scalars())  # noqa: E712
    top = max(realms, key=get_realm_index) if realms else None
    return be.ceiling_index(top, be.load_config())


async def bot_count(session) -> int:
    return await session.scalar(select(func.count()).select_from(Player).where(Player.is_bot == True))  # noqa: E712


VACANCY_KEY = "tianjiao_vacancy"        # 离场的天骄数（死 / 被杀 / 飞升），补员时优先补新秀天骄


async def generate_bots(count: int = DEFAULT_COUNT, rng: random.Random | None = None, *,
                        track_target: bool = True, fill_vacancies: bool = False) -> dict:
    """生成一批机器人。出生境界不超过当前天花板。`track_target`：把「目标人数」记成生成后的在世人数（补员用）；
    补员自己生成时传 False，不改目标。`fill_vacancies`（补员用）：先把离场天骄的空缺补成新秀天骄，并为每个天骄记「出世」传闻。
    天骄会得到称号和一句话背景（utils/bot_legends.py）。返回 {"ok", "created": [{id, name, tier, archetype, realm, city}], "by_tier": {...}} 或 {"ok": False, "reason"}。"""
    if not 1 <= count <= MAX_PER_BATCH:
        return {"ok": False, "reason": f"一次生成 1~{MAX_PER_BATCH} 个。"}
    rng, names, now = rng or random.Random(), load_names(), time.time()
    async with AsyncSessionLocal() as session:
        # 先拿写锁：「查现有数量 → 编号 → 写入」不能被另一次生成打断，否则会抢到同一个编号
        await session.execute(update(Player).where(Player.discord_id == "").values(discord_id=""))
        existing = await bot_count(session)
        if existing + count > MAX_BOTS:
            return {"ok": False, "reason": f"机器人总数上限 {MAX_BOTS}，现有 {existing}，最多还能生成 {MAX_BOTS - existing} 个。"}
        ceiling_idx = await current_ceiling_index(session)
        taken = set((await session.execute(select(Player.name))).scalars())
        last = await session.scalar(select(func.max(Player.discord_id)).where(Player.is_bot == True))  # noqa: E712
        next_no = int(last[len(BOT_ID_PREFIX):]) + 1 if last else 1
        created, by_tier = [], {t: 0 for t in TIER_WEIGHTS}
        vacancies = int(await get_state(session, VACANCY_KEY, "0") or 0) if fill_vacancies else 0
        titles_taken = set((await session.execute(select(BotPersonality.epithet).where(BotPersonality.epithet != ""))).scalars())
        for i in range(count):
            tier, bot_id = ("天骄" if i < vacancies else roll_tier(rng)), f"{BOT_ID_PREFIX}{next_no + i:05d}"
            name = unique_name(rng, names, taken)
            taken.add(name)
            fields = roll_player_fields(rng, tier, bot_id, name, now, ceiling_idx)
            session.add(Player(**fields))
            persona = generate_personality(rng)
            traits = bot_traits.roll_traits(persona["archetype"], persona["talk"], random.Random(f"{bot_id}:traits"))
            profile = bot_profile.roll_profile(persona["archetype"], traits["origin"], random.Random(f"{bot_id}:profile"))
            epithet = backstory = ""
            if tier == "天骄":
                epithet, backstory = make_legend(persona["archetype"], fields["current_city"], random.Random(bot_id), titles_taken)
            session.add(BotPersonality(
                bot_id=bot_id, archetype=persona["archetype"], tier=tier, home_city=fields["current_city"],
                epithet=epithet, backstory=backstory, traits=json.dumps(traits, ensure_ascii=False), profile=json.dumps(profile),
                kindness=persona["kindness"], greed=persona["greed"], pride=persona["pride"], talk=persona["talk"],
                likes=json.dumps(persona["likes"], ensure_ascii=False),
                dislikes=json.dumps(persona["dislikes"], ensure_ascii=False)))
            by_tier[tier] += 1
            created.append({"id": bot_id, "name": name, "tier": tier, "archetype": persona["archetype"],
                            "realm": fields["realm"], "city": fields["current_city"], "epithet": epithet, "backstory": backstory})
        if track_target:
            await set_state(session, "target", str(existing + count))
        if fill_vacancies:
            await set_state(session, VACANCY_KEY, str(max(0, vacancies - by_tier["天骄"])))
        await session.commit()
    await bot_ties.seed_new([c["id"] for c in created], rng)      # 初始关系网（认识的人、同门小团体）
    if fill_vacancies:                                       # 补员的新秀天骄露面；管理员一次性生成的不播（会刷屏）
        for c in created:
            if c["tier"] == "天骄":
                await rumors.record_rumor("tianjiao_debut", c["id"], c["name"], epithet=c["epithet"], legend=c["backstory"], city=c["city"])
    return {"ok": True, "created": created, "by_tier": by_tier}


# ---- 清除 -------------------------------------------------------------------

# 带玩家 ID 的表 -> 要按哪一列清（该列属于机器人的行全部删掉）
CLEANUP = {
    AdventureProgress: "discord_id", AlchemyMastery: "discord_id", BankAccount: "discord_id",
    BankDeposit: "discord_id", Equipment: "discord_id", Inventory: "discord_id", KnownRecipe: "discord_id",
    Residence: "discord_id", PublicEventParticipant: "discord_id", WanbaoFrozen: "discord_id",
    MarketListing: "seller_id", BotRelation: "bot_id", BotMemory: "bot_id", BotRequest: "bot_id", BotPersonality: "bot_id",
}
# 带玩家 ID 却不用清的表（原因写在这里，别悄悄略过）
CLEANUP_EXEMPT = {
    "players": "最后统一删",
    "parties": "队长只可能是真人（机器人不主动邀请）；机器人只是队员，删掉它的行即退队",
    "wanbao_lots": "机器人不参与万宝楼出价 / 上架",
    "bot_raids": "按真人的 ID 记每天打劫 / 击杀的次数，不是机器人名下的东西",
    "rumor_optout": "真人的『事迹不进传闻』开关",
    "bot_ties": "两个 ID 列（a_id / b_id）都可能是机器人：remove_bots 里单独处理（bot_ties.remove_for）",
    "bot_grudges": "holder_id / target_id 都可能是机器人：remove_bots 里单独处理（bot_grudges.remove_for）；victim_id 只是历史记录里的受害者",
    "chatter_state": "按真人的 ID 记今日搭话计数和屏蔽开关，不是机器人名下的东西",
    "chatter_pair": "bot_id 在 remove_bots 里单独清（bot_chatter.remove_for）",
    "chatter_queue": "speaker_id 在 remove_bots 里单独清（bot_chatter.remove_for）；player_id 是真人",
    "bot_encounters": "target_id 是真人；leader_id / rescuer_id 是机器人，remove_bots 里单独处理（bot_ambush.remove_for）",
    "player_ambush": "按真人的 ID 记最近一次被拦的时间和保护期，不是机器人名下的东西",
    "player_enemies": "玩家前世的仇人记录（enemy_id 可能是已经不在的机器人，记录本来就是历史）",
}
# 表里哪些列是玩家 ID（棘轮用）
PLAYER_KEY_COLUMNS = ("discord_id", "seller_id", "leader_id", "bidder_id", "player_id", "bot_id", "a_id", "b_id", "holder_id", "target_id", "victim_id", "enemy_id", "rescuer_id")


async def remove_bots(ids: list[str]) -> dict:
    """删除指定的机器人及其名下的东西。返回 {"removed": 删了几个, "rows": {表名: 行数}}。

    **只会删 `is_bot = 1` 的行**：传进来的 ID 先和数据库核对一遍，真人的 ID 混进来也删不掉（宁可漏删，不可错删）。
    """
    if not ids:
        return {"removed": 0, "rows": {}}
    async with AsyncSessionLocal() as session:
        await session.execute(update(Player).where(Player.discord_id == "").values(discord_id=""))
        ids = list((await session.execute(
            select(Player.discord_id).where(Player.discord_id.in_(ids), Player.is_bot == True))).scalars())  # noqa: E712
        if not ids:
            return {"removed": 0, "rows": {}}
        rows = {}
        gone = await session.scalar(select(func.count()).select_from(BotPersonality)
                                    .where(BotPersonality.bot_id.in_(ids), BotPersonality.tier == "天骄"))
        if gone:                                             # 天骄离场：留一个空缺，补员时优先补新秀
            await set_state(session, VACANCY_KEY, str(int(await get_state(session, VACANCY_KEY, "0") or 0) + gone))
        for model, column in CLEANUP.items():
            res = await session.execute(delete(model).where(getattr(model, column).in_(ids)))
            rows[model.__tablename__] = res.rowcount
        rows["chatter"] = await bot_chatter.remove_for(session, ids)
        rows["bot_encounters"] = await bot_ambush.remove_for(session, ids)
        rows["bot_grudges"] = await bot_grudges.remove_for(session, ids)
        rows["bot_ties"] = await bot_ties.remove_for(session, ids)       # 关系网：一对人一行，两头任何一个是它都删
        # 真人双修的搭档是机器人：搭档关系清掉（闭关本身照常结束）
        await session.execute(update(Player).where(Player.dual_partner_id.in_(ids)).values(dual_partner_id=None))
        res = await session.execute(delete(Player).where(Player.discord_id.in_(ids)))
        rows["players"] = res.rowcount
        await session.commit()
    return {"removed": len(ids), "rows": rows}


async def clear_bots() -> dict:
    """清除所有机器人及其名下的东西，并把目标人数归零（不再补员）。"""
    async with AsyncSessionLocal() as session:
        ids = list((await session.execute(select(Player.discord_id).where(Player.is_bot == True))).scalars())  # noqa: E712
    out = await remove_bots(ids)
    async with AsyncSessionLocal() as session:
        await session.execute(delete(BotWorldState))
        await session.commit()
    return out
