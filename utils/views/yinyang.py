import discord


class YinYangView(discord.ui.View):
    def __init__(self, author, event: dict, finale_event: dict, player, cog, uid: str):
        super().__init__(timeout=300)
        self.author = author
        self.event = event
        self.finale_event = finale_event
        self.player = player
        self.cog = cog
        self.uid = uid
        seen = set()
        for i, choice in enumerate(event["choices"]):
            if choice["label"] in seen:
                continue
            seen.add(choice["label"])
            self.add_item(YinYangButton(choice["label"], i))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user != self.author:
            await interaction.response.send_message("这不是你的奇遇。", ephemeral=True)
            return False
        return True


class YinYangButton(discord.ui.Button):
    def __init__(self, label: str, index: int):
        super().__init__(label=label, style=discord.ButtonStyle.primary)
        self.index = index

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer()
        for item in self.view.children:
            item.disabled = True
        self.view.stop()
        choice = self.view.event["choices"][self.index]
        if choice.get("next"):
            embed = discord.Embed(title=f"✦ {self.view.event['title']} ✦", description=choice["next"]["desc"], color=discord.Color.dark_purple())
            await interaction.followup.send(embed=embed, view=YinYangNextView(
                self.view.author, self.view.event, choice["next"], self.view.finale_event, self.view.player, self.view.cog, self.view.uid))
        else:
            from cogs.explore import _apply_rewards, _pick_choice_result
            same = [c for c in self.view.event["choices"] if c["label"] == choice["label"]]
            result = _pick_choice_result(same, dict(self.view.player))
            _apply_rewards(self.view.uid, result.get("rewards", {}))
            await _send_yinyang_finale(interaction, self.view.finale_event, self.view.player, self.view.cog, self.view.uid, result.get("flavor", ""))


class YinYangNextView(discord.ui.View):
    def __init__(self, author, original_event, next_event, finale_event, player, cog, uid):
        super().__init__(timeout=300)
        self.author = author
        self.original_event = original_event
        self.next_event = next_event
        self.finale_event = finale_event
        self.player = player
        self.cog = cog
        self.uid = uid
        seen = set()
        for i, choice in enumerate(next_event["choices"]):
            if choice["label"] in seen:
                continue
            seen.add(choice["label"])
            self.add_item(YinYangNextButton(choice["label"], i))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user != self.author:
            await interaction.response.send_message("这不是你的奇遇。", ephemeral=True)
            return False
        return True


class YinYangNextButton(discord.ui.Button):
    def __init__(self, label: str, index: int):
        super().__init__(label=label, style=discord.ButtonStyle.secondary)
        self.index = index

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer()
        for item in self.view.children:
            item.disabled = True
        self.view.stop()
        from cogs.explore import _apply_rewards, _pick_choice_result
        choices = self.view.next_event["choices"]
        choice = choices[self.index]
        if choice.get("next"):
            embed = discord.Embed(title=f"✦ {self.view.original_event['title']} ✦", description=choice["next"]["desc"], color=discord.Color.dark_purple())
            await interaction.followup.send(embed=embed, view=YinYangNextView(
                self.view.author, self.view.original_event, choice["next"], self.view.finale_event, self.view.player, self.view.cog, self.view.uid))
            return
        same = [c for c in choices if c["label"] == choice["label"]]
        result = _pick_choice_result(same, dict(self.view.player))
        _apply_rewards(self.view.uid, result.get("rewards", {}))
        await _send_yinyang_finale(interaction, self.view.finale_event, self.view.player, self.view.cog, self.view.uid, result.get("flavor", ""))


async def _send_yinyang_finale(interaction, finale_event, player, cog, uid, prev_flavor):
    embed = discord.Embed(
        title=f"✦ {finale_event['title']} ✦",
        description=(f"*{prev_flavor}*\n\n" if prev_flavor else "") + finale_event["desc"],
        color=discord.Color.dark_purple(),
    )
    await interaction.followup.send(embed=embed, view=YinYangFinaleView(interaction.user, finale_event, player, cog, uid))


class YinYangFinaleView(discord.ui.View):
    def __init__(self, author, event, player, cog, uid):
        super().__init__(timeout=300)
        self.author = author
        self.event = event
        self.player = player
        self.cog = cog
        self.uid = uid
        seen = set()
        for i, choice in enumerate(event["choices"]):
            if choice["label"] in seen:
                continue
            seen.add(choice["label"])
            self.add_item(YinYangFinaleButton(choice["label"], i))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user != self.author:
            await interaction.response.send_message("这不是你的奇遇。", ephemeral=True)
            return False
        return True


class YinYangFinaleButton(discord.ui.Button):
    def __init__(self, label: str, index: int):
        super().__init__(label=label, style=discord.ButtonStyle.primary)
        self.index = index

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer()
        for item in self.view.children:
            item.disabled = True
        self.view.stop()
        from cogs.explore import _apply_rewards, _pick_choice_result
        choices = self.view.event["choices"]
        choice = choices[self.index]
        if choice.get("next"):
            embed = discord.Embed(title=f"✦ {self.view.event['title']} ✦", description=choice["next"]["desc"], color=discord.Color.dark_purple())
            await interaction.followup.send(embed=embed, view=YinYangFinaleSubView(
                self.view.author, self.view.event, choice["next"], self.view.player, self.view.cog, self.view.uid))
            return
        same = [c for c in choices if c["label"] == choice["label"]]
        result = _pick_choice_result(same, dict(self.view.player))
        _apply_rewards(self.view.uid, result.get("rewards", {}))
        await _do_yinyang_rebirth(interaction, self.view.player, self.view.cog, self.view.uid, result.get("flavor", ""))


class YinYangFinaleSubView(discord.ui.View):
    def __init__(self, author, original_event, next_event, player, cog, uid):
        super().__init__(timeout=300)
        self.author = author
        self.original_event = original_event
        self.next_event = next_event
        self.player = player
        self.cog = cog
        self.uid = uid
        seen = set()
        for i, choice in enumerate(next_event["choices"]):
            if choice["label"] in seen:
                continue
            seen.add(choice["label"])
            self.add_item(YinYangFinaleSubButton(choice["label"], i))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user != self.author:
            await interaction.response.send_message("这不是你的奇遇。", ephemeral=True)
            return False
        return True


class YinYangFinaleSubButton(discord.ui.Button):
    def __init__(self, label: str, index: int):
        super().__init__(label=label, style=discord.ButtonStyle.secondary)
        self.index = index

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer()
        for item in self.view.children:
            item.disabled = True
        self.view.stop()
        from cogs.explore import _apply_rewards, _pick_choice_result
        choices = self.view.next_event["choices"]
        same = [c for c in choices if c["label"] == choices[self.index]["label"]]
        result = _pick_choice_result(same, dict(self.view.player))
        _apply_rewards(self.view.uid, result.get("rewards", {}))
        await _do_yinyang_rebirth(interaction, self.view.player, self.view.cog, self.view.uid, result.get("flavor", ""))


async def _do_yinyang_rebirth(interaction, player, cog, uid, final_flavor):
    import time
    from utils.db import get_conn
    from utils.realms import lifespan_max_for_realm
    now = time.time()
    new_lifespan = lifespan_max_for_realm(player["realm"])
    with get_conn() as conn:
        conn.execute("""
            UPDATE players SET
                lifespan = ?, cultivation = 0,
                cultivating_until = NULL, cultivating_years = NULL,
                is_dead = 0, is_virgin = 1,
                rebirth_count = rebirth_count + 1,
                has_bahongchen = 1, escape_rate = 50,
                last_active = ?
            WHERE discord_id = ?
        """, (new_lifespan, now, uid))
        conn.commit()
    embed = discord.Embed(
        title="✦ 大梦初醒 ✦",
        description=(
            (f"*{final_flavor}*\n\n" if final_flavor else "") +
            "——\n\n你猛地睁开眼睛。\n\n天花板。\n\n"
            "是你熟悉的天花板，木纹，裂缝，还有角落里那块陈年的水渍。\n"
            "你躺在床上，被褥还是原来的被褥，枕头还是原来的枕头。\n\n"
            "窗外有鸟叫，有风，有人声。\n阳光从窗缝里透进来，落在你的手背上，暖的。\n\n"
            "你坐起来，大口喘气，发现自己满身冷汗。\n\n"
            "洛道村，秋叶青，沈渡，杨敬远——\n一切像是一场梦。\n\n"
            "但那些悲欢离合，那些选择与沉默，那个女孩最后的笑，\n"
            "却清晰地刻在心里，像是真实发生过的事，挥之不去。\n\n"
            "你低下头，发现手心里有一道淡淡的印记——\n"
            "那块令牌留下的，冰凉的触感，像是某种证明。\n\n"
            "杨敬远的声音最后一次在耳边响起，\n像是从很远很远的地方传来：\n\n"
            "*「霸红尘会在你需要的时候出现。」*\n*「好好活着。」*\n\n——\n\n"
            f"寿元恢复至 **{new_lifespan} 年**，修为清零，处身重置。\n"
            "永久获得：**逃跑成功率 +50%**\n"
            "灵魂深处铭刻：**【一梦浮生·霸红尘使者】**"
        ),
        color=discord.Color.gold(),
    )
    await interaction.followup.send(embed=embed)
