import random
import time

import discord

from utils.db import get_conn, give_equipment
from utils.combat import calc_power
from utils.character import years_to_seconds
from utils.equipment import generate_equipment

META = {
    "type": "spirit_rain",
    "title": "天降灵雨",
    "duration_real_mins": 60,
}

CULTIVATION_BONUS = 1.5
BEAST_TIDE_CHANCE = 0.30
BEAST_TIDE_DURATION_MINS = 30


def _pick_city() -> str:
    from utils.world import CITIES
    return random.choice(CITIES)["name"]


def _get_participants(event_id: str) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT ep.discord_id, ep.contribution, ep.joined_at, ep.activity,
                   p.name, p.realm, p.current_city, p.party_id,
                   p.cultivating_until, p.gathering_until, p.active_quest
            FROM public_event_participants ep
            JOIN players p ON ep.discord_id = p.discord_id
            WHERE ep.event_id = ?
            ORDER BY ep.contribution DESC
        """, (event_id,)).fetchall()
    return [dict(r) for r in rows]


def _get_defense_participants(event_id: str) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT ep.discord_id, ep.contribution, ep.joined_at, ep.activity,
                   p.name, p.realm, p.current_city, p.party_id,
                   p.cultivating_until, p.gathering_until, p.active_quest
            FROM public_event_participants ep
            JOIN players p ON ep.discord_id = p.discord_id
            WHERE ep.event_id = ? AND ep.activity = 'defense'
            ORDER BY ep.contribution DESC
        """, (event_id,)).fetchall()
    return [dict(r) for r in rows]


def _get_idle_in_city(city: str, participant_ids: set) -> list[dict]:
    now = time.time()
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT discord_id, name, realm
            FROM players
            WHERE current_city = ? AND is_dead = 0
              AND (cultivating_until IS NULL OR cultivating_until <= ?)
              AND (gathering_until IS NULL OR gathering_until <= ?)
              AND active_quest IS NULL
        """, (city, now, now)).fetchall()
    return [dict(r) for r in rows if r["discord_id"] not in participant_ids]


async def on_trigger(bot, channel, event_id: str, city: str):
    embed = discord.Embed(
        title="✦ 天降灵雨 · 降临 ✦",
        description=(
            f"天地异象，灵气暴涨！\n\n"
            f"灵雨降临 **{city}**，在场修士修炼速度提升 **+150%**，持续 **1小时**（现实）。\n\n"
            "在场修士可参与以下活动获得额外奖励："
        ),
        color=discord.Color.blue(),
    )
    embed.add_field(name="💎 灵雨结晶", value="收集落地灵晶，获得材料与灵石", inline=True)
    embed.add_field(name="🧘 灵雨感悟", value="打坐感悟，有概率获得属性点", inline=True)
    embed.add_field(name="💪 灵雨淬体", value="以体魄承受灵雨（需体魄≥7）", inline=True)
    embed.set_footer(text=f"事件ID: {event_id} · 灵雨城市：{city} · 持续60分钟")

    view = SpiritRainView(event_id, city)
    msg = await channel.send(embed=embed, view=view)

    with get_conn() as conn:
        conn.execute(
            "UPDATE public_events SET message_id = ? WHERE event_id = ?",
            (str(msg.id), event_id)
        )
        conn.commit()


async def on_settle(bot, channel, event: dict):
    import json
    event_id = event["event_id"]
    data = json.loads(event["data"])
    city = data.get("city", "未知城市")
    has_beast_tide = data.get("beast_tide", False)

    participants = _get_participants(event_id)
    participant_ids = {p["discord_id"] for p in participants}
    defense_participants = _get_defense_participants(event_id)

    now = time.time()
    with get_conn() as conn:
        conn.execute(
            "UPDATE public_events SET status = 'ended' WHERE event_id = ?",
            (event_id,)
        )
        conn.commit()

    if has_beast_tide:
        await _settle_beast_tide(bot, channel, event_id, city, defense_participants, participants, participant_ids)
    else:
        await _settle_spirit_rain_only(channel, city, participants)


async def _settle_spirit_rain_only(channel, city: str, participants: list[dict]):
    if not channel:
        return
    seen = set()
    unique = []
    for p in participants:
        if p["discord_id"] not in seen:
            seen.add(p["discord_id"])
            unique.append(p)
    in_city = [p for p in unique if p["current_city"] == city]
    fled = [p for p in unique if p["current_city"] != city]

    defenders = [p for p in participants if p.get("activity") == "defense" and p["current_city"] == city]
    defender_ids = {p["discord_id"] for p in defenders}
    defense_lines = []
    for p in defenders:
        stones = random.randint(100, 300)
        rep = 5
        with get_conn() as conn:
            conn.execute(
                "UPDATE players SET spirit_stones = spirit_stones + ?, reputation = reputation + ? WHERE discord_id = ?",
                (stones, rep, p["discord_id"])
            )
            conn.commit()
        defense_lines.append(f"· **{p['name']}** — 灵石 +{stones}，声望 +{rep}")

    embed = discord.Embed(
        title="✦ 天降灵雨 · 结束 ✦",
        description=f"**{city}** 的灵雨已散，天地灵气恢复平静。",
        color=discord.Color.greyple(),
    )
    if in_city:
        lines = [f"· **{p['name']}**" for p in in_city[:15] if p["discord_id"] not in defender_ids]
        if lines:
            embed.add_field(name="参与修士", value="\n".join(lines), inline=False)
    if defense_lines:
        embed.add_field(name="⚔️ 守城奖励", value="\n".join(defense_lines), inline=False)
    if fled:
        embed.add_field(
            name="⚠️ 临阵脱逃",
            value="、".join(f"**{p['name']}**" for p in fled[:5]) + "　领取奖励后已离城",
            inline=False
        )
    await channel.send(embed=embed)


async def _settle_beast_tide(bot, channel, event_id: str, city: str, participants: list[dict], all_participants: list[dict], participant_ids: set):
    if not channel:
        return

    defenders = [p for p in participants if p.get("activity") == "defense" and p["current_city"] == city]
    idle_players = _get_idle_in_city(city, participant_ids)

    medal = ["🥇", "🥈", "🥉"]
    result_lines = []

    for i, p in enumerate(defenders):
        uid = p["discord_id"]
        if i == 0:
            stones = random.randint(3000, 5000)
            rep = 50
            eq1 = generate_equipment(tier=_get_tier(p["realm"]), quality="稀有")
            eq2 = generate_equipment(tier=_get_tier(p["realm"]), quality="稀有")
            give_equipment(uid, eq1)
            give_equipment(uid, eq2)
            with get_conn() as conn:
                conn.execute("UPDATE players SET spirit_stones = spirit_stones + ?, reputation = reputation + ? WHERE discord_id = ?", (stones, rep, uid))
                conn.commit()
            result_lines.append(f"{medal[0]} **{p['name']}**（贡献 {p['contribution']}）— 灵石 +{stones}，声望 +{rep}，获得 2件稀有装备")
        elif i in (1, 2):
            stones = random.randint(1500, 2500)
            rep = 30
            eq = generate_equipment(tier=_get_tier(p["realm"]), quality="稀有")
            give_equipment(uid, eq)
            with get_conn() as conn:
                conn.execute("UPDATE players SET spirit_stones = spirit_stones + ?, reputation = reputation + ? WHERE discord_id = ?", (stones, rep, uid))
                conn.commit()
            result_lines.append(f"{medal[i]} **{p['name']}**（贡献 {p['contribution']}）— 灵石 +{stones}，声望 +{rep}，获得 1件稀有装备")
        else:
            stones = random.randint(300, 800)
            rep = 10
            with get_conn() as conn:
                conn.execute("UPDATE players SET spirit_stones = spirit_stones + ?, reputation = reputation + ? WHERE discord_id = ?", (stones, rep, uid))
                conn.commit()
            if i < 8:
                result_lines.append(f"· **{p['name']}**（贡献 {p['contribution']}）— 灵石 +{stones}，声望 +{rep}")

    if len(defenders) > 8:
        result_lines.append(f"…共 {len(defenders)} 名修士坚守城池")

    fled = []
    seen_fled = set()
    for p in all_participants:
        if p.get("activity") != "defense" and p["current_city"] != city and p["discord_id"] not in seen_fled:
            seen_fled.add(p["discord_id"])
            fled.append(p)
    if fled:
        result_lines.append(f"\n⚠️ 以下修士领取灵雨奖励后临阵脱逃：" + "、".join(f"**{p['name']}**" for p in fled[:5]))

    embed_battle = discord.Embed(
        title="⚔️ 万兽齐鸣 · 守城结算",
        description=f"**{city}** 的妖兽已被击退！",
        color=discord.Color.red(),
    )
    embed_battle.add_field(
        name="贡献榜",
        value="\n".join(result_lines) if result_lines else "无人参与守城。",
        inline=False,
    )
    await channel.send(embed=embed_battle)

    if not idle_players:
        return

    loss_list = []
    for p in idle_players:
        if random.random() < 0.30:
            loss = random.randint(5, 15)
            with get_conn() as conn:
                conn.execute(
                    "UPDATE players SET lifespan = MAX(1, lifespan - ?) WHERE discord_id = ?",
                    (loss, p["discord_id"])
                )
                conn.commit()
            loss_list.append((p["name"], p["realm"], loss))

    if not loss_list:
        return

    pages = [loss_list[i:i+10] for i in range(0, len(loss_list), 10)]
    view = SlackerView(pages, city)
    embed_slack = _build_slacker_embed(pages, 0, city)
    await channel.send(embed=embed_slack, view=view)


def _build_slacker_embed(pages: list, page: int, city: str) -> discord.Embed:
    embed = discord.Embed(
        title="😴 万兽齐鸣 · 摸鱼榜",
        description=f"以下修士在妖兽肆虐 **{city}** 期间袖手旁观，遭到妖兽袭击——",
        color=discord.Color.dark_orange(),
    )
    lines = [f"· **{name}**　{realm}　损失 **{loss}年** 寿元" for name, realm, loss in pages[page]]
    embed.add_field(name="受害修士", value="\n".join(lines), inline=False)
    embed.set_footer(text=f"第 {page+1} 页 / 共 {len(pages)} 页　|　参与守城可免受妖兽袭击，下次记得出手！")
    return embed


def _get_tier(realm: str) -> int:
    from utils.equipment import get_player_tier
    return get_player_tier(realm)


class SlackerView(discord.ui.View):
    def __init__(self, pages: list, city: str):
        super().__init__(timeout=300)
        self.pages = pages
        self.city = city
        self.page = 0
        self._update_buttons()

    def _update_buttons(self):
        self.prev_btn.disabled = self.page == 0
        self.next_btn.disabled = self.page >= len(self.pages) - 1

    @discord.ui.button(label="◀", style=discord.ButtonStyle.secondary)
    async def prev_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.page -= 1
        self._update_buttons()
        await interaction.response.edit_message(embed=_build_slacker_embed(self.pages, self.page, self.city), view=self)

    @discord.ui.button(label="▶", style=discord.ButtonStyle.secondary)
    async def next_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.page += 1
        self._update_buttons()
        await interaction.response.edit_message(embed=_build_slacker_embed(self.pages, self.page, self.city), view=self)


class SpiritRainView(discord.ui.View):
    def __init__(self, event_id: str, city: str, pe_cog=None):
        super().__init__(timeout=None)
        self.event_id = event_id
        self.city = city
        self.pe_cog = pe_cog

    @discord.ui.button(label="💎 灵雨结晶", style=discord.ButtonStyle.primary)
    async def crystal(self, interaction: discord.Interaction, button: discord.ui.Button):
        await _handle_activity(interaction, self.event_id, self.city, "crystal")

    @discord.ui.button(label="🧘 灵雨感悟", style=discord.ButtonStyle.primary)
    async def enlighten(self, interaction: discord.Interaction, button: discord.ui.Button):
        await _handle_activity(interaction, self.event_id, self.city, "enlighten")

    @discord.ui.button(label="💪 灵雨淬体", style=discord.ButtonStyle.primary)
    async def temper(self, interaction: discord.Interaction, button: discord.ui.Button):
        await _handle_activity(interaction, self.event_id, self.city, "temper")

    @discord.ui.button(label="⚔️ 参与守城", style=discord.ButtonStyle.danger)
    async def join_defense(self, interaction: discord.Interaction, button: discord.ui.Button):
        await _handle_activity(interaction, self.event_id, self.city, "defense")

    @discord.ui.button(label="返回主菜单", style=discord.ButtonStyle.secondary, row=1)
    async def back_menu(self, interaction: discord.Interaction, button: discord.ui.Button):
        from utils.views.world import _send_main_menu
        cog = self.pe_cog.bot.cogs.get("Cultivation") if self.pe_cog else None
        if not cog:
            await interaction.response.send_message("无法返回。", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        await _send_main_menu(interaction, cog)


async def _handle_activity(interaction: discord.Interaction, event_id: str, city: str, activity: str):
    await interaction.response.defer(ephemeral=True)
    uid = str(interaction.user.id)
    now = time.time()

    with get_conn() as conn:
        row = conn.execute("SELECT * FROM players WHERE discord_id = ?", (uid,)).fetchone()
        if not row:
            return await interaction.followup.send("尚未踏入修仙之路。", ephemeral=True)
        player = dict(row)
        event_row = conn.execute(
            "SELECT * FROM public_events WHERE event_id = ? AND status = 'active'", (event_id,)
        ).fetchone()
        if not event_row:
            return await interaction.followup.send("此事件已结束。", ephemeral=True)
        existing_rows = conn.execute(
            "SELECT activity, joined_at FROM public_event_participants WHERE event_id = ? AND discord_id = ? ORDER BY joined_at DESC",
            (event_id, uid)
        ).fetchall()

    existing_activities = [dict(r) for r in existing_rows]
    activity_set = {r["activity"] for r in existing_activities}

    if player["is_dead"]:
        return await interaction.followup.send("道友已坐化。", ephemeral=True)

    if player["current_city"] != city:
        return await interaction.followup.send(
            f"你不在 **{city}**，无法参与此次灵雨活动。\n当前位置：**{player['current_city']}**",
            ephemeral=True
        )

    if activity == "defense":
        if "defense" in activity_set:
            return await interaction.followup.send("你已参与守城，坚守阵地直到结束。", ephemeral=True)
    else:
        non_defense = [r for r in existing_activities if r["activity"] != "defense"]
        if len(non_defense) >= 2:
            return await interaction.followup.send("本次灵雨你已参与 2 次活动，已达上限。", ephemeral=True)
        if non_defense:
            last_time = non_defense[0]["joined_at"]
            cooldown = 600
            elapsed = now - last_time
            if elapsed < cooldown:
                remaining_secs = int(cooldown - elapsed)
                return await interaction.followup.send(
                    f"灵雨活动冷却中，还需等待 **{remaining_secs // 60} 分 {remaining_secs % 60} 秒**。",
                    ephemeral=True
                )

    if activity == "temper" and player.get("physique", 5) < 7:
        return await interaction.followup.send("体魄不足（需≥7），无法承受灵雨淬体。", ephemeral=True)

    with get_conn() as conn:
        try:
            conn.execute("""
                INSERT INTO public_event_participants (event_id, discord_id, joined_at, contribution, activity)
                VALUES (?, ?, ?, 0, ?)
            """, (event_id, uid, now, activity))
            conn.commit()
        except Exception:
            return await interaction.followup.send("操作失败，请稍后再试。", ephemeral=True)

    msg = ""

    if activity == "crystal":
        stones = random.randint(150, 400)
        items_gained = []
        from utils.items import ITEMS
        from utils.db import add_item
        if random.random() < 0.65:
            rarity_weights = {"普通": 70, "稀有": 25, "珍贵": 4, "绝世": 1}
            herb_pool = [(k, v) for k, v in ITEMS.items() if v.get("type") == "herb"]
            weights = [rarity_weights.get(v.get("rarity", "普通"), 70) for k, v in herb_pool]
            count = random.randint(1, 2)
            picked = random.choices([k for k, v in herb_pool], weights=weights, k=count)
            picked = list(dict.fromkeys(picked))
            for item in picked:
                qty = 1 if ITEMS[item].get("rarity") in ("珍贵", "绝世") else random.randint(1, 2)
                add_item(uid, item, qty)
                items_gained.append(f"{item}×{qty}")
        with get_conn() as conn:
            conn.execute("UPDATE players SET spirit_stones = spirit_stones + ? WHERE discord_id = ?", (stones, uid))
            conn.commit()
        items_str = "、".join(items_gained) if items_gained else "无"
        msg = f"你收集了落地灵晶，获得 **{stones} 灵石**，材料：{items_str}"
        power = 0

    elif activity == "enlighten":
        stat = random.choice(["comprehension", "soul", "fortune"])
        stat_names = {"comprehension": "悟性", "soul": "神识", "fortune": "机缘"}
        gain = 1 if random.random() < 0.15 else 0
        cult_gain = random.randint(80, 200)
        with get_conn() as conn:
            if gain:
                conn.execute(f"UPDATE players SET {stat} = {stat} + 1, cultivation = cultivation + ? WHERE discord_id = ?", (cult_gain, uid))
            else:
                conn.execute("UPDATE players SET cultivation = cultivation + ? WHERE discord_id = ?", (cult_gain, uid))
            conn.commit()
        if gain:
            msg = f"灵雨中你心有所悟，**{stat_names[stat]} +1**，修为 +{cult_gain}"
        else:
            msg = f"你在灵雨中打坐，修为 +{cult_gain}"
        power = 0

    elif activity == "temper":
        physique_gain = 1 if random.random() < 0.12 else 0
        bone_gain = 1 if random.random() < 0.08 else 0
        cult_gain = random.randint(100, 250)
        updates = [f"cultivation = cultivation + {cult_gain}"]
        if physique_gain:
            updates.append("physique = physique + 1")
        if bone_gain:
            updates.append("bone = bone + 1")
        with get_conn() as conn:
            conn.execute(f"UPDATE players SET {', '.join(updates)} WHERE discord_id = ?", (uid,))
            conn.commit()
        parts = [f"修为 +{cult_gain}"]
        if physique_gain:
            parts.append("体魄 +1")
        if bone_gain:
            parts.append("根骨 +1")
        msg = "灵雨淬体，" + "，".join(parts)
        power = 0

    elif activity == "defense":
        power = int(calc_power(player) * random.uniform(0.9, 1.1))
        with get_conn() as conn:
            conn.execute(
                "UPDATE public_event_participants SET contribution = ? WHERE event_id = ? AND discord_id = ? AND activity = 'defense'",
                (power, event_id, uid)
            )
            conn.commit()
        msg = f"你加入守城队伍！战力贡献：**{power}**"

    await interaction.followup.send(msg, ephemeral=True)
