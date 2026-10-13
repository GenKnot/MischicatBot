"""拦路遭遇的 Discord 界面（U1·江湖百态 P4）：逃跑 / 迎战 → 交涉 → 处置。逻辑在 utils/bot_ambush.py。

遭遇的状态存在库里，面板只是个遥控器：bot 重启后面板没了，后台循环（cogs/ambush.py）会按超时规则收尾。
"""

import logging

import discord

from utils import bot_ambush as ba
from utils.views.base import TimedView

log = logging.getLogger(__name__)

OUTCOME_TEXT = {
    "release": "放你一条生路。",
    "rob": "搜走了你身上的灵石。",
    "cripple": "废去了你的修为，把你扔到了远处的城里。",
    "kill": "取了你的性命。",
}


def encounter_embed(enc: dict) -> discord.Embed:
    leader = enc["leader"]
    e = discord.Embed(title=f"⚔️ 拦路 · {leader['name']}", color=discord.Color.dark_red(),
                      description=f"「{enc['taunt']}」" if enc.get("taunt") else None)
    shown = enc["companions"][:ba.load()["companions"]["show_names"]]
    who = f"**{leader['name']}**（{leader['realm']}）" + "".join(f"、**{c['name']}**（{c['realm']}）" for c in shown)
    if len(enc["companions"]) > len(shown):
        who += f"……等共 **{len(enc['companions']) + 1}** 人"
    elif enc["companions"]:
        who += f"（共 {len(enc['companions']) + 1} 人）"
    e.add_field(name="来者", value=who, inline=False)
    e.add_field(name="缘由", value=enc["reason"], inline=False)
    if enc.get("rescuer"):
        e.add_field(name="🤝 援手", value=f"**{enc['rescuer']['name']}** 恰好在附近，赶来助你。", inline=False)
    e.set_footer(text="一分钟内选择逃跑或迎战；不选视为逃跑。")
    return e


def bargain_embed(leader_name: str, demand: str, price: int, powers=None, rate=None) -> discord.Embed:
    how = (f"逃跑失败（成功率 {rate * 100:.0f}%）" if rate is not None else
           f"迎战落败（你 {powers[0]} ／ 对方 {powers[1]}）" if powers else "你落败了")
    e = discord.Embed(title=f"⚖️ 交涉 · {leader_name}", description=f"{how}，**{leader_name}**：\n「{demand}」", color=discord.Color.orange())
    if price:
        e.add_field(name="买命钱", value=f"{price} 灵石（对方未必肯收）", inline=False)
    e.set_footer(text="一分钟内回应；不回应视为拒绝。")
    return e


def outcome_embed(res: dict, leader_name: str) -> discord.Embed:
    if res["stage"] == "escaped":
        text = f"你成功脱身（逃跑成功率 {res['rate'] * 100:.0f}%）。"
        if res.get("line"):
            text += f"\n**{leader_name}**：「{res['line']}」"
        return discord.Embed(title="🏃 脱身", description=text, color=discord.Color.green())
    if res["stage"] == "won":
        return discord.Embed(title="🏆 击退", description=f"你击退了 **{leader_name}**（战力 {res['mine']} ／ {res['theirs']}）。怎么处置它，由你决定。",
                             color=discord.Color.green())
    if res["stage"] == "done":
        out = res["outcome"]
        text = ("你奉上灵石买命，" if res.get("bought") else "") + f"**{leader_name}** " + OUTCOME_TEXT[out]
        if res.get("amount") and out != "release":
            text += f"（{res['amount']} 灵石）"
        if res.get("line"):
            text += f"\n**{leader_name}**：「{res['line']}」"
        if res.get("killed"):
            text += "\n*你的角色已坐化。江湖不会因你而停，可以重新创建角色。*"
        return discord.Embed(title="💀 拦路了结" if out == "kill" else "拦路了结", description=text,
                             color=discord.Color.dark_red() if out in ("kill", "cripple") else discord.Color.light_grey())
    return discord.Embed(title="拦路已结束", description="这场遭遇已经结束了。", color=discord.Color.light_grey())


class AmbushView(TimedView):
    """遭遇面板：只有被拦的玩家能点（TimedView 的归属校验）；timeout=None —— 超时由后台循环按库里的 expires_at 收尾。"""

    def __init__(self, enc_id: str, author, leader_name: str):
        super().__init__(author=author, timeout=None)
        self.author = author
        self.enc_id, self.leader_name = enc_id, leader_name

    @discord.ui.button(label="🏃 逃跑", style=discord.ButtonStyle.secondary)
    async def flee(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        await show_result(interaction, self.enc_id, self.leader_name, await ba.choose_flee(self.enc_id))

    @discord.ui.button(label="⚔️ 迎战", style=discord.ButtonStyle.danger)
    async def fight(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        await show_result(interaction, self.enc_id, self.leader_name, await ba.choose_fight(self.enc_id))


class BargainView(TimedView):
    def __init__(self, enc_id: str, author, leader_name: str, price: int):
        super().__init__(author=author, timeout=None)
        self.author = author
        self.enc_id, self.leader_name = enc_id, leader_name
        for key, r in ba.load()["responses"].items():
            self.add_item(_RespondButton(key, r["label"]))
        if price > 0:
            self.add_item(_RespondButton("buyout", f"💰 买命（{price}）", discord.ButtonStyle.success))


class _RespondButton(discord.ui.Button):
    def __init__(self, key: str, label: str, style=discord.ButtonStyle.secondary):
        super().__init__(label=label, style=style)
        self.key = key

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer()
        view = self.view
        res = await ba.respond(view.enc_id, self.key)
        if res["stage"] == "bargain" and res.get("error"):          # 买命钱不够：面板还在，可以改选
            return await interaction.followup.send(res["error"], ephemeral=True)
        await show_result(interaction, view.enc_id, view.leader_name, res)


async def show_result(interaction: discord.Interaction, enc_id: str, leader_name: str, res: dict) -> None:
    """把一步的结果画到原消息上：交涉阶段换成交涉面板，其余收起按钮；迎战获胜再给战后面板。"""
    target_id = str(interaction.user.id)
    if res["stage"] == "bargain":
        embed = bargain_embed(leader_name, res.get("demand", ""), res["price"], res.get("powers"), res.get("rate"))
        return await interaction.edit_original_response(embed=embed, view=BargainView(enc_id, interaction.user, leader_name, res["price"]))
    await interaction.edit_original_response(embed=outcome_embed(res, leader_name), view=None)
    if res["stage"] == "won":
        from utils.player import get_player
        from utils.views.combat import VictoryActionView
        winner, loser = await get_player(target_id), await get_player(res["leader"])
        if winner and loser and not loser["is_dead"]:
            await interaction.followup.send(f"**{leader_name}** 败了，你要怎么处置？", view=VictoryActionView(interaction.user, winner, loser))


async def start_encounter(send, enc: dict, user) -> None:
    """发出拦路消息（带逃跑 / 迎战按钮），并把消息位置记进库里，供后台循环收尾时编辑。"""
    msg = await send(f"<@{user.id}>", embed=encounter_embed(enc), view=AmbushView(enc["id"], user, enc["leader"]["name"]))
    channel = getattr(msg, "channel", None)
    if msg is not None and getattr(msg, "id", None) is not None and channel is not None and getattr(channel, "id", None) is not None:
        await ba.set_message(enc["id"], channel.id, msg.id)


async def run_hook(send, user, context: str) -> bool:
    """野外动作的拦路钩子：判定一次，有人找上门就发消息。返回有没有拦路（True = 这次动作被打断了）。"""
    enc = await ba.maybe_ambush(str(user.id), context)
    if enc is None:
        return False
    if enc["aborted"]:
        await send(f"{user.mention} **{enc['leader']['name']}** 本想拦你，却见 **{enc['rescuer']['name']}** 赶到，悻悻而去。\n*缘由：{enc['reason']}*")
        return True
    await start_encounter(send, enc, user)
    return True
