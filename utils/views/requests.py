"""机器人请求 / 委托的 Discord 界面（U1·江湖百态）：开口 → 答应 / 婉拒；碰面时的结算消息。逻辑在 utils/bot_requests.py。"""

import logging

import discord

from utils import bot_requests as br
from utils.views.base import TimedView

log = logging.getLogger(__name__)

EVENT_TITLE = {"repay": "💰 还钱", "repay_plus": "💰 多还了些", "repay_item": "📦 物归原主", "short": "💸 先还一部分", "default": "😒 赖账",
               "errand_done": "✉️ 信已送到", "gather_done": "🌿 一起采集"}


def offer_summary(offer: dict) -> str:
    p, kind = offer["params"], offer["kind"]
    return {"loan_stones": f"借给它 **{p.get('amount')}** 灵石（它约定 1~5 年内归还）",
            "loan_item": f"借给它 **{p.get('item')}**（它约定 1~5 年内归还）",
            "errand": f"替它给 **{p.get('city')}** 的 **{p.get('target_name')}** 送一封信（到了那座城，对方在场就算送到）",
            "companion_gather": f"陪它{p.get('what')}（期限内你在它所在的城开始采集即可）"}.get(kind, "")


def offer_embed(offer: dict) -> discord.Embed:
    e = discord.Embed(title=f"📨 {offer['bot_name']}（{offer['bot_realm']}）有事相求", description=f"「{offer['line']}」", color=discord.Color.teal())
    e.add_field(name="请求", value=offer_summary(offer), inline=False)
    e.set_footer(text="不答应也没关系，不会影响交情。")
    return e


def events_embed(events: list[dict]) -> discord.Embed:
    first = events[0]
    e = discord.Embed(title=EVENT_TITLE.get(first["kind"], "📜 了结") if len(events) == 1 else f"📜 {len(events)} 件事有了结果",
                      color=discord.Color.dark_red() if first["kind"] == "default" else discord.Color.green())
    lines = []
    for ev in events:
        note = ""
        if ev["kind"] in ("repay", "repay_plus", "short") and ev.get("amount"):
            note = f"（{'收回' if ev['kind'] != 'short' else '仍欠'} {ev['amount']} 灵石）"
        elif ev["kind"] in ("errand_done", "gather_done") and ev.get("amount"):
            note = f"（酬劳 {ev['amount']} 灵石）"
        elif ev["kind"] == "repay_item":
            note = f"（{ev.get('item')} 归还）"
        lines.append(f"{EVENT_TITLE.get(ev['kind'], '')} **{ev['bot_name']}**：「{ev['line']}」{note}")
    e.description = "\n".join(lines)
    return e


class OfferView(TimedView):
    """请求面板：只有被求的玩家能点。"""

    def __init__(self, offer: dict, author):
        super().__init__(author=author)
        self.author = author
        self.offer = offer

    @discord.ui.button(label="答应", style=discord.ButtonStyle.success)
    async def agree(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.try_claim():
            return await interaction.response.send_message("已经答复过了。", ephemeral=True)
        await interaction.response.defer()
        res = await br.accept(self.offer["id"])
        if not res["ok"]:
            return await interaction.edit_original_response(embed=discord.Embed(title="📨 没能答应", description=res["reason"]), view=None)
        embed = offer_embed(self.offer)
        embed.add_field(name="你答应了", value=f"**{res['bot_name']}**：「{res['line']}」", inline=False)
        await interaction.edit_original_response(embed=embed, view=None)

    @discord.ui.button(label="婉拒", style=discord.ButtonStyle.secondary)
    async def refuse(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.try_claim():
            return await interaction.response.send_message("已经答复过了。", ephemeral=True)
        await interaction.response.defer()
        res = await br.decline(self.offer["id"])
        embed = offer_embed(self.offer)
        embed.add_field(name="你婉拒了", value=f"**{self.offer['bot_name']}**：「{res.get('line', '')}」", inline=False)
        await interaction.edit_original_response(embed=embed, view=None)


async def send_offer(send, user, offer: dict) -> None:
    view = OfferView(offer, user)
    view.message = await send(f"<@{user.id}>", embed=offer_embed(offer), view=view)


async def run_meet(send, user, present_ids: list[str]) -> bool:
    """玩家和一群机器人碰面：结算到期的借款 / 送到的信，熟人可能开口相求。返回有没有发消息。"""
    res = await br.on_meet(str(user.id), present_ids)
    if res["events"]:
        await send(embed=events_embed(res["events"]))
    if res["offer"]:
        await send_offer(send, user, res["offer"])
    return bool(res["events"] or res["offer"])


async def run_gather(send, user, city: str) -> bool:
    """玩家开始采集：约好陪采集的机器人若在同一座城，这次就一起去了。"""
    events = await br.on_gather(str(user.id), city)
    if events:
        await send(embed=events_embed(events))
    return bool(events)
