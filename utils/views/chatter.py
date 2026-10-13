"""机器人主动搭话的界面（U1·江湖百态 P5）：一条带回应按钮的消息。逻辑在 utils/bot_chatter.py。

普通搭话（到城 / 道贺 / 公共事件 / 劝架）：💞热情 🙂客气 😐淡淡 😒冷淡 —— 好感小幅变化，机器人回一句；冲突后的放话：🕊️化解。都有 🔕屏蔽。
"""

import logging

import discord

from utils import bot_chatter as bc
from utils.views.base import TimedView

log = logging.getLogger(__name__)

CONFLICT_SCENES = {"chatter_conflict_self", "chatter_conflict_friend"}
REPLY_LABELS = (("warm", "💞 热情", discord.ButtonStyle.success), ("ok", "🙂 客气", discord.ButtonStyle.primary),
                ("neutral", "😐 淡淡", discord.ButtonStyle.secondary), ("cold", "😒 冷淡", discord.ButtonStyle.secondary))


def chatter_embed(payload: dict) -> discord.Embed:
    entries = payload.get("entries") or []
    color = discord.Color.dark_gold() if payload["scene"] in CONFLICT_SCENES else discord.Color.blurple()
    if len(entries) > 1 or payload.get("more"):                  # 好几个人一起说话：一人一行
        body = "\n".join(f"**{e['bot_name']}**（{e['bot_realm']}）：「{e['line']}」" for e in entries)
        if payload.get("more"):
            body += f"\n……另有 **{payload['more']}** 位也来了。"
        e = discord.Embed(title=f"💬 {len(entries) + payload.get('more', 0)} 位修士", description=body, color=color)
    else:
        e = discord.Embed(title=f"💬 {payload['bot_name']}（{payload['bot_realm']}）", description=f"「{payload['line']}」", color=color)
    e.set_footer(text="不想再收到这类消息，可以点 🔕 屏蔽。")
    return e


class ChatterView(TimedView):
    """搭话面板：只有被搭话的玩家能点。"""
    public = True

    def __init__(self, payload: dict):
        super().__init__(author=None)
        self.payload = payload
        self.player_id, self.bot_id = payload["player_id"], payload["bot_id"]
        if payload["scene"] in CONFLICT_SCENES:
            from utils.views.bot_actions import BotAppeaseButton
            self.add_item(BotAppeaseButton({"discord_id": self.bot_id, "name": payload["bot_name"]}))
        else:
            for key, label, style in REPLY_LABELS:
                self.add_item(_ReplyButton(key, label, style))
        self.add_item(_MuteButton())

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        self.message = interaction.message
        if str(interaction.user.id) != self.player_id:
            await interaction.response.send_message("这不是对你说的。", ephemeral=True)
            return False
        return True


class _ReplyButton(discord.ui.Button):
    def __init__(self, key: str, label: str, style):
        super().__init__(label=label, style=style)
        self.key = key

    async def callback(self, interaction: discord.Interaction):
        view = self.view
        if not view.try_claim():
            return await interaction.response.send_message("你已经回应过了。", ephemeral=True)
        await interaction.response.defer()
        res = await bc.respond(view.player_id, view.bot_id, self.key)
        embed = chatter_embed(view.payload)
        if res.get("line"):
            embed.add_field(name=f"你{self.label.split(' ', 1)[1]}地回应", value=f"**{view.payload['bot_name']}**：「{res['line']}」", inline=False)
        await interaction.edit_original_response(embed=embed, view=None)


class _MuteButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="🔕 屏蔽", style=discord.ButtonStyle.secondary)

    async def callback(self, interaction: discord.Interaction):
        await bc.set_muted(self.view.player_id, True)
        await interaction.response.send_message("已屏蔽机器人的主动搭话（仇怨和拦路不受影响）。想恢复用 `屏蔽机器人消息 关`。", ephemeral=True)


async def send_payload(send, payload: dict):
    """发出一条搭话（带按钮），返回消息。"""
    view = ChatterView(payload)
    msg = await send(f"<@{payload['player_id']}>", embed=chatter_embed(payload), view=view)
    view.message = msg
    return msg


async def run_arrive(send, user, city: str) -> bool:
    """玩家到了 city：有熟人搭话就发出去（并记账）。返回有没有发。"""
    import time
    from utils.views.requests import run_meet
    payload = await bc.maybe_arrive(str(user.id), city)
    if payload is not None:
        await bc.record(payload["player_id"], payload.get("all_bot_ids") or payload["bot_id"], time.time())
        await send_payload(send, payload)
    spoke = await run_meet(send, user, await bc.bots_in_city(city))        # 借款到期、信送到、熟人相求（打招呼被每日上限挡住时也照常结算）
    return payload is not None or spoke
