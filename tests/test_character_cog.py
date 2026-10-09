"""角色 cog（cogs/character.py）与按钮式创建面板的提交（utils/views/character_create.py）。

B30 —— `解散队伍` 命令调用 `utils.views.party.disband_party(uid, bot)`，但那个名字其实是
  `utils.party.disband_party(uid)`（只收一个参数、返回元组）；带 DM 通知的是 `disband_party_func`。
  结果：这个命令每次都 TypeError，队长永远解散不了队伍。
B31 —— 文字创建（cog）与按钮创建（`_commit_character`）把同一大段『新建 / 轮回重置』逻辑各抄了一份，
  轮回加成公式又抄了三份；改一处忘另一处就会出现两种创建方式结果不同。现在共用 `utils/character_create_logic.py`。
B32 —— 创建提交没有『已存在』保护：同一个玩家同时走完文字和按钮两条路（或两次点击），
  两次提交都越过 `existing` 检查，后一个新增同主键直接 IntegrityError。
"""

import asyncio
import json
from types import SimpleNamespace

import pytest

from cogs.character import CharacterCog
from tests.conftest import make_player
from tests.discord_fakes import FakeContext, FakeInteraction
from utils import death_rebirth_logic as dr
from utils.character import QUESTIONS, REALM_LIFESPAN
from utils.views.character_create import CharacterCreateView

UID = "1001"


class ScriptedBot:
    """`wait_for("message")` 依次吐出预设的输入；放进 TimeoutError 实例就模拟超时。"""

    def __init__(self, ctx=None, inputs=()):
        self.ctx, self.inputs = ctx, list(inputs)
        self.sent_dm = []

    async def wait_for(self, event, check=None, timeout=None):
        item = self.inputs.pop(0)
        if isinstance(item, BaseException):
            raise item
        msg = SimpleNamespace(content=item, author=self.ctx.author, channel=self.ctx.channel)
        assert check is None or check(msg), "输入没通过 check（作者 / 频道不对）"
        return msg

    async def fetch_user(self, uid):
        bot = self

        class U:
            async def send(self_inner, text):
                bot.sent_dm.append((uid, text))
        return U()


def flow(name="青玄", gender="A", answer="A"):
    return [gender] + [answer] * len(QUESTIONS) + [name]


def make_cog(ctx, inputs=()):
    return CharacterCog(ScriptedBot(ctx, inputs))


async def _row(db, uid=UID):
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        return await s.get(D.Player, uid)


async def _add(db, uid=UID, **fields):
    D = db["db_async"]
    p = make_player(D, uid, stones=0)
    p.name = f"旧{uid}"
    for k, v in fields.items():
        setattr(p, k, v)
    async with D.AsyncSessionLocal() as s:
        s.add(p)
        await s.commit()


def ctx(uid=UID):
    return FakeContext(user_id=uid)


# --- 轮回加成公式 -------------------------------------------------------------

@pytest.mark.parametrize("rebirth_count", [0, 1, 3])
def test_轮回加成_cog与逻辑层同一公式(rebirth_count):
    p = {k: 15 for k in ("comprehension", "physique", "fortune", "bone", "soul")}
    p["rebirth_count"] = rebirth_count
    assert CharacterCog(None)._calc_rebirth_bonus(p) == dr.calculate_rebirth_bonus(p)


# --- 文字创建流程 -------------------------------------------------------------

async def test_文字创建_新玩家(db):
    c = ctx()
    cog = make_cog(c, flow("青玄", "B"))
    await cog._create_character_text(c)
    row = await _row(db)
    assert row.name == "青玄" and row.gender == "女"
    assert row.lifespan == row.lifespan_max == REALM_LIFESPAN["炼气期"] and row.realm == "炼气期1层"
    assert row.spirit_root and row.spirit_root_type and row.current_city
    assert "青玄" in c.last.embed.title and "天地感应" in c.last.content


async def test_文字创建_属性由答案决定(db):
    from utils.character import calc_stats
    c = ctx()
    cog = make_cog(c, flow(answer="B"))
    await cog._create_character_text(c)
    stats = calc_stats({i: "B" for i in range(len(QUESTIONS))})
    row = await _row(db)
    assert (row.comprehension, row.physique, row.fortune, row.bone, row.soul, row.spirit_stones) == (
        stats["comprehension"], stats["physique"], stats["fortune"], stats["bone"], stats["soul"], stats["spirit_stones"])


@pytest.mark.parametrize("inputs,msg", [
    (["C"], "输入有误"),                                       # 性别只有 A/B
    (["A", "Z"], "输入有误"),                                  # 第一题选项不存在
    (["A"] + ["A"] * len(QUESTIONS) + [""], "道号无效"),
    (["A"] + ["A"] * len(QUESTIONS) + ["x" * 17], "道号无效"),
])
async def test_文字创建_输入非法时取消且不写库(db, inputs, msg):
    c = ctx()
    cog = make_cog(c, inputs)
    await cog._create_character_text(c)
    assert c.said(msg) and await _row(db) is None


async def test_文字创建_超时取消(db):
    c = ctx()
    cog = make_cog(c, ["A", asyncio.TimeoutError()])
    await cog._create_character_text(c)
    assert c.said("响应超时") and await _row(db) is None


async def test_文字创建_道号16字可以_带空白会去掉(db):
    c = ctx()
    await make_cog(c, flow("  " + "道" * 16 + "  ")).__class__._create_character_text(make_cog(c, flow("  " + "道" * 16 + "  ")), c)
    assert (await _row(db)).name == "道" * 16


DEAD = dict(is_dead=1, sect="仙葬谷", techniques='["基础吐纳"]', cultivation=999, realm="筑基期3层",
            spirit_stones=77, active_quest='{"id":"q"}', quest_due=123.0, reputation=40,
            comprehension=15, physique=15, fortune=15, bone=15, soul=15, dual_partner_id="9",
            gathering_until=9e9, gathering_type="采药", explore_count=5, cave="x")


async def test_文字创建_已坐化的玩家轮回_重置状态(db):
    await _add(db, **DEAD)
    c = ctx()
    await make_cog(c, flow("新名")).__class__._create_character_text(make_cog(c, flow("新名")), c)
    row = await _row(db)
    assert row.name == "新名" and not row.is_dead and row.sect is None and row.techniques == "[]"
    assert row.cultivation == 0 and row.realm == "炼气期1层" and row.reputation == 0
    assert row.active_quest is None and row.quest_due is None and row.dual_partner_id is None
    assert row.gathering_until is None and row.gathering_type is None and row.cave is None
    assert row.explore_count == 0 and row.is_virgin


async def test_文字创建_仙葬谷轮回继承属性(db):
    await _add(db, **DEAD)
    c = ctx()
    cog = make_cog(c, flow(answer="A"))
    await cog._create_character_text(c)
    from utils.character import calc_stats
    base = calc_stats({i: "A" for i in range(len(QUESTIONS))})
    row = await _row(db)
    assert row.comprehension == base["comprehension"] + 3                       # (15-5)*0.3
    assert any(f.name == "✨ 轮回感悟" for f in c.last.embed.fields)


async def test_文字创建_没有轮回资格的坐化玩家不继承(db):
    await _add(db, **{**DEAD, "sect": None})
    c = ctx()
    cog = make_cog(c, flow(answer="A"))
    await cog._create_character_text(c)
    from utils.character import calc_stats
    base = calc_stats({i: "A" for i in range(len(QUESTIONS))})
    assert (await _row(db)).comprehension == base["comprehension"]
    assert not any(f.name == "✨ 轮回感悟" for f in c.last.embed.fields)


async def test_文字创建_巴红尘持有者也继承(db):
    await _add(db, **{**DEAD, "sect": None, "has_bahongchen": True})
    c = ctx()
    cog = make_cog(c, flow(answer="A"))
    await cog._create_character_text(c)
    assert any(f.name == "✨ 轮回感悟" for f in c.last.embed.fields)


# --- 创建角色命令 -------------------------------------------------------------

async def test_创建角色_已有存活角色_拒绝(db):
    await _add(db)
    c = ctx()
    cog = make_cog(c)
    await cog.create_character.callback(cog, c)
    assert c.said("无需重新创建") and not cog._creating


async def test_创建角色_正在创建中_拒绝(db):
    c = ctx()
    cog = make_cog(c)
    cog._creating.add(UID)
    await cog.create_character.callback(cog, c)
    assert c.said("正在创建中")


@pytest.mark.parametrize("mode", ["文本", "text", "T", " msg "])
async def test_创建角色_文本模式_走文字流程_结束后释放(db, mode):
    c = ctx()
    cog = make_cog(c, flow())
    await cog.create_character.callback(cog, c, mode)
    assert (await _row(db)) is not None and UID not in cog._creating


async def test_创建角色_文本模式出错也会释放占位(db):
    c = ctx()
    cog = make_cog(c, [RuntimeError("网络断了")])
    with pytest.raises(RuntimeError):
        await cog.create_character.callback(cog, c, "文本")
    assert UID not in cog._creating


async def test_创建角色_按钮模式_发出面板_占位由面板释放(db):
    c = ctx()
    cog = make_cog(c)
    await cog.create_character.callback(cog, c)
    view = c.last.view
    assert isinstance(view, CharacterCreateView) and UID in cog._creating
    view._text_task.cancel()
    view.stop()


async def test_创建角色_按钮模式_发消息失败时释放占位(db):
    c = ctx()
    cog = make_cog(c)

    async def boom(*a, **k):
        raise RuntimeError("发不出去")
    c.send = boom
    with pytest.raises(RuntimeError):
        await cog.create_character.callback(cog, c)
    assert UID not in cog._creating


async def test_创建角色_坐化后可以重新创建(db):
    await _add(db, is_dead=1)
    c = ctx()
    cog = make_cog(c, flow("重生"))
    await cog.create_character.callback(cog, c, "文本")
    assert (await _row(db)).name == "重生" and not (await _row(db)).is_dead


# --- 按钮面板的提交与文字流程一致 ---------------------------------------------

def view_for(cog, c, gender="男"):
    v = CharacterCreateView(c.author, cog)
    v.gender = gender
    v.answers = {i: "A" for i in range(len(QUESTIONS))}
    v.step = len(QUESTIONS)
    return v


async def test_按钮提交_新玩家(db):
    c = ctx()
    cog = make_cog(c)
    v = view_for(cog, c)
    embed = await v._commit_character("按钮道号")
    row = await _row(db)
    assert row.name == "按钮道号" and row.gender == "男" and embed.title


async def test_按钮提交与文字流程_坐化重置的字段一致(db):
    """B31：两份拷贝一旦漂移，选哪种创建方式会得到不同的角色。"""
    from utils.db_async import Player
    await _add(db, "2001", **DEAD)
    await _add(db, "2002", **DEAD)
    ca, cb = ctx("2001"), ctx("2002")

    cog_a = make_cog(ca, flow("同名", "A", "A"))
    await cog_a._create_character_text(ca)
    cog_b = make_cog(cb)
    v = view_for(cog_b, cb, "男")
    await v._commit_character("同名")

    a, b = await _row(db, "2001"), await _row(db, "2002")
    skip = {"discord_id", "spirit_root", "spirit_root_type", "current_city", "created_at", "last_active"}
    diff = {c.key: (getattr(a, c.key), getattr(b, c.key)) for c in Player.__table__.columns
            if c.key not in skip and getattr(a, c.key) != getattr(b, c.key)}
    assert not diff, diff


async def test_按钮_已有存活角色时不重复创建(db):
    await _add(db)
    c = ctx()
    cog = make_cog(c)
    v = view_for(cog, c)
    i = FakeInteraction(UID)
    await v.finalize(i, "新名")
    assert (await _row(db)).name == f"旧{UID}"


async def test_按钮_同时提交两次只创建一次(db):
    """B32：以前两次提交都越过『已存在』检查，后一个新增同主键 IntegrityError。"""
    c = ctx()
    cog = make_cog(c)
    v1, v2 = view_for(cog, c), view_for(cog, c)
    r = await asyncio.gather(v1.finalize(FakeInteraction(UID), "甲"), v2.finalize(FakeInteraction(UID), "乙"),
                             return_exceptions=True)
    assert not [x for x in r if isinstance(x, BaseException)], r
    assert (await _row(db)).name in ("甲", "乙")


async def test_文字与按钮同时提交_只创建一次(db):
    c = ctx()
    cog = make_cog(c, flow("文字名"))
    v = view_for(cog, c)
    r = await asyncio.gather(cog._create_character_text(c), v.finalize(FakeInteraction(UID), "按钮名"),
                             return_exceptions=True)
    assert not [x for x in r if isinstance(x, BaseException)], r


async def test_按钮_信息不全时不提交(db):
    c = ctx()
    cog = make_cog(c)
    v = CharacterCreateView(c.author, cog)
    i = FakeInteraction(UID)
    await v.finalize(i, "名")
    assert "创建流程未完成" in i.last and await _row(db) is None
    v.gender, v.answers = "男", {i_: "A" for i_ in range(len(QUESTIONS))}
    i = FakeInteraction(UID)
    await v.finalize(i, "x" * 17)
    assert "道号无效" in i.last


# --- 解散队伍 / help ----------------------------------------------------------

async def _party(db, leader=UID, members=("1002", "1003")):
    from sqlalchemy import text
    await _add(db, leader, party_id="P1")
    for m in members:
        await _add(db, m, party_id="P1")
    async with db["db_async"].AsyncSessionLocal() as s:
        await s.execute(text("INSERT INTO parties (party_id, leader_id, city, created_at) VALUES ('P1', :u, '灵虚城', 0)"),
                        {"u": leader})
        await s.commit()


async def test_解散队伍_队长解散_成员退出并收到私信(db):
    """B30：以前这里直接 TypeError，队长永远解散不了。"""
    await _party(db)
    c = ctx()
    cog = make_cog(c)
    await cog.disband_party.callback(cog, c)
    assert c.said("队伍已解散")
    for u in (UID, "1002", "1003"):
        assert (await _row(db, u)).party_id is None
    assert sorted(u for u, _ in cog.bot.sent_dm) == [1002, 1003]                  # 队长自己不发


async def test_解散队伍_非队长不能解散(db):
    await _party(db)
    c = ctx("1002")
    cog = make_cog(c)
    await cog.disband_party.callback(cog, c)
    assert c.said("只有队长") and (await _row(db, UID)).party_id == "P1"


async def test_解散队伍_不在队伍中(db):
    await _add(db)
    c = ctx()
    cog = make_cog(c)
    await cog.disband_party.callback(cog, c)
    assert c.said("不在任何队伍中")


async def test_解散队伍_私信失败不影响解散(db):
    await _party(db)
    c = ctx()
    cog = make_cog(c)

    async def closed(uid):
        raise RuntimeError("对方关了私信")
    cog.bot.fetch_user = closed
    await cog.disband_party.callback(cog, c)
    assert c.said("队伍已解散") and (await _row(db, "1002")).party_id is None


async def test_help_没有角色(db):
    c = ctx()
    cog = make_cog(c)
    await cog.help_cmd.callback(cog, c)
    assert c.last.embed.fields and "双修系统" not in c.last.embed.description


@pytest.mark.parametrize("techs", [["双修功法"], [{"name": "双修功法"}]])
async def test_help_有双修功法时显示双修说明(db, techs):
    await _add(db, techniques=json.dumps(techs, ensure_ascii=False))
    c = ctx()
    cog = make_cog(c)
    await cog.help_cmd.callback(cog, c)
    assert "双修系统" in c.last.embed.description


async def test_help_没有双修功法(db):
    await _add(db, techniques=json.dumps(["基础吐纳"], ensure_ascii=False))
    c = ctx()
    cog = make_cog(c)
    await cog.help_cmd.callback(cog, c)
    assert "双修系统" not in c.last.embed.description


# --- 共用落库逻辑 -------------------------------------------------------------

async def test_落库_存活玩家返回None_且不改任何东西(db):
    from utils.character_create_logic import commit_character
    await _add(db, spirit_stones=5)
    assert await commit_character(UID, "新", "男", {0: "A"}) is None
    row = await _row(db)
    assert row.name == f"旧{UID}" and row.spirit_stones == 5


@pytest.mark.parametrize("dead", [False, True])
async def test_落库_并发提交只有一个成功(db, dead):
    from utils.character_create_logic import commit_character
    if dead:
        await _add(db, is_dead=1)
    answers = {i: "A" for i in range(len(QUESTIONS))}
    results = await asyncio.gather(*[commit_character(UID, f"名{i}", "男", answers) for i in range(6)],
                                   return_exceptions=True)
    assert not [r for r in results if isinstance(r, BaseException)], results
    assert len([r for r in results if r]) == 1
    row = await _row(db)
    assert row.name == next(r["name"] for r in results if r) and not row.is_dead


async def test_落库_新玩家返回摘要(db):
    from utils.character_create_logic import commit_character
    r = await commit_character(UID, "道号", "女", {i: "A" for i in range(len(QUESTIONS))})
    assert r["name"] == "道号" and r["gender"] == "女" and r["rebirth_bonus"] == {}
    assert r["lifespan"] == REALM_LIFESPAN["炼气期"] and r["starting_city"]


async def test_落库_撞上并发插入时返回None而不是抛异常(db, monkeypatch):
    """另一次提交在我们检查之后、提交之前插入了同一个玩家。"""
    from sqlalchemy.ext.asyncio import AsyncSession
    from utils import character_create_logic as m
    real_commit = AsyncSession.commit
    calls = {"n": 0}

    async def racing_commit(self):
        if calls["n"] == 0:
            calls["n"] += 1
            async with db["db_async"].AsyncSessionLocal() as other:
                other.add(make_player(db["db_async"], UID, stones=0))
                await real_commit(other)
        return await real_commit(self)
    monkeypatch.setattr(AsyncSession, "commit", racing_commit)
    assert await m.commit_character(UID, "晚到", "男", {i: "A" for i in range(len(QUESTIONS))}) is None


async def test_文字创建_落库发现已存在时提示而不是崩(db, monkeypatch):
    c = ctx()
    cog = make_cog(c, flow())

    async def lost(*a, **k):
        return None
    monkeypatch.setattr("cogs.character.commit_character", lost)
    await cog._create_character_text(c)
    assert c.said("无需重新创建")


async def test_按钮_提交被抢先时提示已创建并释放占位(db, monkeypatch):
    async def lost(*a, **k):
        return None
    monkeypatch.setattr("utils.views.character_create.commit_character", lost)
    c = ctx()
    cog = make_cog(c)
    cog._creating.add(UID)
    v = view_for(cog, c)
    edits = []
    v.message = SimpleNamespace(edit=lambda **k: _rec(edits, k))
    i = FakeInteraction(UID)
    await v.finalize(i, "名")
    assert "你已创建角色" in i.last and UID not in cog._creating
    assert edits and "无需重复创建" in edits[0]["content"]


async def test_文字消息提交被抢先时同样处理(db, monkeypatch):
    async def lost(*a, **k):
        return None
    monkeypatch.setattr("utils.views.character_create.commit_character", lost)
    c = ctx()
    cog = make_cog(c)
    cog._creating.add(UID)
    v = view_for(cog, c)
    edits = []
    v.message = SimpleNamespace(edit=lambda **k: _rec(edits, k))
    await v.finalize_from_message(None, "名")
    assert UID not in cog._creating and v._done and "无需重复创建" in edits[0]["content"]


async def _rec(lst, k):
    lst.append(k)


async def test_按钮_取消与超时都会释放占位(db):
    c = ctx()
    cog = make_cog(c)
    cog._creating.add(UID)
    v = view_for(cog, c)
    await v.cancel(FakeInteraction(UID))
    assert UID not in cog._creating and v._done

    cog._creating.add(UID)
    v2 = view_for(cog, c)
    await v2.on_timeout()
    assert UID not in cog._creating


async def test_落库_真正的约束错误不会被当成已被抢先(db):
    """以前任何 IntegrityError 都返回 None（『你已创建角色』），连缺性别这种真错误也被吞了。"""
    from sqlalchemy.exc import IntegrityError
    from utils.character_create_logic import commit_character
    with pytest.raises(IntegrityError):
        await commit_character(UID, "名", None, {i: "A" for i in range(len(QUESTIONS))})
    assert await _row(db) is None
