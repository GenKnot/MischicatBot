"""玩家与机器人修士的互动面板：搭话、送礼（U1「江湖百态」）。

按钮挂在 `PlayerActionView`（点同城修士后出现的面板）上，只在对方是机器人时出现。
给不给、涨多少好感由 utils/bot_social.py 判定；这里只负责把结果连同台词（utils/bot_dialogue.py）展示出来。
"""

import discord

from utils import bot_social as bs
from utils.bots import is_bot_id
from utils.inventory import get_inventory
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
    lines = [f"性格：{persona['archetype'] if persona else '未知'}", f"交情：{favor_text(favor)}"]
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


def add_bot_buttons(view: discord.ui.View, target: dict) -> None:
    if is_bot_id(target["discord_id"]):
        view.add_item(BotChatButton(target))
        view.add_item(BotGiftButton(target))
