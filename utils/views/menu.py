import discord
from utils.sects import SECTS, check_requirements


def _get_event_hint() -> str:
    import json, time as _time
    from utils.db import get_conn
    with get_conn() as conn:
        row = conn.execute(
            "SELECT title, status, ends_at FROM public_events WHERE status IN ('active', 'pending') ORDER BY started_at DESC LIMIT 1"
        ).fetchone()
    if not row:
        return "每日 22:00（北美东部时间）触发，天下修士皆可参与"
    if row["status"] == "active":
        remaining = max(0, row["ends_at"] - _time.time())
        return f"「{row['title']}」进行中，还剩 {remaining/60:.0f} 分钟"
    return f"「{row['title']}」即将开始，敬请关注公告频道"


def _build_menu_embed(has_dual: bool = False, event_hint: str = "") -> discord.Embed:
    if not event_hint:
        event_hint = _get_event_hint()
    dual_section = (
        "\n\n**双修系统**\n"
        "· 使用 `cat!双修 @对方` 邀请他人进行双修（需双修功法）\n"
        "· 双方皆为清白之身时修为暴涨（10-20倍），一方清白5倍，否则1.2倍\n"
        "· 双修冷却 2 游戏年，闭关中无法双修"
    ) if has_dual else ""
    embed = discord.Embed(
        title="✦ 修仙长生路 ✦",
        description=(
            "天地初开，灵气充盈，万物皆可修仙。\n"
            "踏入此道，以寿元换修为，历经炼气、筑基、结丹……直至飞升成仙。\n\n"
            "**基本规则**\n"
            "· 现实 2 小时 = 游戏 1 年，寿元随时间流逝\n"
            "· 修炼消耗寿元，换取修为积累\n"
            "· 修为积满可尝试突破，失败有代价\n"
            "· 寿元归零，角色坐化，需重新创建\n"
            "· 超过 2 年未行动，自动进入修炼状态\n\n"
            "**探险系统**\n"
            "· `cat!探险` 随机触发事件，每 5 游戏年可探险 8 次\n"
            "· 12% 概率触发稀有事件，奖励丰厚\n"
            "· 所在城市与地区影响事件池，加入宗门后有专属事件\n\n"
            "**移动与世界**\n"
            "· 天下共 30 座城市，分布于东域、南域、西域、北域、中州\n"
            "· 点击「移动」按钮或使用 `cat!移动 [城市名]` 前往目的地\n"
            "· 闭关期间无法移动\n\n"
            "**居所与洞府**\n"
            "· 声望 ≥ 300 可使用 `cat!买房` 在当前城市置业，提升修炼速度与探险次数\n"
            "· 声望 ≥ 600 可使用 `cat!开辟洞府 [秘地名]` 开辟野外洞府，加成更强且全局生效\n"
            "· 使用 `cat!我的居所` 查看已有居所与加成详情\n\n"
            "**宗门系统**\n"
            "· 满足条件后可加入宗门，获得专属事件与功法加成\n"
            "· 使用 `cat!宗门列表` 查看天下宗门，`cat!加入宗门 [名]` 加入\n"
            "· 加入后自动获得全部3本功法，`cat!门派功法` 可补领遗漏\n\n"
            "**功法系统**\n"
            "· 最多装备5本功法，装备后获得属性加成\n"
            "· `cat!我的功法` 查看功法　`cat!装备功法 [名]` 装备/卸下\n"
            "· `cat!修炼功法 [名]` 消耗灵石与寿元提升功法阶段（入门→破限）\n"
            "· `cat!功法属性` 查看当前装备功法的总属性加成"
            + dual_section
            + (
                "\n\n**公共事件**\n"
                f"· {event_hint}\n"
                "· 点击「公共事件」按钮或使用 `cat!公共事件` 查看详情"
            )
        ),
        color=discord.Color.teal(),
    )
    embed.set_footer(text="天道有常，长生路远，望道友珍重。")
    return embed


def _get_joinable_sects(player: dict) -> list[str]:
    if not player or player.get("sect"):
        return []
    city = player.get("current_city", "")
    result = []
    for name, data in SECTS.items():
        if data["alignment"] == "隐世":
            continue
        if data["location"] != city:
            continue
        ok, _ = check_requirements(dict(player), name)
        if ok:
            result.append(name)
    return result


class MainMenuView(discord.ui.View):
    def __init__(self, author, has_player: bool, can_breakthrough: bool, cog, player=None, city_players=None):
        super().__init__(timeout=120)
        self.author = author
        self.cog = cog
        self._city_players = city_players or []
        self._player = player

        if not has_player:
            self.add_item(MenuButton("创建角色", discord.ButtonStyle.success, "create"))
        self.add_item(MenuButton("我的角色", discord.ButtonStyle.primary, "profile"))
        self.add_item(MenuButton("修炼", discord.ButtonStyle.success, "cultivate"))
        self.add_item(MenuButton("世界", discord.ButtonStyle.secondary, "world"))
        self.add_item(MenuButton("移动", discord.ButtonStyle.secondary, "travel"))
        if can_breakthrough:
            self.add_item(MenuButton("突破", discord.ButtonStyle.danger, "breakthrough"))
        self.add_item(MenuButton("探险", discord.ButtonStyle.secondary, "explore"))
        if has_player:
            from utils.world import get_region
            region = get_region(player.get("current_city", "")) if player else None
            if not region:
                self.add_item(MenuButton("茶馆", discord.ButtonStyle.secondary, "tavern"))
            if region:
                emoji_map = {"采矿": "⛏️", "采药": "🌿", "伐木": "🪓", "钓鱼": "🎣"}
                rtype = region.get("type", "")
                if rtype in emoji_map:
                    self.add_item(MenuButton(rtype, discord.ButtonStyle.success, f"gather:{rtype}"))
            self.add_item(MenuButton("背包", discord.ButtonStyle.secondary, "backpack"))
            self.add_item(MenuButton("功法", discord.ButtonStyle.secondary, "techniques"))
            self.add_item(MenuButton("装备", discord.ButtonStyle.secondary, "equipment"))
        if city_players:
            self.add_item(MenuButton("玩家", discord.ButtonStyle.secondary, "city_players"))
        if player and player.get("party_id"):
            self.add_item(MenuButton("查看队伍", discord.ButtonStyle.primary, "party_info"))
            self.add_item(MenuButton("退出队伍", discord.ButtonStyle.danger, "party_leave"))
        if player:
            for sect_name in _get_joinable_sects(player):
                self.add_item(MenuButton(f"加入{sect_name}", discord.ButtonStyle.success, f"join_sect:{sect_name}"))
        self.add_item(MenuButton("公共事件", discord.ButtonStyle.secondary, "public_event"))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user != self.author:
            await interaction.response.send_message("这不是你的面板。", ephemeral=True)
            return False
        return True


class MenuButton(discord.ui.Button):
    def __init__(self, label: str, style: discord.ButtonStyle, action: str, disabled: bool = False):
        super().__init__(label=label, style=style, disabled=disabled)
        self.action = action

    async def callback(self, interaction: discord.Interaction):
        from utils.views.world import WorldMenuView, _world_overview_embed
        from utils.views.travel import TravelRegionView
        from utils.views.city_players import CityPlayersView, _city_players_embed
        cog = self.view.cog

        if self.action == "world":
            await interaction.response.send_message(embed=_world_overview_embed(), view=WorldMenuView(interaction.user, cog))
            return

        if self.action == "travel":
            await interaction.response.send_message(
                embed=discord.Embed(title="✦ 移动 · 选择地区 ✦", description="请选择目标地区：", color=discord.Color.teal()),
                view=TravelRegionView(interaction.user, cog),
            )
            return

        if self.action == "city_players":
            city_players = getattr(self.view, "_city_players", [])
            player = getattr(self.view, "_player", None)
            if not city_players:
                await interaction.response.send_message("此地暂无其他修士。", ephemeral=True)
                return
            await interaction.response.send_message(
                embed=_city_players_embed(city_players, player),
                view=CityPlayersView(interaction.user, city_players, player, cog),
                ephemeral=True,
            )
            return

        if self.action == "party_info":
            from utils.views.party import party_info_embed
            from utils.db import get_conn
            uid = str(interaction.user.id)
            with get_conn() as conn:
                player = dict(conn.execute("SELECT * FROM players WHERE discord_id = ?", (uid,)).fetchone())
                party_id = player.get("party_id")
                if not party_id:
                    return await interaction.response.send_message("你不在任何队伍中。", ephemeral=True)
                members = [dict(r) for r in conn.execute(
                    "SELECT * FROM players WHERE party_id = ?", (party_id,)).fetchall()]
                leader = dict(conn.execute("SELECT leader_id FROM parties WHERE party_id = ?", (party_id,)).fetchone())
            await interaction.response.send_message(
                embed=party_info_embed(members, leader["leader_id"]),
                ephemeral=True,
            )
            return

        if self.action == "party_leave":
            from utils.views.party import leave_party
            uid = str(interaction.user.id)
            msg = await leave_party(uid, interaction.client)
            await interaction.response.send_message(msg, ephemeral=True)
            return

        await interaction.response.defer()
        try:
            if self.action == "create":
                ctx = await cog.bot.get_context(interaction.message)
                ctx.author = interaction.user
                await cog.create_character(ctx)
            elif self.action == "profile":
                await cog.send_profile(interaction)
            elif self.action == "cultivate":
                await cog.send_cultivate(interaction)
            elif self.action == "breakthrough":
                await cog.send_breakthrough(interaction)
            elif self.action == "stop":
                await cog.send_stop(interaction)
            elif self.action == "explore":
                explore_cog = cog.bot.cogs.get("Explore")
                if explore_cog:
                    ctx = await cog.bot.get_context(interaction.message)
                    ctx.author = interaction.user
                    await explore_cog.explore(ctx)
                else:
                    await interaction.followup.send("探险系统暂时不可用。", ephemeral=True)
            elif self.action == "tavern":
                tavern_cog = cog.bot.cogs.get("Tavern")
                if tavern_cog:
                    ctx = await cog.bot.get_context(interaction.message)
                    ctx.author = interaction.user
                    await tavern_cog.tavern(ctx)
                else:
                    await interaction.followup.send("茶馆暂时不可用。", ephemeral=True)
            elif self.action == "backpack":
                equip_cog = cog.bot.cogs.get("Equipment")
                if equip_cog:
                    ctx = await cog.bot.get_context(interaction.message)
                    ctx.author = interaction.user
                    await equip_cog.backpack(ctx)
                else:
                    await interaction.followup.send("背包系统暂时不可用。", ephemeral=True)
            elif self.action == "techniques":
                from utils.views.techniques import TechniquesView, _build_techniques_embed, _get_player as _tech_get_player
                uid = str(interaction.user.id)
                player = _tech_get_player(uid)
                if not player:
                    await interaction.followup.send("尚未踏入修仙之路。", ephemeral=True)
                else:
                    embed = _build_techniques_embed(player)
                    view = TechniquesView(interaction.user, cog)
                    await interaction.followup.send(embed=embed, view=view)
            elif self.action == "equipment":
                equip_cog = cog.bot.cogs.get("Equipment")
                if equip_cog:
                    ctx = await cog.bot.get_context(interaction.message)
                    ctx.author = interaction.user
                    await equip_cog.equip_details(ctx)
                else:
                    await interaction.followup.send("装备系统暂时不可用。", ephemeral=True)
            elif self.action.startswith("gather:"):
                gather_type = self.action[len("gather:"):]
                from utils.views.gathering import GatherView, TYPE_EMOJI
                from utils.db import get_conn
                from utils.character import seconds_to_years
                import time as _time
                uid = str(interaction.user.id)
                with get_conn() as conn:
                    player = dict(conn.execute("SELECT * FROM players WHERE discord_id = ?", (uid,)).fetchone())
                now = _time.time()
                with get_conn() as conn:
                    defense_row = conn.execute(
                        "SELECT 1 FROM public_event_participants ep "
                        "JOIN public_events e ON ep.event_id = e.event_id "
                        "WHERE ep.discord_id = ? AND ep.activity = 'defense' AND e.status = 'active'",
                        (uid,)
                    ).fetchone()
                if defense_row:
                    await interaction.followup.send("守城期间无法采集，专心守城！", ephemeral=True)
                elif player["cultivating_until"] and now < player["cultivating_until"]:
                    remaining = seconds_to_years(player["cultivating_until"] - now)
                    await interaction.followup.send(f"道友正在闭关，无法采集。还剩约 **{remaining:.1f} 年**。", ephemeral=True)
                elif player["gathering_until"] and now < player["gathering_until"]:
                    remaining = seconds_to_years(player["gathering_until"] - now)
                    await interaction.followup.send(f"道友正在采集中，还剩约 **{remaining:.1f} 年**。", ephemeral=True)
                else:
                    region_name = player.get("current_city", "")
                    emoji = TYPE_EMOJI.get(gather_type, "⛏️")
                    embed = discord.Embed(
                        title=f"✦ {emoji} {gather_type} · {region_name} ✦",
                        description=f"当前寿元：**{player['lifespan']} 年**\n\n请选择采集时长：",
                        color=discord.Color.green(),
                    )
                    await interaction.followup.send(
                        embed=embed,
                        view=GatherView(interaction.user, cog, player, gather_type, region_name),
                    )
            elif self.action.startswith("join_sect:"):
                sect_name = self.action[len("join_sect:"):]
                sect_cog = cog.bot.cogs.get("Sect")
                if sect_cog:
                    ctx = await cog.bot.get_context(interaction.message)
                    ctx.author = interaction.user
                    await sect_cog.join_sect(ctx, name=sect_name)
                else:
                    await interaction.followup.send("宗门系统暂时不可用。", ephemeral=True)
            elif self.action == "public_event":
                pe_cog = cog.bot.cogs.get("PublicEvents")
                if pe_cog:
                    ctx = await cog.bot.get_context(interaction.message)
                    ctx.author = interaction.user
                    await pe_cog.show_active_event(ctx)
                else:
                    await interaction.followup.send("公共事件系统暂时不可用。", ephemeral=True)
            elif self.action == "back_to_menu":
                import json
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
                    from utils.db import get_conn as _gc
                    with _gc() as conn:
                        rows = conn.execute(
                            "SELECT discord_id, name, realm, cultivation FROM players "
                            "WHERE current_city = ? AND is_dead = 0 AND discord_id != ?",
                            (player["current_city"], uid)
                        ).fetchall()
                    city_players = [dict(r) for r in rows]
                await interaction.followup.send(
                    embed=_build_menu_embed(has_dual),
                    view=MainMenuView(interaction.user, has_player, can_bt, cog, player, city_players)
                )
        except Exception as e:
            await interaction.followup.send(f"出错了：{e}", ephemeral=True)


class ProfileView(discord.ui.View):
    def __init__(self, author, can_breakthrough: bool, is_cultivating: bool, cog, player=None, city_players=None):
        super().__init__(timeout=120)
        self.author = author
        self.cog = cog
        self.player = player
        self.city_players = city_players or []
        self.add_item(MenuButton("修炼", discord.ButtonStyle.success, "cultivate"))
        if is_cultivating:
            self.add_item(MenuButton("停止闭关", discord.ButtonStyle.danger, "stop"))
        if can_breakthrough:
            self.add_item(MenuButton("突破", discord.ButtonStyle.danger, "breakthrough"))
        self.add_item(MenuButton("返回主菜单", discord.ButtonStyle.secondary, "back_to_menu"))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user != self.author:
            await interaction.response.send_message("这不是你的面板。", ephemeral=True)
            return False
        return True
