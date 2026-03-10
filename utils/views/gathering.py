import random
import discord
from utils.items.materials import MATERIALS
from utils.items.wood import WOOD
from utils.items.fish import FISH
from utils.items.herbs import HERBS
from utils.world import SPECIAL_REGIONS, get_region
from utils.realms import get_realm_index


GATHER_OPTIONS = [
    (0.25, "3个月", "现实 30 分钟"),
    (0.5,  "6个月", "现实 1 小时"),
    (1,    "1年",   "现实 2 小时"),
    (2,    "2年",   "现实 4 小时"),
    (3,    "3年",   "现实 6 小时"),
    (5,    "5年",   "现实 10 小时"),
]

RARITY_WEIGHTS_BASE = {"普通": 70, "稀有": 20, "珍贵": 5, "绝世": 0.3}

REGION_ELEMENT_BIAS = {
    "寒玉窟": "水",
    "火云洞": "火",
}

TYPE_EMOJI = {"采矿": "⛏️", "采药": "🌿", "伐木": "🪓", "钓鱼": "🎣"}


def _rarity_weights(years: float, realm_idx: int) -> dict:
    w = dict(RARITY_WEIGHTS_BASE)
    time_bonus = min(years * 1.5, 8)
    realm_bonus = min(realm_idx * 0.3, 10)
    w["稀有"] += time_bonus + realm_bonus
    w["珍贵"] += time_bonus * 0.3 + realm_bonus * 0.3
    w["绝世"] += time_bonus * 0.05 + realm_bonus * 0.08
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
    base_count = max(1, int(years * 2))
    realm_extra = realm_idx // 5
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
            if biased and random.random() < 0.4:
                candidates = biased
        if not candidates:
            candidates = [m for m in pool if m["rarity"] == "普通"]
        if not candidates:
            continue
        chosen = random.choice(candidates)
        results[chosen["name"]] = results.get(chosen["name"], 0) + 1

    return sorted(results.items(), key=lambda x: x[1], reverse=True)


class GatherView(discord.ui.View):
    def __init__(self, author, cog, player: dict, gather_type: str, region_name: str):
        super().__init__(timeout=60)
        self.author = author
        self.cog = cog
        self.player = player
        self.gather_type = gather_type
        self.region_name = region_name
        emoji = TYPE_EMOJI.get(gather_type, "⛏️")
        for years, label, hint in GATHER_OPTIONS:
            disabled = player["lifespan"] < years
            self.add_item(GatherButton(years, f"{emoji} {label}（{hint}）", disabled))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user != self.author:
            await interaction.response.send_message("这不是你的面板。", ephemeral=True)
            return False
        return True


class GatherButton(discord.ui.Button):
    def __init__(self, years: float, label: str, disabled: bool):
        super().__init__(label=label, style=discord.ButtonStyle.primary, disabled=disabled)
        self.years = years

    async def callback(self, interaction: discord.Interaction):
        import time as _time
        from utils.character import years_to_seconds, seconds_to_years
        from utils.db import get_conn

        await interaction.response.defer()
        view: GatherView = self.view
        uid = str(interaction.user.id)

        with get_conn() as conn:
            player = dict(conn.execute("SELECT * FROM players WHERE discord_id = ?", (uid,)).fetchone())

        now = _time.time()
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

        from utils.buffs import get_gather_bonus, get_buff_value, consume_once_buff, buffs_to_json
        gather_bonus = get_gather_bonus(player)
        cooldown_reduction = get_buff_value(player, "gather_cooldown_reduction", 0) / 100.0

        actual_years = self.years * (1 - cooldown_reduction)
        actual_years = max(0.25, actual_years)

        gathering_until = now + years_to_seconds(actual_years)
        lifespan_cost = max(1, int(actual_years)) if actual_years >= 1 else 0
        new_lifespan = player["lifespan"] - lifespan_cost

        active_buffs_raw = player.get("active_buffs") or "{}"
        buffs_changed = False
        if gather_bonus > 0:
            _, active_buffs_raw = consume_once_buff(active_buffs_raw, "gather_bonus_once")
            buffs_changed = True
        if cooldown_reduction > 0:
            _, active_buffs_raw = consume_once_buff(active_buffs_raw, "gather_cooldown_reduction")
            buffs_changed = True

        with get_conn() as conn:
            if buffs_changed:
                conn.execute(
                    "UPDATE players SET gathering_until = ?, gathering_type = ?, lifespan = ?, last_active = ?, active_buffs = ?, gathering_bonus = ? WHERE discord_id = ?",
                    (gathering_until, view.gather_type, new_lifespan, now, active_buffs_raw, gather_bonus, uid)
                )
            else:
                conn.execute(
                    "UPDATE players SET gathering_until = ?, gathering_type = ?, lifespan = ?, last_active = ?, gathering_bonus = ? WHERE discord_id = ?",
                    (gathering_until, view.gather_type, new_lifespan, now, gather_bonus, uid)
                )
            conn.commit()

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
