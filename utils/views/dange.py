import discord
from sqlalchemy import func, update

from utils.atomic import spend_stones
from utils.db_async import AsyncSessionLocal, Player, Inventory
from utils.views.base import TimedView

EXAM_COST = 500
MATERIAL_COST = 300

REALM_TIER = {
    "炼气": 0, "筑基": 1, "结丹": 2, "元婴": 3, "化神": 4,
    "炼虚": 5, "合体": 6, "大乘": 7, "真仙": 8, "金仙": 9,
    "太乙": 10, "大罗": 11, "道祖": 12,
}


def _get_realm_tier(realm: str) -> int:
    for k, v in REALM_TIER.items():
        if realm.startswith(k):
            return v
    return 0


def _lifespan_label(player: dict) -> str:
    lifespan = player.get("lifespan", 100)
    max_lifespan = player.get("lifespan_max", player.get("max_lifespan", 100))
    if max_lifespan <= 0:
        return "少年"
    ratio = lifespan / max_lifespan
    if ratio >= 0.8:
        return "少年"
    elif ratio >= 0.5:
        return "中年"
    else:
        return "老年"


def _elder_greeting(player: dict) -> str:
    tier = _get_realm_tier(player.get("realm", "炼气"))
    rep = player.get("reputation", 0)
    name = player.get("name", "道友")
    if tier >= 4:
        return (
            f"老朽眼拙，竟未认出是**{name}**大人驾临。\n"
            f"以您的修为，屈尊来此考核，实在令丹阁蓬荜生辉。\n"
            f"规矩归规矩，还请大人莫要见怪，走个过场便是。"
        )
    elif tier >= 2:
        return (
            f"哦？**{name}**道友，修为不俗，竟也有意踏入炼丹一道？\n"
            f"炼丹与修炼并不相悖，说不定能相辅相成。\n"
            f"规矩不能废，还请道友参加入门考核。"
        )
    elif rep >= 500:
        return (
            f"**{name}**道友，久仰大名，声望斐然。\n"
            f"有此声望，想必也是个有毅力之人。\n"
            f"炼丹之道，贵在坚持，老朽期待你的表现。"
        )
    else:
        return (
            f"年轻人，你来丹阁所为何事？\n"
            f"想学炼丹？哼，炼丹可不是闹着玩的。\n"
            f"先把考核费交了，老朽看看你有没有这个资质。"
        )


def _elder_greeting_paid(player: dict) -> str:
    tier = _get_realm_tier(player.get("realm", "炼气"))
    if tier >= 2:
        return "你已缴过考核费了。材料在背包里，去炼丹台继续摸索吧。材料不够可以再买。"
    else:
        return "你已经缴过费了，材料在背包里呢。去炼丹台试试，材料用完了可以花灵石再买。"


async def _give_materials(uid: str, session):
    from sqlalchemy.dialects.sqlite import insert as sqlite_insert
    items = [("灵芝草", 6), ("茯苓灵块", 3)]
    for item_id, qty in items:
        stmt = sqlite_insert(Inventory).values(
            discord_id=uid, item_id=item_id, quantity=qty
        ).on_conflict_do_update(
            index_elements=["discord_id", "item_id"],
            set_={"quantity": Inventory.quantity + qty},
        )
        await session.execute(stmt)


class DangeView(TimedView):
    def __init__(self, author, cog, player: dict, paid: bool = False):
        super().__init__()
        self.author = author
        self.cog = cog
        self.player = player
        self.paid = paid

    @discord.ui.button(label="缴费参加考核（500灵石）", style=discord.ButtonStyle.success, row=0)
    async def pay_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        uid = str(interaction.user.id)
        async with AsyncSessionLocal() as session:
            player = await session.get(Player, uid)
            if not player:
                return await interaction.response.send_message("角色不存在。", ephemeral=True)
            if player.alchemy_level > 0:
                return await interaction.response.send_message("你已经是炼丹师了，无需再考核。", ephemeral=True)
            # exam_attempts_left > 0 就是已缴费。只有从 0 翻到 1 那次收费。
            claimed = await session.execute(
                update(Player)
                .where(
                    Player.discord_id == uid,
                    Player.alchemy_level == 0,
                    func.coalesce(Player.exam_attempts_left, 0) == 0,
                )
                .values(exam_attempts_left=1)
            )
            if claimed.rowcount != 1:
                return await interaction.response.send_message(
                    "*「你已经交过钱了，材料用完再来找我补。」*", ephemeral=True)

            # rollback 会让 ORM 对象过期，之后再读属性会触发同步 IO，
            # 所以先把要显示的余额取成普通变量
            stones_now = player.spirit_stones
            if not await spend_stones(session, uid, EXAM_COST):
                await session.rollback()      # 连带退回刚打上的缴费标记
                return await interaction.response.send_message(
                    f"*「灵石不够就别来凑热闹了，{EXAM_COST} 灵石，一个子儿都不能少。」*\n\n"
                    f"当前灵石：**{stones_now}**",
                    ephemeral=True,
                )
            await _give_materials(uid, session)
            await session.commit()

        await _go_to_alchemy(interaction, self.author, self.player, self.cog,
                             "材料已放入你的背包（灵芝草 ×6、茯苓灵块 ×3），能不能炼出来就看你的造化了。去炼丹台碰碰运气吧。")

    @discord.ui.button(label="前往炼丹台", style=discord.ButtonStyle.primary, row=0)
    async def alchemy_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await _go_to_alchemy(interaction, self.author, self.player, self.cog,
                             _elder_greeting_paid(self.player))

    @discord.ui.button(label="购买材料（300灵石）", style=discord.ButtonStyle.secondary, row=0)
    async def buy_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        uid = str(interaction.user.id)
        async with AsyncSessionLocal() as session:
            player = await session.get(Player, uid)
            if not player:
                return await interaction.response.send_message("角色不存在。", ephemeral=True)
            if not await spend_stones(session, uid, MATERIAL_COST):
                return await interaction.response.send_message(
                    f"*「{MATERIAL_COST} 灵石都拿不出来？」*\n\n当前灵石：**{player.spirit_stones}**",
                    ephemeral=True,
                )
            await _give_materials(uid, session)
            await session.commit()
        await interaction.response.send_message(
            f"材料已补充到背包。\n获得：灵芝草 ×6、茯苓灵块 ×3",
            ephemeral=True,
        )

    @discord.ui.button(label="返回主菜单", style=discord.ButtonStyle.secondary, row=1)
    async def back_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        from utils.views.world import _send_main_menu
        await interaction.response.defer()
        await _send_main_menu(interaction, self.cog)

    def set_paid(self, paid: bool):
        self.paid = paid
        self.pay_btn.disabled = paid
        self.pay_btn.label = "已缴费" if paid else f"缴费参加考核（{EXAM_COST}灵石）"
        self.alchemy_btn.disabled = not paid
        self.buy_btn.disabled = not paid


async def _go_to_alchemy(interaction, author, player, cog, msg: str):
    from utils.views.alchemy import AlchemyMainView
    from utils.alchemy import get_known_recipes_with_choices
    uid = str(interaction.user.id)
    known_map = await get_known_recipes_with_choices(uid)
    view = AlchemyMainView(author, player, False, set(known_map.keys()), cog=cog, known_choices=known_map)
    await interaction.response.edit_message(
        content=f"*「{msg}」*",
        embed=None,
        view=view,
    )
