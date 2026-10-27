import logging
import discord
from utils import rules
from utils.party import (
    get_party, get_party_members, accept_invite,
    remove_from_party, disband_party,
)
from utils.bot_social import say
from utils.bots import is_bot_id, send_dm
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
    embed.set_footer(text=f"共 {len(members)} 人 · 最多{rules.section('party')['max_size']}人")
    return embed


async def leave_party(uid: str, client) -> str:
    return await remove_from_party(uid)


async def disband_party_func(uid: str, client) -> str:
    msg, member_ids = await disband_party(uid)
    for mid in member_ids:
        if mid == uid:
            continue
        try:
            await send_dm(client, mid, "队长已解散队伍，你已退出。")
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
        if uid == target_uid:
            return await interaction.response.send_message("不能邀请自己。", ephemeral=True)
        inv = await get_player(uid)
        tgt = await get_player(target_uid)
        if not inv or not tgt:
            return await interaction.response.send_message("对方数据不存在。", ephemeral=True)
        if tgt["is_dead"]:
            return await interaction.response.send_message("对方已坐化。", ephemeral=True)
        if inv["current_city"] != tgt["current_city"]:
            return await interaction.response.send_message("对方已离开此地。", ephemeral=True)
        if inv.get("party_id"):
            members = await get_party_members(inv["party_id"])
            if len(members) >= rules.section("party")["max_size"]:
                return await interaction.response.send_message(f"队伍已满（最多{rules.section('party')['max_size']}人）。", ephemeral=True)
        if tgt.get("party_id"):
            return await interaction.response.send_message(f"**{tgt['name']}** 已在其他队伍中。", ephemeral=True)
        if is_bot_id(target_uid):
            return await self._invite_bot(interaction, uid, inv, tgt)
        embed = discord.Embed(
            title="🤝 组队邀请",
            description=f"**{inv['name']}** 邀请你加入队伍。\n当前位置：{inv['current_city']}",
            color=discord.Color.blue(),
        )
        try:
            sent = await send_dm(interaction.client, target_uid, embed=embed,
                                 view=PartyInviteResponseView(inv, tgt, interaction.user))
        except Exception:
            sent = False
        if sent:
            await interaction.response.send_message(f"已向 **{tgt['name']}** 发送组队邀请。", ephemeral=True)
        else:
            await interaction.response.send_message("无法发送邀请，对方可能关闭了私信。", ephemeral=True)


    async def _invite_bot(self, interaction: discord.Interaction, uid: str, inv: dict, tgt: dict):
        """机器人没有私信可收：好感与性格够了就当场答应（加入逻辑与真人接受邀请同一个 accept_invite）。"""
        result = await accept_invite(uid, tgt["discord_id"])
        if not result["ok"]:
            reason = result["reason"]
            if result.get("bot_refused"):
                reason = f"「{await say('party_refuse', uid, tgt['discord_id'])}」\n\n{reason}"
            return await interaction.response.send_message(reason, ephemeral=True)
        members = await get_party_members(result["party_id"])
        party = await get_party(result["party_id"])
        embed = party_info_embed(members, party["leader_id"])
        embed.title = "✦ 组队成功 ✦"
        embed.description = f"**{tgt['name']}**：「{await say('party_accept', uid, tgt['discord_id'])}」\n欣然应允，与你结伴同行。"
        await interaction.response.send_message(embed=embed)


class PartyInviteResponseView(TimedView):
    public = True          # 归属校验在按钮回调里（比对 self.target）
    def __init__(self, inviter: dict, target: dict, inviter_user):
        super().__init__()
        self.inviter = inviter
        self.target = target
        self.inviter_user = inviter_user

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        # public = True 时基类不校验归属：邀请是私信发给被邀请者的，这里再核对一次点击者（B68）
        if interaction.message is not None:
            self.message = interaction.message
        if str(interaction.user.id) != str(self.target["discord_id"]):
            await interaction.response.send_message("这不是你的邀请。", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="接受", style=discord.ButtonStyle.success)
    async def accept(self, interaction: discord.Interaction, button: discord.ui.Button):
        uid = str(interaction.user.id)
        result = await accept_invite(self.inviter["discord_id"], uid)
        if not result["ok"]:
            return await interaction.response.send_message(result["reason"])
        party_id = result["party_id"]
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
