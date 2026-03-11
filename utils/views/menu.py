import discord
from utils.config import COMMAND_PREFIX
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
        f"· 使用 `{COMMAND_PREFIX}双修 @对方` 邀请他人进行双修（需双修功法）\n"
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
            f"· `{COMMAND_PREFIX}探险` 随机触发事件，每 5 游戏年可探险 8 次\n"
            "· 12% 概率触发稀有事件，奖励丰厚\n"
            "· 所在城市与地区影响事件池，加入宗门后有专属事件\n\n"
            "**移动与世界**\n"
            "· 天下共 30 座城市，分布于东域、南域、西域、北域、中州\n"
            f"· 点击「移动」按钮或使用 `{COMMAND_PREFIX}移动 [城市名]` 前往目的地\n"
            "· 闭关期间无法移动\n\n"
            "**居所与洞府**\n"
            f"· 声望 ≥ 300 可使用 `{COMMAND_PREFIX}买房` 在当前城市置业，提升修炼速度与探险次数\n"
            f"· 声望 ≥ 600 可使用 `{COMMAND_PREFIX}开辟洞府 [秘地名]` 开辟野外洞府，加成更强且全局生效\n"
            f"· 使用 `{COMMAND_PREFIX}我的居所` 查看已有居所与加成详情\n\n"
            "**宗门系统**\n"
            "· 满足条件后可加入宗门，获得专属事件与功法加成\n"
            f"· 使用 `{COMMAND_PREFIX}宗门列表` 查看天下宗门，`{COMMAND_PREFIX}加入宗门 [名]` 加入\n"
            f"· 加入后自动获得全部3本功法，`{COMMAND_PREFIX}门派功法` 可补领遗漏\n\n"
            "**功法系统**\n"
            "· 最多装备5本功法，装备后获得属性加成\n"
            f"· `{COMMAND_PREFIX}我的功法` 查看功法　`{COMMAND_PREFIX}装备功法 [名]` 装备/卸下\n"
            f"· `{COMMAND_PREFIX}修炼功法 [名]` 消耗灵石与寿元提升功法阶段（入门→破限）\n"
            f"· `{COMMAND_PREFIX}功法属性` 查看当前装备功法的总属性加成"
            + dual_section
            + (
                "\n\n**公共事件**\n"
                f"· {event_hint}\n"
                f"· 点击「公共事件」按钮或使用 `{COMMAND_PREFIX}公共事件` 查看详情"
            )
        ),
        color=discord.Color.teal(),
    )
    # 命令速查（前缀缩写仅对消息命令生效；斜杠命令请用原名）
    embed.add_field(
        name="指令速查（前缀缩写）",
        value=(
            f"说明：缩写仅对 `{COMMAND_PREFIX}` 前缀命令生效，`/` 斜杠命令仍使用中文原名。\n"
            f"主入口：`{COMMAND_PREFIX}c` / `{COMMAND_PREFIX}h`（无角色=创建；有角色=主菜单）"
        ),
        inline=False,
    )
    embed.add_field(
        name="基础 / 修炼",
        value="\n".join([
            f"`{COMMAND_PREFIX}创建角色` / `{COMMAND_PREFIX}cjjs`：创建新角色",
            f"`{COMMAND_PREFIX}查看` / `{COMMAND_PREFIX}ck`：查看角色状态",
            f"`{COMMAND_PREFIX}修炼` / `{COMMAND_PREFIX}xl`：闭关修炼提升修为",
            f"`{COMMAND_PREFIX}停止` / `{COMMAND_PREFIX}tz`：提前结束闭关",
            f"`{COMMAND_PREFIX}突破` / `{COMMAND_PREFIX}tp`：尝试突破境界",
            f"`{COMMAND_PREFIX}双修` / `{COMMAND_PREFIX}sx`：与他人双修（需功法）",
        ]),
        inline=False,
    )
    embed.add_field(
        name="出行 / 探险 / 任务",
        value="\n".join([
            f"`{COMMAND_PREFIX}世界` / `{COMMAND_PREFIX}sj`：查看天下城市",
            f"`{COMMAND_PREFIX}移动` / `{COMMAND_PREFIX}yd`：前往城市/秘地",
            f"`{COMMAND_PREFIX}探险` / `{COMMAND_PREFIX}tx`：触发随机事件",
            f"`{COMMAND_PREFIX}茶馆` / `{COMMAND_PREFIX}cg`：接取任务/委托",
            f"`{COMMAND_PREFIX}交任务` / `{COMMAND_PREFIX}jrw`：结算当前任务",
        ]),
        inline=False,
    )
    embed.add_field(
        name="背包 / 装备 / 物品",
        value="\n".join([
            f"`{COMMAND_PREFIX}背包` / `{COMMAND_PREFIX}bb`：查看背包与装备",
            f"`{COMMAND_PREFIX}装备详情` / `{COMMAND_PREFIX}zbxq`：查看装备属性",
            f"`{COMMAND_PREFIX}装备` / `{COMMAND_PREFIX}zb`：装备指定ID",
            f"`{COMMAND_PREFIX}卸下` / `{COMMAND_PREFIX}xx`：卸下指定ID",
            f"`{COMMAND_PREFIX}丢弃装备` / `{COMMAND_PREFIX}dqzb`：丢弃指定ID",
            f"`{COMMAND_PREFIX}使用` / `{COMMAND_PREFIX}sy`：使用道具/丹药",
            f"`{COMMAND_PREFIX}出售` / `{COMMAND_PREFIX}cs`：出售物品换灵石",
        ]),
        inline=False,
    )
    embed.add_field(
        name="居所 / 宗门 / 功法",
        value="\n".join([
            f"`{COMMAND_PREFIX}买房` / `{COMMAND_PREFIX}mf`：当前城市置业",
            f"`{COMMAND_PREFIX}开辟洞府` / `{COMMAND_PREFIX}kpdf`：开辟洞府",
            f"`{COMMAND_PREFIX}我的居所` / `{COMMAND_PREFIX}wdjs`：查看居所加成",
            f"`{COMMAND_PREFIX}宗门列表` / `{COMMAND_PREFIX}zmlb`：查看宗门",
            f"`{COMMAND_PREFIX}宗门详情` / `{COMMAND_PREFIX}zmxq`：查看宗门要求",
            f"`{COMMAND_PREFIX}加入宗门` / `{COMMAND_PREFIX}jrzm`：加入宗门",
            f"`{COMMAND_PREFIX}退出宗门` / `{COMMAND_PREFIX}qtzm`：退出宗门",
            f"`{COMMAND_PREFIX}门派功法` / `{COMMAND_PREFIX}mpgf`：查看/补领功法",
            f"`{COMMAND_PREFIX}我的功法` / `{COMMAND_PREFIX}wdgf`：功法面板",
            f"`{COMMAND_PREFIX}装备功法` / `{COMMAND_PREFIX}zbgf`：装备/卸下功法",
            f"`{COMMAND_PREFIX}修炼功法` / `{COMMAND_PREFIX}xlgf`：提升功法阶段",
            f"`{COMMAND_PREFIX}功法属性` / `{COMMAND_PREFIX}gfsx`：查看功法加成",
        ]),
        inline=False,
    )
    embed.add_field(
        name="公共事件 / 其他",
        value="\n".join([
            f"`{COMMAND_PREFIX}公共事件` / `{COMMAND_PREFIX}ggsj`：查看当前事件",
            f"`{COMMAND_PREFIX}解散队伍` / `{COMMAND_PREFIX}jsdw`：解散队伍",
            f"`join/leave/play(p)/pause/resume/stop/skip/queue`：音乐指令",
        ]),
        inline=False,
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
            self.add_item(MenuButton("城市", discord.ButtonStyle.secondary, "city"))
            if region:
                emoji_map = {"采矿": "⛏️", "采药": "🌿", "伐木": "🪓", "钓鱼": "🎣"}
                rtype = region.get("type", "")
                if rtype in emoji_map:
                    self.add_item(MenuButton(rtype, discord.ButtonStyle.success, f"gather:{rtype}"))
            self.add_item(MenuButton("背包", discord.ButtonStyle.secondary, "backpack"))
            self.add_item(MenuButton("功法", discord.ButtonStyle.secondary, "techniques"))
            self.add_item(MenuButton("装备", discord.ButtonStyle.secondary, "equipment"))
            self.add_item(MenuButton("技艺", discord.ButtonStyle.secondary, "crafting"))
        if city_players:
            self.add_item(MenuButton("玩家", discord.ButtonStyle.secondary, "city_players"))
        if player and player.get("party_id"):
            self.add_item(MenuButton("查看队伍", discord.ButtonStyle.primary, "party_info"))
            self.add_item(MenuButton("退出队伍", discord.ButtonStyle.danger, "party_leave"))
        if player:
            for sect_name in _get_joinable_sects(player):
                self.add_item(MenuButton(f"加入{sect_name}", discord.ButtonStyle.success, f"join_sect:{sect_name}"))
        self.add_item(MenuButton("公共事件", discord.ButtonStyle.secondary, "public_event"))
        if player and player.get("current_city") == "万宝楼":
            self.add_item(MenuButton("万宝楼", discord.ButtonStyle.primary, "wanbao"))
        if player and player.get("current_city") == "丹阁" and player.get("alchemy_level", 0) == 0:
            self.add_item(MenuButton("丹阁考核", discord.ButtonStyle.success, "dange_exam"))

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
            await interaction.response.edit_message(embed=_world_overview_embed(), view=WorldMenuView(interaction.user, cog))
            return

        if self.action == "travel":
            await interaction.response.edit_message(
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
                char_cog = cog.bot.cogs.get("Character") or cog
                await char_cog.create_character(ctx)
            elif self.action == "profile":
                await cog.send_profile(interaction)
            elif self.action == "cultivate":
                from utils.events.public.wanbao import is_auction_locked
                if is_auction_locked(str(interaction.user.id)):
                    await interaction.followup.send("拍卖会进行中，在万宝楼内无法闭关修炼。", ephemeral=True)
                else:
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
            elif self.action == "city":
                from utils.views.city import CityMenuView, _city_menu_embed
                from utils.db import get_conn as _gc
                uid = str(interaction.user.id)
                with _gc() as conn:
                    player = dict(conn.execute("SELECT * FROM players WHERE discord_id = ?", (uid,)).fetchone())
                await interaction.followup.edit_message(
                    message_id=interaction.message.id,
                    embed=_city_menu_embed(player),
                    view=CityMenuView(interaction.user, player, cog),
                )
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
                from utils.views.equipment import EquipmentManageView, _build_equipment_embed
                from utils.db import get_equipment_list, get_conn as _gc
                uid = str(interaction.user.id)
                with _gc() as conn:
                    row = conn.execute("SELECT * FROM players WHERE discord_id = ?", (uid,)).fetchone()
                    player = dict(row)
                equips = get_equipment_list(uid)
                embed = _build_equipment_embed(player, equips)
                view = EquipmentManageView(interaction.user, cog)
                await interaction.followup.edit_message(message_id=interaction.message.id, embed=embed, view=view)
            elif self.action == "crafting":
                from utils.views.crafting import CraftingMenuView, _crafting_overview_embed
                await interaction.followup.edit_message(
                    message_id=interaction.message.id,
                    embed=_crafting_overview_embed(),
                    view=CraftingMenuView(interaction.user, cog),
                )
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
                from utils.events.public.wanbao import is_auction_locked
                if is_auction_locked(uid):
                    await interaction.followup.send("拍卖会进行中，在万宝楼内无法采集。", ephemeral=True)
                elif defense_row:
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
            elif self.action == "wanbao":
                pe_cog = cog.bot.cogs.get("PublicEvents")
                if pe_cog:
                    ctx = await cog.bot.get_context(interaction.message)
                    ctx.author = interaction.user
                    await pe_cog.wanbao(ctx)
                else:
                    await interaction.followup.send("万宝楼系统暂时不可用。", ephemeral=True)
            elif self.action == "dange_exam":
                from utils.views.dange import DangeView
                from utils.db import get_conn as _gc
                from utils.db_async import AsyncSessionLocal, Player as _Player
                uid = str(interaction.user.id)
                with _gc() as conn:
                    row = conn.execute("SELECT * FROM players WHERE discord_id = ?", (uid,)).fetchone()
                    player = dict(row)
                if player.get("alchemy_level", 0) > 0:
                    await interaction.followup.send("你已经是炼丹师了，无需再考核。", ephemeral=True)
                elif player.get("fortune", 0) < 3 or player.get("soul", 0) < 3:
                    await interaction.followup.send(
                        f"机缘与神识各需达到 **3点** 方可进入丹阁。\n"
                        f"当前：机缘 {player.get('fortune',0)} / 神识 {player.get('soul',0)}",
                        ephemeral=True,
                    )
                else:
                    async with AsyncSessionLocal() as session:
                        p = await session.get(_Player, uid)
                        paid = (p.exam_attempts_left > 0) if p else False
                    view = DangeView(interaction.user, cog, player, paid=paid)
                    view.set_paid(paid)
                    from utils.views.dange import _elder_greeting, _elder_greeting_paid
                    greeting = _elder_greeting_paid(player) if paid else _elder_greeting(player)
                    embed = discord.Embed(
                        title="✦ 丹阁 · 炼丹师考核 ✦",
                        color=discord.Color.gold(),
                    )
                    embed.add_field(name="丹阁长老", value=f"*「{greeting}」*", inline=False)
                    if not paid:
                        embed.add_field(
                            name="考核规则",
                            value=(
                                f"· 费用：**500 灵石**（含材料）\n"
                                "· 成功炼出考核丹药即可获得一品炼丹师资质\n"
                                "· 材料用完可花 300 灵石补充"
                            ),
                            inline=False,
                        )
                    await interaction.followup.edit_message(
                        message_id=interaction.message.id, embed=embed, view=view
                    )
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
