import discord
from utils.views.base import TimedView


class CultivateView(TimedView):
    YEAR_OPTIONS = [
        (1, "1年",  "现实 2 小时"),
        (2, "2年",  "现实 4 小时"),
        (4, "4年",  "现实 8 小时"),
        (8, "8年",  "现实 16 小时"),
    ]

    def __init__(self, author, cog, player: dict):
        super().__init__()
        self.author = author
        self.cog = cog
        self.player = player
        for years, label, hint in self.YEAR_OPTIONS:
            disabled = player["lifespan"] < years
            self.add_item(CultivateButton(years, label, hint, disabled))
        self.add_item(_BackToMenuButton())


class CultivateButton(discord.ui.Button):
    def __init__(self, years: int, label: str, hint: str, disabled: bool):
        super().__init__(label=f"{label}（{hint}）", style=discord.ButtonStyle.primary, disabled=disabled)
        self.years = years

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer()
        await self.view.cog.start_cultivate(interaction, self.years)
        self.view.stop()


class ClaimCultivationView(TimedView):
    public = True          # 归属校验在按钮回调里（比对 self.uid）
    def __init__(self, cog, uid: str):
        super().__init__()
        self.cog = cog
        self.uid = uid

    @discord.ui.button(label="领取修炼成果", style=discord.ButtonStyle.success)
    async def claim(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        await self.cog.claim_cultivation(interaction, self.uid)
        self.stop()


class ZhujiBreakthroughView(TimedView):
    def __init__(self, author, cog, player: dict, has_pill: bool, uid: str):
        super().__init__()
        self.author = author
        self.cog = cog
        self.player = player
        self.uid = uid
        self.has_pill = has_pill

        from utils.items import can_skip_pill
        self.can_skip = can_skip_pill(player)

        if has_pill:
            self.add_item(_ZhujiButton("服用筑基丹冲关", use_pill=True))
        self.add_item(_ZhujiButton("直接冲关", use_pill=False))


class _ZhujiButton(discord.ui.Button):
    def __init__(self, label: str, use_pill: bool):
        style = discord.ButtonStyle.success if use_pill else discord.ButtonStyle.primary
        super().__init__(label=label, style=style)
        self.use_pill = use_pill

    async def callback(self, interaction: discord.Interaction):
        import time
        import random
        from sqlalchemy import text
        from utils.db_async import AsyncSessionLocal
        from utils.items import calc_zhuji_breakthrough_rate
        from utils.inventory import remove_item
        from utils.realms import lifespan_max_for_realm, apply_failure, next_realm
        from utils.player import get_player

        await interaction.response.defer()
        view: ZhujiBreakthroughView = self.view
        cog = view.cog
        uid = view.uid
        player = await get_player(uid)
        now = time.time()

        if self.use_pill:
            if not await remove_item(uid, "筑基丹"):
                await interaction.followup.send("筑基丹已不在背包中。")
                view.stop()
                return

        rate = calc_zhuji_breakthrough_rate(player, use_pill=self.use_pill) / 100
        success = random.random() < rate

        if success:
            nxt = next_realm(player["realm"])
            new_lifespan_max = lifespan_max_for_realm(nxt)
            lifespan_gain = max(0, new_lifespan_max - player["lifespan_max"])
            new_lifespan = player["lifespan"] + lifespan_gain
            async with AsyncSessionLocal() as session:
                # 带上读到的境界和修为当条件，连点的第二次就匹配不到行。
                # 否则同一份状态会被判定两遍，可能连升两级。
                result = await session.execute(
                    text("UPDATE players SET realm = :realm, lifespan = :ls, lifespan_max = :lsm, "
                         "cultivation = 0, last_active = :la "
                         "WHERE discord_id = :uid AND realm = :old_realm AND cultivation = :old_cult"),
                    {"realm": nxt, "ls": new_lifespan, "lsm": new_lifespan_max, "la": now, "uid": uid,
                     "old_realm": player["realm"], "old_cult": player["cultivation"]}
                )
                if result.rowcount != 1:
                    await session.rollback()
                    return await interaction.followup.send("状态已变化，请重新尝试突破。")
                await session.commit()
            pill_note = "（服用筑基丹）" if self.use_pill else ""
            await interaction.followup.send(
                f"🎉 **{player['name']}** 炼气化液，成功筑基{pill_note}！\n"
                f"**炼气期10层** ➜ **{nxt}**\n"
                f"寿元上限→{new_lifespan_max}年，当前寿元→{new_lifespan}年"
            )
        else:
            from utils.realms import roll_breakthrough, apply_failure
            _, outcome = roll_breakthrough(player["realm"], player["physique"], player["bone"], player["cultivation"])
            new_cultivation, new_lifespan, fail_msg = apply_failure(player["cultivation"], player["lifespan"], outcome)
            async with AsyncSessionLocal() as session:
                # 同上，失败惩罚也只能结算一次
                result = await session.execute(
                    text("UPDATE players SET cultivation = :cult, lifespan = :ls, last_active = :la "
                         "WHERE discord_id = :uid AND realm = :old_realm AND cultivation = :old_cult"),
                    {"cult": new_cultivation, "ls": new_lifespan, "la": now, "uid": uid,
                     "old_realm": player["realm"], "old_cult": player["cultivation"]}
                )
                if result.rowcount != 1:
                    await session.rollback()
                    return await interaction.followup.send("状态已变化，请重新尝试突破。")
                await session.commit()
            pill_note = "（筑基丹已消耗）" if self.use_pill else ""
            await interaction.followup.send(
                f"💔 **{player['name']}** 筑基失败{pill_note}！{fail_msg}\n"
                f"修为：{new_cultivation}　寿元：{new_lifespan}年"
            )
        view.stop()


class _BackToMenuButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="返回主菜单", style=discord.ButtonStyle.secondary, row=1)

    async def callback(self, interaction: discord.Interaction):
        import json
        from sqlalchemy import text
        from utils.db_async import AsyncSessionLocal
        from utils.views.menu import MainMenuView, _build_menu_embed
        from utils.player import get_player, settle_time, apply_updates, can_breakthrough
        await interaction.response.defer()
        cog = self.view.cog
        uid = str(interaction.user.id)
        player = await get_player(uid)
        if player and not player["is_dead"]:
            updates, _ = await settle_time(player)
            await apply_updates(uid, updates)
            player = await get_player(uid)
        has_player = player is not None and not player["is_dead"]
        can_bt = has_player and can_breakthrough(player)
        has_dual = has_player and any(
            (t if isinstance(t, str) else t.get("name", "")) == "双修功法"
            for t in json.loads(player["techniques"] or "[]")
        )
        city_players = []
        if has_player:
            async with AsyncSessionLocal() as session:
                r = await session.execute(
                    text(
                        "SELECT discord_id, name, realm, cultivation FROM players "
                        "WHERE current_city = :city AND is_dead = 0 AND discord_id != :uid"
                    ),
                    {"city": player["current_city"], "uid": uid}
                )
                city_players = [dict(row._mapping) for row in r.fetchall()]
        self.view.stop()
        await interaction.followup.send(
            embed=_build_menu_embed(has_dual),
            view=MainMenuView(interaction.user, has_player, can_bt, cog, player, city_players)
        )


class NingdanBreakthroughView(TimedView):
    def __init__(self, author, cog, player: dict, has_pill: bool, uid: str):
        super().__init__()
        self.author = author
        self.cog = cog
        self.player = player
        self.uid = uid
        if has_pill:
            self.add_item(_MajorBreakthroughButton("服用凝丹丹冲关", "凝丹丹", use_pill=True))
        self.add_item(_MajorBreakthroughButton("直接冲关", "凝丹丹", use_pill=False))


class HuayingBreakthroughView(TimedView):
    def __init__(self, author, cog, player: dict, has_pill: bool, uid: str):
        super().__init__()
        self.author = author
        self.cog = cog
        self.player = player
        self.uid = uid
        if has_pill:
            self.add_item(_MajorBreakthroughButton("服用化婴丹冲关", "化婴丹", use_pill=True))
        self.add_item(_MajorBreakthroughButton("直接冲关", "化婴丹", use_pill=False))


class _MajorBreakthroughButton(discord.ui.Button):
    def __init__(self, label: str, pill_name: str, use_pill: bool):
        style = discord.ButtonStyle.success if use_pill else discord.ButtonStyle.primary
        super().__init__(label=label, style=style)
        self.pill_name = pill_name
        self.use_pill = use_pill

    async def callback(self, interaction: discord.Interaction):
        import time
        import random
        from sqlalchemy import text
        from utils.db_async import AsyncSessionLocal
        from utils.items.breakthrough import calc_ningdan_breakthrough_rate, calc_huaying_breakthrough_rate
        from utils.inventory import remove_item
        from utils.realms import lifespan_max_for_realm, apply_failure, next_realm
        from utils.player import get_player

        await interaction.response.defer()
        view = self.view
        cog = view.cog
        uid = view.uid
        player = await get_player(uid)
        now = time.time()

        if self.use_pill:
            if not await remove_item(uid, self.pill_name):
                await interaction.followup.send(f"「{self.pill_name}」已不在背包中。")
                view.stop()
                return

        if self.pill_name == "凝丹丹":
            rate = calc_ningdan_breakthrough_rate(player, use_pill=self.use_pill) / 100
            pill_note_fail = "（凝丹丹已消耗）" if self.use_pill else ""
            pill_note_win = "（服用凝丹丹）" if self.use_pill else ""
            from_realm_label = "筑基化液，凝结金丹"
        else:
            rate = calc_huaying_breakthrough_rate(player, use_pill=self.use_pill) / 100
            pill_note_fail = "（化婴丹已消耗）" if self.use_pill else ""
            pill_note_win = "（服用化婴丹）" if self.use_pill else ""
            from_realm_label = "金丹破碎，元婴化形"

        success = random.random() < rate

        if success:
            nxt = next_realm(player["realm"])
            new_lifespan_max = lifespan_max_for_realm(nxt)
            lifespan_gain = max(0, new_lifespan_max - player["lifespan_max"])
            new_lifespan = player["lifespan"] + lifespan_gain
            async with AsyncSessionLocal() as session:
                # 带上读到的境界和修为当条件，连点的第二次就匹配不到行。
                # 否则同一份状态会被判定两遍，可能连升两级。
                result = await session.execute(
                    text("UPDATE players SET realm = :realm, lifespan = :ls, lifespan_max = :lsm, "
                         "cultivation = 0, last_active = :la "
                         "WHERE discord_id = :uid AND realm = :old_realm AND cultivation = :old_cult"),
                    {"realm": nxt, "ls": new_lifespan, "lsm": new_lifespan_max, "la": now, "uid": uid,
                     "old_realm": player["realm"], "old_cult": player["cultivation"]}
                )
                if result.rowcount != 1:
                    await session.rollback()
                    return await interaction.followup.send("状态已变化，请重新尝试突破。")
                await session.commit()
            await interaction.followup.send(
                f"🎉 **{player['name']}** {from_realm_label}{pill_note_win}！\n"
                f"**{player['realm']}** ➜ **{nxt}**\n"
                f"寿元上限→{new_lifespan_max}年，当前寿元→{new_lifespan}年"
            )
        else:
            from utils.realms import roll_breakthrough
            _, outcome = roll_breakthrough(player["realm"], player["physique"], player["bone"], player["cultivation"])
            new_cultivation, new_lifespan, fail_msg = apply_failure(player["cultivation"], player["lifespan"], outcome)
            async with AsyncSessionLocal() as session:
                # 同上，失败惩罚也只能结算一次
                result = await session.execute(
                    text("UPDATE players SET cultivation = :cult, lifespan = :ls, last_active = :la "
                         "WHERE discord_id = :uid AND realm = :old_realm AND cultivation = :old_cult"),
                    {"cult": new_cultivation, "ls": new_lifespan, "la": now, "uid": uid,
                     "old_realm": player["realm"], "old_cult": player["cultivation"]}
                )
                if result.rowcount != 1:
                    await session.rollback()
                    return await interaction.followup.send("状态已变化，请重新尝试突破。")
                await session.commit()
            await interaction.followup.send(
                f"💔 **{player['name']}** 突破失败{pill_note_fail}！{fail_msg}\n"
                f"修为：{new_cultivation}　寿元：{new_lifespan}年"
            )
        view.stop()
