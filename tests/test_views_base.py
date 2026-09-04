"""面板基类测试。

原先 79 个 View 里只有 1 个实现了 on_timeout —— 超时后按钮看着还在、
点了没反应也没提示。
"""

import discord
import pytest

from tests.discord_fakes import FakeInteraction, FakeUser
from utils.views.base import TIMEOUT_NOTICE, VIEW_TIMEOUT, TimedView


class _Panel(TimedView):
    @discord.ui.button(label="点我")
    async def press(self, interaction, button):
        await interaction.response.send_message("ok")


class _FakeMessage:
    def __init__(self):
        self.edits = []
        self.raises = None

    async def edit(self, **kwargs):
        if self.raises:
            raise self.raises
        self.edits.append(kwargs)


# --- 归属校验 ----------------------------------------------------------------

async def test_面板主人可以操作():
    view = _Panel(author=FakeUser(id=1))
    assert await view.interaction_check(FakeInteraction(user_id=1)) is True


async def test_别人点不动():
    view = _Panel(author=FakeUser(id=1))
    intruder = FakeInteraction(user_id=999)

    assert await view.interaction_check(intruder) is False
    assert intruder.said("这不是你的面板")


async def test_公共面板人人可点():
    """公共事件那类面板本来就该谁都能点。"""
    view = _Panel(author=None)
    assert await view.interaction_check(FakeInteraction(user_id=999)) is True


async def test_可以自定义拒绝文案():
    class _Invite(TimedView):
        not_owner_message = "这不是发给你的邀请。"

    view = _Invite(author=FakeUser(id=1))
    other = FakeInteraction(user_id=2)
    await view.interaction_check(other)
    assert other.said("这不是发给你的邀请")


# --- 超时 --------------------------------------------------------------------

def test_默认超时统一():
    assert _Panel(author=None).timeout == VIEW_TIMEOUT


def test_可以指定别的超时():
    """拍卖竞价这类面板的存活时间和拍品绑定，要能单独设。"""
    assert _Panel(author=None, timeout=42).timeout == 42
    assert _Panel(author=None, timeout=None).timeout is None


async def test_超时会禁用按钮并改提示():
    view = _Panel(author=FakeUser(id=1))
    message = _FakeMessage()
    interaction = FakeInteraction(user_id=1)
    interaction.message = message
    await view.interaction_check(interaction)      # 点一次，让 view 记住消息

    await view.on_timeout()

    assert all(item.disabled for item in view.children), "超时后按钮必须禁用"
    assert message.edits and message.edits[0]["content"] == TIMEOUT_NOTICE


async def test_没人点过时静默过期():
    """一次都没点过就拿不到消息，不能因此报错。"""
    view = _Panel(author=FakeUser(id=1))

    await view.on_timeout()          # 不应抛异常

    assert all(item.disabled for item in view.children)


async def test_消息被删时不报错():
    view = _Panel(author=FakeUser(id=1))
    message = _FakeMessage()
    # 构造一个真实的 HTTPException 需要 response 对象，这里给个最小替身
    class _Resp:
        status = 404
        reason = "Not Found"
    message.raises = discord.HTTPException(_Resp(), "Unknown Message")
    interaction = FakeInteraction(user_id=1)
    interaction.message = message
    await view.interaction_check(interaction)

    await view.on_timeout()          # 不应把异常抛给调用方


async def test_每次交互都会刷新记住的消息():
    view = _Panel(author=FakeUser(id=1))
    first, second = _FakeMessage(), _FakeMessage()
    for msg in (first, second):
        it = FakeInteraction(user_id=1)
        it.message = msg
        await view.interaction_check(it)

    assert view.message is second


# --- 全项目约束 --------------------------------------------------------------

def _view_classes():
    """遍历 utils/views 下所有 View 类，返回 (文件, 类名, 基类, 类体源码)。"""
    import ast
    import os

    root = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "utils", "views")
    for name in sorted(os.listdir(root)):
        if not name.endswith(".py") or name == "base.py":
            continue
        src = open(os.path.join(root, name), encoding="utf-8").read()
        for node in ast.walk(ast.parse(src)):
            if isinstance(node, ast.ClassDef):
                bases = [ast.unparse(b) for b in node.bases]
                if any("View" in b for b in bases):
                    yield name, node.name, bases[0], ast.unparse(node)


def test_所有面板都继承_timedview():
    """直接继承 discord.ui.View 就拿不到超时提示，也拿不到统一的归属校验。"""
    offenders = [f"{f}:{c}" for f, c, base, _ in _view_classes() if base != "TimedView"]
    assert not offenders, f"这些面板没有继承 TimedView：{offenders}"


def test_面板要么有_author_要么显式标记_public():
    """默认放行是个洞：漏写 author 就悄悄做出一个谁都能操作的面板。"""
    offenders = []
    for f, c, _base, body in _view_classes():
        if "self.author" in body or "public = True" in body:
            continue
        offenders.append(f"{f}:{c}")
    assert not offenders, (
        f"这些面板既没设 author 也没标 public：{offenders}。"
        "公共面板请显式写 public = True。")


def test_自定义的_interaction_check_要记录_message():
    """覆盖了基类的校验就拿不到 message，超时提示会失效。"""
    offenders = [
        f"{f}:{c}" for f, c, _b, body in _view_classes()
        if "async def interaction_check" in body
        and "self.message = interaction.message" not in body
    ]
    assert not offenders, f"这些面板的 interaction_check 没记录 message：{offenders}"


def test_没有面板再自己写超时数字():
    """超时值统一由基类给。确实需要不同值的（拍卖竞价）走 timeout= 参数并写明理由。"""
    import re

    allowed = {"None", "LOT_DURATION"}
    offenders = []
    for f, c, _b, body in _view_classes():
        for m in re.finditer(r"super\(\)\.__init__\(timeout=([^)]+)\)", body):
            if m.group(1).strip() not in allowed:
                offenders.append(f"{f}:{c} timeout={m.group(1)}")
    assert not offenders, f"这些面板硬写了超时值：{offenders}"
