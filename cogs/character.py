import asyncio
from typing import Optional

import discord
from discord.ext import commands

from utils.character import QUESTIONS
from utils.character_create_logic import commit_character
from utils.death_rebirth_logic import calculate_rebirth_bonus
from utils.player import get_player
from utils.views.character_create import CharacterCreateView, _build_result_embed


class CharacterCog(commands.Cog, name="Character"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._creating: set[str] = set()

    def _calc_rebirth_bonus(self, player: dict) -> dict:
        return calculate_rebirth_bonus(player)

    async def _create_character_text(self, ctx):
        uid = str(ctx.author.id)

        def check(m: discord.Message):
            return m.author == ctx.author and m.channel == ctx.channel

        try:
            await ctx.send(f"{ctx.author.mention} 道友，请问你是男修还是女修？\nA. 男修\nB. 女修")
            msg = await self.bot.wait_for("message", check=check, timeout=60)
            gender_choice = msg.content.strip().upper()
            if gender_choice not in ("A", "B"):
                return await ctx.send("输入有误，创建已取消。")
            gender = "男" if gender_choice == "A" else "女"

            answers = {}
            for i, q in enumerate(QUESTIONS):
                options_text = "\n".join(f"{k}. {v[0]}" for k, v in q["options"].items())
                await ctx.send(f"**第{i + 1}问：{q['text']}**\n{options_text}")
                msg = await self.bot.wait_for("message", check=check, timeout=60)
                choice = msg.content.strip().upper()
                if choice not in q["options"]:
                    return await ctx.send("输入有误，创建已取消。")
                answers[i] = choice

            await ctx.send("请赐下你的道号（1-16字）：")
            msg = await self.bot.wait_for("message", check=check, timeout=60)
            name = msg.content.strip()
            if not name or len(name) > 16:
                return await ctx.send("道号无效，创建已取消。")

            created = await commit_character(uid, name, gender, answers)
            if created is None:
                return await ctx.send(f"{ctx.author.mention} 道友已踏入修仙之路，无需重新创建。")
            await ctx.send(f"天地感应，灵根初现……\n{ctx.author.mention}", embed=_build_result_embed(**created))

        except asyncio.TimeoutError:
            await ctx.send(f"{ctx.author.mention} 响应超时，创建已取消。")

    @commands.hybrid_command(name="创建角色", aliases=["cjjs"], description="创建新的修仙角色，开辟修行之路")
    async def create_character(self, ctx, mode: Optional[str] = None):
        uid = str(ctx.author.id)
        existing = await get_player(uid)
        if existing and not existing["is_dead"]:
            return await ctx.send(f"{ctx.author.mention} 道友已踏入修仙之路，无需重新创建。")
        if uid in self._creating:
            return await ctx.send(f"{ctx.author.mention} 正在创建中，请完成当前流程。")

        self._creating.add(uid)
        try:
            m = (mode or "").strip().lower()
            if m in ("文本", "text", "t", "msg"):
                await self._create_character_text(ctx)
                return

            ui_started = False
            view = CharacterCreateView(ctx.author, self)
            msg = await ctx.send(
                f"{ctx.author.mention}（如需文字输入：`创建角色 文本`）",
                embed=view._build_step_embed(),
                view=view,
            )
            view.attach_message(msg)
            ui_started = True
        finally:
            # UI 模式由 View 在完成/取消/超时里释放；这里只在“发送失败/文本流程结束”时兜底释放
            # 文本流程：_create_character_text 内部结束后应释放
            if (mode or "").strip().lower() in ("文本", "text", "t", "msg") or "ui_started" in locals() and not ui_started:
                self._creating.discard(uid)

    @commands.hybrid_command(name="解散队伍", aliases=["jsdw"], description="解散当前所在队伍")
    async def disband_party(self, ctx):
        from utils.views.party import disband_party_func
        msg = await disband_party_func(str(ctx.author.id), self.bot)
        await ctx.send(f"{ctx.author.mention} {msg}")

    @commands.hybrid_command(name="help", description="查看修仙系统主菜单与可用指令")
    async def help_cmd(self, ctx):
        import json
        uid = str(ctx.author.id)
        player = await get_player(uid)
        has_dual = False
        if player:
            has_dual = any(
                (t if isinstance(t, str) else t.get("name", "")) == "双修功法"
                for t in json.loads(player.get("techniques") or "[]")
            )
        from utils.views.menu import _build_menu_embed
        await ctx.send(ctx.author.mention, embed=_build_menu_embed(has_dual))


async def setup(bot: commands.Bot):
    await bot.add_cog(CharacterCog(bot))
