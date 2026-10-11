import asyncio
import logging
import time

import discord
from sqlalchemy import text
from utils.db_async import AsyncSessionLocal
from utils.realms import get_realm_index
from utils.views.base import TimedView


log = logging.getLogger(__name__)

MEDALS = ["🥇", "🥈", "🥉"]
BOT_MARK = "🤖"

# 战力榜要给每个存活玩家算一遍战力，玩家多了（机器人接入后是几千个）每点一次都很重，所以缓存：
# 排名结果存 POWER_TTL 秒，并发点击只算一次，重算失败时优先沿用旧榜。代价是榜单最多滞后 5 分钟
# （刚坐化的人可能还在榜上、刚变强的人要等下一轮）——排行榜本来就不要求实时。
POWER_TTL = 300.0
_power_cache: tuple[float, list[dict]] | None = None       # (算出的时间, 前十名)
_power_lock = asyncio.Lock()


def _now() -> float:
    return time.time()


def reset_power_cache() -> None:
    """清掉战力榜缓存（测试、或将来管理员手动刷新用）。"""
    global _power_cache
    _power_cache = None


def _medal(i: int) -> str:
    return MEDALS[i] if i < 3 else f"`{i+1}.`"


def _who(name: str, is_bot) -> str:
    """榜上的名字：机器人前面带 🤖（机器人和真人同榜，用户 2026-10-09 决定『显示但带标记』）。"""
    return f"{BOT_MARK} **{name}**" if is_bot else f"**{name}**"


async def _build_realm_embed() -> discord.Embed:
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            text("SELECT name, realm, rebirth_count, cultivation, is_bot FROM players WHERE is_dead = 0")
        )
        rows = result.fetchall()
    # 同境界按修为排：只按境界下标排的话，同境界的人顺序取决于库里的行序（B70）
    rows = sorted(rows, key=lambda r: (get_realm_index(r.realm), r.cultivation or 0), reverse=True)[:10]
    embed = discord.Embed(title="✦ 境界榜 ✦", color=discord.Color.gold())
    lines = []
    for i, r in enumerate(rows):
        rebirth = f"（轮回 {r.rebirth_count} 次）" if r.rebirth_count > 0 else ""
        lines.append(f"{_medal(i)} {_who(r.name, r.is_bot)} — {r.realm}{rebirth}")
    embed.description = "\n".join(lines) or "暂无数据"
    return embed


async def _compute_power_ranking() -> list[dict]:
    """实打实地算一遍：2 次查询（全部存活玩家 + 全部已穿装备），再逐人算战力。"""
    from utils.combat import calc_power
    from utils.equipment_db import get_all_equipped
    async with AsyncSessionLocal() as session:
        result = await session.execute(text("SELECT * FROM players WHERE is_dead = 0"))
        players = [dict(r._mapping) for r in result.fetchall()]
    equipped = await get_all_equipped()
    scored = [(await calc_power(p, equipped=equipped.get(p["discord_id"], [])), p) for p in players]
    scored.sort(key=lambda t: t[0], reverse=True)
    return [{"name": p["name"], "realm": p["realm"], "power": power, "is_bot": bool(p["is_bot"])}
            for power, p in scored[:10]]


async def _get_power_ranking() -> list[dict]:
    global _power_cache
    cached = _power_cache
    if cached and _now() - cached[0] < POWER_TTL:
        return cached[1]
    async with _power_lock:
        cached = _power_cache
        if cached and _now() - cached[0] < POWER_TTL:       # 等锁期间别人已经算好了
            return cached[1]
        try:
            ranking = await _compute_power_ranking()
        except Exception:
            if cached:                                      # 重算失败：沿用旧榜，下次点击再试
                log.exception("战力榜重算失败，沿用旧榜")
                return cached[1]
            raise
        _power_cache = (_now(), ranking)
        return ranking


async def _build_power_embed() -> discord.Embed:
    ranked = await _get_power_ranking()
    embed = discord.Embed(title="✦ 战力榜 ✦", color=discord.Color.red())
    lines = [f"{_medal(i)} {_who(r['name'], r['is_bot'])} — {r['power']:.1f}　{r['realm']}" for i, r in enumerate(ranked)]
    embed.description = "\n".join(lines) or "暂无数据"
    embed.set_footer(text=f"每 {int(POWER_TTL // 60)} 分钟刷新一次")
    return embed


async def _build_lifespan_embed() -> discord.Embed:
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            text("SELECT name, lifespan, realm, is_bot FROM players WHERE is_dead = 0 ORDER BY lifespan DESC LIMIT 10")
        )
        rows = result.fetchall()
    embed = discord.Embed(title="✦ 寿元榜 ✦", color=discord.Color.green())
    lines = []
    for i, r in enumerate(rows):
        lines.append(f"{_medal(i)} {_who(r.name, r.is_bot)} — {r.lifespan} 年　{r.realm}")
    embed.description = "\n".join(lines) or "暂无数据"
    return embed


async def _build_reputation_embed() -> discord.Embed:
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            text("SELECT name, reputation, realm, is_bot FROM players WHERE is_dead = 0 ORDER BY reputation DESC LIMIT 10")
        )
        rows = result.fetchall()
    embed = discord.Embed(title="✦ 声望榜 ✦", color=discord.Color.blue())
    lines = []
    for i, r in enumerate(rows):
        lines.append(f"{_medal(i)} {_who(r.name, r.is_bot)} — {r.reputation} 声望　{r.realm}")
    embed.description = "\n".join(lines) or "暂无数据"
    return embed


async def _build_alchemy_embed() -> discord.Embed:
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            text(
                "SELECT name, alchemy_level, alchemy_exp, is_bot FROM players WHERE is_dead = 0 AND alchemy_level > 0 "
                "ORDER BY alchemy_level DESC, alchemy_exp DESC LIMIT 10"
            )
        )
        rows = result.fetchall()
    embed = discord.Embed(title="✦ 炼丹榜 ✦", color=discord.Color.orange())
    lines = []
    for i, r in enumerate(rows):
        lines.append(f"{_medal(i)} {_who(r.name, r.is_bot)} — {r.alchemy_level} 品　经验 {r.alchemy_exp}")
    embed.description = "\n".join(lines) or "暂无入门炼丹师"
    return embed


async def _build_wealth_embed() -> discord.Embed:
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            text("SELECT name, spirit_stones, realm, is_bot FROM players WHERE is_dead = 0 ORDER BY spirit_stones DESC LIMIT 10")
        )
        rows = result.fetchall()
    embed = discord.Embed(title="✦ 富豪榜 ✦", color=discord.Color.yellow())
    lines = []
    for i, r in enumerate(rows):
        lines.append(f"{_medal(i)} {_who(r.name, r.is_bot)} — {r.spirit_stones:,} 灵石　{r.realm}")
    embed.description = "\n".join(lines) or "暂无数据"
    return embed


_BOARDS = {
    "境界榜": _build_realm_embed,
    "战力榜": _build_power_embed,
    "寿元榜": _build_lifespan_embed,
    "声望榜": _build_reputation_embed,
    "炼丹榜": _build_alchemy_embed,
    "富豪榜": _build_wealth_embed,
}


class LeaderboardView(TimedView):
    def __init__(self, author, cog=None):
        super().__init__()
        self.author = author
        self.cog = cog

    async def _show(self, interaction: discord.Interaction, key: str):
        embed = await _BOARDS[key]()
        extra = embed.footer.text if embed.footer and embed.footer.text else ""         # 战力榜自带「每 5 分钟刷新」
        notes = ["仅显示存活修士 · 前十名"]
        if BOT_MARK in (embed.description or ""):
            notes.append(f"{BOT_MARK} = 机器人修士")
        if extra:
            notes.append(extra)
        embed.set_footer(text=" · ".join(notes))
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="境界榜", style=discord.ButtonStyle.primary, row=0)
    async def realm_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._show(interaction, "境界榜")

    @discord.ui.button(label="战力榜", style=discord.ButtonStyle.danger, row=0)
    async def power_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._show(interaction, "战力榜")

    @discord.ui.button(label="寿元榜", style=discord.ButtonStyle.success, row=0)
    async def lifespan_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._show(interaction, "寿元榜")

    @discord.ui.button(label="声望榜", style=discord.ButtonStyle.secondary, row=1)
    async def reputation_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._show(interaction, "声望榜")

    @discord.ui.button(label="炼丹榜", style=discord.ButtonStyle.secondary, row=1)
    async def alchemy_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._show(interaction, "炼丹榜")

    @discord.ui.button(label="富豪榜", style=discord.ButtonStyle.secondary, row=1)
    async def wealth_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._show(interaction, "富豪榜")

    @discord.ui.button(label="返回世界", style=discord.ButtonStyle.secondary, row=2)
    async def back_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        from utils.views.world import WorldMenuView, _world_overview_embed
        await interaction.response.edit_message(embed=_world_overview_embed(), view=WorldMenuView(interaction.user, self.cog))
