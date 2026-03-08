import random
import discord
from utils.views.party import PartyInviteButton


class PlayerActionView(discord.ui.View):
    def __init__(self, author, viewer: dict, target: dict, in_pvp_zone: bool):
        super().__init__(timeout=60)
        self.author = author
        self.viewer = viewer
        self.target = target
        self.in_pvp_zone = in_pvp_zone
        self.add_item(PartyInviteButton(viewer, target))
        atk_btn = discord.ui.Button(label="⚔️ 发起攻击", style=discord.ButtonStyle.danger, disabled=not in_pvp_zone)
        atk_btn.callback = self._attack_callback
        self.add_item(atk_btn)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user != self.author:
            await interaction.response.send_message("这不是你的面板。", ephemeral=True)
            return False
        return True

    async def _attack_callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        from utils.db import get_conn
        from utils.combat import roll_combat, roll_escape
        uid = str(interaction.user.id)
        def_uid = self.target["discord_id"]
        with get_conn() as conn:
            atk = dict(conn.execute("SELECT * FROM players WHERE discord_id = ?", (uid,)).fetchone())
            dfn = dict(conn.execute("SELECT * FROM players WHERE discord_id = ?", (def_uid,)).fetchone())
        if atk["is_dead"] or dfn["is_dead"]:
            return await interaction.followup.send("对方已坐化。", ephemeral=True)
        if atk["current_city"] != dfn["current_city"]:
            return await interaction.followup.send("对方已离开此地。", ephemeral=True)
        won, atk_power, def_power = roll_combat(atk, dfn)
        for item in self.children:
            item.disabled = True
        self.stop()
        result_embed = discord.Embed(
            title="⚔️ 战斗结算",
            description=f"**{atk['name']}** 战力：{atk_power}\n**{dfn['name']}** 战力：{def_power}\n\n",
            color=discord.Color.red() if won else discord.Color.dark_gray(),
        )
        if won:
            result_embed.description += f"**{atk['name']}** 胜！"
            await interaction.followup.send(embed=result_embed, view=VictoryActionView(interaction.user, atk, dfn), ephemeral=True)
        else:
            escaped, escape_pct = roll_escape(dfn)
            if escaped:
                result_embed.description += f"**{atk['name']}** 败北！\n**{dfn['name']}** 趁乱逃脱（逃跑成功率 {escape_pct}%）。"
                await interaction.followup.send(embed=result_embed, ephemeral=True)
            else:
                result_embed.description += f"**{atk['name']}** 败北，但 **{dfn['name']}** 未能逃脱（逃跑成功率 {escape_pct}%）！"
                result_embed.color = discord.Color.dark_red()
                await interaction.followup.send(embed=result_embed, view=VictoryActionView(interaction.user, atk, dfn), ephemeral=True)


class VictoryActionView(discord.ui.View):
    def __init__(self, author, winner: dict, loser: dict):
        super().__init__(timeout=60)
        self.author = author
        self.winner = winner
        self.loser = loser

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user != self.author:
            await interaction.response.send_message("这不是你的面板。", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="💰 打劫灵石", style=discord.ButtonStyle.danger)
    async def rob(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        from utils.db import get_conn
        def_uid = self.loser["discord_id"]
        atk_uid = self.winner["discord_id"]
        with get_conn() as conn:
            row = conn.execute("SELECT spirit_stones FROM players WHERE discord_id = ?", (def_uid,)).fetchone()
            if not row:
                return await interaction.followup.send("对方数据异常。", ephemeral=True)
            loot = max(1, int(row["spirit_stones"] * random.uniform(0.3, 0.6)))
            conn.execute("UPDATE players SET spirit_stones = spirit_stones - ? WHERE discord_id = ?", (loot, def_uid))
            conn.execute("UPDATE players SET spirit_stones = spirit_stones + ? WHERE discord_id = ?", (loot, atk_uid))
            conn.commit()
        for item in self.children:
            item.disabled = True
        self.stop()
        await interaction.followup.send(f"你从 **{self.loser['name']}** 身上搜刮了 **{loot} 灵石**。", ephemeral=True)

    @discord.ui.button(label="💀 废去修为", style=discord.ButtonStyle.danger)
    async def cripple(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        from utils.db import get_conn
        with get_conn() as conn:
            conn.execute("UPDATE players SET cultivation = 0 WHERE discord_id = ?", (self.loser["discord_id"],))
            conn.commit()
        for item in self.children:
            item.disabled = True
        self.stop()
        await interaction.followup.send(f"你强行打散了 **{self.loser['name']}** 的修为，其修为归零。", ephemeral=True)

    @discord.ui.button(label="☠️ 击杀", style=discord.ButtonStyle.danger)
    async def kill(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        from utils.db import get_conn
        with get_conn() as conn:
            conn.execute("UPDATE players SET is_dead = 1, lifespan = 0 WHERE discord_id = ?", (self.loser["discord_id"],))
            conn.commit()
        for item in self.children:
            item.disabled = True
        self.stop()
        await interaction.followup.send(f"你取了 **{self.loser['name']}** 的性命。其魂归天道，尘归尘，土归土。", ephemeral=True)
