import asyncio
import json
import random
import time
import uuid

import discord
from discord.ext import commands, tasks

from utils.db import get_conn, add_item
from utils.character import years_to_seconds, seconds_to_years

GAME_YEAR_SECS = years_to_seconds(1)
PUBLIC_EVENT_INTERVAL_YEARS = 10
PUBLIC_EVENT_CHANNEL_ENV = "PUBLIC_EVENT_CHANNEL_ID"

PUBLIC_EVENT_TYPES = [
    {
        "type": "auction",
        "title": "✦ 万宝楼大型拍卖会 ✦",
        "desc": (
            "万宝楼百年一度的大型拍卖会正式开幕！\n"
            "本次拍卖品包括稀有丹药与上古装备，灵石竞拍，现实 **30分钟** 后结算。\n"
            "出价最高者得，机不可失！"
        ),
        "duration_real_mins": 30,
        "auction_pool": [
            {"type": "item", "id": "筑基丹"},
            {"type": "item", "id": "续命丹"},
            {"type": "item", "id": "破障丹"},
            {"type": "equip", "tier": 2, "quality": "史诗"},
            {"type": "equip", "tier": 3, "quality": "稀有"},
            {"type": "equip", "tier": 1, "quality": "传说"},
        ],
    },
    {
        "type": "trial",
        "title": "✦ 神殿试炼开启 ✦",
        "desc": (
            "上古神殿突然降临，向天下修士发出试炼邀请！\n"
            "参与者将根据战力排名获得奖励，现实 **1小时** 后结算。\n"
            "前三名额外获得稀有装备与丹药。"
        ),
        "duration_real_mins": 60,
        "rewards": {
            1: {"spirit_stones": 2000, "items": ["续命丹"], "equip": {"tier": 3, "quality": "传说"}},
            2: {"spirit_stones": 1200, "items": ["破障丹"], "equip": {"tier": 2, "quality": "史诗"}},
            3: {"spirit_stones": 800,  "items": ["筑基丹"], "equip": {"tier": 2, "quality": "稀有"}},
            "other": {"spirit_stones": 300, "equip": {"tier": 1, "quality": None}},
        },
    },
    {
        "type": "spirit_rain",
        "title": "✦ 天降灵雨 ✦",
        "desc": (
            "天地异象，灵气暴涨！\n"
            "全服修炼速度提升 **50%**，持续 **1游戏年**（现实2小时）。\n"
            "此乃天赐良机，望道友把握。"
        ),
        "duration_real_mins": 120,
        "effect": {"cultivation_speed_bonus": 50},
    },
    {
        "type": "beast_tide",
        "title": "✦ 妖兽潮来袭 ✦",
        "desc": (
            "万妖岭妖兽大规模出动，向各大城市涌来！\n"
            "天下修士速速参与抵御，按贡献值发放奖励。\n"
            "现实 **45分钟** 后结算，贡献值由战力决定。\n"
            "前列修士可获得妖兽掉落的稀有装备！"
        ),
        "duration_real_mins": 45,
        "rewards": {
            "top": {"spirit_stones": 1500, "cultivation": 500, "equip": {"tier": 2, "quality": "史诗"}},
            "mid": {"spirit_stones": 800,  "cultivation": 300, "equip": {"tier": 1, "quality": "稀有"}},
            "low": {"spirit_stones": 300,  "cultivation": 100},
        },
    },
    {
        "type": "secret_realm",
        "title": "✦ 秘境短暂开启 ✦",
        "desc": (
            "虚空裂缝中一处上古秘境短暂显现！\n"
            "所有修士探险次数 **+4**，且有概率触发秘境专属事件。\n"
            "持续 **1游戏年**（现实2小时），机不可失。\n"
            "参与者有机会获得秘境遗留的古代装备。"
        ),
        "duration_real_mins": 120,
        "effect": {"explore_bonus": 4},
        "participation_reward": {"equip": {"tier": 1, "quality": None}},
    },
    {
        "type": "ancient_ruins",
        "title": "✦ 上古遗迹现世 ✦",
        "desc": (
            "一处沉寂万年的上古遗迹突然出现在天地之间！\n"
            "遗迹中封存着先辈修士的宝物，勇者方可取之。\n"
            "现实 **1小时** 后遗迹封闭，参与者按战力分配宝物。"
        ),
        "duration_real_mins": 60,
        "rewards": {
            "top": {"spirit_stones": 1000, "equip": {"tier": 3, "quality": "传说"}, "items": ["破障丹"]},
            "mid": {"spirit_stones": 500,  "equip": {"tier": 2, "quality": "史诗"}},
            "low": {"spirit_stones": 200,  "equip": {"tier": 1, "quality": "稀有"}},
        },
    },
]


def _get_next_event_time() -> float:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT started_at FROM public_events ORDER BY started_at DESC LIMIT 1"
        ).fetchone()
    if not row:
        return time.time()
    return row["started_at"] + years_to_seconds(PUBLIC_EVENT_INTERVAL_YEARS)


def _get_active_event() -> dict | None:
    now = time.time()
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM public_events WHERE status = 'active' AND ends_at > ? ORDER BY started_at DESC LIMIT 1",
            (now,)
        ).fetchone()
    return dict(row) if row else None


class PublicEventsCog(commands.Cog, name="PublicEvents"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._event_loop.start()

    def cog_unload(self):
        self._event_loop.cancel()

    def _get_announce_channel(self) -> discord.TextChannel | None:
        import os
        channel_id = os.getenv(PUBLIC_EVENT_CHANNEL_ENV)
        if not channel_id:
            return None
        return self.bot.get_channel(int(channel_id))

    @tasks.loop(minutes=5)
    async def _event_loop(self):
        await self.bot.wait_until_ready()
        now = time.time()

        active = _get_active_event()
        if active:
            if now >= active["ends_at"]:
                await self._settle_event(active)
            return

        next_time = _get_next_event_time()
        if now >= next_time:
            await self._trigger_event()

    async def _trigger_event(self):
        template = random.choice(PUBLIC_EVENT_TYPES)
        event_id = str(uuid.uuid4())[:8]
        now = time.time()
        duration_secs = template["duration_real_mins"] * 60
        ends_at = now + duration_secs

        with get_conn() as conn:
            conn.execute(
                "INSERT INTO public_events (event_id, event_type, title, started_at, ends_at, status, data) VALUES (?, ?, ?, ?, ?, 'active', ?)",
                (event_id, template["type"], template["title"], now, ends_at, json.dumps(template))
            )
            conn.commit()

        channel = self._get_announce_channel()
        if not channel:
            return

        embed = discord.Embed(
            title=template["title"],
            description=template["desc"],
            color=discord.Color.gold(),
        )
        embed.set_footer(text=f"事件ID: {event_id} · 持续 {template['duration_real_mins']} 分钟")

        view = PublicEventView(event_id, template["type"])
        msg = await channel.send("@everyone", embed=embed, view=view)

        with get_conn() as conn:
            conn.execute(
                "UPDATE public_events SET channel_id = ?, message_id = ? WHERE event_id = ?",
                (str(channel.id), str(msg.id), event_id)
            )
            conn.commit()

    async def _settle_event(self, event: dict):
        with get_conn() as conn:
            conn.execute(
                "UPDATE public_events SET status = 'ended' WHERE event_id = ?",
                (event["event_id"],)
            )
            participants = [dict(r) for r in conn.execute(
                "SELECT p.discord_id, p.contribution, pl.name, pl.physique, pl.bone, pl.soul "
                "FROM public_event_participants p JOIN players pl ON p.discord_id = pl.discord_id "
                "WHERE p.event_id = ? ORDER BY p.contribution DESC",
                (event["event_id"],)
            ).fetchall()]
            conn.commit()

        template = json.loads(event["data"])
        event_type = event["event_type"]

        channel = self._get_announce_channel()

        if event_type == "auction":
            await self._settle_auction(event, participants, template, channel)
        elif event_type == "trial":
            await self._settle_trial(event, participants, template, channel)
        elif event_type == "beast_tide":
            await self._settle_beast_tide(event, participants, template, channel)
        elif event_type == "ancient_ruins":
            await self._settle_ancient_ruins(event, participants, template, channel)
        elif event_type in ("spirit_rain", "secret_realm"):
            if channel:
                embed = discord.Embed(
                    title=f"{event['title']} · 已结束",
                    description="天地灵气恢复平静，此次异象已过。",
                    color=discord.Color.greyple(),
                )
                if event_type == "secret_realm" and participants:
                    reward_cfg = template.get("participation_reward", {})
                    equip_cfg = reward_cfg.get("equip")
                    if equip_cfg:
                        from utils.equipment import generate_equipment
                        from utils.db import give_equipment
                        lines = []
                        for p in participants:
                            eq = generate_equipment(tier=equip_cfg.get("tier", 1), quality=equip_cfg.get("quality"))
                            give_equipment(p["discord_id"], eq)
                            lines.append(f"**{p['name']}** 获得 {eq['name']}")
                        embed.add_field(name="秘境遗宝", value="\n".join(lines[:10]), inline=False)
                await channel.send(embed=embed)

    async def _settle_auction(self, event, participants, template, channel):
        if not participants or not channel:
            return
        pool = template.get("auction_pool", [])
        lines = []
        for i, lot in enumerate(pool):
            if i >= len(participants):
                break
            winner = participants[i]
            if lot["type"] == "item":
                add_item(winner["discord_id"], lot["id"])
                lines.append(f"**{lot['id']}** → {winner['name']}（出价 {winner['contribution']} 灵石）")
            elif lot["type"] == "equip":
                from utils.equipment import generate_equipment
                from utils.db import give_equipment
                eq = generate_equipment(tier=lot.get("tier", 1), quality=lot.get("quality"))
                give_equipment(winner["discord_id"], eq)
                lines.append(f"**{eq['name']}** → {winner['name']}（出价 {winner['contribution']} 灵石）")
        embed = discord.Embed(
            title="✦ 拍卖会结算 ✦",
            description="\n".join(lines) if lines else "无人参与竞拍。",
            color=discord.Color.gold(),
        )
        await channel.send(embed=embed)

    async def _settle_trial(self, event, participants, template, channel):
        if not channel:
            return
        rewards_cfg = template.get("rewards", {})
        lines = []
        for i, p in enumerate(participants[:10]):
            rank = i + 1
            cfg = rewards_cfg.get(rank, rewards_cfg.get("other", {}))
            stones = cfg.get("spirit_stones", 0)
            items = cfg.get("items", [])
            equip_cfg = cfg.get("equip")
            with get_conn() as conn:
                conn.execute(
                    "UPDATE players SET spirit_stones = spirit_stones + ? WHERE discord_id = ?",
                    (stones, p["discord_id"])
                )
                conn.commit()
            for item_id in items:
                add_item(p["discord_id"], item_id)
            equip_note = ""
            if equip_cfg:
                from utils.equipment import generate_equipment
                from utils.db import give_equipment
                eq = generate_equipment(tier=equip_cfg.get("tier", 1), quality=equip_cfg.get("quality"))
                give_equipment(p["discord_id"], eq)
                equip_note = f"，{eq['name']}"
            medal = ["🥇", "🥈", "🥉"][i] if i < 3 else f"#{rank}"
            extra = (f"，{', '.join(items)}" if items else "") + equip_note
            lines.append(f"{medal} **{p['name']}** — 灵石 +{stones}{extra}")
        embed = discord.Embed(
            title="✦ 神殿试炼结算 ✦",
            description="\n".join(lines) if lines else "无人参与试炼。",
            color=discord.Color.purple(),
        )
        await channel.send(embed=embed)

    async def _settle_beast_tide(self, event, participants, template, channel):
        if not channel:
            return
        rewards_cfg = template.get("rewards", {})
        total = len(participants)
        lines = []
        for i, p in enumerate(participants):
            ratio = i / max(total - 1, 1)
            if ratio < 0.2:
                cfg = rewards_cfg.get("top", {})
            elif ratio < 0.6:
                cfg = rewards_cfg.get("mid", {})
            else:
                cfg = rewards_cfg.get("low", {})
            stones = cfg.get("spirit_stones", 0)
            cult = cfg.get("cultivation", 0)
            equip_cfg = cfg.get("equip")
            with get_conn() as conn:
                conn.execute(
                    "UPDATE players SET spirit_stones = spirit_stones + ?, cultivation = cultivation + ? WHERE discord_id = ?",
                    (stones, cult, p["discord_id"])
                )
                conn.commit()
            equip_note = ""
            if equip_cfg:
                from utils.equipment import generate_equipment
                from utils.db import give_equipment
                eq = generate_equipment(tier=equip_cfg.get("tier", 1), quality=equip_cfg.get("quality"))
                give_equipment(p["discord_id"], eq)
                equip_note = f"，{eq['name']}"
            if i < 5:
                lines.append(f"**{p['name']}** — 灵石 +{stones}，修为 +{cult}{equip_note}")
        if total > 5:
            lines.append(f"…共 {total} 名修士参与抵御")
        embed = discord.Embed(
            title="✦ 妖兽潮结算 ✦",
            description="\n".join(lines) if lines else "无人参与抵御。",
            color=discord.Color.red(),
        )
        await channel.send(embed=embed)

    async def _settle_ancient_ruins(self, event, participants, template, channel):
        if not channel:
            return
        rewards_cfg = template.get("rewards", {})
        total = len(participants)
        lines = []
        for i, p in enumerate(participants):
            ratio = i / max(total - 1, 1)
            if ratio < 0.2:
                cfg = rewards_cfg.get("top", {})
            elif ratio < 0.6:
                cfg = rewards_cfg.get("mid", {})
            else:
                cfg = rewards_cfg.get("low", {})
            stones = cfg.get("spirit_stones", 0)
            items = cfg.get("items", [])
            equip_cfg = cfg.get("equip")
            with get_conn() as conn:
                conn.execute(
                    "UPDATE players SET spirit_stones = spirit_stones + ? WHERE discord_id = ?",
                    (stones, p["discord_id"])
                )
                conn.commit()
            for item_id in items:
                add_item(p["discord_id"], item_id)
            equip_note = ""
            if equip_cfg:
                from utils.equipment import generate_equipment
                from utils.db import give_equipment
                eq = generate_equipment(tier=equip_cfg.get("tier", 1), quality=equip_cfg.get("quality"))
                give_equipment(p["discord_id"], eq)
                equip_note = f"，{eq['name']}"
            if i < 8:
                extra = (f"，{', '.join(items)}" if items else "") + equip_note
                lines.append(f"**{p['name']}** — 灵石 +{stones}{extra}")
        if total > 8:
            lines.append(f"…共 {total} 名修士探索遗迹")
        embed = discord.Embed(
            title="✦ 上古遗迹结算 ✦",
            description="\n".join(lines) if lines else "无人探索遗迹。",
            color=discord.Color.dark_gold(),
        )
        await channel.send(embed=embed)

    @commands.command(name="公共事件")
    async def show_active_event(self, ctx):
        active = _get_active_event()
        if not active:
            next_time = _get_next_event_time()
            remaining = max(0, next_time - time.time())
            remaining_years = seconds_to_years(remaining)
            return await ctx.send(
                f"{ctx.author.mention} 当前无公共事件。\n"
                f"下次事件约在 **{remaining_years:.1f} 游戏年**（现实 {remaining/3600:.1f} 小时）后触发。"
            )
        template = json.loads(active["data"])
        remaining = max(0, active["ends_at"] - time.time())
        embed = discord.Embed(
            title=active["title"],
            description=template["desc"],
            color=discord.Color.gold(),
        )
        embed.add_field(name="剩余时间", value=f"{remaining/60:.0f} 分钟", inline=True)
        with get_conn() as conn:
            count = conn.execute(
                "SELECT COUNT(*) FROM public_event_participants WHERE event_id = ?",
                (active["event_id"],)
            ).fetchone()[0]
        embed.add_field(name="参与人数", value=str(count), inline=True)
        await ctx.send(
            ctx.author.mention,
            embed=embed,
            view=PublicEventView(active["event_id"], active["event_type"])
        )


class PublicEventView(discord.ui.View):
    def __init__(self, event_id: str, event_type: str):
        super().__init__(timeout=None)
        self.event_id = event_id
        self.event_type = event_type

        if event_type == "auction":
            self.add_item(_BidButton(event_id))
        elif event_type in ("trial", "beast_tide"):
            self.add_item(_JoinEventButton(event_id, event_type))

    @discord.ui.button(label="查看详情", style=discord.ButtonStyle.secondary)
    async def details(self, interaction: discord.Interaction, button: discord.ui.Button):
        active = _get_active_event()
        if not active or active["event_id"] != self.event_id:
            return await interaction.response.send_message("此事件已结束。", ephemeral=True)
        with get_conn() as conn:
            count = conn.execute(
                "SELECT COUNT(*) FROM public_event_participants WHERE event_id = ?",
                (self.event_id,)
            ).fetchone()[0]
        remaining = max(0, active["ends_at"] - time.time())
        await interaction.response.send_message(
            f"参与人数：{count}\n剩余时间：{remaining/60:.0f} 分钟",
            ephemeral=True
        )


class _BidButton(discord.ui.Button):
    def __init__(self, event_id: str):
        super().__init__(label="💰 出价竞拍", style=discord.ButtonStyle.success)
        self.event_id = event_id

    async def callback(self, interaction: discord.Interaction):
        uid = str(interaction.user.id)
        active = _get_active_event()
        if not active or active["event_id"] != self.event_id:
            return await interaction.response.send_message("拍卖会已结束。", ephemeral=True)
        with get_conn() as conn:
            player = conn.execute("SELECT * FROM players WHERE discord_id = ?", (uid,)).fetchone()
            if not player:
                return await interaction.response.send_message("尚未踏入修仙之路。", ephemeral=True)
            player = dict(player)
            existing = conn.execute(
                "SELECT contribution FROM public_event_participants WHERE event_id = ? AND discord_id = ?",
                (self.event_id, uid)
            ).fetchone()
        current_bid = existing["contribution"] if existing else 0
        await interaction.response.send_modal(_BidModal(self.event_id, uid, player, current_bid))


class _BidModal(discord.ui.Modal, title="出价竞拍"):
    amount = discord.ui.TextInput(label="出价灵石数量", placeholder="请输入整数", min_length=1, max_length=10)

    def __init__(self, event_id: str, uid: str, player: dict, current_bid: int):
        super().__init__()
        self.event_id = event_id
        self.uid = uid
        self.player = player
        self.current_bid = current_bid

    async def on_submit(self, interaction: discord.Interaction):
        try:
            bid = int(self.amount.value)
        except ValueError:
            return await interaction.response.send_message("请输入有效数字。", ephemeral=True)
        if bid <= 0:
            return await interaction.response.send_message("出价必须大于0。", ephemeral=True)
        if bid > self.player["spirit_stones"]:
            return await interaction.response.send_message(
                f"灵石不足，当前拥有 {self.player['spirit_stones']} 灵石。", ephemeral=True
            )
        if bid <= self.current_bid:
            return await interaction.response.send_message(
                f"出价必须高于当前出价 {self.current_bid} 灵石。", ephemeral=True
            )
        with get_conn() as conn:
            conn.execute("""
                INSERT INTO public_event_participants (event_id, discord_id, joined_at, contribution)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(event_id, discord_id) DO UPDATE SET contribution = ?
            """, (self.event_id, self.uid, time.time(), bid, bid))
            conn.commit()
        await interaction.response.send_message(
            f"已出价 **{bid}** 灵石，等待拍卖结算。", ephemeral=True
        )


class _JoinEventButton(discord.ui.Button):
    def __init__(self, event_id: str, event_type: str):
        label = "⚔️ 参与试炼" if event_type == "trial" else "🛡️ 参与抵御"
        super().__init__(label=label, style=discord.ButtonStyle.danger)
        self.event_id = event_id
        self.event_type = event_type

    async def callback(self, interaction: discord.Interaction):
        uid = str(interaction.user.id)
        active = _get_active_event()
        if not active or active["event_id"] != self.event_id:
            return await interaction.response.send_message("事件已结束。", ephemeral=True)
        with get_conn() as conn:
            player = conn.execute("SELECT * FROM players WHERE discord_id = ?", (uid,)).fetchone()
            if not player:
                return await interaction.response.send_message("尚未踏入修仙之路。", ephemeral=True)
            player = dict(player)
            existing = conn.execute(
                "SELECT 1 FROM public_event_participants WHERE event_id = ? AND discord_id = ?",
                (self.event_id, uid)
            ).fetchone()
            if existing:
                return await interaction.response.send_message("你已参与此事件。", ephemeral=True)
            power = player["physique"] + player["bone"] + player["soul"]
            conn.execute("""
                INSERT INTO public_event_participants (event_id, discord_id, joined_at, contribution)
                VALUES (?, ?, ?, ?)
            """, (self.event_id, uid, time.time(), power))
            conn.commit()
        await interaction.response.send_message(
            f"**{player['name']}** 已参与！战力贡献：{power}", ephemeral=True
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(PublicEventsCog(bot))
