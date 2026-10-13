"""服务器的『江湖设置』：世界模式（决定谁能杀谁）、管理员、拦路总开关、死亡保护期（U1·江湖百态 P0）。

用户 2026-10-12 的决定：残酷程度由服务器管理员选，分三种模式 ——
· 幸福：玩家能杀机器人；机器人不能杀玩家；玩家之间不能互杀。
· 正常：玩家能杀机器人；机器人不能杀玩家；玩家之间可以互杀（**玩家互杀玩法本轮还没有，只留开关**）。
· 真实：玩家能杀机器人；机器人能杀玩家；玩家之间可以互杀。
模式只管『致死』；打劫、废修为等非致死行为的细节另行配置。
现网升级的默认模式是『正常』（机器人不杀人）；新服务器要走一遍初始化（`cogs/world_setup.py`）。

存储：复用 `bot_world_state`（键值表），键都带 `ws.` 前缀，不新建表。读写出错时读回默认值，不让设置问题拖垮游戏。
"""

import json
import logging

from sqlalchemy import select

from utils.db_async import AsyncSessionLocal, BotWorldState

log = logging.getLogger(__name__)

PREFIX = "ws."
DEFAULT_MODE = "正常"

MODES = {
    "幸福": {
        "title": "🌸 幸福模式",
        "bots_kill_humans": False, "humans_kill_humans": False,
        "short": "世界相对安全：你可以杀机器人，机器人和其他玩家都杀不了你。",
        "detail": ("• 玩家可以打劫、废修为、击杀机器人。\n"
                   "• 机器人**不会**杀死玩家；被机器人擒获最重只会被劫走一点灵石或放走。\n"
                   "• 玩家之间**不能**互相击杀。\n"
                   "适合：想让大家安心养成、把江湖当背景故事的服务器。"),
    },
    "正常": {
        "title": "⚔️ 正常模式",
        "bots_kill_humans": False, "humans_kill_humans": True,
        "short": "玩家之间有杀伐，机器人只会劫你、废你，不会取你性命。",
        "detail": ("• 玩家可以击杀机器人。\n"
                   "• 玩家之间**可以**互相击杀（该玩法尚在制作中，开关已预留）。\n"
                   "• 机器人**不会**杀死玩家：即使对你怀恨在心，最重也是废除修为、劫走财物。\n"
                   "适合：喜欢玩家之间博弈、但不想被 AI 取走角色的服务器。"),
    },
    "真实": {
        "title": "💀 真实模式",
        "bots_kill_humans": True, "humans_kill_humans": True,
        "short": "没有任何保险：机器人会为朋友复仇，也可能杀死你。",
        "detail": ("• 玩家可以击杀机器人，机器人**也可以击杀玩家**。\n"
                   "• 机器人会记仇：你杀了它的朋友，它或它的朋友可能多年后找上门，性格阴狠的甚至会直接取你性命。\n"
                   "• 玩家之间可以互相击杀。\n"
                   "• 玩家投入大量时间培养的角色可能因此死亡，死后只能重新创建角色（世界不会重置，机器人依然记得发生过的事）。\n"
                   "适合：愿意为『一个有后果的江湖』承担风险的服务器。**这是不可逆的体验，请先确认玩家都知情。**"),
    },
}

PROTECT_CHOICES = (0.0, 0.5, 1.0, 2.0, 3.0, 7.0)        # 死亡保护期可选（天）
DEFAULTS = {"mode": DEFAULT_MODE, "initialized": False, "admin_ids": [], "ambush_enabled": True,
            "death_protect_days": 1.0}


async def get_all() -> dict:
    """全部设置（缺的键用默认值；出错也返回默认值）。"""
    out = dict(DEFAULTS)
    out["admin_ids"] = []
    try:
        async with AsyncSessionLocal() as session:
            rows = (await session.execute(select(BotWorldState).where(BotWorldState.key.like(PREFIX + "%")))).scalars()
            for r in rows:
                key = r.key[len(PREFIX):]
                if key in DEFAULTS:
                    try:
                        out[key] = json.loads(r.value)
                    except ValueError:
                        log.warning("江湖设置 %s 的值损坏，用默认值", key)
    except Exception:
        log.warning("读取江湖设置失败，用默认值", exc_info=True)
    if out["mode"] not in MODES:
        out["mode"] = DEFAULT_MODE
    return out


async def _put(session, key: str, value) -> None:
    await session.merge(BotWorldState(key=PREFIX + key, value=json.dumps(value, ensure_ascii=False)))


async def set_values(**values) -> None:
    for k, v in values.items():
        if k not in DEFAULTS:
            raise KeyError(k)
    if "mode" in values and values["mode"] not in MODES:
        raise ValueError(f"未知世界模式 {values['mode']!r}")
    if "death_protect_days" in values and not 0 <= values["death_protect_days"] <= 30:
        raise ValueError("死亡保护期应在 0~30 天")
    async with AsyncSessionLocal() as session:
        for k, v in values.items():
            await _put(session, k, v)
        await session.commit()


async def initialize(admin_id: str, mode: str, protect_days: float = 1.0) -> None:
    """首次（或重新）初始化：记下模式、保护期和管理员（已有管理员保留，新的追加）。"""
    cur = await get_all()
    admins = list(cur["admin_ids"])
    if str(admin_id) not in admins:
        admins.append(str(admin_id))
    await set_values(mode=mode, death_protect_days=protect_days, admin_ids=admins, initialized=True)


async def is_admin(user_id) -> bool:
    return str(user_id) in (await get_all())["admin_ids"]


async def bots_can_kill_humans() -> bool:
    return MODES[(await get_all())["mode"]]["bots_kill_humans"]


async def humans_can_kill_humans() -> bool:
    """预留：玩家互杀玩法还没有，先把开关立好。"""
    return MODES[(await get_all())["mode"]]["humans_kill_humans"]


async def ambush_enabled() -> bool:
    """拦路总开关（管理员可随时关；改完立刻生效，不用重启）。"""
    return bool((await get_all())["ambush_enabled"])


def describe(settings: dict) -> str:
    mode = MODES[settings["mode"]]
    return (f"{mode['title']}：{mode['short']}\n拦路：{'开' if settings['ambush_enabled'] else '关'}　"
            f"死亡保护：{settings['death_protect_days']:g} 天　"
            f"{'已初始化' if settings['initialized'] else '尚未初始化（沿用默认的正常模式）'}")
