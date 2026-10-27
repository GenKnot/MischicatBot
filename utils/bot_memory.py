"""机器人对真人的记忆（U1·关系记忆）。**纯文案，不改任何数值**。

记什么（用户 2026-10-12 定）：送过的礼物 · 聊天次数与上次见面 · 被打劫 / 废修为 · 一起组队 / 双修 · 你攻击它却输了。
记多久（按重要程度）：礼物最近 8 件；其余每种只有一行（次数 + 最近一次），所以大事不会被冲掉；机器人没了记忆也没了。
怎么体现：① 对话里偶尔（约 20%~30%，内向的少、外向的多；结仇后第一次见面、久别重逢更容易）追加一句回忆（`recall_*` 场景，
按性格原型分别写，见 data/bot_dialogues）；② 资料页的『交往』一行。

所有写入都是旁路：出错只记 warning，不影响主流程（和传闻一样）。
"""

import json
import logging
import random
import time
from functools import lru_cache
from pathlib import Path

from sqlalchemy import delete, select

from utils import settings_hub
from utils.db_async import AsyncSessionLocal, BotMemory

log = logging.getLogger(__name__)

_PATH = Path(__file__).resolve().parent.parent / "data" / "bot_memory.json"
DAY = 86400
LEVELS = ("内向", "偏内向", "中性", "偏外向", "外向")


@lru_cache(maxsize=1)
def _load() -> dict:
    return settings_hub.read(_PATH)


def load() -> dict:
    return _load()


def reload() -> None:
    _load.cache_clear()


def validate(cfg: dict) -> list[str]:
    errors = []
    if cfg.get("max_gifts", 0) < 1 or cfg.get("absence_days", 0) < 1 or cfg.get("familiar_chats", 0) < 1 or cfg.get("shared_min", 0) < 1:
        errors.append("max_gifts / absence_days / familiar_chats / shared_min 应 ≥ 1")
    r = cfg.get("recall", {})
    if not (0 <= r.get("base", -1) <= 1 and 0 <= r.get("cap", -1) <= 1 and 0 <= r.get("boost_p", -1) <= 1):
        errors.append("recall: base / cap / boost_p 应在 0~1")
    lf = r.get("level_factor", {})
    if set(lf) != set(LEVELS) or any(v < 0 for v in lf.values()):
        errors.append(f"recall.level_factor 需要 {LEVELS}，系数非负")
    return errors


# 哪些场景后面可以追加回忆；礼物场景不提『送过的礼物』（刚送的那件就是现在这件）
RECALL_SCENES = {"greet", "chat_again", "gift_love", "gift_like", "gift_neutral", "gift_dislike", "gift_hate",
                 "gift_limit", "party_accept", "party_refuse", "dual_accept", "dual_refuse"}
KINDS = ("gift", "chat", "robbed", "crippled", "party", "dual", "defeated")


async def remember(player_id: str, bot_id: str, kind: str, detail: str = "", extra: str = "",
                   now: float | None = None) -> None:
    """记一笔（同一个 种类+细节 累加次数，更新最近一次）。出错只记 warning。"""
    now = now or time.time()
    try:
        async with AsyncSessionLocal() as session:
            row = await session.get(BotMemory, (player_id, bot_id, kind, detail))
            if row is None:
                session.add(BotMemory(player_id=player_id, bot_id=bot_id, kind=kind, detail=detail, count=1, extra=extra,
                                      first_at=now, prev_at=0, last_at=now))
            else:
                row.prev_at, row.last_at, row.count = row.last_at, now, row.count + 1
                if extra:
                    row.extra = extra
            await session.flush()
            if kind == "gift":                                # 礼物只留最近 max_gifts 件
                keep = list((await session.execute(
                    select(BotMemory.detail).where(BotMemory.player_id == player_id, BotMemory.bot_id == bot_id,
                                                   BotMemory.kind == "gift").order_by(BotMemory.last_at.desc())
                    .limit(load()["max_gifts"]))).scalars())
                await session.execute(delete(BotMemory).where(
                    BotMemory.player_id == player_id, BotMemory.bot_id == bot_id, BotMemory.kind == "gift",
                    BotMemory.detail.notin_(keep)))
            await session.commit()
    except Exception:
        log.warning("记录机器人记忆失败：%s %s %s", player_id, bot_id, kind, exc_info=True)


async def forget_player(session, player_id: str, life: int = 0) -> None:
    """玩家转世 / 重新创建角色：机器人默认不认识新的他 —— 记忆和好感都清掉（跟着调用方的事务走）。"""
    from utils.db_async import BotRelation
    await session.execute(delete(BotMemory).where(BotMemory.player_id == player_id))
    await session.execute(delete(BotRelation).where(BotRelation.player_id == player_id))
    from utils import bot_ambush, bot_chatter, bot_grudges, bot_investigation, bot_requests, bot_ties
    await bot_investigation.forget_player(session, player_id)
    await bot_requests.forget_player(session, player_id)
    await bot_chatter.forget_player(session, player_id)
    await bot_ambush.forget_player(session, player_id)
    await bot_ties.forget_player(session, player_id)
    await bot_grudges.archive_player(session, player_id, life)


async def recall(player_id: str, bot_id: str) -> dict[str, list]:
    """这对 (真人, 机器人) 的全部记忆 {种类: [行,...]}。"""
    async with AsyncSessionLocal() as session:
        rows = list((await session.execute(select(BotMemory).where(
            BotMemory.player_id == player_id, BotMemory.bot_id == bot_id))).scalars())
    out: dict[str, list] = {}
    for r in rows:
        out.setdefault(r.kind, []).append(r)
    return out


def _days(ts: float, now: float) -> int:
    return max(0, int((now - ts) // DAY))


def candidates(memories: dict, scene: str, tier: str, now: float | None = None) -> list[tuple[str, dict, float]]:
    """此刻能追加的回忆 [(场景名, 填充变量, 概率加成)]，概率加成 None 表示用普通概率，数字表示『关键时刻』的概率。"""
    now, cfg = now or time.time(), load()
    out = []
    if "gift" in memories and not scene.startswith("gift_"):
        rows = sorted(memories["gift"], key=lambda r: r.last_at, reverse=True)
        best = next((r for r in rows if r.extra in ("love", "hate")), rows[0])        # 优先提最合心意 / 最踩雷的
        out.append(("recall_gift", {"item": best.detail, "count": len(rows)}, None))
    chat = (memories.get("chat") or [None])[0]
    if chat:
        if chat.prev_at and _days(chat.prev_at, now) >= cfg["absence_days"]:
            out.append(("recall_absence", {"days": _days(chat.prev_at, now), "city": chat.extra or "此地"}, cfg["recall"]["boost_p"]))
        elif chat.count >= cfg["familiar_chats"]:
            out.append(("recall_chat", {"count": chat.count}, None))
    grudge = (memories.get("robbed") or []) + (memories.get("crippled") or [])
    if grudge:
        out.append(("recall_grudge", {"count": sum(r.count for r in grudge)}, cfg["recall"]["boost_p"] if tier in ("仇视", "陌生") else None))
    together = (memories.get("party") or []) + (memories.get("dual") or [])
    if together and sum(r.count for r in together) >= cfg["shared_min"]:   # 记录发生在说话之前，≥2 才是『以前也一起过』
        out.append(("recall_together", {"count": sum(r.count for r in together) - 1}, None))
    if memories.get("defeated"):
        row = memories["defeated"][0]
        out.append(("recall_defeat", {"count": row.count}, None))
    return out


def pick_recall(memories: dict, scene: str, tier: str, level: str, rng: random.Random | None = None,
                now: float | None = None) -> tuple[str, dict] | None:
    """要不要追加一句回忆、追加哪一句。返回 (场景名, 变量) 或 None。"""
    if scene not in RECALL_SCENES or not memories:
        return None
    rng = rng or random.Random()
    options = candidates(memories, scene, tier, now)
    if not options:
        return None
    name, fmt, boost = rng.choice(options)
    r = load()["recall"]
    p = boost if boost is not None else min(r["cap"], r["base"] * r["level_factor"].get(level, 1.0))
    return (name, fmt) if rng.random() < p else None


# ---- 资料页『交往』一行 ------------------------------------------------------

def summary(memories: dict, now: float | None = None) -> str:
    """给玩家看的一行交往记录；什么都没有返回空串。"""
    now = now or time.time()
    parts = []
    chat = (memories.get("chat") or [None])[0]
    if chat:
        days = _days(chat.last_at, now)
        parts.append(f"聊过 {chat.count} 次（{'今天' if days == 0 else f'{days} 天前'}）")
    gifts = memories.get("gift") or []
    if gifts:
        parts.append(f"送过 {len(gifts)} 样礼物")
    for kind, text in (("robbed", "你劫过它"), ("crippled", "你废过它的修为")):
        rows = memories.get(kind) or []
        if rows:
            parts.append(f"{text} {sum(r.count for r in rows)} 次")
    together = (memories.get("party") or []) + (memories.get("dual") or [])
    if together:
        parts.append(f"一起行动过 {sum(r.count for r in together)} 次")
    if memories.get("defeated"):
        parts.append(f"你败给它 {memories['defeated'][0].count} 次")
    return "交往：" + " · ".join(parts) if parts else ""
