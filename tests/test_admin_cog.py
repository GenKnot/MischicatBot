"""运维命令（cogs/admin.py）：只有 bot 所有者能同步斜杠命令。

B72 —— `sync` 会改变整个 bot 在 Discord 上的命令列表（全局同步影响所有服务器），属于管理员操作，
  却没写审计日志（其余管理命令都有 `audit(...)`）。补上，记录谁、同步到哪、同步了多少条。
"""

import logging
from types import SimpleNamespace

import pytest
from discord.ext import commands

from cogs.admin import AdminCog
from tests.discord_fakes import FakeContext


class FakeTree:
    def __init__(self, n=3):
        self.n, self.calls = n, []

    def copy_global_to(self, guild):
        self.calls.append(("copy", guild))

    async def sync(self, guild=None):
        self.calls.append(("sync", guild))
        return list(range(self.n))


def make(n=3, owner_ids=("1",)):
    async def is_owner(user):
        return str(user.id) in owner_ids
    bot = SimpleNamespace(tree=FakeTree(n), is_owner=is_owner)
    return AdminCog(bot), bot


def ctx_in_guild(uid=1):
    c = FakeContext(user_id=uid)
    c.guild = SimpleNamespace(id=99, name="测试服")
    return c


async def run(cog, c, scope="guild"):
    return await cog.sync.callback(cog, c, scope)


async def test_本服同步_默认(db):
    cog, bot = make(5)
    c = ctx_in_guild()
    await run(cog, c)
    assert bot.tree.calls == [("copy", c.guild), ("sync", c.guild)]
    assert c.said("已同步 5 个斜杠命令到本服")


async def test_全局同步(db):
    cog, bot = make(7)
    c = ctx_in_guild()
    await run(cog, c, "global")
    assert bot.tree.calls == [("sync", None)] and c.said("已全局同步 7 个") and c.said("一小时")


async def test_私聊里没有服务器可同步(db):
    cog, bot = make()
    c = FakeContext(user_id=1)
    await run(cog, c)
    assert bot.tree.calls == [] and c.said("私聊里没有服务器") and c.said("sync global")


async def test_私聊也能全局同步(db):
    cog, bot = make(2)
    c = FakeContext(user_id=1)
    await run(cog, c, "global")
    assert c.said("已全局同步 2 个")


async def test_未知范围按本服处理(db):
    cog, bot = make()
    c = ctx_in_guild()
    await run(cog, c, "whatever")
    assert ("sync", c.guild) in bot.tree.calls


async def test_B72_同步会留审计日志(db, caplog):
    cog, _ = make(4)
    with caplog.at_level(logging.WARNING, logger="mischicat.audit"):
        await run(cog, ctx_in_guild(), "global")
        await run(cog, ctx_in_guild())
    msgs = [r.getMessage() for r in caplog.records]
    assert any("sync" in m and "global" in m and "count=4" in m for m in msgs)
    assert any("sync" in m and "guild" in m for m in msgs)


async def test_只有所有者通过检查(db):
    cog, _ = make(owner_ids=("1",))
    check = cog.sync.checks[0]
    assert await check(ctx_with_bot(cog, 1)) is True
    with pytest.raises(commands.NotOwner):
        await check(ctx_with_bot(cog, 2))


def ctx_with_bot(cog, uid):
    c = ctx_in_guild(uid)
    c.bot = cog.bot
    return c


async def test_非所有者被拒时的提示(db):
    cog, _ = make()
    c = ctx_in_guild(2)
    await cog.sync_error(c, commands.NotOwner())
    assert c.said("只有 bot 所有者能用")


async def test_其他错误不在这里回复(db):
    cog, _ = make()
    c = ctx_in_guild()
    await cog.sync_error(c, commands.CommandError("别的错"))
    assert c.messages == []


async def test_setup注册cog(db):
    from cogs import admin
    added = []

    class Bot:
        async def add_cog(self, cog):
            added.append(cog)
    await admin.setup(Bot())
    assert isinstance(added[0], AdminCog)
