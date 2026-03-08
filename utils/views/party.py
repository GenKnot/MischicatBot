import uuid
import time
import discord
from utils.db import get_conn


def party_info_embed(members: list, leader_id: str) -> discord.Embed:
    embed = discord.Embed(title="✦ 当前队伍 ✦", color=discord.Color.blue())
    lines = []
    for m in members:
        tag = "👑 " if m["discord_id"] == leader_id else "· "
        lines.append(f"{tag}**{m['name']}**（{m['realm']}）寿元 {m['lifespan']} 年")
    embed.description = "\n".join(lines)
    embed.set_footer(text=f"共 {len(members)} 人 · 最多4人")
    return embed


async def leave_party(uid: str, client) -> str:
    with get_conn() as conn:
        row = conn.execute("SELECT party_id FROM players WHERE discord_id = ?", (uid,)).fetchone()
        if not row or not row["party_id"]:
            return "你不在任何队伍中。"
        party_id = row["party_id"]
        leader_row = conn.execute("SELECT leader_id FROM parties WHERE party_id = ?", (party_id,)).fetchone()
        if not leader_row:
            conn.execute("UPDATE players SET party_id = NULL WHERE discord_id = ?", (uid,))
            conn.commit()
            return "已退出队伍。"
        leader_id = leader_row["leader_id"]
        conn.execute("UPDATE players SET party_id = NULL WHERE discord_id = ?", (uid,))
        remaining = conn.execute("SELECT discord_id FROM players WHERE party_id = ?", (party_id,)).fetchall()
        if not remaining:
            conn.execute("DELETE FROM parties WHERE party_id = ?", (party_id,))
        elif uid == leader_id and remaining:
            new_leader = remaining[0]["discord_id"]
            conn.execute("UPDATE parties SET leader_id = ? WHERE party_id = ?", (new_leader, party_id))
        conn.commit()
    return "已退出队伍。"


async def disband_party(uid: str, client) -> str:
    with get_conn() as conn:
        row = conn.execute("SELECT party_id FROM players WHERE discord_id = ?", (uid,)).fetchone()
        if not row or not row["party_id"]:
            return "你不在任何队伍中。"
        party_id = row["party_id"]
        leader_row = conn.execute("SELECT leader_id FROM parties WHERE party_id = ?", (party_id,)).fetchone()
        if not leader_row or leader_row["leader_id"] != uid:
            return "只有队长才能解散队伍。"
        members = [r["discord_id"] for r in conn.execute(
            "SELECT discord_id FROM players WHERE party_id = ?", (party_id,)).fetchall()]
        conn.execute("UPDATE players SET party_id = NULL WHERE party_id = ?", (party_id,))
        conn.execute("DELETE FROM parties WHERE party_id = ?", (party_id,))
        conn.commit()
    for mid in members:
        if mid == uid:
            continue
        try:
            user = await client.fetch_user(int(mid))
            await user.send("队长已解散队伍，你已退出。")
        except Exception:
            pass
    return "队伍已解散，所有成员已退出。"


class PartyInviteButton(discord.ui.Button):
    def __init__(self, inviter: dict, target: dict):
        super().__init__(label="🤝 邀请组队", style=discord.ButtonStyle.primary)
        self.inviter = inviter
        self.target = target

    async def callback(self, interaction: discord.Interaction):
        uid = str(interaction.user.id)
        target_uid = self.target["discord_id"]
        with get_conn() as conn:
            inv = dict(conn.execute("SELECT * FROM players WHERE discord_id = ?", (uid,)).fetchone())
            tgt = dict(conn.execute("SELECT * FROM players WHERE discord_id = ?", (target_uid,)).fetchone())
        if inv["current_city"] != tgt["current_city"]:
            return await interaction.response.send_message("对方已离开此地。", ephemeral=True)
        if inv.get("party_id"):
            with get_conn() as conn:
                count = conn.execute("SELECT COUNT(*) FROM players WHERE party_id = ?", (inv["party_id"],)).fetchone()[0]
            if count >= 4:
                return await interaction.response.send_message("队伍已满（最多4人）。", ephemeral=True)
        if tgt.get("party_id"):
            return await interaction.response.send_message(f"**{tgt['name']}** 已在其他队伍中。", ephemeral=True)
        embed = discord.Embed(
            title="🤝 组队邀请",
            description=f"**{inv['name']}** 邀请你加入队伍。\n当前位置：{inv['current_city']}",
            color=discord.Color.blue(),
        )
        try:
            target_user = await interaction.client.fetch_user(int(target_uid))
            await target_user.send(embed=embed, view=PartyInviteResponseView(inv, tgt, interaction.user))
            await interaction.response.send_message(f"已向 **{tgt['name']}** 发送组队邀请。", ephemeral=True)
        except Exception:
            await interaction.response.send_message("无法发送邀请，对方可能关闭了私信。", ephemeral=True)


class PartyInviteResponseView(discord.ui.View):
    def __init__(self, inviter: dict, target: dict, inviter_user):
        super().__init__(timeout=60)
        self.inviter = inviter
        self.target = target
        self.inviter_user = inviter_user

    @discord.ui.button(label="接受", style=discord.ButtonStyle.success)
    async def accept(self, interaction: discord.Interaction, button: discord.ui.Button):
        uid = str(interaction.user.id)
        inv_uid = self.inviter["discord_id"]
        with get_conn() as conn:
            inv = dict(conn.execute("SELECT * FROM players WHERE discord_id = ?", (inv_uid,)).fetchone())
            tgt = dict(conn.execute("SELECT * FROM players WHERE discord_id = ?", (uid,)).fetchone())
        if inv["current_city"] != tgt["current_city"]:
            return await interaction.response.send_message("邀请者已离开原城市，组队失败。")
        if inv.get("party_id"):
            party_id = inv["party_id"]
            with get_conn() as conn:
                count = conn.execute("SELECT COUNT(*) FROM players WHERE party_id = ?", (party_id,)).fetchone()[0]
            if count >= 4:
                return await interaction.response.send_message("队伍已满，无法加入。")
        else:
            party_id = str(uuid.uuid4())[:8]
            with get_conn() as conn:
                conn.execute("INSERT INTO parties VALUES (?, ?, ?, ?)",
                             (party_id, inv_uid, inv["current_city"], time.time()))
                conn.execute("UPDATE players SET party_id = ? WHERE discord_id = ?", (party_id, inv_uid))
                conn.commit()
        with get_conn() as conn:
            conn.execute("UPDATE players SET party_id = ? WHERE discord_id = ?", (party_id, uid))
            conn.commit()
            members = [dict(r) for r in conn.execute(
                "SELECT * FROM players WHERE party_id = ?", (party_id,)).fetchall()]
            leader_row = dict(conn.execute("SELECT leader_id FROM parties WHERE party_id = ?", (party_id,)).fetchone())
        self.stop()
        embed = party_info_embed(members, leader_row["leader_id"])
        embed.title = "✦ 组队成功 ✦"
        await interaction.response.send_message(embed=embed)
        try:
            await self.inviter_user.send(embed=embed)
        except Exception:
            pass

    @discord.ui.button(label="拒绝", style=discord.ButtonStyle.secondary)
    async def decline(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.stop()
        await interaction.response.send_message("已拒绝组队邀请。")
        try:
            await self.inviter_user.send(f"**{self.target['name']}** 拒绝了你的组队邀请。")
        except Exception:
            pass
