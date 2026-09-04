"""Discord 交互层的轻量替身。

cogs 和 views 里混着真正的业务判断，但拿不到 ctx/interaction 就一行都测不了。
这里只实现被真正用到的那几个属性，并记下发出的消息供断言 ——
替身越薄，越不会被 discord.py 升级带崩。
"""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class FakeUser:
    id: int = 1
    name: str = "测试修士"

    @property
    def mention(self) -> str:
        return f"<@{self.id}>"

    def __str__(self) -> str:
        return self.name


@dataclass
class SentMessage:
    """一条被发出去的消息。embed / view 原样保留，便于断言。"""
    content: str | None = None
    embed: Any = None
    view: Any = None
    ephemeral: bool = False

    def __contains__(self, text: str) -> bool:
        """`"灵石不足" in message` —— 同时看正文和 embed 的文字。"""
        haystack = [self.content or ""]
        if self.embed is not None:
            haystack += [getattr(self.embed, "title", "") or "",
                         getattr(self.embed, "description", "") or ""]
            for f in getattr(self.embed, "fields", []) or []:
                haystack += [getattr(f, "name", "") or "", getattr(f, "value", "") or ""]
        return any(text in h for h in haystack)


class _Recorder:
    """记录消息的公共部分。"""

    def __init__(self):
        self.messages: list[SentMessage] = []

    def _record(self, content=None, *, embed=None, view=None, ephemeral=False, **_):
        msg = SentMessage(content=content, embed=embed, view=view, ephemeral=ephemeral)
        self.messages.append(msg)
        return msg

    # --- 断言辅助 ---
    @property
    def last(self) -> SentMessage:
        assert self.messages, "没有发出任何消息"
        return self.messages[-1]

    def said(self, text: str) -> bool:
        return any(text in m for m in self.messages)


class FakeContext(_Recorder):
    """替代 commands.Context，够 cogs 里的命令跑起来。"""

    def __init__(self, user_id: str | int = 1, name: str = "测试修士"):
        super().__init__()
        self.author = FakeUser(id=int(user_id), name=name)
        self.guild = None

    async def send(self, content=None, **kwargs):
        return self._record(content, **kwargs)

    def typing(self):
        class _Noop:
            async def __aenter__(self_inner): return None
            async def __aexit__(self_inner, *a): return False
        return _Noop()


class _Response(_Recorder):
    def __init__(self, parent):
        super().__init__()
        self._parent = parent
        self.deferred = False

    async def send_message(self, content=None, **kwargs):
        msg = self._record(content, **kwargs)
        self._parent.messages.append(msg)
        return msg

    async def defer(self, **kwargs):
        self.deferred = True

    async def edit_message(self, content=None, **kwargs):
        msg = self._record(content, **kwargs)
        self._parent.messages.append(msg)
        return msg


class _Followup(_Recorder):
    def __init__(self, parent):
        super().__init__()
        self._parent = parent

    async def send(self, content=None, **kwargs):
        msg = self._record(content, **kwargs)
        self._parent.messages.append(msg)
        return msg


class FakeInteraction(_Recorder):
    """替代 discord.Interaction，够 views 里的按钮回调跑起来。"""

    def __init__(self, user_id: str | int = 1, name: str = "测试修士"):
        super().__init__()
        self.user = FakeUser(id=int(user_id), name=name)
        self.response = _Response(self)
        self.followup = _Followup(self)
        self.edited: list[SentMessage] = []
        # 真实的 Interaction 上有这个；面板超时要靠它拿到消息去编辑
        self.message = None

    async def edit_original_response(self, content=None, **kwargs):
        msg = SentMessage(content=content, embed=kwargs.get("embed"),
                          view=kwargs.get("view"))
        self.edited.append(msg)
        self.messages.append(msg)
        return msg


class FakeButton:
    """按钮回调的第二个参数，绝大多数回调只读它的 label / disabled。"""

    def __init__(self, label: str = "按钮"):
        self.label = label
        self.disabled = False
