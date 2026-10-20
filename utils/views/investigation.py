"""失踪调查的 Discord 界面（U1·江湖百态）：机器人问『你见过某某吗』，玩家用按钮回答。逻辑在 utils/bot_investigation.py。"""

import discord

from utils import bot_investigation as bi
from utils.views.base import TimedView

CHOICE_LABEL = {"seen": "见过", "unseen": "没见过", "silent": "不想说"}


def question_embed(q: dict) -> discord.Embed:
    e = discord.Embed(title=f"🔎 {q['seeker_name']}（{q['seeker_realm']}）在打听人", description=f"「{q['line']}」", color=discord.Color.dark_teal())
    e.set_footer(text="你可以如实回答，也可以不说。")
    return e


class QuestionView(TimedView):
    """问话面板：只有被问的玩家能点，答一次。"""

    def __init__(self, q: dict, author):
        super().__init__(author=author)
        self.author = author
        self.q = q
        for key, label in CHOICE_LABEL.items():
            self.add_item(_AnswerButton(key, label))


class _AnswerButton(discord.ui.Button):
    def __init__(self, key: str, label: str):
        super().__init__(label=label, style=discord.ButtonStyle.primary if key == "seen" else discord.ButtonStyle.secondary)
        self.key = key

    async def callback(self, interaction: discord.Interaction):
        view = self.view
        if not view.try_claim():
            return await interaction.response.send_message("你已经回答过了。", ephemeral=True)
        await interaction.response.defer()
        res = await bi.answer(view.q["id"], str(interaction.user.id), self.key)
        embed = question_embed(view.q)
        if res.get("ok") and res["line"]:
            embed.add_field(name=f"你答：{CHOICE_LABEL[self.key]}", value=f"**{res['bot_name'] or view.q['seeker_name']}**：「{res['line']}」", inline=False)
        elif not res.get("ok"):
            embed.add_field(name="——", value=res["reason"], inline=False)
        await interaction.edit_original_response(embed=embed, view=None)


async def run_question(send, user, present_ids: list[str]) -> bool:
    """玩家碰到一群机器人：有人在找失踪的朋友就问一句。返回有没有发。"""
    q = await bi.maybe_question(str(user.id), present_ids)
    if q is None:
        return False
    view = QuestionView(q, user)
    view.message = await send(f"<@{user.id}>", embed=question_embed(q), view=view)
    return True
