import asyncio
import random
import time

import discord

from typing import Optional, Dict

from utils.character import QUESTIONS, calc_stats, roll_spirit_root, REALM_LIFESPAN
from utils.db import get_conn
from utils.player import get_player
from utils.world import CITIES


def _speed_label(root_type: str) -> str:
    return {
        "单灵根": "极快",
        "双灵根": "较快",
        "三灵根": "普通",
        "四灵根": "较慢",
        "五灵根": "迟缓",
        "变异灵根": "特殊",
    }.get(root_type, "未知")


def _build_result_embed(
    name: str,
    gender: str,
    starting_city: str,
    spirit_root: str,
    root_type: str,
    lifespan: int,
    stats: dict,
    rebirth_bonus: Optional[dict] = None,
) -> discord.Embed:
    rebirth_bonus = rebirth_bonus or {}
    embed = discord.Embed(
        title=f"✦ {name} ✦",
        description=f"{gender}修 · 炼气期1层 · {starting_city}",
        color=discord.Color.teal(),
    )
    embed.add_field(
        name="灵根",
        value=f"{root_type}·{spirit_root}（修炼速度：{_speed_label(root_type)}）",
        inline=False,
    )
    embed.add_field(name="悟性", value=stats["comprehension"] + rebirth_bonus.get("comprehension", 0), inline=True)
    embed.add_field(name="体魄", value=stats["physique"] + rebirth_bonus.get("physique", 0), inline=True)
    embed.add_field(name="机缘", value=stats["fortune"] + rebirth_bonus.get("fortune", 0), inline=True)
    embed.add_field(name="根骨", value=stats["bone"] + rebirth_bonus.get("bone", 0), inline=True)
    embed.add_field(name="神识", value=stats["soul"] + rebirth_bonus.get("soul", 0), inline=True)
    embed.add_field(name="寿元", value=f"{lifespan} 年", inline=True)
    embed.add_field(name="灵石", value=stats["spirit_stones"], inline=True)
    if rebirth_bonus and any(v > 0 for v in rebirth_bonus.values()):
        bonus_str = "  ".join(f"{k} +{v}" for k, v in rebirth_bonus.items() if v > 0)
        embed.add_field(name="✨ 轮回感悟", value=bonus_str, inline=False)
    embed.set_footer(text="天道有常，长生路远，望道友珍重。")
    return embed


class CharacterNameModal(discord.ui.Modal, title="赐下道号"):
    name = discord.ui.TextInput(
        label="道号（1-16字）",
        placeholder="例如：青玄、云游子、南山客",
        min_length=1,
        max_length=16,
        required=True,
    )

    def __init__(self, view: "CharacterCreateView"):
        super().__init__()
        self._view = view

    async def on_submit(self, interaction: discord.Interaction):
        await self._view.finalize(interaction, str(self.name.value).strip())


class CharacterCreateView(discord.ui.View):
    """
    Button-UI character creation flow:
    - Choose gender
    - Answer 10 questions (A/B/C)
    - Enter name via modal
    """

    def __init__(self, author: discord.User, char_cog):
        super().__init__(timeout=180)
        self.author = author
        self.char_cog = char_cog
        self.uid = str(author.id)
        self.gender: Optional[str] = None
        self.answers: Dict[int, str] = {}
        self.step: int = -1  # -1=gender, 0..len(QUESTIONS)-1=questions, len=done
        self.message: Optional[discord.Message] = None
        self._text_task: Optional[asyncio.Task] = None
        self._done: bool = False

        self._render_components()

    def attach_message(self, message: discord.Message):
        self.message = message
        if self._text_task is None:
            self._text_task = asyncio.create_task(self._text_listener())

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user != self.author:
            await interaction.response.send_message("这不是你的创建面板。", ephemeral=True)
            return False
        return True

    async def on_timeout(self) -> None:
        try:
            self._done = True
            if self._text_task:
                self._text_task.cancel()
            if self.message:
                await self.message.edit(content="创建已超时取消。", view=None)
        finally:
            if hasattr(self.char_cog, "_creating"):
                self.char_cog._creating.discard(self.uid)
            self.stop()

    def _msg_choice(self, content: str) -> Optional[str]:
        c = (content or "").strip().upper()
        if c in ("A", "B", "C"):
            return c
        return None

    async def _advance_message(self):
        self._render_components()
        if self.message:
            await self.message.edit(embed=self._build_step_embed(), view=self)

    async def _text_listener(self):
        # Allow A/B/C message input as an alternative to buttons.
        while not self._done:
            try:
                if not self.message:
                    await asyncio.sleep(0.2)
                    continue

                channel = self.message.channel

                def check(m: discord.Message):
                    return m.author.id == self.author.id and m.channel == channel

                m: discord.Message = await self.char_cog.bot.wait_for("message", check=check, timeout=180)
                if self._done:
                    return

                choice = self._msg_choice(m.content)

                # Gender step: accept A/B
                if self.step == -1:
                    if choice in ("A", "B"):
                        self.gender = "男" if choice == "A" else "女"
                        self.step = 0
                        await self._advance_message()
                    continue

                # Question steps: accept A/B/C
                if 0 <= self.step < len(QUESTIONS):
                    if choice in ("A", "B", "C"):
                        self.answers[self.step] = choice
                        self.step += 1
                        await self._advance_message()
                    continue

                # Name step: allow direct message input as well
                if self.step == len(QUESTIONS):
                    name = (m.content or "").strip()
                    if 1 <= len(name) <= 16:
                        await self.finalize_from_message(m, name)
                    continue
            except asyncio.TimeoutError:
                return
            except asyncio.CancelledError:
                return
            except Exception:
                # Ignore listener errors; user can still use buttons.
                await asyncio.sleep(0.2)

    def _build_step_embed(self) -> discord.Embed:
        if self.step == -1:
            return discord.Embed(
                title="✦ 创建角色 ✦",
                description="请选择你的性别：\nA. 男修\nB. 女修",
                color=discord.Color.teal(),
            )
        if 0 <= self.step < len(QUESTIONS):
            q = QUESTIONS[self.step]
            lines = []
            for k, v in q["options"].items():
                lines.append(f"**{k}.** {v[0]}")
            chosen = f"\n\n已选：{self.gender}修" if self.gender else ""
            return discord.Embed(
                title=f"✦ 创建角色 · 第 {self.step + 1}/{len(QUESTIONS)} 问 ✦",
                description=f"**{q['text']}**\n\n" + "\n".join(lines) + chosen,
                color=discord.Color.teal(),
            )
        return discord.Embed(
            title="✦ 创建角色 ✦",
            description="最后一步：点击下方按钮填写道号。\n（也可以直接发送道号，1-16字）",
            color=discord.Color.teal(),
        )

    def _render_components(self):
        self.clear_items()

        if self.step == -1:
            self.add_item(_GenderButton("男修", "男", style=discord.ButtonStyle.primary))
            self.add_item(_GenderButton("女修", "女", style=discord.ButtonStyle.danger))
        elif 0 <= self.step < len(QUESTIONS):
            q = QUESTIONS[self.step]
            for key in ("A", "B", "C"):
                label = q["options"][key][0]
                self.add_item(_AnswerButton(label=label, choice=key, style=discord.ButtonStyle.success))
        else:
            self.add_item(_OpenNameModalButton())

        self.add_item(_CancelCreateButton())

    async def _advance(self, interaction: discord.Interaction):
        self._render_components()
        embed = self._build_step_embed()
        await interaction.response.edit_message(embed=embed, view=self)

    async def choose_gender(self, interaction: discord.Interaction, gender: str):
        if get_player(self.uid) and not get_player(self.uid).get("is_dead"):
            await interaction.response.edit_message(content="你已创建角色，无需重复创建。", embed=None, view=None)
            self.char_cog._creating.discard(self.uid)
            return
        self.gender = gender
        self.step = 0
        await self._advance(interaction)

    async def choose_answer(self, interaction: discord.Interaction, choice: str):
        if self.step < 0 or self.step >= len(QUESTIONS):
            await interaction.response.send_message("当前不在答题阶段。", ephemeral=True)
            return
        self.answers[self.step] = choice
        self.step += 1
        await self._advance(interaction)

    async def open_name_modal(self, interaction: discord.Interaction):
        if self.step != len(QUESTIONS):
            await interaction.response.send_message("请先完成所有问题。", ephemeral=True)
            return
        await interaction.response.send_modal(CharacterNameModal(self))

    async def cancel(self, interaction: discord.Interaction):
        self._done = True
        if self._text_task:
            self._text_task.cancel()
        self.char_cog._creating.discard(self.uid)
        await interaction.response.edit_message(content="已取消创建。", embed=None, view=None)
        self.stop()

    async def _commit_character(self, name: str):
        answers = dict(self.answers)
        stats = calc_stats(answers)
        spirit_root, root_type = roll_spirit_root()
        lifespan = REALM_LIFESPAN["炼气期"]
        now = time.time()
        starting_city = random.choice(CITIES)["name"]

        rebirth_bonus = {}
        with get_conn() as conn:
            old = get_player(self.uid)
            if old and old.get("is_dead"):
                rebirth_bonus = self.char_cog._calc_rebirth_bonus(old) if (
                    old.get("sect") == "仙葬谷" or old.get("has_bahongchen")
                ) else {}
                conn.execute(
                    """
                    UPDATE players SET
                        name=?, gender=?, spirit_root=?, spirit_root_type=?,
                        comprehension=?, physique=?, fortune=?, bone=?, soul=?,
                        lifespan=?, lifespan_max=?, spirit_stones=?,
                        cultivation=0, realm='炼气期1层',
                        cultivating_until=NULL, cultivating_years=NULL,
                        is_dead=0, is_virgin=1, rebirth_count=rebirth_count,
                        sect=NULL, sect_rank=NULL, techniques='[]',
                        dual_partner_id=NULL,
                        cultivation_overflow=0, current_city=?,
                        explore_count=0, explore_reset_year=0,
                        reputation=0, cave=NULL,
                        active_quest=NULL, quest_due=NULL,
                        gathering_until=NULL, gathering_type=NULL,
                        created_at=?, last_active=?
                    WHERE discord_id=?
                    """,
                    (
                        name,
                        self.gender,
                        spirit_root,
                        root_type,
                        stats["comprehension"] + rebirth_bonus.get("comprehension", 0),
                        stats["physique"] + rebirth_bonus.get("physique", 0),
                        stats["fortune"] + rebirth_bonus.get("fortune", 0),
                        stats["bone"] + rebirth_bonus.get("bone", 0),
                        stats["soul"] + rebirth_bonus.get("soul", 0),
                        lifespan,
                        lifespan,
                        stats["spirit_stones"],
                        starting_city,
                        now,
                        now,
                        self.uid,
                    ),
                )
            else:
                conn.execute(
                    """
                    INSERT INTO players (
                        discord_id, name, gender, spirit_root, spirit_root_type,
                        comprehension, physique, fortune, bone, soul,
                        lifespan, lifespan_max, spirit_stones,
                        created_at, last_active, current_city
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        self.uid,
                        name,
                        self.gender,
                        spirit_root,
                        root_type,
                        stats["comprehension"],
                        stats["physique"],
                        stats["fortune"],
                        stats["bone"],
                        stats["soul"],
                        lifespan,
                        lifespan,
                        stats["spirit_stones"],
                        now,
                        now,
                        starting_city,
                    ),
                )
            conn.commit()

        embed = _build_result_embed(
            name=name,
            gender=self.gender,
            starting_city=starting_city,
            spirit_root=spirit_root,
            root_type=root_type,
            lifespan=lifespan,
            stats=stats,
            rebirth_bonus=rebirth_bonus,
        )
        return embed

    async def finalize(self, interaction: discord.Interaction, name: str):
        if not name or len(name) > 16:
            await interaction.response.send_message("道号无效，请输入 1-16 字。", ephemeral=True)
            return
        if self.gender is None or len(self.answers) != len(QUESTIONS):
            await interaction.response.send_message("创建流程未完成。", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        existing = get_player(self.uid)
        if existing and not existing.get("is_dead"):
            self._done = True
            if self._text_task:
                self._text_task.cancel()
            self.char_cog._creating.discard(self.uid)
            if self.message:
                await self.message.edit(content="你已创建角色，无需重复创建。", embed=None, view=None)
            await interaction.followup.send("你已创建角色。", ephemeral=True)
            self.stop()
            return

        embed = await self._commit_character(name)

        self._done = True
        if self._text_task:
            self._text_task.cancel()
        self.char_cog._creating.discard(self.uid)
        if self.message:
            await self.message.edit(
                content=f"天地感应，灵根初现……\n{self.author.mention}",
                embed=embed,
                view=None,
            )
        await interaction.followup.send("创建完成。", ephemeral=True)
        self.stop()

    async def finalize_from_message(self, message: discord.Message, name: str):
        if self._done:
            return
        if not name or len(name) > 16:
            return
        if self.gender is None or len(self.answers) != len(QUESTIONS):
            return

        existing = get_player(self.uid)
        if existing and not existing.get("is_dead"):
            self._done = True
            if self._text_task:
                self._text_task.cancel()
            self.char_cog._creating.discard(self.uid)
            if self.message:
                await self.message.edit(content="你已创建角色，无需重复创建。", embed=None, view=None)
            self.stop()
            return

        embed = await self._commit_character(name)

        self._done = True
        if self._text_task:
            self._text_task.cancel()
        self.char_cog._creating.discard(self.uid)
        if self.message:
            await self.message.edit(
                content=f"天地感应，灵根初现……\n{self.author.mention}",
                embed=embed,
                view=None,
            )
        self.stop()


class _GenderButton(discord.ui.Button):
    def __init__(self, label: str, gender: str, style: discord.ButtonStyle):
        super().__init__(label=label, style=style, row=0)
        self.gender = gender

    async def callback(self, interaction: discord.Interaction):
        await self.view.choose_gender(interaction, self.gender)


class _AnswerButton(discord.ui.Button):
    def __init__(self, label: str, choice: str, style: discord.ButtonStyle):
        super().__init__(label=label, style=style, row=0)
        self.choice = choice

    async def callback(self, interaction: discord.Interaction):
        await self.view.choose_answer(interaction, self.choice)


class _OpenNameModalButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="填写道号", style=discord.ButtonStyle.primary, row=0)

    async def callback(self, interaction: discord.Interaction):
        await self.view.open_name_modal(interaction)


class _CancelCreateButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="取消", style=discord.ButtonStyle.secondary, row=1)

    async def callback(self, interaction: discord.Interaction):
        await self.view.cancel(interaction)

