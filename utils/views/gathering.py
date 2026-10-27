import random
import discord
from utils import rules
from utils.items.materials import MATERIALS
from utils.items.wood import WOOD
from utils.items.fish import FISH
from utils.items.herbs import HERBS
from utils.views.base import TimedView


# 可选时长、稀有度权重和加成、抽取次数等数值在 data/game_rules.json 的 gathering（管理员可以调），用的时候读


def gather_options() -> list[tuple[float, str, str]]:
    """[(游戏年数, 按钮文字, 现实时长提示)]，文字由年数生成（1 游戏年 = 现实 2 小时）。"""
    from utils.character import HOURS_PER_YEAR
    out = []
    for years in rules.section("gathering")["options"]:
        label = f"{years * 12:g}个月" if years < 1 else f"{years:g}年"
        hours = years * HOURS_PER_YEAR
        out.append((years, label, f"现实 {hours * 60:g} 分钟" if hours < 1 else f"现实 {hours:g} 小时"))
    return out


def rarity_weights_base() -> dict:
    return rules.section("gathering")["rarity_base"]


REGION_ELEMENT_BIAS = {
    "寒玉窟": "水",
    "火云洞": "火",
}

TYPE_EMOJI = {"采矿": "⛏️", "采药": "🌿", "伐木": "🪓", "钓鱼": "🎣"}


def _rarity_weights(years: float, realm_idx: int) -> dict:
    g = rules.section("gathering")
    w = dict(g["rarity_base"])
    time_bonus = min(years * g["rarity_time"]["per_year"], g["rarity_time"]["cap"])
    realm_bonus = min(realm_idx * g["rarity_realm"]["per_realm"], g["rarity_realm"]["cap"])
    sc = g["rarity_scale"]
    w["稀有"] += time_bonus + realm_bonus
    w["珍贵"] += time_bonus * sc["珍贵_time"] + realm_bonus * sc["珍贵_realm"]
    w["绝世"] += time_bonus * sc["绝世_time"] + realm_bonus * sc["绝世_realm"]
    return w


def _pick_rarity(weights: dict) -> str:
    rarities = list(weights.keys())
    w = [weights[r] for r in rarities]
    return random.choices(rarities, weights=w, k=1)[0]


GATHER_TYPE_POOL = {
    "采矿": "ore",
    "采药": "herb",
    "伐木": "wood",
    "钓鱼": "fish",
}


def _ore_pool(region_name: str | None, gather_type: str = "采矿") -> list[dict]:
    item_type = GATHER_TYPE_POOL.get(gather_type, "ore")
    if item_type == "wood":
        pool = [m for m in WOOD.values()]
    elif item_type == "fish":
        pool = [m for m in FISH.values()]
    elif item_type == "herb":
        pool = [m for m in HERBS.values()]
    else:
        pool = [m for m in MATERIALS.values() if m["type"] == "ore"]
    return pool if pool else list(MATERIALS.values())


def roll_gathering_rewards(years: float, realm_idx: int, region_name: str, gather_type: str = "采矿", gather_bonus: float = 0.0) -> list[tuple[str, int]]:
    rolls = rules.section("gathering")["rolls"]
    base_count = max(1, int(years * rolls["per_year"]))
    realm_extra = realm_idx // rolls["realm_div"]
    total_rolls = base_count + realm_extra + random.randint(0, max(1, int(years)))

    if gather_bonus > 0:
        total_rolls = int(total_rolls * (1 + gather_bonus))

    pool = _ore_pool(region_name, gather_type)
    if not pool:
        return []

    element_bias = REGION_ELEMENT_BIAS.get(region_name)
    weights = _rarity_weights(years, realm_idx)

    results: dict[str, int] = {}
    for _ in range(total_rolls):
        rarity = _pick_rarity(weights)
        candidates = [m for m in pool if m["rarity"] == rarity]
        if element_bias:
            biased = [m for m in candidates if m.get("element") == element_bias]
            if biased and random.random() < rules.section("gathering")["element_bias_p"]:
                candidates = biased
        if not candidates:
            candidates = [m for m in pool if m["rarity"] == "普通"]
        if not candidates:
            continue
        chosen = random.choice(candidates)
        results[chosen["name"]] = results.get(chosen["name"], 0) + 1

    return sorted(results.items(), key=lambda x: x[1], reverse=True)


class GatherView(TimedView):
    def __init__(self, author, cog, player: dict, gather_type: str, region_name: str):
        super().__init__()
        self.author = author
        self.cog = cog
        self.player = player
        self.gather_type = gather_type
        self.region_name = region_name
        emoji = TYPE_EMOJI.get(gather_type, "⛏️")
        for years, label, hint in gather_options():
            disabled = player["lifespan"] < years
            self.add_item(GatherButton(years, f"{emoji} {label}（{hint}）", disabled))


class GatherButton(discord.ui.Button):
    def __init__(self, years: float, label: str, disabled: bool):
        super().__init__(label=label, style=discord.ButtonStyle.primary, disabled=disabled)
        self.years = years

    async def callback(self, interaction: discord.Interaction):
        import time as _time
        import math
        from sqlalchemy import text
        from utils.db_async import AsyncSessionLocal
        from utils.character import years_to_seconds, seconds_to_years

        await interaction.response.defer()
        view: GatherView = self.view
        uid = str(interaction.user.id)

        async with AsyncSessionLocal() as session:
            r = await session.execute(text("SELECT * FROM players WHERE discord_id = :uid"), {"uid": uid})
            row = r.fetchone()
            player = dict(row._mapping) if row else None

        if not player:
            await interaction.followup.send("数据异常。", ephemeral=True)
            view.stop()
            return

        now = _time.time()
        if player["is_dead"]:
            await interaction.followup.send("道友已坐化，无法采集。", ephemeral=True)
            view.stop()
            return
        if player["active_quest"]:
            await interaction.followup.send("道友正在执行任务，无法同时采集。", ephemeral=True)
            view.stop()
            return
        from utils.player import is_defending
        from utils.events.public.wanbao import is_auction_locked
        if await is_defending(uid):
            await interaction.followup.send("守城期间无法采集，专心守城！", ephemeral=True)
            view.stop()
            return
        if await is_auction_locked(uid):
            await interaction.followup.send("拍卖会进行中，在万宝楼内无法采集。", ephemeral=True)
            view.stop()
            return
        if player["cultivating_until"] and now < player["cultivating_until"]:
            await interaction.followup.send("道友正在闭关，无法采集。", ephemeral=True)
            view.stop()
            return
        if player["gathering_until"] and now < player["gathering_until"]:
            remaining = seconds_to_years(player["gathering_until"] - now)
            await interaction.followup.send(f"道友正在采集中，还剩约 **{remaining:.1f} 年**。", ephemeral=True)
            view.stop()
            return
        if player["lifespan"] < self.years:
            await interaction.followup.send("寿元不足。", ephemeral=True)
            view.stop()
            return

        from utils.buffs import get_gather_bonus, get_buff_value, consume_once_buff
        gather_bonus = get_gather_bonus(player)
        # 速灵丹：限时 buff，24 小时内每次采集都生效，不消耗；百草增益丹：一次性，用一次就消耗（B56）。两者叠加。
        timed_reduction = get_buff_value(player, "gather_cooldown_reduction", 0) / 100.0
        once_reduction = get_buff_value(player, "gather_cooldown_reduction_once", 0) / 100.0
        cooldown_reduction = min(rules.section("gathering")["max_cooldown_reduction"], timed_reduction + once_reduction)

        actual_years = self.years * (1 - cooldown_reduction)
        actual_years = max(rules.section("gathering")["min_actual_years"], actual_years)

        gathering_until = now + years_to_seconds(actual_years)
        lifespan_cost = math.ceil(actual_years) if actual_years > 0 else 0

        active_buffs_raw = player.get("active_buffs") or "{}"
        old_buffs_raw = active_buffs_raw      # CAS 用：写回前 buff 表的原值
        buffs_changed = False
        if gather_bonus > 0:
            _, active_buffs_raw = consume_once_buff(active_buffs_raw, "gather_bonus_once")
            buffs_changed = True
        if once_reduction > 0:
            _, active_buffs_raw = consume_once_buff(active_buffs_raw, "gather_cooldown_reduction_once")
            buffs_changed = True

        # 上面的检查是先读再判断，连点会两次都通过、把一次性 buff 用两遍。
        # 条件写进 UPDATE 里。
        # 菜单入口和上面的检查都是先读后判，这里把同样的条件再写进 WHERE（B55）
        conditions = ("WHERE discord_id = :uid AND is_dead = 0 AND active_quest IS NULL "
                      "AND (gathering_until IS NULL OR gathering_until <= :now) "
                      "AND (cultivating_until IS NULL OR cultivating_until <= :now) "
                      "AND lifespan >= :cost")
        params = {"gu": gathering_until, "gt": view.gather_type, "cost": lifespan_cost,
                  "la": now, "now": now, "gb": gather_bonus, "uid": uid}
        async with AsyncSessionLocal() as session:
            if buffs_changed:
                params.update({"ab": active_buffs_raw, "old_ab": old_buffs_raw})
                result = await session.execute(
                    text("UPDATE players SET gathering_until = :gu, gathering_type = :gt, "
                         "lifespan = lifespan - :cost, last_active = :la, "
                         "active_buffs = :ab, gathering_bonus = :gb "
                         + conditions + " AND COALESCE(active_buffs, '{}') = :old_ab"),
                    params
                )
            else:
                result = await session.execute(
                    text("UPDATE players SET gathering_until = :gu, gathering_type = :gt, "
                         "lifespan = lifespan - :cost, last_active = :la, gathering_bonus = :gb "
                         + conditions),
                    params
                )
            if result.rowcount != 1:
                await session.rollback()
                await interaction.followup.send("状态已变化，请重新操作。", ephemeral=True)
                view.stop()
                return
            await session.commit()

        real_time = actual_years * 2
        unit = "小时" if real_time >= 1 else "分钟"
        real_display = f"{real_time:.0f}" if real_time >= 1 else f"{real_time * 60:.0f}"

        bonus_note = f"（采集量 +{int(gather_bonus * 100)}%）" if gather_bonus > 0 else ""
        reduction_note = f"（时间缩短 {int(cooldown_reduction * 100)}%）" if cooldown_reduction > 0 else ""

        await interaction.followup.send(
            f"{interaction.user.mention} **{player['name']}** 开始在 **{view.region_name}** {view.gather_type}，"
            f"预计 **{real_display} {unit}**后完成。{bonus_note}{reduction_note}\n"
            f"采集结束后将收到通知。"
        )
        view.stop()
        from utils.views.ambush import run_hook
        await run_hook(interaction.followup.send, interaction.user, "gathering")     # 采集到一半，记仇的人找上门
        from utils.views.requests import run_gather
        await run_gather(interaction.followup.send, interaction.user, player["current_city"])      # 约好陪采集的机器人一起去
