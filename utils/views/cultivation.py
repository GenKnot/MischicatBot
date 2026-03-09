import discord


class CultivateView(discord.ui.View):
    YEAR_OPTIONS = [
        (1, "1年",  "现实 2 小时"),
        (2, "2年",  "现实 4 小时"),
        (4, "4年",  "现实 8 小时"),
        (8, "8年",  "现实 16 小时"),
    ]

    def __init__(self, author, cog, player: dict):
        super().__init__(timeout=60)
        self.author = author
        self.cog = cog
        self.player = player
        for years, label, hint in self.YEAR_OPTIONS:
            disabled = player["lifespan"] < years
            self.add_item(CultivateButton(years, label, hint, disabled))
        self.add_item(_BackToMenuButton())

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user != self.author:
            await interaction.response.send_message("这不是你的面板。", ephemeral=True)
            return False
        return True


class CultivateButton(discord.ui.Button):
    def __init__(self, years: int, label: str, hint: str, disabled: bool):
        super().__init__(label=f"{label}（{hint}）", style=discord.ButtonStyle.primary, disabled=disabled)
        self.years = years

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer()
        await self.view.cog.start_cultivate(interaction, self.years)
        self.view.stop()


class ClaimCultivationView(discord.ui.View):
    def __init__(self, cog, uid: str):
        super().__init__(timeout=300)
        self.cog = cog
        self.uid = uid

    @discord.ui.button(label="领取修炼成果", style=discord.ButtonStyle.success)
    async def claim(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        await self.cog.claim_cultivation(interaction, self.uid)
        self.stop()


class ZhujiBreakthroughView(discord.ui.View):
    def __init__(self, author, cog, player: dict, has_pill: bool, uid: str):
        super().__init__(timeout=60)
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

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user != self.author:
            await interaction.response.send_message("这不是你的面板。", ephemeral=True)
            return False
        return True


class _ZhujiButton(discord.ui.Button):
    def __init__(self, label: str, use_pill: bool):
        style = discord.ButtonStyle.success if use_pill else discord.ButtonStyle.primary
        super().__init__(label=label, style=style)
        self.use_pill = use_pill

    async def callback(self, interaction: discord.Interaction):
        import time
        import random
        from utils.items import calc_zhuji_breakthrough_rate
        from utils.db import remove_item
        from utils.realms import lifespan_max_for_realm, apply_failure, next_realm

        await interaction.response.defer()
        view: ZhujiBreakthroughView = self.view
        cog = view.cog
        uid = view.uid
        player = cog._get_player(uid)
        now = time.time()

        if self.use_pill:
            if not remove_item(uid, "筑基丹"):
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
            from utils.db import get_conn
            with get_conn() as conn:
                conn.execute(
                    "UPDATE players SET realm = ?, lifespan = ?, lifespan_max = ?, cultivation = 0, last_active = ? WHERE discord_id = ?",
                    (nxt, new_lifespan, new_lifespan_max, now, uid)
                )
                conn.commit()
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
            from utils.db import get_conn
            with get_conn() as conn:
                conn.execute(
                    "UPDATE players SET cultivation = ?, lifespan = ?, last_active = ? WHERE discord_id = ?",
                    (new_cultivation, new_lifespan, now, uid)
                )
                conn.commit()
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
        from utils.views.menu import MainMenuView, _build_menu_embed
        await interaction.response.defer()
        cog = self.view.cog
        uid = str(interaction.user.id)
        player = cog._get_player(uid)
        if player and not player["is_dead"]:
            updates, _ = cog._settle_time(player)
            cog._apply_updates(uid, updates)
            player = cog._get_player(uid)
        has_player = player is not None and not player["is_dead"]
        can_bt = has_player and cog._can_breakthrough(player)
        has_dual = has_player and any(
            (t if isinstance(t, str) else t.get("name", "")) == "双修功法"
            for t in json.loads(player["techniques"] or "[]")
        )
        city_players = []
        if has_player:
            from utils.db import get_conn
            with get_conn() as conn:
                rows = conn.execute(
                    "SELECT discord_id, name, realm, cultivation FROM players "
                    "WHERE current_city = ? AND is_dead = 0 AND discord_id != ?",
                    (player["current_city"], uid)
                ).fetchall()
            city_players = [dict(r) for r in rows]
        self.view.stop()
        await interaction.followup.send(
            embed=_build_menu_embed(has_dual),
            view=MainMenuView(interaction.user, has_player, can_bt, cog, player, city_players)
        )


class NingdanBreakthroughView(discord.ui.View):
    def __init__(self, author, cog, player: dict, has_pill: bool, uid: str):
        super().__init__(timeout=60)
        self.author = author
        self.cog = cog
        self.player = player
        self.uid = uid
        if has_pill:
            self.add_item(_MajorBreakthroughButton("服用凝丹丹冲关", "凝丹丹", use_pill=True))
        self.add_item(_MajorBreakthroughButton("直接冲关", "凝丹丹", use_pill=False))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user != self.author:
            await interaction.response.send_message("这不是你的面板。", ephemeral=True)
            return False
        return True


class HuayingBreakthroughView(discord.ui.View):
    def __init__(self, author, cog, player: dict, has_pill: bool, uid: str):
        super().__init__(timeout=60)
        self.author = author
        self.cog = cog
        self.player = player
        self.uid = uid
        if has_pill:
            self.add_item(_MajorBreakthroughButton("服用化婴丹冲关", "化婴丹", use_pill=True))
        self.add_item(_MajorBreakthroughButton("直接冲关", "化婴丹", use_pill=False))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user != self.author:
            await interaction.response.send_message("这不是你的面板。", ephemeral=True)
            return False
        return True


class _MajorBreakthroughButton(discord.ui.Button):
    def __init__(self, label: str, pill_name: str, use_pill: bool):
        style = discord.ButtonStyle.success if use_pill else discord.ButtonStyle.primary
        super().__init__(label=label, style=style)
        self.pill_name = pill_name
        self.use_pill = use_pill

    async def callback(self, interaction: discord.Interaction):
        import time
        import random
        from utils.items.breakthrough import calc_ningdan_breakthrough_rate, calc_huaying_breakthrough_rate
        from utils.db import remove_item
        from utils.realms import lifespan_max_for_realm, apply_failure, next_realm

        await interaction.response.defer()
        view = self.view
        cog = view.cog
        uid = view.uid
        player = cog._get_player(uid)
        now = time.time()

        if self.use_pill:
            if not remove_item(uid, self.pill_name):
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
            from utils.db import get_conn
            with get_conn() as conn:
                conn.execute(
                    "UPDATE players SET realm = ?, lifespan = ?, lifespan_max = ?, cultivation = 0, last_active = ? WHERE discord_id = ?",
                    (nxt, new_lifespan, new_lifespan_max, now, uid)
                )
                conn.commit()
            await interaction.followup.send(
                f"🎉 **{player['name']}** {from_realm_label}{pill_note_win}！\n"
                f"**{player['realm']}** ➜ **{nxt}**\n"
                f"寿元上限→{new_lifespan_max}年，当前寿元→{new_lifespan}年"
            )
        else:
            from utils.realms import roll_breakthrough
            _, outcome = roll_breakthrough(player["realm"], player["physique"], player["bone"], player["cultivation"])
            new_cultivation, new_lifespan, fail_msg = apply_failure(player["cultivation"], player["lifespan"], outcome)
            from utils.db import get_conn
            with get_conn() as conn:
                conn.execute(
                    "UPDATE players SET cultivation = ?, lifespan = ?, last_active = ? WHERE discord_id = ?",
                    (new_cultivation, new_lifespan, now, uid)
                )
                conn.commit()
            await interaction.followup.send(
                f"💔 **{player['name']}** 突破失败{pill_note_fail}！{fail_msg}\n"
                f"修为：{new_cultivation}　寿元：{new_lifespan}年"
            )
        view.stop()
