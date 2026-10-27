"""调参（U1·江湖百态 B）：管理员在游戏里查看 / 修改各系统的概率、次数、冷却等数字，立即生效、重启不丢。

`cat!调参`（总览）· `cat!调参 列表 <文件> [关键词]` · `cat!调参 说明 <文件>` · `cat!调参 搜索 <关键词>` · `cat!调参 设置 <文件> <路径> <值>` · `cat!调参 恢复 <文件> [路径]`。
权限同『江湖设置』（bot 所有者 / 记下的管理员）。规则与存储见 utils/settings_hub.py。
"""

from discord.ext import commands

from cogs.world_setup import can_manage
from utils import settings_hub as hub
from utils.config import COMMAND_PREFIX
from utils.logging_setup import audit

PAGE = 25
MAX_CHARS = 1800


def fmt(value) -> str:
    return "开" if value is True else "关" if value is False else f"{value:g}" if isinstance(value, float) else str(value)


def line(e: dict) -> str:
    mark = "✏️ " if e["changed"] else ""
    tail = f"（默认 {fmt(e['default'])}）" if e["changed"] else ""
    return f"{mark}`{e['path']}` = **{fmt(e['value'])}**{tail}"


def overview_text() -> str:
    rows = [f"• `{o['file']}`：{o['count']} 项可调" + (f"，✏️ 已改 {o['changed']} 项" if o["changed"] else "") for o in hub.overview()]
    return ("**🎛️ 调参总览**（只能调数字和开关；文字内容请改 data/ 里的文件）\n" + "\n".join(rows)
            + f"\n\n`{COMMAND_PREFIX}调参 列表 <文件> [关键词]` 看某个文件 · `{COMMAND_PREFIX}调参 说明 <文件>` 看每个字段的意思 · `{COMMAND_PREFIX}调参 搜索 <关键词>` 跨文件找 · "
              f"`{COMMAND_PREFIX}调参 设置 <文件> <路径> <值>` 修改 · `{COMMAND_PREFIX}调参 恢复 <文件> [路径]` 恢复默认。\n"
              f"文件名可以简写，例如 `feuds`；开关填 开 / 关。")


def clip(lines: list[str], total: int, head: str) -> str:
    out, size = [], len(head)
    for l in lines:
        if size + len(l) + 1 > MAX_CHARS or len(out) >= PAGE:
            break
        out.append(l)
        size += len(l) + 1
    more = total - len(out)
    return head + "\n".join(out) + (f"\n…还有 {more} 项，请加关键词缩小范围。" if more > 0 else "")


class TuningCog(commands.Cog, name="Tuning"):
    def __init__(self, bot):
        self.bot = bot

    async def _allowed(self, ctx) -> bool:
        if await can_manage(self.bot, ctx.author, getattr(ctx.author, "guild_permissions", None)):
            return True
        await ctx.send("只有服务器管理员（或 bot 所有者）能调参。")
        return False

    def _file(self, name: str) -> str | None:
        return hub.resolve(name)

    @commands.hybrid_group(name="调参", fallback="总览", description="（管理员）查看 / 修改各系统的概率和数字")
    async def tune(self, ctx):
        if await self._allowed(ctx):
            await ctx.send(overview_text())

    @tune.command(name="列表", description="（管理员）看某个配置文件里能调的项")
    async def tune_list(self, ctx, file: str, keyword: str = ""):
        if not await self._allowed(ctx):
            return
        name = self._file(file)
        if name is None:
            return await ctx.send(f"没有这个配置文件：{file}。发 `{COMMAND_PREFIX}调参` 看全部。")
        es = hub.entries(name, keyword)
        await ctx.send(clip([line(e) for e in es], len(es), f"**{name}**" + (f" · 含「{keyword}」" if keyword else "") + f"（{len(es)} 项）\n") if es
                       else f"{name} 里没有路径含「{keyword}」的可调项。")

    @tune.command(name="搜索", description="（管理员）跨文件按关键词找可调项")
    async def tune_search(self, ctx, keyword: str):
        if not await self._allowed(ctx):
            return
        found = hub.search(keyword, limit=PAGE + 1)
        if not found:
            return await ctx.send(f"没找到路径含「{keyword}」的可调项。")
        await ctx.send(clip([f"`{e['file']}` " + line(e) for e in found], len(found), f"**搜索「{keyword}」**\n"))

    @tune.command(name="说明", description="（管理员）看某个配置文件里每个字段是什么意思")
    async def tune_note(self, ctx, file: str):
        if not await self._allowed(ctx):
            return
        name = self._file(file)
        if name is None:
            return await ctx.send(f"没有这个配置文件：{file}。")
        text = hub.note(name) or "这个文件没有写说明。"
        for i in range(0, len(text), MAX_CHARS):
            await ctx.send(f"**{name} 说明**\n{text[i:i + MAX_CHARS]}" if i == 0 else text[i:i + MAX_CHARS])

    @tune.command(name="设置", description="（管理员）修改一项：文件 路径 值，立即生效")
    async def tune_set(self, ctx, file: str, path: str, value: str):
        if not await self._allowed(ctx):
            return
        name = self._file(file)
        if name is None:
            return await ctx.send(f"没有这个配置文件：{file}。")
        ok, msg = await hub.set_value(name, path, value)
        if ok:
            audit("tuning_set", ctx.author, file=name, path=path, value=value)
        await ctx.send(("✅ " if ok else "❌ ") + msg)

    @tune.command(name="恢复", description="（管理员）恢复默认：一项，或整个文件")
    async def tune_reset(self, ctx, file: str, path: str = ""):
        if not await self._allowed(ctx):
            return
        name = self._file(file)
        if name is None:
            return await ctx.send(f"没有这个配置文件：{file}。")
        ok, msg = await hub.reset(name, path or None)
        if ok:
            audit("tuning_reset", ctx.author, file=name, path=path or "*")
        await ctx.send(("✅ " if ok else "❌ ") + msg)


async def setup(bot):
    await bot.add_cog(TuningCog(bot))
