"""探险测试（cogs/explore.py）。

结构：
  A 探险次数的原子占用  B 次数上限与窗口  C 奖励结算的辅助  D `探险` 命令
  E 「继续探险」按钮    F 选项按钮         G 连点            H 重置探险

重点是 A 与 G：
- 探险次数曾是「先 `_check_explore_limit` 判断，再把计数写成绝对值」。
  两次点击几乎同时到达，都读到旧计数、都通过检查、写同一个值 —— 两次探险只占一次次数。
- 选项按钮曾是「先 defer，后 stop()」。defer 要走网络，两次点击会一起越过入口，奖励发两遍。
"""

import asyncio
import json
import time

import pytest

from cogs import explore as ex
from cogs.explore import (
    EXPLORE_LIMIT, EXPLORE_RESET_YEARS, ExploreCog, ExploreNextView, ExploreResultView, ExploreView,
)
from tests.conftest import make_player
from tests.discord_fakes import FakeContext, FakeInteraction, FakeUser
from utils.character import CAVE_EXPLORE_BONUS
from utils.player import get_player

UID = "1"


def _now_years():
    return time.time() / (2 * 3600)


async def _add_player(db, uid=UID, **fields):
    D = db["db_async"]
    p = make_player(D, uid, stones=100)
    for k, v in fields.items():
        setattr(p, k, v)
    async with D.AsyncSessionLocal() as s:
        s.add(p)
        await s.commit()


async def _row(db, uid=UID):
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        return await s.get(D.Player, uid)


async def _pd(uid=UID):
    return await get_player(uid)


@pytest.fixture
def cog():
    return ExploreCog(bot=None)


# 一个确定的两层事件：「拾取」直接出结果，「深入」进入下一层。
EVENT = {
    "title": "山间小径",
    "desc": "你在山间行走。",
    "choices": [
        {"label": "拾取", "condition": None, "flavor": "你捡到一些灵石。", "rewards": {"spirit_stones": 50}},
        {"label": "深入", "condition": None, "flavor": "", "rewards": {}, "next": {
            "desc": "洞内幽深。",
            "choices": [
                {"label": "取宝", "condition": None, "flavor": "你取走了宝物。", "rewards": {"fortune": 1}},
            ],
        }},
    ],
}


def _event(**overrides):
    return json.loads(json.dumps({**EVENT, **overrides}))


def _slow_defer(interaction):
    """让 defer 会让出事件循环 —— 模拟真实的网络延迟，这才是连点能钻进来的窗口。"""
    real = interaction.response.defer

    async def _slow(**kw):
        await asyncio.sleep(0.01)
        await real(**kw)
    interaction.response.defer = _slow
    return interaction


# =============================================================================
# A. 探险次数的原子占用
# =============================================================================

async def test_首次探险_计数为一_并记下窗口起点(db):
    await _add_player(db)
    before = _now_years()

    assert await ex._increment_explore(UID, await _pd()) is True

    p = await _row(db)
    assert p.explore_count == 1
    assert before <= p.explore_reset_year <= _now_years()


async def test_窗口内再探险_计数加一_窗口起点不变(db):
    start = _now_years() - 1
    await _add_player(db, explore_count=3, explore_reset_year=start)

    assert await ex._increment_explore(UID, await _pd()) is True

    p = await _row(db)
    assert p.explore_count == 4 and p.explore_reset_year == pytest.approx(start)


async def test_次数满了_拒绝且计数不动(db):
    start = _now_years() - 1
    await _add_player(db, explore_count=EXPLORE_LIMIT, explore_reset_year=start)

    assert await ex._increment_explore(UID, await _pd()) is False

    p = await _row(db)
    assert p.explore_count == EXPLORE_LIMIT and p.explore_reset_year == pytest.approx(start)


async def test_窗口过期_计数重置为一(db):
    await _add_player(db, explore_count=EXPLORE_LIMIT, explore_reset_year=_now_years() - EXPLORE_RESET_YEARS - 1)

    assert await ex._increment_explore(UID, await _pd()) is True

    p = await _row(db)
    assert p.explore_count == 1
    assert p.explore_reset_year == pytest.approx(_now_years(), abs=0.01)


async def test_洞府加成提高上限(db):
    await _add_player(db, cave="青云洞府", explore_count=EXPLORE_LIMIT, explore_reset_year=_now_years() - 1)
    assert await ex._increment_explore(UID, await _pd()) is True
    assert (await _row(db)).explore_count == EXPLORE_LIMIT + 1


async def test_角色不存在时拒绝(db):
    assert await ex._increment_explore("nobody", {"discord_id": "nobody", "current_city": "灵虚城", "cave": None}) is False


async def test_并发抢最后一个名额_只有一个成功(db):
    """B11：曾经两次都读到旧计数、都通过上限检查、写同一个值 —— 两次探险只占一次次数。"""
    await _add_player(db, explore_count=EXPLORE_LIMIT - 1, explore_reset_year=_now_years() - 1)
    player = await _pd()

    results = await asyncio.gather(*(ex._increment_explore(UID, player) for _ in range(2)))

    assert sorted(results) == [False, True]
    assert (await _row(db)).explore_count == EXPLORE_LIMIT


async def test_并发再多也不会超过上限(db):
    await _add_player(db, explore_count=0, explore_reset_year=_now_years() - 1)
    player = await _pd()

    results = await asyncio.gather(*(ex._increment_explore(UID, player) for _ in range(EXPLORE_LIMIT + 5)))

    assert sum(results) == EXPLORE_LIMIT
    assert (await _row(db)).explore_count == EXPLORE_LIMIT


# =============================================================================
# B. 次数上限与窗口
# =============================================================================

async def test_上限_基础值加洞府加成(db):
    await _add_player(db, cave="x")
    assert await ex._get_explore_limit(await _pd()) == EXPLORE_LIMIT + CAVE_EXPLORE_BONUS
    await _add_player(db, "2")
    assert await ex._get_explore_limit(await _pd("2")) == EXPLORE_LIMIT


async def test_检查上限_窗口内未满可以探险(db):
    await _add_player(db, explore_count=EXPLORE_LIMIT - 1, explore_reset_year=_now_years() - 1)
    assert await ex._check_explore_limit(await _pd()) == (True, "")


async def test_检查上限_满了给出剩余游戏年(db):
    await _add_player(db, explore_count=EXPLORE_LIMIT, explore_reset_year=_now_years() - 1)
    ok, msg = await ex._check_explore_limit(await _pd())
    assert ok is False and f"{EXPLORE_LIMIT}/{EXPLORE_LIMIT}" in msg and "游戏年" in msg


async def test_检查上限_窗口过期即使满了也可以(db):
    await _add_player(db, explore_count=EXPLORE_LIMIT, explore_reset_year=_now_years() - EXPLORE_RESET_YEARS - 1)
    assert (await ex._check_explore_limit(await _pd()))[0] is True


# =============================================================================
# C. 奖励结算的辅助
# =============================================================================

def test_条件判断():
    assert ex._check_condition({"soul": 5}, None) is True
    assert ex._check_condition({"soul": 5}, {"stat": "soul", "val": 5}) is True
    assert ex._check_condition({"soul": 4}, {"stat": "soul", "val": 5}) is False
    assert ex._check_condition({}, {"stat": "soul", "val": 1}) is False


def test_选结果_满足条件的优先_否则从无条件里随机_再否则取最后一个(monkeypatch):
    import random
    hi = {"tag": "hi", "condition": {"stat": "soul", "val": 8}}
    a = {"tag": "a", "condition": None}
    b = {"tag": "b", "condition": None}
    only_cond = [{"tag": "x", "condition": {"stat": "soul", "val": 8}}, {"tag": "y", "condition": {"stat": "soul", "val": 9}}]
    monkeypatch.setattr(random, "choice", lambda seq: seq[-1])

    assert ex._pick_choice_result([a, hi, b], {"soul": 8})["tag"] == "hi"
    assert ex._pick_choice_result([a, hi, b], {"soul": 1})["tag"] == "b"
    assert ex._pick_choice_result(only_cond, {"soul": 1})["tag"] == "y"


async def test_一次性丹药buff_探险稀有加成用掉就清(db):
    buffs = json.dumps({"explore_rare_bonus_once": {"value": 30}, "titles": ["甲"]})
    await _add_player(db, active_buffs=buffs)

    await ex._consume_explore_buffs(UID, await _pd(), {})

    left = json.loads((await _row(db)).active_buffs)
    assert "explore_rare_bonus_once" not in left and left["titles"] == ["甲"]


async def test_一次性灵石加成_按本次灵石奖励追加并清掉buff(db):
    buffs = json.dumps({"spirit_stones_bonus_once": {"value": 50}})
    await _add_player(db, spirit_stones=100, active_buffs=buffs)

    await ex._consume_explore_buffs(UID, await _pd(), {"spirit_stones": 200})

    p = await _row(db)
    assert p.spirit_stones == 100 + 100                        # 200 * 50%
    assert "spirit_stones_bonus_once" not in json.loads(p.active_buffs)


async def test_一次性灵石加成_本次没得灵石就不消耗(db):
    """记录现状：没拿到灵石的探险不会白白吃掉这份加成。"""
    buffs = json.dumps({"spirit_stones_bonus_once": {"value": 50}})
    await _add_player(db, spirit_stones=100, active_buffs=buffs)

    await ex._consume_explore_buffs(UID, await _pd(), {"fortune": 1})

    p = await _row(db)
    assert p.spirit_stones == 100 and "spirit_stones_bonus_once" in json.loads(p.active_buffs)


async def test_没有buff什么都不动(db):
    await _add_player(db, spirit_stones=100)
    await ex._consume_explore_buffs(UID, await _pd(), {"spirit_stones": 200})
    assert (await _row(db)).spirit_stones == 100


# =============================================================================
# D. `探险` 命令
# =============================================================================

@pytest.fixture
def fixed_event(monkeypatch):
    monkeypatch.setattr(ex, "get_event_pool", lambda player: _event())
    monkeypatch.setattr(ex, "_try_adventure_chain", _no_chain)


async def _no_chain(player):
    return None, -1


async def _explore(cog, uid=1):
    ctx = FakeContext(user_id=uid)
    await cog.explore.callback(cog, ctx)
    return ctx


async def test_命令_没有角色(db, cog):
    ctx = await _explore(cog)
    assert ctx.said("尚未踏入修仙之路")


async def test_命令_已坐化(db, cog):
    await _add_player(db, is_dead=True)
    assert (await _explore(cog)).said("已坐化")


@pytest.mark.parametrize("fields,phrase", [
    ({"cultivating_until": time.time() + 9999}, "正在闭关"),
    ({"gathering_until": time.time() + 9999, "gathering_type": "采药"}, "正在采集"),
    ({"active_quest": json.dumps({"title": "护送商队"})}, "护送商队"),
])
async def test_命令_忙着别的事不能探险(db, cog, fields, phrase):
    await _add_player(db, **fields)
    ctx = await _explore(cog)
    assert ctx.said(phrase) and ctx.last.view is None
    assert (await _row(db)).explore_count == 0                 # 被拒绝不占次数


async def test_命令_次数用尽(db, cog):
    await _add_player(db, explore_count=EXPLORE_LIMIT, explore_reset_year=_now_years() - 1)
    ctx = await _explore(cog)
    assert ctx.said("探险次数已用尽") and ctx.last.view is None
    assert (await _row(db)).explore_count == EXPLORE_LIMIT


async def test_命令_成功_占一次次数并给出事件和选项(db, cog, fixed_event):
    await _add_player(db)

    ctx = await _explore(cog)

    assert (await _row(db)).explore_count == 1
    msg = ctx.last
    assert "山间小径" in msg.embed.title and f"1/{EXPLORE_LIMIT}" in msg.embed.footer.text
    assert isinstance(msg.view, ExploreView)
    assert [b.label for b in msg.view.children] == ["拾取", "深入"]


async def test_命令_触发奇遇时给出章节面板(db, cog, monkeypatch):
    from utils.events.adventure_chains import ALL_CHAINS
    from utils.views.adventure_chain import ChainStageView
    fox = next(c for c in ALL_CHAINS if c["id"] == "spirit_fox")

    async def _fox(player):
        return fox, 0
    monkeypatch.setattr(ex, "_try_adventure_chain", _fox)
    await _add_player(db)

    ctx = await _explore(cog)

    assert isinstance(ctx.last.view, ChainStageView) and "奇遇触发" in ctx.last.embed.footer.text
    assert (await _row(db)).explore_count == 1                 # 奇遇也占次数


async def test_命令_占次数失败_不发事件(db, cog, fixed_event, monkeypatch):
    """检查通过后、占用前名额被别人抢走：不能照样发一个事件。"""
    async def _lost(*a, **k):
        return False
    monkeypatch.setattr(ex, "_increment_explore", _lost)
    await _add_player(db)

    ctx = await _explore(cog)

    assert ctx.said("探险次数已用尽，请稍后再试") and ctx.last.view is None


# =============================================================================
# E. 「继续探险」按钮
# =============================================================================

def _result_view(uid=1):
    return ExploreResultView(FakeUser(id=uid), ExploreCog(bot=None))


async def test_继续探险_占一次次数并发出新事件(db, fixed_event):
    await _add_player(db, explore_count=2, explore_reset_year=_now_years() - 1)
    view = _result_view()
    it = FakeInteraction(user_id=1)

    await view.continue_explore.callback(it)

    assert (await _row(db)).explore_count == 3
    assert isinstance(it.last.view, ExploreView) and f"3/{EXPLORE_LIMIT}" in it.last.embed.footer.text
    assert not view.is_finished()                              # 结果面板仍可点「主菜单」


@pytest.mark.parametrize("fields,phrase", [
    ({"is_dead": True}, "无法继续探险"),
    ({"cultivating_until": time.time() + 9999}, "正在闭关"),
    ({"gathering_until": time.time() + 9999, "gathering_type": "采药"}, "正在采集"),
    ({"active_quest": json.dumps({"title": "护送商队"})}, "护送商队"),
    ({"explore_count": EXPLORE_LIMIT, "explore_reset_year": time.time() / 7200 - 1}, "探险次数已用尽"),
])
async def test_继续探险_被拒绝的情形(db, fixed_event, fields, phrase):
    await _add_player(db, **fields)
    before = (await _row(db)).explore_count
    it = FakeInteraction(user_id=1)

    await _result_view().continue_explore.callback(it)

    assert it.said(phrase) and it.last.view is None
    assert (await _row(db)).explore_count == before


async def test_继续探险_没有角色(db, fixed_event):
    it = FakeInteraction(user_id=1)
    await _result_view().continue_explore.callback(it)
    assert it.said("无法继续探险")


async def test_别人点不动我的探险面板(db):
    intruder = FakeInteraction(user_id=999)
    assert await _result_view().interaction_check(intruder) is False
    assert intruder.said("这不是你的探险")


async def test_连点继续探险_只剩一个名额时只发一个事件(db, fixed_event):
    """B11：曾经两次点击都通过上限检查、写同一个计数 —— 两次探险只占一次次数，白送一次。"""
    await _add_player(db, explore_count=EXPLORE_LIMIT - 1, explore_reset_year=_now_years() - 1)
    view = _result_view()
    its = [_slow_defer(FakeInteraction(user_id=1)) for _ in range(2)]

    await asyncio.gather(*(view.continue_explore.callback(it) for it in its))

    events = [m for it in its for m in it.messages if isinstance(m.view, ExploreView)]
    refused = [m for it in its for m in it.messages if "探险次数已用尽" in m]
    assert len(events) == 1 and len(refused) == 1
    assert (await _row(db)).explore_count == EXPLORE_LIMIT


async def test_连点继续探险_名额充足时两次都算(db, fixed_event):
    await _add_player(db, explore_count=0, explore_reset_year=_now_years() - 1)
    view = _result_view()
    its = [_slow_defer(FakeInteraction(user_id=1)) for _ in range(2)]

    await asyncio.gather(*(view.continue_explore.callback(it) for it in its))

    assert (await _row(db)).explore_count == 2                 # 各占一次，不多不少


# =============================================================================
# F. 选项按钮
# =============================================================================

def _explore_view(event=None, player=None, uid=1):
    return ExploreView(FakeUser(id=uid), event or _event(), player or {"discord_id": UID}, ExploreCog(bot=None))


def _btn(view, label):
    return next(b for b in view.children if b.label == label)


def test_按钮按标签去重(db=None):
    event = _event()
    event["choices"].append({"label": "拾取", "condition": {"stat": "soul", "val": 9}, "flavor": "", "rewards": {}})
    assert [b.label for b in _explore_view(event).children] == ["拾取", "深入"]


async def test_别人点不动选项面板(db):
    intruder = FakeInteraction(user_id=999)
    assert await _explore_view().interaction_check(intruder) is False
    assert intruder.said("这不是你的探险")


async def test_选项直接出结果_奖励入账并给出结果面板(db):
    await _add_player(db, spirit_stones=100)
    view = _explore_view()
    it = FakeInteraction(user_id=1)

    await _btn(view, "拾取").callback(it)

    assert (await _row(db)).spirit_stones == 150
    assert "你捡到一些灵石" in it.last.embed.description and "结果" in it.last.embed.title
    assert isinstance(it.last.view, ExploreResultView)
    assert view.is_finished() and all(b.disabled for b in view.children)


async def test_选项通往下一层_此时还没有奖励(db):
    await _add_player(db, fortune=5)
    view = _explore_view()
    it = FakeInteraction(user_id=1)

    await _btn(view, "深入").callback(it)

    assert (await _row(db)).fortune == 5
    assert "洞内幽深" in it.last.embed.description and isinstance(it.last.view, ExploreNextView)


async def test_下一层选项_奖励入账(db):
    await _add_player(db, fortune=5)
    nxt = ExploreNextView(FakeUser(id=1), _event(), _event()["choices"][1]["next"], {"discord_id": UID}, ExploreCog(bot=None))
    it = FakeInteraction(user_id=1)

    await _btn(nxt, "取宝").callback(it)

    assert (await _row(db)).fortune == 6
    assert "你取走了宝物" in it.last.embed.description and isinstance(it.last.view, ExploreResultView)
    assert nxt.is_finished()


async def test_同名选项按属性择优(db):
    event = _event(choices=[
        {"label": "参悟", "condition": {"stat": "soul", "val": 8}, "flavor": "一眼看穿", "rewards": {}},
        {"label": "参悟", "condition": None, "flavor": "勉强看懂", "rewards": {}},
    ])
    await _add_player(db)

    strong, weak = FakeInteraction(user_id=1), FakeInteraction(user_id=1)
    await _btn(_explore_view(event, {"discord_id": UID, "soul": 8}), "参悟").callback(strong)
    await _btn(_explore_view(event, {"discord_id": UID, "soul": 7}), "参悟").callback(weak)

    assert "一眼看穿" in strong.last.embed.description and "勉强看懂" in weak.last.embed.description


async def test_没有文案时显示平安无事(db):
    await _add_player(db)
    event = _event(choices=[{"label": "路过", "condition": None, "flavor": "", "rewards": {}}])
    it = FakeInteraction(user_id=1)
    await _btn(_explore_view(event), "路过").callback(it)
    assert "平安无事" in it.last.embed.description


async def test_装备掉落_结果里展示获得的装备(db):
    """B6/B7 的端到端：此前『装备掉落』这一支一跑就崩，玩家既看不到装备也看不到结果。"""
    await _add_player(db, realm="筑基期3层")
    event = _event(choices=[{"label": "探囊", "condition": None, "flavor": "你有所得。",
                             "rewards": {"equipment": {"quality": "精良", "chance": 1.0}, "fortune": 1}}])
    it = FakeInteraction(user_id=1)

    await _btn(_explore_view(event), "探囊").callback(it)

    assert "获得装备" in it.last.embed.description and "精良" in it.last.embed.description
    assert (await _row(db)).fortune == 6                       # 装备之后的奖励也没丢


async def test_一次性灵石加成在选项结算时生效(db):
    buffs = json.dumps({"spirit_stones_bonus_once": {"value": 100}})
    await _add_player(db, spirit_stones=100, active_buffs=buffs)
    player = await _pd()
    it = FakeInteraction(user_id=1)

    await _btn(_explore_view(player=player), "拾取").callback(it)

    assert (await _row(db)).spirit_stones == 100 + 50 + 50      # 奖励 50 + 加成 100% 再 50
    assert "spirit_stones_bonus_once" not in json.loads((await _row(db)).active_buffs)


# =============================================================================
# G. 连点
# =============================================================================

async def test_连点选项_奖励只发一次(db):
    """B11：曾经先 defer 后 stop()，defer 要走网络，两次点击会一起越过入口，奖励发两遍。"""
    await _add_player(db, spirit_stones=100)
    view = _explore_view()
    btn = _btn(view, "拾取")
    its = [_slow_defer(FakeInteraction(user_id=1)) for _ in range(2)]

    await asyncio.gather(*(btn.callback(it) for it in its))

    assert (await _row(db)).spirit_stones == 150                # +50，不是 +100
    results = [m for it in its for m in it.messages if m.embed is not None]
    refused = [m for it in its for m in it.messages if m.ephemeral and "已处理" in m]
    assert len(results) == 1 and len(refused) == 1


async def test_连点下一层选项_奖励只发一次(db):
    await _add_player(db, fortune=5)
    nxt = ExploreNextView(FakeUser(id=1), _event(), _event()["choices"][1]["next"], {"discord_id": UID}, ExploreCog(bot=None))
    btn = _btn(nxt, "取宝")
    its = [_slow_defer(FakeInteraction(user_id=1)) for _ in range(2)]

    await asyncio.gather(*(btn.callback(it) for it in its))

    assert (await _row(db)).fortune == 6
    assert len([m for it in its for m in it.messages if m.embed is not None]) == 1


async def test_点过之后再点_得到已处理而不是再发一遍(db):
    await _add_player(db, spirit_stones=100)
    view = _explore_view()
    btn = _btn(view, "拾取")
    await btn.callback(FakeInteraction(user_id=1))
    again = FakeInteraction(user_id=1)

    await btn.callback(again)

    assert again.said("已处理") and (await _row(db)).spirit_stones == 150


# =============================================================================
# H. 重置探险
# =============================================================================

async def test_重置探险_非主人无事发生(db, cog, monkeypatch):
    monkeypatch.setattr(ex, "is_master", lambda uid: False)
    await _add_player(db, explore_count=5, explore_reset_year=3.0)
    ctx = FakeContext(user_id=1)

    await cog.reset_explore.callback(cog, ctx)

    assert ctx.messages == [] and (await _row(db)).explore_count == 5


async def test_重置探险_主人可以重置自己或指定玩家(db, cog, monkeypatch):
    monkeypatch.setattr(ex, "is_master", lambda uid: True)
    await _add_player(db, "1", explore_count=5, explore_reset_year=3.0)
    await _add_player(db, "2", explore_count=7, explore_reset_year=4.0)

    ctx = FakeContext(user_id=1)
    await cog.reset_explore.callback(cog, ctx)
    assert ctx.said("已重置") and (await _row(db, "1")).explore_count == 0 and (await _row(db, "2")).explore_count == 7

    await cog.reset_explore.callback(cog, ctx, "2")
    p = await _row(db, "2")
    assert (p.explore_count, p.explore_reset_year) == (0, 0)


async def test_重置探险_目标不存在也不报错(db, cog, monkeypatch):
    monkeypatch.setattr(ex, "is_master", lambda uid: True)
    ctx = FakeContext(user_id=1)
    await cog.reset_explore.callback(cog, ctx, "nobody")
    assert ctx.said("用户ID: nobody")
