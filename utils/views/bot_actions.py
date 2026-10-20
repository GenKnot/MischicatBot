"""玩家与机器人修士的互动面板：搭话、送礼（U1「江湖百态」）。

按钮挂在 `PlayerActionView`（点同城修士后出现的面板）上，只在对方是机器人时出现。
给不给、涨多少好感由 utils/bot_social.py 判定；这里只负责把结果连同台词（utils/bot_dialogue.py）展示出来。
"""

import time

import discord

from utils import bot_social as bs
from utils import bot_grudges, bot_memory, bot_profile, bot_ties, bot_traits
from utils import bot_requests as br
from utils.bots import is_bot_id
from utils.inventory import get_inventory
from utils.views.base import TimedView
from utils.items import ITEMS

TIER_COLORS = {"仇视": discord.Color.dark_red(), "陌生": discord.Color.light_grey(),
               "熟识": discord.Color.teal(), "至交": discord.Color.gold()}
HINT_ITEMS = 8        # 送礼窗口里最多提示几样背包物品


def favor_text(favor: int) -> str:
    return f"{bs.favor_tier(favor)}（{favor}）"


async def profile_lines(viewer_id: str, bot_id: str) -> list[str]:
    """机器人资料页多出来的几行：性格、与你的交情。"""
    persona = await bs.get_personality(bot_id)
    favor = await bs.get_favor(viewer_id, bot_id)
    lines = [f"性格：{persona['archetype'] if persona else '未知'}"
             + (f" · {bot_profile.alignment(persona['kindness'], persona['profile']['lawful'])}"
                if persona and persona.get("profile") else "")]
    if persona and persona.get("traits"):
        lines.append(bot_traits.describe(persona["traits"]))           # 出身 · 星座 · 内向外向
    lines.append(f"交情：{favor_text(favor)}")
    if (shared := bot_memory.summary(await bot_memory.recall(viewer_id, bot_id))):
        lines.append(shared)
    if (circle := await bot_ties.describe(bot_id)):                    # 它的圈子：结拜兄弟、同门、朋友、仇家
        lines.append(circle)
    if persona and persona.get("tier") == "天骄":                        # 天骄有称号和一句话背景
        if persona.get("epithet"):
            lines.insert(0, f"✨ 天骄「{persona['epithet']}」")
        if persona.get("backstory"):
            lines.append(f"\n*{persona['backstory']}*")
    return lines


def _result_embed(name: str, line: str, delta: int, favor: int, extra: str = "") -> discord.Embed:
    tier = bs.favor_tier(favor)
    embed = discord.Embed(title=f"💬 {name}", description=f"「{line}」", color=TIER_COLORS[tier])
    change = f"好感 {delta:+d} → " if delta else "好感不变 · "
    embed.set_footer(text=f"{change}{favor_text(favor)}{extra}")
    return embed


class BotChatButton(discord.ui.Button):
    def __init__(self, target: dict):
        super().__init__(label="💬 搭话", style=discord.ButtonStyle.primary)
        self.target = target

    async def callback(self, interaction: discord.Interaction):
        uid, bot_id = str(interaction.user.id), self.target["discord_id"]
        res = await bs.chat(uid, bot_id)
        if not res["ok"]:
            return await interaction.response.send_message(res["reason"], ephemeral=True)
        line = await bs.say("greet" if res["delta"] > 0 else "chat_again", uid, bot_id)
        await interaction.response.send_message(
            embed=_result_embed(res["bot_name"], line, res["delta"], res["favor"]), ephemeral=True)
        from utils.views.requests import run_meet
        await run_meet(interaction.followup.send, interaction.user, [bot_id])              # 当面聊：该还的还，熟人可能开口


class GiftModal(discord.ui.Modal, title="赠礼"):
    item = discord.ui.TextInput(label="要送的物品名", placeholder="例如：筑基丹", max_length=30)

    def __init__(self, target: dict, hint: str = ""):
        super().__init__()
        self.target = target
        if hint:
            self.item.placeholder = hint[:100]

    async def on_submit(self, interaction: discord.Interaction):
        uid, bot_id, item = str(interaction.user.id), self.target["discord_id"], str(self.item).strip()
        res = await bs.give_gift(uid, bot_id, item)
        if not res["ok"]:
            if res.get("code") == "limit":
                line = await bs.say("gift_limit", uid, bot_id)
                favor = await bs.get_favor(uid, bot_id)
                return await interaction.response.send_message(
                    embed=_result_embed(self.target["name"], line, 0, favor, "　今日不能再送了"), ephemeral=True)
            return await interaction.response.send_message(res["reason"], ephemeral=True)
        line = await bs.say(f"gift_{res['reaction']}", uid, bot_id, item=item)
        await interaction.response.send_message(
            embed=_result_embed(res["bot_name"], line, res["delta"], res["favor"], f"　今日还能送 {res['gifts_left']} 份"),
            ephemeral=True)


class BotGiftButton(discord.ui.Button):
    def __init__(self, target: dict):
        super().__init__(label="🎁 送礼", style=discord.ButtonStyle.success)
        self.target = target

    async def callback(self, interaction: discord.Interaction):
        inv = await get_inventory(str(interaction.user.id))
        owned = [n for n, q in inv.items() if q > 0 and n in ITEMS]
        if not owned:
            return await interaction.response.send_message("你的背包里没有可以送的物品。", ephemeral=True)
        hint = "背包里有：" + "、".join(sorted(owned)[:HINT_ITEMS])
        await interaction.response.send_modal(GiftModal(self.target, hint))


class BotBondButton(discord.ui.Button):
    def __init__(self, target: dict):
        super().__init__(label="🤝 结拜", style=discord.ButtonStyle.secondary)
        self.target = target

    async def callback(self, interaction: discord.Interaction):
        uid, bot_id = str(interaction.user.id), self.target["discord_id"]
        res = await bot_ties.propose_bond(uid, bot_id, await bs.get_favor(uid, bot_id))
        await interaction.response.send_message(res["reason"], ephemeral=not res["ok"])


APPEASE_STONES = (100, 500, 2000)


class _AppeaseButton(discord.ui.Button):
    def __init__(self, target: dict, method: str, amount: int = 0):
        label = f"赔礼 {amount} 灵石" if method == "stones" else "诚心道歉"
        super().__init__(label=label, style=discord.ButtonStyle.primary if method == "apology" else discord.ButtonStyle.secondary)
        self.target, self.method, self.amount = target, method, amount

    async def callback(self, interaction: discord.Interaction):
        res = await bot_grudges.appease(str(interaction.user.id), self.target["discord_id"], self.method, self.amount)
        await interaction.response.send_message(res["reason"], ephemeral=True)


class AppeaseView(TimedView):
    def __init__(self, target: dict, author=None):
        super().__init__(author=author)
        self.author = author                       # 只有点开面板的人能用（TimedView 的归属校验）
        for amount in APPEASE_STONES:
            self.add_item(_AppeaseButton(target, "stones", amount))
        self.add_item(_AppeaseButton(target, "apology"))


class BotAppeaseButton(discord.ui.Button):
    def __init__(self, target: dict):
        super().__init__(label="🕊️ 化解", style=discord.ButtonStyle.secondary)
        self.target = target

    async def callback(self, interaction: discord.Interaction):
        held = [g for g in await bot_grudges.grudges_of(self.target["discord_id"]) if g["target"] == str(interaction.user.id)]
        if not held:
            return await interaction.response.send_message(f"**{self.target['name']}** 并没有记恨你。", ephemeral=True)
        await interaction.response.send_message(
            f"**{self.target['name']}** 对你有旧怨。你可以赔礼、诚心道歉，或者多送些它喜欢的东西。", view=AppeaseView(self.target, interaction.user), ephemeral=True)


class ItemAskModal(discord.ui.Modal, title="借一件东西"):
    item = discord.ui.TextInput(label="想借的物品名", placeholder="对方背包里有的、不太贵重的东西", max_length=30)

    def __init__(self, target: dict):
        super().__init__()
        self.target = target

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        res = await br.player_ask(str(interaction.user.id), self.target["discord_id"], "loan_item", {"item": str(self.item).strip()})
        await interaction.followup.send(embed=_ask_result_embed(res, self.target["name"]), ephemeral=True)


def _ask_result_embed(res: dict, name: str) -> discord.Embed:
    if not res["ok"]:
        return discord.Embed(title="🙏 没能开口", description=res["reason"], color=discord.Color.light_grey())
    body = f"**{res['bot_name']}**：「{res['line']}」" if res["line"] else ""
    if res["reason"]:
        body = f"{res['reason']}\n{body}".strip()
    if res["accepted"]:
        from utils.character import seconds_to_years
        body += f"\n*约定 {seconds_to_years(max(0, res['due_at'] - time.time())):.1f} 年内了结。*" if res.get("due_at") else ""
    return discord.Embed(title="🙏 " + ("答应了" if res["accepted"] else "婉拒了"), description=body,
                         color=discord.Color.green() if res["accepted"] else discord.Color.light_grey())


class _AskButton(discord.ui.Button):
    def __init__(self, target: dict, kind: str, params: dict, label: str, style=discord.ButtonStyle.secondary):
        super().__init__(label=label, style=style)
        self.target, self.kind, self.params = target, kind, params

    async def callback(self, interaction: discord.Interaction):
        if not self.view.try_claim():
            return await interaction.response.send_message("你已经开过口了。", ephemeral=True)
        await interaction.response.defer()
        res = await br.player_ask(str(interaction.user.id), self.target["discord_id"], self.kind, self.params)
        await interaction.edit_original_response(embed=_ask_result_embed(res, self.target["name"]), view=None)


class _AskItemButton(discord.ui.Button):
    def __init__(self, target: dict):
        super().__init__(label="借物品…", style=discord.ButtonStyle.secondary)
        self.target = target

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.send_modal(ItemAskModal(self.target))


class AskView(TimedView):
    """向熟人求助：借灵石（几档）/ 借物品 / 请它陪你采集（四种）。每次只能开一次口。"""

    def __init__(self, target: dict, author):
        super().__init__(author=author)
        self.author = author
        pa = br.load()["player_ask"]
        for amount in pa["amounts"]:
            self.add_item(_AskButton(target, "loan_stones", {"amount": amount}, f"借 {amount} 灵石", discord.ButtonStyle.primary))
        self.add_item(_AskItemButton(target))
        for what in pa["gather_types"]:
            self.add_item(_AskButton(target, "companion_gather", {"what": what}, f"陪我{what}"))


class BotAskButton(discord.ui.Button):
    def __init__(self, target: dict):
        super().__init__(label="🙏 求助", style=discord.ButtonStyle.secondary)
        self.target = target

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.send_message(
            f"向 **{self.target['name']}** 开口求助：借灵石、借东西，或请它陪你去采集。答应与否看你们的交情和它的为人；借了要按时还。",
            view=AskView(self.target, interaction.user), ephemeral=True)


class BotRepayButton(discord.ui.Button):
    def __init__(self, target: dict):
        super().__init__(label="💰 还钱", style=discord.ButtonStyle.success)
        self.target = target

    async def callback(self, interaction: discord.Interaction):
        res = await br.repay_debt(str(interaction.user.id), self.target["discord_id"])
        if not res["ok"]:
            return await interaction.response.send_message(res["reason"], ephemeral=True)
        text = (f"还了 **{res['paid']}** 灵石" if res["paid"] else "") + ("、" if res["paid"] and res.get("items") else "") + \
               ("、".join(f"{i}（原物奉还）" for i in res.get("items", [])))
        text += f"，还欠 **{res['left']}** 灵石。" if res["left"] else "，账清了。"
        if res["line"]:
            text += f"\n**{self.target['name']}**：「{res['line']}」"
        await interaction.response.send_message(text, ephemeral=True)


def add_bot_buttons(view: discord.ui.View, target: dict) -> None:
    if is_bot_id(target["discord_id"]):
        view.add_item(BotChatButton(target))
        view.add_item(BotGiftButton(target))
        view.add_item(BotBondButton(target))
        view.add_item(BotAppeaseButton(target))
        view.add_item(BotAskButton(target))
        view.add_item(BotRepayButton(target))
