import logging
import discord
from utils.party import (
    get_party, get_party_members, create_party, add_to_party,
    remove_from_party, disband_party,
)
from utils.player import get_player
from utils.views.base import TimedView

log = logging.getLogger(__name__)


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
    return await remove_from_party(uid)


async def disband_party_func(uid: str, client) -> str:
    msg, member_ids = await disband_party(uid)
    for mid in member_ids:
        if mid == uid:
            continue
        try:
            user = await client.fetch_user(int(mid))
            await user.send("队长已解散队伍，你已退出。")
        except Exception:
            # 对方关了私信是常态
            log.debug("私信发送失败 uid=%s", mid, exc_info=True)
    return msg


class PartyView(TimedView):
    def __init__(self, author, cog=None):
        super().__init__()
        self.author = author
        self.cog = cog


class PartyInviteButton(discord.ui.Button):
    def __init__(self, inviter: dict, target: dict):
        super().__init__(label="🤝 邀请组队", style=discord.ButtonStyle.primary)
        self.inviter = inviter
        self.target = target

    async def callback(self, interaction: discord.Interaction):
        uid = str(interaction.user.id)
        target_uid = self.target["discord_id"]
        inv = await get_player(uid)
        tgt = await get_player(target_uid)
        if inv["current_city"] != tgt["current_city"]:
            return await interaction.response.send_message("对方已离开此地。", ephemeral=True)
        if inv.get("party_id"):
            members = await get_party_members(inv["party_id"])
            if len(members) >= 4:
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


class PartyInviteResponseView(TimedView):
    public = True          # 归属校验在按钮回调里（比对 self.target）
    def __init__(self, inviter: dict, target: dict, inviter_user):
        super().__init__()
        self.inviter = inviter
        self.target = target
        self.inviter_user = inviter_user

    @discord.ui.button(label="接受", style=discord.ButtonStyle.success)
    async def accept(self, interaction: discord.Interaction, button: discord.ui.Button):
        uid = str(interaction.user.id)
        inv_uid = self.inviter["discord_id"]
        inv = await get_player(inv_uid)
        tgt = await get_player(uid)
        if inv["current_city"] != tgt["current_city"]:
            return await interaction.response.send_message("邀请者已离开原城市，组队失败。")
        if inv.get("party_id"):
            party_id = inv["party_id"]
            members = await get_party_members(party_id)
            if len(members) >= 4:
                return await interaction.response.send_message("队伍已满，无法加入。")
            await add_to_party(party_id, uid)
        else:
            party_id = await create_party(inv_uid, inv["current_city"])
            await add_to_party(party_id, uid)
        party = await get_party(party_id)
        members = await get_party_members(party_id)
        self.stop()
        embed = party_info_embed(members, party["leader_id"])
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
