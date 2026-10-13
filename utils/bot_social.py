"""机器人的性格、偏好与好感度（U1「江湖百态」）。

· **性格**：原型（data/bot_archetypes.json）+ 四个 0~100 的数值（善意 / 贪婪 / 好胜 / 健谈）。
· **偏好**：喜欢 / 讨厌的物品**类别**各 1~2 个，外加 1~2 件具体的心头好 / 眼中钉。物品来自现有 items 表。
· **好感度**：真人 × 机器人一条记录，-100~100，分 仇视 / 陌生 / 熟识 / 至交 四档。送礼、闲聊会涨，送了讨厌的东西会跌。
· **闸门**：机器人愿不愿意组队 / 双修，由好感度和性格共同决定（`bot_gate`），规则是确定的、能告诉玩家差多少：
  组队要「熟识」(20)，双修要「至交」(50)；善意高的人门槛低、善意低的人门槛高（±10）。仇视的人一律拒绝。

结果都由代码判定，台词（以后）只负责说。涨跌好感一律在一个事务里，跟扣物品一起提交。
"""

import json
import random
import time
from pathlib import Path

from utils import bot_grudges, bot_memory, bot_ties
from utils.atomic import consume_item, grant_item, refuse_if_dead
from utils.bot_dialogue import get_line
from utils.bots import bot_refusal, is_bot_id
from utils.db_async import AsyncSessionLocal, BotPersonality, BotRelation, Player
from utils.items import ITEMS

_DATA = Path(__file__).resolve().parent.parent / "data" / "bot_archetypes.json"

# items 表的 type -> 玩家看到的类别名
CATEGORY_OF_TYPE = {"pill": "丹药", "herb": "药材", "ore": "矿石", "wood": "灵木", "fish": "灵鱼"}
CATEGORIES = tuple(CATEGORY_OF_TYPE.values())

FAVOR_MIN, FAVOR_MAX = -100, 100
TIER_HOSTILE, TIER_STRANGER, TIER_ACQUAINT, TIER_CLOSE = "仇视", "陌生", "熟识", "至交"
HOSTILE_BELOW = -30
# 各互动要的基础好感（再按善意 ±10）
BASE_REQUIRED = {"party": 20, "dual": 50}
CAPABILITY_TEXT = {"party": "组队", "dual": "双修"}

MAX_GIFTS_PER_DAY = 3            # 同一个机器人每天最多收你几份礼
GIFT_GAIN_DAILY_CAP = 12         # 每天靠送礼最多涨多少好感（跌不设限）
RARITY_BONUS = {"普通": 0, "稀有": 1, "珍贵": 2, "绝世": 3}
# 反应 -> 基础好感变化
GIFT_DELTA = {"love": 8, "like": 4, "neutral": 1, "dislike": -3, "hate": -8}
CHAT_DELTA, CHAT_DELTA_TALKATIVE, TALKATIVE_AT = 1, 2, 60


def category_of(item_name: str) -> str | None:
    item = ITEMS.get(item_name)
    return CATEGORY_OF_TYPE.get(item["type"]) if item else None


def _today() -> str:
    return time.strftime("%Y-%m-%d")


# ---- 性格生成 ---------------------------------------------------------------

def load_archetypes() -> dict:
    return json.loads(_DATA.read_text(encoding="utf-8"))["archetypes"]


def generate_personality(rng: random.Random | None = None, archetype: str | None = None) -> dict:
    """随机生成一个性格。传同样的 rng 种子得到同样的结果（便于测试与复现）。"""
    rng = rng or random.Random()
    archetypes = load_archetypes()
    archetype = archetype or rng.choice(sorted(archetypes))
    spec = archetypes[archetype]
    stats = {k: rng.randint(*spec[k]) for k in ("kindness", "greed", "pride", "talk")}
    like_cats = rng.sample(spec["likes"], k=min(len(spec["likes"]), rng.randint(1, 2)))
    dislike_cats = rng.sample(spec["dislikes"], k=min(len(spec["dislikes"]), rng.randint(1, 2)))

    def pick_items(cats, n):
        pool = sorted(name for name in ITEMS if category_of(name) in cats)
        return rng.sample(pool, k=min(n, len(pool)))

    return {
        "archetype": archetype, **stats,
        "likes": {"categories": like_cats, "items": pick_items(like_cats, rng.randint(1, 2))},
        "dislikes": {"categories": dislike_cats, "items": pick_items(dislike_cats, rng.randint(1, 2))},
    }


async def save_personality(bot_id: str, p: dict) -> None:
    async with AsyncSessionLocal() as session:
        await session.merge(BotPersonality(
            bot_id=bot_id, archetype=p["archetype"], kindness=p["kindness"], greed=p["greed"],
            pride=p["pride"], talk=p["talk"], tier=p.get("tier", "正常"),
            likes=json.dumps(p["likes"], ensure_ascii=False), dislikes=json.dumps(p["dislikes"], ensure_ascii=False),
        ))
        await session.commit()


def _personality_dict(row: BotPersonality) -> dict:
    return {"traits": json.loads(row.traits) if row.traits else None, "profile": json.loads(row.profile) if row.profile else None, "epithet": row.epithet, "backstory": row.backstory, "archetype": row.archetype, "tier": row.tier, "kindness": row.kindness, "greed": row.greed, "pride": row.pride,
            "talk": row.talk, "likes": json.loads(row.likes or "{}"), "dislikes": json.loads(row.dislikes or "{}")}


async def get_personality(bot_id: str) -> dict | None:
    async with AsyncSessionLocal() as session:
        row = await session.get(BotPersonality, bot_id)
        return _personality_dict(row) if row else None


# ---- 好感度 -----------------------------------------------------------------

def favor_tier(favor: int) -> str:
    if favor <= HOSTILE_BELOW:
        return TIER_HOSTILE
    if favor >= BASE_REQUIRED["dual"]:
        return TIER_CLOSE
    if favor >= BASE_REQUIRED["party"]:
        return TIER_ACQUAINT
    return TIER_STRANGER


def required_favor(capability: str, kindness: int = 50) -> int:
    """善意 0 → 门槛 +10，善意 100 → 门槛 -10。"""
    return BASE_REQUIRED[capability] + (50 - kindness) // 5


async def get_favor(player_id: str, bot_id: str) -> int:
    async with AsyncSessionLocal() as session:
        row = await session.get(BotRelation, (player_id, bot_id))
        return row.favor if row else 0


async def _relation(session, player_id: str, bot_id: str, today: str) -> BotRelation:
    """取（没有就建）关系行；跨天时把当日计数清零。调用方负责先拿到写锁。"""
    row = await session.get(BotRelation, (player_id, bot_id))
    if row is None:
        row = BotRelation(player_id=player_id, bot_id=bot_id, favor=0, last_interact=0, day=today,
                          gifts_today=0, gift_gain_today=0, chatted_today=0)
        session.add(row)
    elif row.day != today:
        row.day, row.gifts_today, row.gift_gain_today, row.chatted_today = today, 0, 0, 0
    return row


def _clamp(favor: int) -> int:
    return max(FAVOR_MIN, min(FAVOR_MAX, favor))


async def adjust_favor(player_id: str, bot_id: str, delta: int) -> int:
    """直接加减好感（给打劫 / 结仇等以后的玩法用）。返回新的好感。"""
    async with AsyncSessionLocal() as session:
        await _touch(session)
        row = await _relation(session, player_id, bot_id, _today())
        row.favor = _clamp(row.favor + delta)
        row.last_interact = time.time()
        await session.commit()
        favor = row.favor
    await bot_ties.sync_player_tie(player_id, bot_id, favor)          # 好感到了线：相识 → 朋友 / 仇敌
    return favor


async def _touch(session) -> None:
    """先做一次空写入拿写锁，之后的读 → 改 → 写才不会被并发打断。"""
    await session.execute(Player.__table__.update().where(Player.discord_id == "").values(discord_id=""))


# ---- 送礼 / 闲聊 ------------------------------------------------------------

def gift_reaction(personality: dict | None, item_name: str) -> tuple[str, int]:
    """(反应, 好感变化)。具体物品 > 类别；稀有度只给正向礼物加成。"""
    likes = (personality or {}).get("likes", {})
    dislikes = (personality or {}).get("dislikes", {})
    cat = category_of(item_name)
    if item_name in dislikes.get("items", []):
        return "hate", GIFT_DELTA["hate"]
    bonus = RARITY_BONUS.get(ITEMS[item_name].get("rarity"), 0)
    if item_name in likes.get("items", []):
        return "love", GIFT_DELTA["love"] + bonus
    if cat in dislikes.get("categories", []):
        return "dislike", GIFT_DELTA["dislike"]
    if cat in likes.get("categories", []):
        return "like", GIFT_DELTA["like"] + bonus
    return "neutral", GIFT_DELTA["neutral"] + bonus


async def _interaction_refusal(session, player: Player | None, bot: Player | None) -> str | None:
    if player is None or bot is None:
        return "对方不存在。"
    if is_bot_id(player.discord_id) or not is_bot_id(bot.discord_id):
        return "只能和机器人修士互动。"
    if (refused := await refuse_if_dead(session, player.discord_id)):
        return refused["reason"]
    if bot.is_dead:
        return f"**{bot.name}** 已经坐化了。"
    if player.current_city != bot.current_city:
        return f"**{bot.name}** 不在此地。"
    return None


async def give_gift(player_id: str, bot_id: str, item_name: str) -> dict:
    """送一件物品给机器人：物品转给机器人，按偏好加减好感。一个事务。"""
    if item_name not in ITEMS:
        return {"ok": False, "reason": "没有这种物品。"}
    async with AsyncSessionLocal() as session:
        await _touch(session)
        player, bot = await session.get(Player, player_id), await session.get(Player, bot_id)
        if (reason := await _interaction_refusal(session, player, bot)):
            return {"ok": False, "reason": reason}
        today = _today()
        rel = await _relation(session, player_id, bot_id, today)
        if rel.gifts_today >= MAX_GIFTS_PER_DAY:
            return {"ok": False, "code": "limit",
                    "reason": f"今天已经送过 {MAX_GIFTS_PER_DAY} 份礼了，**{bot.name}** 笑着摆了摆手。"}
        row = await session.get(BotPersonality, bot_id)
        reaction, delta = gift_reaction(_personality_dict(row) if row else None, item_name)
        if delta > 0:
            delta = min(delta, GIFT_GAIN_DAILY_CAP - rel.gift_gain_today)
        if not await consume_item(session, player_id, item_name, 1):
            return {"ok": False, "reason": f"背包里没有 **{item_name}**。"}
        await grant_item(session, bot_id, item_name, 1)
        rel.gifts_today += 1
        rel.gift_gain_today += max(0, delta)
        rel.favor = _clamp(rel.favor + delta)
        rel.last_interact = time.time()
        await session.commit()
        result = {"ok": True, "reaction": reaction, "delta": delta, "favor": rel.favor,
                  "tier": favor_tier(rel.favor), "bot_name": bot.name,
                  "gifts_left": MAX_GIFTS_PER_DAY - rel.gifts_today}
    await bot_memory.remember(player_id, bot_id, "gift", item_name, reaction)       # 记住这份礼（提交之后；旁路）
    await bot_ties.sync_player_tie(player_id, bot_id, result["favor"])
    await bot_grudges.on_gift(player_id, bot_id, result["delta"])           # 好礼能让对方消点气
    return result


async def chat(player_id: str, bot_id: str) -> dict:
    """闲聊：每天第一次涨一点好感（健谈的多涨一点），之后只是聊聊。"""
    async with AsyncSessionLocal() as session:
        await _touch(session)
        player, bot = await session.get(Player, player_id), await session.get(Player, bot_id)
        if (reason := await _interaction_refusal(session, player, bot)):
            return {"ok": False, "reason": reason}
        rel = await _relation(session, player_id, bot_id, _today())
        delta = 0
        first_today = not rel.chatted_today
        city = bot.current_city
        if not rel.chatted_today:
            row = await session.get(BotPersonality, bot_id)
            delta = CHAT_DELTA_TALKATIVE if row and row.talk >= TALKATIVE_AT else CHAT_DELTA
            rel.chatted_today = 1
            rel.favor = _clamp(rel.favor + delta)
        rel.last_interact = time.time()
        await session.commit()
        result = {"ok": True, "delta": delta, "favor": rel.favor, "tier": favor_tier(rel.favor), "bot_name": bot.name}
    if first_today:                                          # 每天只记一次（重复点『搭话』不算多聊）
        await bot_memory.remember(player_id, bot_id, "chat", "", city)
    await bot_ties.sync_player_tie(player_id, bot_id, result["favor"])
    return result


# ---- 台词 -------------------------------------------------------------------

async def say(scene: str, player_id: str, bot_id: str, **fmt) -> str:
    """机器人在某个场景下说的一句话：按它的原型和它对这个玩家的好感档位取台词（utils/bot_dialogue.py）。"""
    async with AsyncSessionLocal() as session:
        row = await session.get(BotPersonality, bot_id)
        rel = await session.get(BotRelation, (player_id, bot_id))
        player, bot = await session.get(Player, player_id), await session.get(Player, bot_id)
    traits = json.loads(row.traits) if row and row.traits else None
    archetype, tier = row.archetype if row else None, favor_tier(rel.favor if rel else 0)
    names = {"player": player.name if player else "道友", "bot": bot.name if bot else "在下"}
    line = get_line(archetype, scene, tier, traits=traits, **names, **fmt)
    if scene in bot_memory.RECALL_SCENES:                    # 偶尔追加一句回忆（纯文案）
        picked = bot_memory.pick_recall(await bot_memory.recall(player_id, bot_id), scene, tier,
                                        (traits or {}).get("introversion", "中性"))
        if picked:
            line += get_line(archetype, picked[0], tier, traits=traits, **names, **picked[1])
    return line


# ---- 闸门 -------------------------------------------------------------------

async def bot_gate(capability: str, a_id: str, b_id: str) -> str | None:
    """涉及机器人的组队 / 双修是否允许。允许返回 None，否则返回写给玩家的理由。

    两个都是真人：None。机器人之间：不允许（机器人只和真人互动）。
    """
    a_bot, b_bot = is_bot_id(a_id), is_bot_id(b_id)
    if not (a_bot or b_bot):
        return None
    if (refused := bot_refusal(capability, a_id, b_id)):      # 总开关
        return refused
    text = CAPABILITY_TEXT[capability]
    if a_bot and b_bot:
        return f"机器人修士之间不会{text}。"
    player_id, bot_id = (b_id, a_id) if a_bot else (a_id, b_id)
    async with AsyncSessionLocal() as session:
        bot = await session.get(Player, bot_id)
        row = await session.get(BotPersonality, bot_id)
        rel = await session.get(BotRelation, (player_id, bot_id))
    name = bot.name if bot else "对方"
    favor = rel.favor if rel else 0
    if favor_tier(favor) == TIER_HOSTILE:
        return f"**{name}** 对你怀恨在心，不愿与你{text}。"
    need = required_favor(capability, row.kindness if row else 50)
    if favor < need:
        return f"**{name}** 与你交情尚浅（好感 {favor}/{need}），不愿与你{text}。多聊聊天、送些对方喜欢的东西吧。"
    return None
