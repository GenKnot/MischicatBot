"""按钮式创建面板（utils/views/character_create.py）：步骤流转、文字输入、道号表单、结果卡片。

落库本身（新建 / 轮回 / 并发）见 test_character_cog.py；这里管面板自己的状态机。

B33 —— 答题按钮没有绑定题号。面板编辑成下一题之前，同一道题的按钮可能被再点一次
  （手快连点、或文字输入与按钮同时到达），第二次点击会被当成『下一题』的答案：
  实际只答了一题，却跳过了一题，最后得到的属性和玩家的选择对不上。
"""

import asyncio
from types import SimpleNamespace

import pytest

from tests.conftest import make_player
from tests.discord_fakes import FakeContext, FakeInteraction
from utils.character import QUESTIONS
from utils.views import character_create as cc
from utils.views.character_create import (CharacterCreateView, CharacterNameModal, _build_result_embed,
                                          _speed_label)

UID = "1001"
N = len(QUESTIONS)


class FakeCog:
    def __init__(self, bot=None):
        self._creating = {UID}
        self.bot = bot


class FakeMessage:
    def __init__(self, channel=None):
        self.channel = channel or object()
        self.edits = []

    async def edit(self, **kw):
        self.edits.append(kw)


def make_view(user_id=UID, bot=None):
    ctx = FakeContext(user_id=user_id)
    cog = FakeCog(bot)
    return CharacterCreateView(ctx.author, cog), cog, ctx


def inter(uid=UID, message=None):
    i = FakeInteraction(uid)
    i.message = message
    return i


async def pick_gender(view, g="男"):
    await view.choose_gender(inter(), g)


async def answer(view, choice="A"):
    await view.choose_answer(inter(), choice, view.step)


async def _row(db, uid=UID):
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        return await s.get(D.Player, uid)


# --- 结果卡片 -----------------------------------------------------------------

@pytest.mark.parametrize("t,label", [("单灵根", "极快"), ("双灵根", "较快"), ("三灵根", "普通"),
                                     ("四灵根", "较慢"), ("五灵根", "迟缓"), ("变异灵根", "特殊"), ("???", "未知")])
def test_灵根速度文案(t, label):
    assert _speed_label(t) == label


STATS = dict(comprehension=5, physique=6, fortune=7, bone=8, soul=9, spirit_stones=100)


def card(bonus=None):
    return _build_result_embed("青玄", "男", "灵虚城", "金", "单灵根", 100, STATS, bonus)


def test_结果卡片_基本信息():
    e = card()
    assert e.title == "✦ 青玄 ✦" and "男修 · 炼气期1层 · 灵虚城" == e.description
    f = {x.name: x.value for x in e.fields}
    assert f["灵根"] == "单灵根·金（修炼速度：极快）"
    assert (f["悟性"], f["体魄"], f["机缘"], f["根骨"], f["神识"], f["灵石"]) == ("5", "6", "7", "8", "9", "100")
    assert f["寿元"] == "100 年" and "✨ 轮回感悟" not in f


def test_结果卡片_轮回加成叠加到属性_并列出正数项():
    e = card({"comprehension": 3, "physique": 0, "fortune": 2, "bone": 0, "soul": 0})
    f = {x.name: x.value for x in e.fields}
    assert f["悟性"] == "8" and f["机缘"] == "9" and f["体魄"] == "6"
    assert f["✨ 轮回感悟"] == "comprehension +3  fortune +2"


def test_结果卡片_加成全为0不显示感悟栏():
    assert "✨ 轮回感悟" not in [x.name for x in card({"comprehension": 0}).fields]


# --- 步骤文案与按钮 -----------------------------------------------------------

def test_初始是性别步骤_两个性别按钮加取消():
    v, *_ = make_view()
    assert v.step == -1
    assert [type(b).__name__ for b in v.children] == ["_GenderButton", "_GenderButton", "_CancelCreateButton"]
    assert "请选择你的性别" in v._build_step_embed().description


async def test_答题步骤_三个选项加取消_文案带题号与已选性别():
    v, *_ = make_view()
    await pick_gender(v, "女")
    e = v._build_step_embed()
    assert f"第 1/{N} 问" in e.title and QUESTIONS[0]["text"] in e.description and "已选：女修" in e.description
    assert [b.label for b in v.children[:3]] == [QUESTIONS[0]["options"][k][0] for k in "ABC"]
    assert len(v.children) == 4


async def test_答完题进入道号步骤():
    v, *_ = make_view()
    await pick_gender(v)
    for _ in range(N):
        await answer(v)
    assert v.step == N and "最后一步" in v._build_step_embed().description
    assert [type(b).__name__ for b in v.children] == ["_OpenNameModalButton", "_CancelCreateButton"]


async def test_答题记录每题的选择():
    v, *_ = make_view()
    await pick_gender(v)
    for c in "ABC" * 4:
        if v.step >= N:
            break
        await answer(v, c)
    assert v.answers == {i: "ABC"[i % 3] for i in range(N)}


# --- 身份校验 -----------------------------------------------------------------

async def test_只有发起人能操作_别人被拒(db):
    v, *_ = make_view()
    other = inter("2002")
    assert await v.interaction_check(other) is False
    assert "不是你的创建面板" in other.last and other.last.ephemeral


async def test_交互时记下消息_供超时提示编辑():
    v, *_ = make_view()
    msg = FakeMessage()
    assert await v.interaction_check(inter(UID, msg)) is True
    assert v.message is msg


# --- 性别 / 答题 / 表单入口 ---------------------------------------------------

async def test_选性别时已有存活角色_直接结束(db):
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        s.add(make_player(D, UID))
        await s.commit()
    v, cog, _ = make_view()
    i = inter()
    await v.choose_gender(i, "男")
    assert "无需重复创建" in i.last and UID not in cog._creating and v.gender is None


async def test_选性别时坐化的玩家可以继续(db):
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        p = make_player(D, UID)
        p.is_dead = 1
        s.add(p)
        await s.commit()
    v, *_ = make_view()
    await pick_gender(v)
    assert v.gender == "男" and v.step == 0


async def test_答题_不在答题阶段被拒(db):
    v, *_ = make_view()
    i = inter()
    await v.choose_answer(i, "A", -1)
    assert "当前不在答题阶段" in i.last and i.last.ephemeral and not v.answers


async def test_答题_过了最后一题再点被拒(db):
    v, *_ = make_view()
    await pick_gender(v)
    for _ in range(N):
        await answer(v)
    i = inter()
    await v.choose_answer(i, "A", N)
    assert "当前不在答题阶段" in i.last and len(v.answers) == N


async def test_答题_旧题的按钮被再点一次_不会被当成下一题的答案(db):
    """B33：连点同一题的按钮 —— 第二下以前会答掉下一题，等于悄悄跳过一题。"""
    v, *_ = make_view()
    await pick_gender(v)
    await v.choose_answer(inter(), "A", 0)
    i = inter()
    await v.choose_answer(i, "B", 0)                    # 仍是第 1 题的按钮
    assert v.step == 1 and v.answers == {0: "A"}
    assert i.last.ephemeral and "已更新" in i.last


async def test_答题_按钮自带题号(db):
    v, *_ = make_view()
    await pick_gender(v)
    assert {b.step for b in v.children if hasattr(b, "step")} == {0}
    await answer(v)
    assert {b.step for b in v.children if hasattr(b, "step")} == {1}


async def test_点按钮走到面板方法(db):
    v, *_ = make_view()
    await v.children[0].callback(inter())                # 男修
    assert v.gender == "男" and v.step == 0
    await v.children[1].callback(inter())                # 第 1 题 B
    assert v.answers == {0: "B"}


async def test_填写道号按钮_答完前被拒_答完后弹出表单(db):
    v, *_ = make_view()
    i = inter()
    await v.open_name_modal(i)
    assert "请先完成所有问题" in i.last

    await pick_gender(v)
    for _ in range(N):
        await answer(v)
    i = inter()
    await v.children[0].callback(i)
    assert isinstance(i.modal, CharacterNameModal)


async def test_表单提交会去掉首尾空白并交给finalize(db):
    v, *_ = make_view()
    got = {}

    async def fake_finalize(interaction, name):
        got["name"] = name
    v.finalize = fake_finalize
    m = CharacterNameModal(v)
    m.name._value = "  青玄  "
    await m.on_submit(inter())
    assert got["name"] == "青玄"


async def test_取消按钮(db):
    v, cog, _ = make_view()
    i = inter()
    await v.children[-1].callback(i)
    assert "已取消创建" in i.last and UID not in cog._creating and v._done


# --- 提交 ---------------------------------------------------------------------

async def full_view(db_unused=None):
    v, cog, ctx = make_view()
    await pick_gender(v)
    for _ in range(N):
        await answer(v)
    return v, cog


async def test_按钮提交_完整流程创建角色(db):
    v, cog = await full_view()
    msg = FakeMessage()
    v.message = msg
    i = inter()
    await v.finalize(i, "青玄")
    row = await _row(db)
    assert row.name == "青玄" and row.gender == "男"
    assert "创建完成" in i.last and UID not in cog._creating and v._done
    assert msg.edits[-1]["embed"].title == "✦ 青玄 ✦" and msg.edits[-1]["view"] is None


@pytest.mark.parametrize("name", ["", "x" * 17])
async def test_按钮提交_道号无效(db, name):
    v, cog = await full_view()
    i = inter()
    await v.finalize(i, name)
    assert "道号无效" in i.last and await _row(db) is None and not v._done


async def test_按钮提交_流程未完成(db):
    v, *_ = make_view()
    i = inter()
    await v.finalize(i, "名")
    assert "创建流程未完成" in i.last and await _row(db) is None


async def test_按钮提交_已有角色_提示并结束面板(db):
    v, cog = await full_view()                           # 答题期间还没有角色，提交前才被别处创建
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        s.add(make_player(D, UID))
        await s.commit()
    msg = FakeMessage()
    v.message = msg
    await v.finalize(inter(), "新名")
    assert "无需重复创建" in msg.edits[-1]["content"] and UID not in cog._creating and v._done


async def test_按钮提交_没有消息引用时也不崩(db):
    v, cog = await full_view()
    assert v.message is None
    await v.finalize(inter(), "青玄")
    assert (await _row(db)).name == "青玄"


# --- 超时 ---------------------------------------------------------------------

async def test_超时_编辑消息并释放占位():
    v, cog, _ = make_view()
    msg = FakeMessage()
    v.message = msg
    await v.on_timeout()
    assert msg.edits[-1]["content"] == "创建已超时取消。" and UID not in cog._creating and v._done


async def test_超时_没有消息也释放占位():
    v, cog, _ = make_view()
    await v.on_timeout()
    assert UID not in cog._creating


async def test_超时_编辑消息失败仍释放占位():
    v, cog, _ = make_view()

    class Bad:
        async def edit(self, **k):
            raise RuntimeError("消息被删了")
    v.message = Bad()
    with pytest.raises(RuntimeError):
        await v.on_timeout()
    assert UID not in cog._creating


# --- 文字输入监听 -------------------------------------------------------------

class ListenBot:
    """依次吐出预设消息；用完后抛 TimeoutError 让监听循环结束。"""

    def __init__(self, view_holder, contents, author_id=int(UID)):
        self.contents, self.author_id, self.holder = list(contents), author_id, view_holder

    async def wait_for(self, event, check=None, timeout=None):
        if not self.contents:
            raise asyncio.TimeoutError()
        c = self.contents.pop(0)
        if isinstance(c, BaseException):
            raise c
        m = SimpleNamespace(content=c, author=SimpleNamespace(id=self.author_id), channel=self.holder.message.channel)
        assert check(m)
        return m


def listener_view(contents, bot_cls=ListenBot):
    holder = SimpleNamespace(message=FakeMessage())
    bot = bot_cls(holder, contents)
    v, cog, _ = make_view(bot=bot)
    v.message = holder.message
    return v, cog


async def test_文字输入_性别与答题(db):
    v, _ = listener_view(["b", "A", "c", "z", "B"])
    await v._text_listener()
    assert v.gender == "女" and v.answers == {0: "A", 1: "C", 2: "B"} and v.step == 3
    assert len(v.message.edits) == 4                            # 性别 + 三次答题各刷新一次面板


async def test_文字输入_性别步骤只认A和B(db):
    v, _ = listener_view(["C", "hello", "A"])
    await v._text_listener()
    assert v.gender == "男" and v.step == 0


async def test_文字输入_道号步骤直接发送道号创建角色(db):
    v, cog = listener_view(["A"] + ["B"] * N + ["云游子"])
    await v._text_listener()
    row = await _row(db)
    assert row.name == "云游子" and v._done and UID not in cog._creating


async def test_文字输入_道号太长或为空不创建_可以继续发(db):
    v, _ = listener_view(["A"] + ["A"] * N + ["x" * 17, "   ", "青玄"])
    await v._text_listener()
    assert (await _row(db)).name == "青玄"


async def test_文字输入_监听器出错不会终止_按钮仍可用(db, monkeypatch):
    v, _ = listener_view(["A", "A"])
    calls = {"n": 0}
    real = v._advance_message

    async def flaky():
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("编辑消息失败")
        await real()
    v._advance_message = flaky
    real_sleep = asyncio.sleep
    monkeypatch.setattr(cc.asyncio, "sleep", lambda s: real_sleep(0))
    await v._text_listener()
    assert v.gender == "男" and v.answers == {0: "A"}


async def test_文字输入_面板结束后不再处理():
    v, _ = listener_view(["A"])
    v._done = True
    await v._text_listener()
    assert v.gender is None


async def test_文字输入_等待期间面板结束_收到的消息被丢弃():
    holder = SimpleNamespace(message=FakeMessage())

    class Late(ListenBot):
        async def wait_for(self, *a, **k):
            m = await super().wait_for(*a, **k)
            v._done = True
            return m
    v, cog, _ = make_view(bot=Late(holder, ["A"]))
    v.message = holder.message
    await v._text_listener()
    assert v.gender is None


async def test_文字输入_被取消时安静退出():
    v, _ = listener_view([asyncio.CancelledError()])
    await v._text_listener()


async def test_文字输入_消息尚未附加时等待(monkeypatch):
    v, cog, _ = make_view(bot=ListenBot(SimpleNamespace(message=FakeMessage()), []))
    sleeps = []

    async def fake_sleep(s):
        sleeps.append(s)
        v._done = True
    monkeypatch.setattr(cc.asyncio, "sleep", fake_sleep)
    await v._text_listener()
    assert sleeps == [0.2]


async def test_文字输入_只认本人_check拒绝别人(db):
    v, cog = listener_view([])
    seen = {}

    async def wf(event, check=None, timeout=None):
        seen["mine"] = check(SimpleNamespace(author=SimpleNamespace(id=int(UID)), channel=v.message.channel))
        seen["other"] = check(SimpleNamespace(author=SimpleNamespace(id=999), channel=v.message.channel))
        seen["elsewhere"] = check(SimpleNamespace(author=SimpleNamespace(id=int(UID)), channel=object()))
        raise asyncio.TimeoutError()
    cog.bot.wait_for = wf
    await v._text_listener()
    assert seen == {"mine": True, "other": False, "elsewhere": False}


@pytest.mark.parametrize("raw,expected", [("a", "A"), (" b ", "B"), ("C", "C"), ("D", None), ("", None), (None, None)])
def test_消息选项解析(raw, expected):
    v, *_ = make_view()
    assert v._msg_choice(raw) == expected


async def test_附加消息时启动监听_只启动一次():
    holder = SimpleNamespace(message=FakeMessage())
    v, cog, _ = make_view(bot=ListenBot(holder, []))
    msg = FakeMessage()
    v.attach_message(msg)
    first = v._text_task
    assert v.message is msg and first is not None
    v.attach_message(msg)
    assert v._text_task is first
    first.cancel()


async def test_刷新面板没有消息时不报错():
    v, *_ = make_view()
    await v._advance_message()


async def test_超时与取消会停掉文字监听任务():
    for how in ("timeout", "cancel"):
        v, *_ = make_view()
        v._text_task = asyncio.create_task(asyncio.sleep(3600))
        if how == "timeout":
            await v.on_timeout()
        else:
            await v.cancel(inter())
        await asyncio.sleep(0)
        assert v._text_task.cancelled(), how


async def test_面板已结束后到达的文字道号被忽略(db):
    v, cog = await full_view()
    v._done = True
    await v.finalize_from_message(None, "迟到")
    assert await _row(db) is None


@pytest.mark.parametrize("name", ["", "x" * 17])
async def test_文字道号无效被忽略(db, name):
    v, cog = await full_view()
    await v.finalize_from_message(None, name)
    assert await _row(db) is None and not v._done


async def test_文字道号时流程未完成被忽略(db):
    v, *_ = make_view()
    await v.finalize_from_message(None, "青玄")
    assert await _row(db) is None


async def test_文字道号时已有角色_结束面板(db):
    v, cog = await full_view()
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        s.add(make_player(D, UID))
        await s.commit()
    msg = FakeMessage()
    v.message = msg
    await v.finalize_from_message(None, "青玄")
    assert "无需重复创建" in msg.edits[-1]["content"] and UID not in cog._creating and v._done
