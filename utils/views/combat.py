import logging
import random
import discord
from utils.views.party import PartyInviteButton
from utils.views.base import TimedView

log = logging.getLogger(__name__)


class PlayerActionView(TimedView):
    def __init__(self, author, viewer: dict, target: dict, in_pvp_zone: bool):
        super().__init__()
        self.author = author
        self.viewer = viewer
        self.target = target
        self.in_pvp_zone = in_pvp_zone
        self.add_item(PartyInviteButton(viewer, target))

        has_dual = self._check_dual_technique(viewer)
        if has_dual:
            dual_btn = discord.ui.Button(label="💕 邀请双修", style=discord.ButtonStyle.primary)
            dual_btn.callback = self._dual_cultivate_callback
            self.add_item(dual_btn)

        atk_btn = discord.ui.Button(label="⚔️ 发起攻击", style=discord.ButtonStyle.danger, disabled=not in_pvp_zone)
        atk_btn.callback = self._attack_callback
        self.add_item(atk_btn)

    def _check_dual_technique(self, player: dict) -> bool:
        import json
        techniques = json.loads(player.get("techniques") or "[]")
        for t in techniques:
            name = t if isinstance(t, str) else t.get("name", "")
            if name == "双修功法":
                return True
        return False

    async def _dual_cultivate_callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        import random
        from sqlalchemy import text
        from utils.db_async import AsyncSessionLocal
        from utils.character import years_to_seconds

        uid = str(interaction.user.id)
        target_uid = self.target["discord_id"]

        async with AsyncSessionLocal() as session:
            r1 = await session.execute(text("SELECT * FROM players WHERE discord_id = :uid"), {"uid": uid})
            row1 = r1.fetchone()
            r2 = await session.execute(text("SELECT * FROM players WHERE discord_id = :uid"), {"uid": target_uid})
            row2 = r2.fetchone()

        inviter = dict(row1._mapping) if row1 else None
        target = dict(row2._mapping) if row2 else None

        if not inviter or not target:
            return await interaction.followup.send("数据异常。", ephemeral=True)

        if inviter["is_dead"] or target["is_dead"]:
            return await interaction.followup.send("对方已坐化。", ephemeral=True)

        if inviter["current_city"] != target["current_city"]:
            return await interaction.followup.send("双修需在同一城市。", ephemeral=True)

        import time
        now = time.time()
        cooldown_secs = years_to_seconds(2)

        if inviter.get("last_dual_cultivate") and now - inviter["last_dual_cultivate"] < cooldown_secs:
            from utils.character import seconds_to_years
            remaining = seconds_to_years(cooldown_secs - (now - inviter["last_dual_cultivate"]))
            return await interaction.followup.send(f"你的双修冷却中，还需 {remaining:.1f} 游戏年。", ephemeral=True)

        if target.get("last_dual_cultivate") and now - target["last_dual_cultivate"] < cooldown_secs:
            from utils.character import seconds_to_years
            remaining = seconds_to_years(cooldown_secs - (now - target["last_dual_cultivate"]))
            return await interaction.followup.send(f"对方双修冷却中，还需 {remaining:.1f} 游戏年。", ephemeral=True)

        if inviter.get("cultivating_until") and now < inviter["cultivating_until"]:
            return await interaction.followup.send("你正在闭关，无法双修。", ephemeral=True)

        if target.get("cultivating_until") and now < target["cultivating_until"]:
            return await interaction.followup.send("对方正在闭关，无法双修。", ephemeral=True)

        if inviter["lifespan"] < 1:
            return await interaction.followup.send("你的寿元不足。", ephemeral=True)

        if target["lifespan"] < 1:
            return await interaction.followup.send("对方寿元不足。", ephemeral=True)

        inv_virgin = bool(inviter["is_virgin"])
        tgt_virgin = bool(target["is_virgin"])
        both_virgin = inv_virgin and tgt_virgin

        if both_virgin:
            multiplier = random.uniform(10, 20)
            mult_desc = f"双方皆为清白之身，阴阳交融，修为暴涨（**{multiplier:.1f}倍**）"
        elif inv_virgin or tgt_virgin:
            multiplier = 5.0
            mult_desc = "一方清白之身，修为大增（**5倍**）"
        else:
            multiplier = 1.2
            mult_desc = "双修加持，修为略有提升（**1.2倍**）"

        from utils.views.dual import DualCultivateInviteView

        try:
            target_user = await interaction.client.fetch_user(int(target_uid))
        except:
            return await interaction.followup.send("无法找到对方用户。", ephemeral=True)

        embed = discord.Embed(
            title="✦ 双修邀请 ✦",
            description=(
                f"**{interaction.user.display_name}** 邀请 {target_user.mention} 进行双修。\n\n"
                f"{mult_desc}\n"
                f"双修将消耗双方各 **1 游戏年** 寿元，持续现实 **2 小时**。\n\n"
                f"{target_user.mention} 是否接受？"
            ),
            color=discord.Color.pink(),
        )

        cultivation_cog = interaction.client.cogs.get("Cultivation")
        if not cultivation_cog:
            return await interaction.followup.send("系统异常。", ephemeral=True)

        await interaction.followup.send(
            target_user.mention,
            embed=embed,
            view=DualCultivateInviteView(cultivation_cog, interaction.user, target_user, multiplier, both_virgin)
        )

    async def _attack_callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        from sqlalchemy import text
        from utils.db_async import AsyncSessionLocal
        from utils.combat import roll_combat, roll_escape
        uid = str(interaction.user.id)
        def_uid = self.target["discord_id"]
        async with AsyncSessionLocal() as session:
            r1 = await session.execute(text("SELECT * FROM players WHERE discord_id = :uid"), {"uid": uid})
            row1 = r1.fetchone()
            r2 = await session.execute(text("SELECT * FROM players WHERE discord_id = :uid"), {"uid": def_uid})
            row2 = r2.fetchone()
        atk = dict(row1._mapping)
        dfn = dict(row2._mapping)
        if atk["is_dead"] or dfn["is_dead"]:
            return await interaction.followup.send("对方已坐化。", ephemeral=True)
        if atk["current_city"] != dfn["current_city"]:
            return await interaction.followup.send("对方已离开此地。", ephemeral=True)
        won, atk_power, def_power = await roll_combat(atk, dfn)
        for item in self.children:
            item.disabled = True
        self.stop()

        from utils.combat import consume_combat_buffs, consume_escape_buff
        await consume_combat_buffs(uid, atk)
        await consume_combat_buffs(def_uid, dfn)

        result_embed = discord.Embed(
            title="⚔️ 战斗结算",
            description=f"**{atk['name']}** 战力：{atk_power}\n**{dfn['name']}** 战力：{def_power}\n\n",
            color=discord.Color.red() if won else discord.Color.dark_gray(),
        )
        if won:
            result_embed.description += f"**{atk['name']}** 胜！"
            await interaction.followup.send(embed=result_embed, view=VictoryActionView(interaction.user, atk, dfn), ephemeral=True)
        else:
            escaped, escape_pct = await roll_escape(dfn)
            if escaped:
                await consume_escape_buff(def_uid, dfn)
                result_embed.description += f"**{atk['name']}** 败北！\n**{dfn['name']}** 趁乱逃脱（逃跑成功率 {escape_pct}%）。"
                await interaction.followup.send(embed=result_embed, ephemeral=True)
            else:
                result_embed.description += f"**{atk['name']}** 败北，但 **{dfn['name']}** 未能逃脱（逃跑成功率 {escape_pct}%）！"
                result_embed.color = discord.Color.dark_red()
                await interaction.followup.send(embed=result_embed, view=VictoryActionView(interaction.user, dfn, atk), ephemeral=True)


class VictoryActionView(TimedView):
    def __init__(self, author, winner: dict, loser: dict):
        super().__init__()
        self.author = author
        self.winner = winner
        self.loser = loser
        self._schedule_lifespan_restore(loser)

    def _schedule_lifespan_restore(self, player: dict):
        import asyncio
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self._check_lifespan_restore(player))
        except RuntimeError:
            # 没有运行中的事件循环，回血只能跳过
            log.debug("拿不到事件循环，跳过战斗回血")

    async def _check_lifespan_restore(self, player: dict):
        from sqlalchemy import text
        from utils.db_async import AsyncSessionLocal
        from utils.buffs import get_buff_value, consume_once_buff
        lifespan = player.get("lifespan", 0)
        lifespan_max = player.get("lifespan_max", 1)
        if lifespan_max <= 0:
            return
        if lifespan / lifespan_max > 0.2:
            return
        restore_pct = get_buff_value(player, "combat_lifespan_restore", 0)
        if restore_pct <= 0:
            return
        restore_amount = int(lifespan_max * restore_pct / 100)
        if restore_amount <= 0:
            return
        old_raw = player.get("active_buffs") or "{}"
        _, raw = consume_once_buff(old_raw, "combat_lifespan_restore")
        uid = player.get("discord_id", "")
        async with AsyncSessionLocal() as session:
            # buff 表 CAS。原先无条件覆盖，两场战斗同时结算会各回一次血。
            await session.execute(
                text("UPDATE players SET lifespan = MIN(lifespan_max, lifespan + :amt), "
                     "active_buffs = :raw "
                     "WHERE discord_id = :uid AND COALESCE(active_buffs, '{}') = :old_raw"),
                {"amt": restore_amount, "raw": raw, "old_raw": old_raw, "uid": uid}
            )
            await session.commit()

    @discord.ui.button(label="💰 打劫灵石", style=discord.ButtonStyle.danger)
    async def rob(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        from sqlalchemy import text
        from utils.db_async import AsyncSessionLocal
        def_uid = self.loser["discord_id"]
        atk_uid = self.winner["discord_id"]
        async with AsyncSessionLocal() as session:
            r = await session.execute(text("SELECT spirit_stones FROM players WHERE discord_id = :uid"), {"uid": def_uid})
            row = r.fetchone()
            if not row:
                return await interaction.followup.send("对方数据异常。", ephemeral=True)
            loot = max(1, int(row._mapping["spirit_stones"] * random.uniform(0.3, 0.6)))
            # 按刚读到的余额算出的 loot，可能在此期间已被对方花掉；
            # 扣不动就说明对方已经没那么多灵石了，本次搜刮落空。
            from utils.atomic import grant_stones, spend_stones
            if not await spend_stones(session, def_uid, loot):
                await session.rollback()
                return await interaction.followup.send("对方身上已经没什么油水了。", ephemeral=True)
            await grant_stones(session, atk_uid, loot)
            await session.commit()
        for item in self.children:
            item.disabled = True
        self.stop()
        await interaction.followup.send(f"你从 **{self.loser['name']}** 身上搜刮了 **{loot} 灵石**。", ephemeral=True)

    @discord.ui.button(label="💀 废去修为", style=discord.ButtonStyle.danger)
    async def cripple(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        from sqlalchemy import text
        from utils.db_async import AsyncSessionLocal
        async with AsyncSessionLocal() as session:
            await session.execute(text("UPDATE players SET cultivation = 0 WHERE discord_id = :uid"), {"uid": self.loser["discord_id"]})
            await session.commit()
        for item in self.children:
            item.disabled = True
        self.stop()
        await interaction.followup.send(f"你强行打散了 **{self.loser['name']}** 的修为，其修为归零。", ephemeral=True)

    @discord.ui.button(label="☠️ 击杀", style=discord.ButtonStyle.danger)
    async def kill(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        from sqlalchemy import text
        from utils.db_async import AsyncSessionLocal
        async with AsyncSessionLocal() as session:
            await session.execute(text("UPDATE players SET is_dead = 1, lifespan = 0 WHERE discord_id = :uid"), {"uid": self.loser["discord_id"]})
            await session.commit()
        for item in self.children:
            item.disabled = True
        self.stop()
        await interaction.followup.send(f"你取了 **{self.loser['name']}** 的性命。其魂归天道，尘归尘，土归土。", ephemeral=True)
