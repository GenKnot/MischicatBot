"""江湖传闻（U1「江湖百态」）。

机器人与真人的事迹都会变成一句传闻，有两个出口：
· **茶馆听闻**（`cat!传闻`）：完整列表，玩家主动去看，真人事迹单列；
· **频道广播**：每个『游戏年』（现实 2 小时）从还没播过的传闻里挑最精彩的一条（`pick_broadcast`）。

挑选规则（数值在 data/rumors.json 的 broadcast）：
· 分值 = 事件基础分 × 机器人档位权重（炮灰 0.5 / 正常 1 / 天骄 1.5）；真人的事迹 ×2 参与排序；低于 `min_score` 的只进茶馆；
· **保底**：一天 12 条里，只要有真人的传闻，至少 `human_quota` 条留给真人；
· **同一人每天最多 1 条负面广播**（炸炉、陨落……），同一人每天最多 `max_per_subject_per_day` 条；
· 真人**全部实名**（用户 2026-09-23 的决定），想低调的可以用 `cat!传闻开关` 关掉自己的事迹。

`record_rumor` **只埋在逻辑层**，并且失败不影响主流程（吞掉、记 warning）：传闻只是旁路。
模板与分值是数据（data/rumors.json），文案可以随时替换成别的、更多的，校验见 `validate_config`。
"""

import json
import logging
import random
import string
import time
from functools import lru_cache
from pathlib import Path

from sqlalchemy import delete, func, select, update

from utils import fame
from utils.bots import is_bot_id
from utils.db_async import AsyncSessionLocal, BotPersonality, Player, Rumor, RumorOptout
from utils.tasks import spawn
from utils import settings_hub

log = logging.getLogger(__name__)

_CONFIG = Path(__file__).resolve().parent.parent / "data" / "rumors.json"
PLACEHOLDERS = {"name", "city", "realm", "target", "amount", "pill", "quality", "item", "title", "chain", "level", "epithet", "legend"}
MAX_TEXT_LEN = 90
MIN_TEMPLATES = 2


@lru_cache(maxsize=1)
def _load() -> dict:
    return settings_hub.read(_CONFIG)


def load_config() -> dict:
    return json.loads(json.dumps(_load()))


def validate_config(cfg: dict) -> list[str]:
    errors = []
    if not cfg.get("kinds"):
        return ["kinds 为空"]
    for name, k in cfg["kinds"].items():
        if not isinstance(k.get("score"), int) or k["score"] < 0:
            errors.append(f"{name}: score 应为非负整数")
        if not isinstance(k.get("negative"), bool):
            errors.append(f"{name}: negative 应为布尔值")
        declared = set(k.get("vars", []))
        if "name" not in declared or declared - PLACEHOLDERS:
            errors.append(f"{name}: vars 必须包含 name，且只能用 {sorted(PLACEHOLDERS)}")
        templates = k.get("templates", [])
        if len(templates) < MIN_TEMPLATES:
            errors.append(f"{name}: 至少 {MIN_TEMPLATES} 条模板")
        for t in templates:
            if not isinstance(t, str) or not t.strip():
                errors.append(f"{name}: 有空模板")
                continue
            if len(t) > MAX_TEXT_LEN:
                errors.append(f"{name}: 模板超过 {MAX_TEXT_LEN} 字：{t[:20]}…")
            try:
                used = {f for _, f, _, _ in string.Formatter().parse(t) if f is not None}
            except ValueError:
                errors.append(f"{name}: 花括号不成对：{t}")
                continue
            if "name" not in used:
                errors.append(f"{name}: 模板里必须出现 {{name}}：{t}")
            if used - declared:
                errors.append(f"{name}: 模板用了没声明的占位符 {sorted(used - declared)}：{t}")
    b = cfg.get("broadcast", {})
    if not (b.get("interval_hours", 0) > 0 and b.get("slots_per_day", 0) >= 1 and b.get("window_hours", 0) > 0
            and b.get("cold_hours", -1) >= 0 and b.get("min_score", -1) >= 0):
        errors.append("broadcast 的时间 / 名额 / 分值参数不合法")
    if not b.get("human_weight", 0) >= 1:
        errors.append("broadcast.human_weight 应 ≥ 1")
    tw = b.get("bot_tier_weight", {})
    if set(tw) != {"炮灰", "正常", "天骄"} or any(v <= 0 for v in tw.values()):
        errors.append("broadcast.bot_tier_weight 应覆盖 炮灰 / 正常 / 天骄，且为正数")
    th = cfg.get("thresholds", {})
    if (not isinstance(th.get("alchemy_great_quality_idx"), int) or not th.get("forge_great_qualities")
            or not isinstance(th.get("auction_win_price"), int) or th["auction_win_price"] < 1):
        errors.append("thresholds 参数不合法")
    if not 0 <= b.get("human_quota", -1) <= b.get("slots_per_day", 0):
        errors.append("broadcast.human_quota 应在 0 ~ slots_per_day 之间")
    if b.get("max_per_subject_per_day", 0) < 1 or b.get("negative_per_human_per_day", 0) < 1:
        errors.append("broadcast.max_per_subject_per_day / negative_per_human_per_day 应 ≥ 1")
    if cfg.get("retention_days", 0) < 1 or cfg.get("list_size", 0) < 1:
        errors.append("retention_days / list_size 应 ≥ 1")
    return errors


# ---- 记录 -------------------------------------------------------------------

def render(kind: str, values: dict, rng=random) -> str:
    """从该种类的模板里挑一条并代入变量。缺变量直接抛 KeyError（调用方的 bug，别悄悄输出带花括号的句子）。"""
    k = load_config()["kinds"][kind]
    return string.Formatter().vformat(rng.choice(k["templates"]), (), values)


async def is_opted_out(session, player_id: str | None) -> bool:
    if not player_id or is_bot_id(player_id):
        return False
    return await session.get(RumorOptout, player_id) is not None


async def toggle_optout(player_id: str) -> bool:
    """切换『我的事迹进传闻』。返回切换之后是否已关闭（True = 不再进传闻）。"""
    async with AsyncSessionLocal() as session:
        row = await session.get(RumorOptout, player_id)
        if row:
            await session.delete(row)
            now_off = False
        else:
            session.add(RumorOptout(player_id=player_id))
            now_off = True
        await session.commit()
    return now_off


async def record_rumor(kind: str, subject_id: str, subject_name: str, *, target_id: str | None = None,
                       rng=random, **values) -> int | None:
    """记一条传闻。返回传闻 id；真人关了开关 / 出任何错都返回 None（只记 warning，绝不抛）。

    `subject_id`：事迹的主角（决定『真人 / 机器人』『负面限频』）；`target_id`：另一方（任一方是真人且关了开关就不记）。
    """
    try:
        kinds = load_config()["kinds"]
        k = kinds[kind]
        text = render(kind, {"name": subject_name, **values}, rng)
        now = time.time()
        async with AsyncSessionLocal() as session:
            if await is_opted_out(session, subject_id) or await is_opted_out(session, target_id):
                return None
            score = k["score"]
            if is_bot_id(subject_id):
                tier = await session.scalar(select(BotPersonality.tier).where(BotPersonality.bot_id == subject_id))
                score = int(round(score * load_config()["broadcast"]["bot_tier_weight"].get(tier or "正常", 1.0)))
            dup = await session.scalar(select(func.count()).select_from(Rumor)
                                       .where(Rumor.content == text, Rumor.created_at > now - 600))
            if dup:
                return None                                      # 十分钟内同一句话不记两遍（连点 / 重试）
            row = Rumor(created_at=now, kind=kind, score=score, subject_id=subject_id, subject_name=subject_name,
                        is_human=not is_bot_id(subject_id), negative=k["negative"], content=text,
                        city=str(values.get("city", "")), broadcast_at=0)
            session.add(row)
            await fame.add_fame(subject_id, fame.gain(score), session)        # 出了事迹就更出名（恶名也是名）
            await session.commit()
            return row.id
    except Exception:
        log.warning("记录传闻失败：%s %s", kind, subject_id, exc_info=True)
        return None


def record_rumor_soon(kind: str, subject_id: str, subject_name: str, **kw) -> None:
    """发出去就不管的版本，给同步 / 不方便 await 的地方用。"""
    coro = record_rumor(kind, subject_id, subject_name, **kw)
    try:
        spawn(coro, log=log, name="记录传闻")
    except RuntimeError:                                         # 没有运行中的事件循环
        coro.close()
        log.debug("拿不到事件循环，跳过传闻 %s", kind)


# ---- 常见场景的封装（逻辑层直接调用）----------------------------------------

async def record_player_rumor(kind: str, player_id: str, **values) -> int | None:
    """主角是某个玩家 / 机器人：自己去查他的道号和所在地。出错同样不抛。"""
    try:
        async with AsyncSessionLocal() as session:
            row = (await session.execute(select(Player.name, Player.current_city, Player.realm)
                                         .where(Player.discord_id == player_id))).first()
        if row is None:
            return None
        values.setdefault("city", row.current_city or "")
        values.setdefault("realm", row.realm or "")
        return await record_rumor(kind, player_id, row.name, **values)
    except Exception:
        log.warning("记录传闻失败：%s %s", kind, player_id, exc_info=True)
        return None


async def tianjiao_epithet(bot_id: str) -> str | None:
    """机器人是天骄就返回它的称号（没有称号用道号兜底），不是天骄返回 None。"""
    if not is_bot_id(bot_id):
        return None
    async with AsyncSessionLocal() as session:
        row = (await session.execute(select(BotPersonality.tier, BotPersonality.epithet, Player.name)
                                     .join(Player, Player.discord_id == BotPersonality.bot_id)
                                     .where(BotPersonality.bot_id == bot_id))).first()
    return (row.epithet or row.name) if row and row.tier == "天骄" else None


async def on_bot_old_age(bot_id: str) -> None:
    """机器人寿尽坐化：天骄用专门的、更郑重的种类。"""
    epithet = await tianjiao_epithet(bot_id)
    if epithet:
        await record_player_rumor("tianjiao_fall_old", bot_id, epithet=epithet)
    else:
        await record_player_rumor("death_old", bot_id)


async def on_breakthrough(player: dict, result: dict) -> None:
    """突破结算之后调：成功（小层 / 大境）、失败、失败致死。`player` 是突破前的玩家字典。
    天骄跨大境、突破致死用专门的种类（带称号）。"""
    from utils.realms import major_realm
    uid, name, city = player["discord_id"], player["name"], player.get("current_city", "")
    epithet = await tianjiao_epithet(uid)
    if result.get("breakthrough"):
        new = result["new_realm"]
        major = major_realm(new) != major_realm(result["old_realm"])
        if major and epithet:
            await record_rumor("tianjiao_rise", uid, name, city=city, realm=new, epithet=epithet)
            return
        await record_rumor("breakthrough_major" if major else "breakthrough_minor", uid, name, city=city, realm=new)
    elif result.get("is_dead"):
        if epithet:
            await record_rumor("tianjiao_fall_breakthrough", uid, name, city=city, realm=player["realm"], epithet=epithet)
            return
        await record_rumor("death_breakthrough", uid, name, city=city, realm=player["realm"])
    elif result.get("breakthrough") is False:
        await record_rumor("breakthrough_fail", uid, name, city=city, realm=player["realm"])


async def on_alchemy(discord_id: str, result: dict) -> None:
    """炼丹结算之后调：炼出高品质丹药、升品、炉毁 / 丹毒反噬。"""
    th = load_config()["thresholds"]
    if result.get("success") is False:
        if result.get("consequence") in th["alchemy_fail_consequences"]:
            await record_player_rumor("alchemy_fail", discord_id)
        return
    if not result.get("success"):
        return
    if result.get("quality_idx", 0) >= th["alchemy_great_quality_idx"]:
        await record_player_rumor("alchemy_great", discord_id, pill=result["pill"], quality=result["quality_name"])
    if result.get("leveled_up"):
        await record_player_rumor("alchemy_levelup", discord_id, level=result["alchemy_level"])


async def on_forge(discord_id: str, result: dict) -> None:
    """锻造结算之后调：锻出史诗 / 传说装备、锻造失败。"""
    if result.get("success") is False:
        await record_player_rumor("forge_fail", discord_id)
    elif result.get("success") and result["equipment"]["quality"] in load_config()["thresholds"]["forge_great_qualities"]:
        eq = result["equipment"]
        await record_player_rumor("forge_great", discord_id, item=eq["name"], quality=eq["quality"])


# ---- 广播挑选 ---------------------------------------------------------------

def day_start(now: float) -> float:
    return time.mktime(time.strptime(time.strftime("%Y-%m-%d", time.localtime(now)), "%Y-%m-%d"))


def effective_score(row: Rumor, cfg: dict) -> float:
    return row.score * (cfg["broadcast"]["human_weight"] if row.is_human else 1.0)


async def last_broadcast_at() -> float:
    async with AsyncSessionLocal() as session:
        return await session.scalar(select(func.max(Rumor.broadcast_at))) or 0.0


async def broadcast_due(now: float | None = None) -> bool:
    cfg = load_config()["broadcast"]
    return (now or time.time()) - await last_broadcast_at() >= cfg["interval_hours"] * 3600


async def pick_broadcast(now: float | None = None) -> Rumor | None:
    """挑下一条要广播的传闻（不改库）。没有合适的返回 None。"""
    now, cfg_all = now or time.time(), load_config()
    cfg = cfg_all["broadcast"]
    async with AsyncSessionLocal() as session:
        pool = list((await session.execute(
            select(Rumor).where(Rumor.broadcast_at == 0, Rumor.created_at >= now - cfg["window_hours"] * 3600)
            .order_by(Rumor.created_at))).scalars())
        today = list((await session.execute(select(Rumor).where(Rumor.broadcast_at >= day_start(now)))).scalars())
    per_subject, neg_human = {}, set()
    for r in today:
        per_subject[r.subject_id] = per_subject.get(r.subject_id, 0) + 1
        if r.is_human and r.negative:
            neg_human.add(r.subject_id)
    human_done = sum(1 for r in today if r.is_human)

    def allowed(r: Rumor) -> bool:
        if effective_score(r, cfg_all) < cfg["min_score"]:
            return False
        if per_subject.get(r.subject_id, 0) >= cfg["max_per_subject_per_day"]:
            return False
        return not (r.is_human and r.negative and r.subject_id in neg_human)

    candidates = [r for r in pool if allowed(r)]
    if not candidates:
        return None
    humans = [r for r in candidates if r.is_human]
    remaining_slots = cfg["slots_per_day"] - len(today)
    must_human = humans and (cfg["human_quota"] - human_done) >= max(1, remaining_slots)       # 保底：再不播真人就来不及了
    chosen_from = humans if must_human else candidates
    return max(chosen_from, key=lambda r: (effective_score(r, cfg_all), r.created_at))


async def claim_broadcast(rumor_id: int, now: float | None = None) -> bool:
    """认领这一条的广播权（条件 UPDATE）：两个循环同时挑中同一条，只有一个播。"""
    async with AsyncSessionLocal() as session:
        res = await session.execute(update(Rumor).where(Rumor.id == rumor_id, Rumor.broadcast_at == 0)
                                    .values(broadcast_at=now or time.time()))
        await session.commit()
    return res.rowcount == 1


async def prune(now: float | None = None) -> int:
    """删掉超过保留期的传闻。"""
    cutoff = (now or time.time()) - load_config()["retention_days"] * 86400
    async with AsyncSessionLocal() as session:
        res = await session.execute(delete(Rumor).where(Rumor.created_at < cutoff))
        await session.commit()
    return res.rowcount


async def recent(limit: int | None = None, now: float | None = None) -> dict[str, list[Rumor]]:
    """茶馆列表：{"human": 真人事迹, "bot": 散修闲谈}，各自最新的几条。"""
    cfg = load_config()
    limit = limit or cfg["list_size"]
    since = (now or time.time()) - cfg["retention_days"] * 86400
    out = {}
    async with AsyncSessionLocal() as session:
        for key, flag in (("human", True), ("bot", False)):
            out[key] = list((await session.execute(
                select(Rumor).where(Rumor.is_human == flag, Rumor.created_at >= since)
                .order_by(Rumor.created_at.desc()).limit(limit))).scalars())
    return out
