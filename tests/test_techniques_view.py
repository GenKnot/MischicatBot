"""功法面板（utils/views/techniques.py）：列表、属性、装备 / 卸下、修炼、学习。

B57 —— 学习功法书时『自动装备』的上限写死成 5，而真正的功法栏位随境界增加（筑基 7、结丹 9、元婴 12 …）：
  高境界玩家已装 5 本时学到新书不会自动装备，还提示『未装备（已满5本）』，其实栏位没满。
B58 —— `TrainConfirmView.confirm`（确认修炼功法 = 进入闭关）只检查了『正在闭关』：
  已坐化的玩家、正在采集的玩家、有进行中任务的玩家（旧面板）都能点确认，同时处在两种忙碌状态里；
  闭关的检查也只在读库之后，写入的 UPDATE 里没有这些条件。现在统一写进 WHERE。
"""

import asyncio
import json
import time

import pytest

from tests.conftest import make_player
from tests.discord_fakes import FakeInteraction
from utils.sects import TECHNIQUES, TECHNIQUE_STAGES, get_technique_cost
from utils.views import techniques as tv
from utils.views.techniques import (LearnSelectView, ToggleEquipView, TrainConfirmView, TrainSelectView, TechniquesView,
                                    _build_stats_embed, _build_techniques_embed, _calc_single_technique_bonus,
                                    _format_stat, _parse_techniques, _save_techniques)

U = "1001"
T1, T2, T3 = "青云心法", "御剑术", "凌云步"          # 黄级上品：500 灵石 / 1 年（入门）
LIFE = "木灵诀"                                      # lifespan_bonus 5


def tj(*items):
    """功法 JSON：每项 (name, stage, equipped)。"""
    return json.dumps([{"name": n, "stage": s, "equipped": e} for n, s, e in items], ensure_ascii=False)


async def _add(db, uid=U, techniques=None, stones=10_000, **kw):
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        p = make_player(D, uid, stones=stones)
        p.name = f"道友{uid}"
        p.lifespan = 100
        if techniques is not None:
            p.techniques = techniques
        for k, v in kw.items():
            setattr(p, k, v)
        s.add(p)
        await s.commit()


async def row(db, uid=U):
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        return await s.get(D.Player, uid)


def inter(uid=U):
    return FakeInteraction(uid)


def view(cls=TechniquesView, *a):
    return cls(inter().user, None, *a)


async def pick(v, i, value):
    v.select._values = [value]
    await v.select.callback(i)


# --- 纯函数 -------------------------------------------------------------------

def test_解析_旧格式字符串与新格式字典():
    raw = json.dumps(["青云心法", {"name": "御剑术", "stage": "熟练", "equipped": False}, 123])
    out = _parse_techniques(raw)
    assert out == [{"name": "青云心法", "stage": "入门", "equipped": True},
                   {"name": "御剑术", "stage": "熟练", "equipped": False}]
    assert _parse_techniques(None) == [] and _parse_techniques("") == []


def test_属性文案():
    assert _format_stat("cultivation_speed", 0.15) == "修炼速度 +15%"
    assert _format_stat("escape_rate", 10) == "逃跑成功率 +10%"
    assert _format_stat("comprehension", 3.0) == "悟性 +3"
    assert _format_stat("未知", 2) == "未知 +2"


def test_单本加成随阶段放大():
    assert _calc_single_technique_bonus({"name": T1, "stage": "入门"}) == {"comprehension": 1, "cultivation_speed": 0.15}
    big = _calc_single_technique_bonus({"name": T1, "stage": "大成"})
    assert big["comprehension"] == 4 and big["cultivation_speed"] == pytest.approx(0.15 * 1.8)
    assert _calc_single_technique_bonus({"name": "不存在", "stage": "入门"}) == {}


def player_dict(**kw):
    base = dict(name="甲", realm="炼气期1层", sect=None, techniques="[]")
    base.update(kw)
    return base


def test_功法列表文案_空():
    assert _build_techniques_embed(player_dict()).description == "尚未习得任何功法。"


def test_功法列表文案_装备标记_栏位_宗门():
    e = _build_techniques_embed(player_dict(techniques=tj((T1, "入门", True), (T2, "熟练", False)),
                                            sect="青云宗", sect_rank="亲传"))
    lines = e.description.splitlines()
    assert lines[0].startswith("✦ **青云心法**") and "阶段：入门" in lines[0] and lines[1].startswith("○ **御剑术**")
    assert "已装备 1/5" in e.footer.text and e.fields[0].value == "青云宗 · 亲传"


def test_功法属性文案():
    e = _build_stats_embed(player_dict())
    assert "没有装备任何功法" in e.description
    e = _build_stats_embed(player_dict(techniques=tj((T1, "入门", True), (T2, "入门", False), (T3, "入门", True))))
    names = [f.name for f in e.fields]
    assert names[0].startswith("✦ 青云心法") and names[1].startswith("✦ 凌云步") and names[-1] == "─── 总加成 ───"
    assert "悟性 +1" in e.fields[0].value and "逃跑成功率 +10%" in e.fields[1].value
    assert "悟性 +1" in e.fields[-1].value and "逃跑成功率 +10%" in e.fields[-1].value


def test_功法属性文案_无加成的功法():
    e = _build_stats_embed(player_dict(techniques=tj(("不存在的功法", "入门", True))))
    assert e.fields[0].value == "无加成" and e.fields[-1].value == "无"


# --- 写回 ---------------------------------------------------------------------

async def test_保存功法_期望值对得上才写(db):
    await _add(db, techniques=tj((T1, "入门", True)))
    cur = (await row(db)).techniques
    assert await _save_techniques(U, [{"name": T1, "stage": "熟练", "equipped": True}], cur) is True
    assert await _save_techniques(U, [], cur) is False                          # 旧值已过期
    assert json.loads((await row(db)).techniques)[0]["stage"] == "熟练"


# --- 主面板 -------------------------------------------------------------------

async def test_只有本人能操作(db):
    other = inter("2002")
    assert await view().interaction_check(other) is False


async def test_装备按钮_没有角色_没有功法_列出选项(db):
    i = inter("9999")
    await view().toggle_equip.callback(i)
    assert "尚未创建角色" in i.last
    await _add(db, techniques="[]")
    i = inter()
    await view().toggle_equip.callback(i)
    assert "尚未习得任何功法" in i.last
    await _add(db, "1002", techniques=tj((T1, "入门", True), (T2, "精通", False)))
    i = inter("1002")
    await view().toggle_equip.callback(i)
    sv = i.last.view
    assert isinstance(sv, ToggleEquipView) and i.last.ephemeral
    desc = {o.value: o.description for o in sv.select.options}
    assert "已装备" in desc[T1] and "未装备" in desc[T2] and "精通" in desc[T2]


async def test_功法属性按钮(db):
    i = inter("9999")
    await view().stats.callback(i)
    assert "尚未创建角色" in i.last
    await _add(db, techniques=tj((T1, "入门", True)))
    i = inter()
    await view().stats.callback(i)
    assert "功法属性加成" in i.last.embed.title and i.last.ephemeral


async def test_修炼按钮_各分支(db):
    i = inter("9999")
    await view().train.callback(i)
    assert "尚未创建角色" in i.last
    await _add(db, techniques=tj((T1, "入门", True)), cultivating_until=time.time() + 3600)
    i = inter()
    await view().train.callback(i)
    assert "正在闭关" in i.last
    await _add(db, "1002", techniques=tj((T1, "破限", True)))
    i = inter("1002")
    await view().train.callback(i)
    assert "最高阶段" in i.last
    await _add(db, "1003", techniques=tj((T1, "入门", True), (T2, "破限", True)))
    i = inter("1003")
    await view().train.callback(i)
    sv = i.last.view
    assert isinstance(sv, TrainSelectView) and [o.value for o in sv.select.options] == [T1]
    stones, years = get_technique_cost(T1, "入门")
    assert f"灵石 {stones}" in sv.select.options[0].description and "入门 → 熟练" in sv.select.options[0].description


async def test_学习按钮(db):
    i = inter("9999")
    await view().learn.callback(i)
    assert "尚未创建角色" in i.last
    await _add(db)
    i = inter()
    await view().learn.callback(i)
    assert "没有可学习的功法书" in i.last
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        s.add(D.Inventory(discord_id=U, item_id=T2, quantity=2))
        s.add(D.Inventory(discord_id=U, item_id="铜矿石", quantity=5))
        await s.commit()
    i = inter()
    await view().learn.callback(i)
    sv = i.last.view
    assert isinstance(sv, LearnSelectView) and [o.value for o in sv.select.options] == [T2]
    assert "×2" in sv.select.options[0].description


async def test_返回菜单按钮(db):
    await _add(db, techniques=tj(("双修功法", "入门", True)))
    await _add(db, "1002")
    i = inter()
    await view().back.callback(i)
    assert "双修系统" in i.last.embed.description and "city_players" in [getattr(b, "action", None) for b in i.last.view.children]
    i = inter("9999")
    await view().back.callback(i)
    assert i.last.view is not None


# --- 装备 / 卸下 --------------------------------------------------------------

async def test_装备选择_装上与卸下(db):
    await _add(db, techniques=tj((T1, "入门", False)))
    v = view(ToggleEquipView)
    i = inter()
    await pick(v, i, T1)
    assert "已装备功法" in i.last and json.loads((await row(db)).techniques)[0]["equipped"] is True
    i = inter()
    await pick(v, i, T1)
    assert "已卸下功法" in i.last and json.loads((await row(db)).techniques)[0]["equipped"] is False


async def test_装备选择_各种拒绝(db):
    v = view(ToggleEquipView)
    i = inter("9999")
    await pick(v, i, T1)
    assert "角色不存在" in i.last
    await _add(db, techniques=tj((T1, "入门", False)))
    i = inter()
    await pick(v, i, T2)
    assert "未习得功法" in i.last


async def test_装备选择_栏位已满(db):
    names = list(TECHNIQUES)[:6]
    await _add(db, techniques=tj(*[(n, "入门", n != names[5]) for n in names]))           # 炼气期 5 个栏位，已装 5
    i = inter()
    await pick(view(ToggleEquipView), i, names[5])
    assert "最多装备 5 本" in i.last and i.last.ephemeral
    assert sum(1 for t in json.loads((await row(db)).techniques) if t["equipped"]) == 5


async def test_卸下延寿功法_寿元超过卸下后的上限则拒绝(db):
    await _add(db, techniques=tj((LIFE, "入门", True)), lifespan=104, lifespan_max=100)       # 有效上限 105
    i = inter()
    await pick(view(ToggleEquipView), i, LIFE)
    assert "无法卸下" in i.last and json.loads((await row(db)).techniques)[0]["equipped"] is True
    await _add(db, "1002", techniques=tj((LIFE, "入门", True)), lifespan=100, lifespan_max=100)
    i = inter("1002")
    await pick(view(ToggleEquipView), i, LIFE)
    assert "已卸下功法" in i.last


async def test_装备选择_功法列表被改动_提示重试(db, monkeypatch):
    await _add(db, techniques=tj((T1, "入门", False)))

    async def stale(uid, techniques, expected_raw):
        return False
    monkeypatch.setattr(tv, "_save_techniques", stale)
    i = inter()
    await pick(view(ToggleEquipView), i, T1)
    assert "有变动" in i.last and i.last.ephemeral


# --- 修炼 ---------------------------------------------------------------------

async def test_修炼选择_各分支(db):
    v = view(TrainSelectView)
    i = inter("9999")
    await pick(v, i, T1)
    assert "角色不存在" in i.last
    await _add(db, techniques=tj((T1, "入门", True)), is_dead=1)
    i = inter()
    await pick(v, i, T1)
    assert "已坐化" in i.last
    await _add(db, "1002", techniques=tj((T1, "入门", True)), cultivating_until=time.time() + 3600)
    i = inter("1002")
    await pick(v, i, T1)
    assert "正在闭关" in i.last
    await _add(db, "1003", techniques=tj((T1, "入门", True)))
    i = inter("1003")
    await pick(v, i, T2)
    assert "未习得" in i.last
    await _add(db, "1004", techniques=tj((T1, "破限", True)))
    i = inter("1004")
    await pick(v, i, T1)
    assert "最高阶段" in i.last
    await _add(db, "1005", techniques=tj((T1, "入门", True)), stones=100)
    i = inter("1005")
    await pick(v, i, T1)
    assert "灵石不足" in i.last and "500" in i.last
    await _add(db, "1006", techniques=tj((T1, "入门", True)), lifespan=0)
    i = inter("1006")
    await pick(v, i, T1)
    assert "寿元不足" in i.last


async def test_修炼选择_展示确认面板(db):
    await _add(db, techniques=tj((T1, "入门", True)))
    i = inter()
    await pick(view(TrainSelectView), i, T1)
    assert isinstance(i.last.view, TrainConfirmView) and "确认修炼功法" in i.last.embed.title
    assert "入门 ➜ **熟练**" in i.last.embed.description and "现实 **2 小时**" in i.last.embed.description


def confirm_view(name=T1, stage="入门", nxt="熟练", stones=500, years=1):
    return TrainConfirmView(inter().user, None, name, stage, nxt, stones, years)


async def confirm(v, uid=U):
    i = inter(uid)
    await v.confirm.callback(i)
    return i


async def test_确认修炼_成功_扣费升阶进入闭关(db):
    await _add(db, techniques=tj((T1, "入门", True)))
    i = await confirm(confirm_view())
    p = await row(db)
    assert json.loads(p.techniques)[0]["stage"] == "熟练" and p.spirit_stones == 9500 and p.lifespan == 99
    assert p.cultivating_until == pytest.approx(time.time() + 7200, abs=5) and p.cultivating_years == 1
    assert "功法修炼中" in i.last.embed.title and i.last.view is None


async def test_确认修炼_取消(db):
    i = inter()
    await confirm_view().cancel.callback(i)
    assert "已取消修炼" in i.last


async def test_确认修炼_各种拒绝(db):
    i = await confirm(confirm_view(), "9999")
    assert "角色不存在" in i.last
    await _add(db, techniques=tj((T1, "入门", True)), cultivating_until=time.time() + 3600)
    assert "正在闭关" in (await confirm(confirm_view())).last
    await _add(db, "1002", techniques=tj((T1, "入门", True)), stones=100)
    assert (await confirm(confirm_view(), "1002")).last.content == "灵石不足。"
    await _add(db, "1003", techniques=tj((T1, "入门", True)), lifespan=0)
    assert (await confirm(confirm_view(), "1003")).last.content == "寿元不足。"
    await _add(db, "1004", techniques=tj((T2, "入门", True)))
    assert "功法不存在" in (await confirm(confirm_view(), "1004")).last
    await _add(db, "1005", techniques=tj((T1, "熟练", True)))
    assert "阶段已变化" in (await confirm(confirm_view(), "1005")).last
    for uid in ("1002", "1003", "1004", "1005"):
        assert (await row(db, uid)).cultivating_until is None


async def test_B58_已坐化_采集中_有任务_不能确认修炼(db):
    await _add(db, techniques=tj((T1, "入门", True)), is_dead=1)
    await _add(db, "1002", techniques=tj((T1, "入门", True)), gathering_until=time.time() + 3600)
    await _add(db, "1003", techniques=tj((T1, "入门", True)), active_quest=json.dumps({"id": "q"}), quest_due=time.time() + 3600)
    for uid, word in (("1001", "坐化"), ("1002", "采集"), ("1003", "任务")):
        i = await confirm(confirm_view(), uid)
        assert word in i.last and "状态已变化" not in i.last, uid                # 走的是预检查，不是兜底
        p = await row(db, uid)
        assert p.cultivating_until is None and p.spirit_stones == 10_000 and json.loads(p.techniques)[0]["stage"] == "入门"


async def _race_before_update(db, monkeypatch, **values):
    from sqlalchemy import update
    from sqlalchemy.ext.asyncio import AsyncSession
    D = db["db_async"]
    orig, state = AsyncSession.execute, {"done": False}

    async def hooked(self, stmt, *a, **k):
        if not state["done"] and "UPDATE players SET techniques" in str(stmt):
            state["done"] = True
            async with D.AsyncSessionLocal() as other:
                await other.execute(update(D.Player).values(**values))
                await other.commit()
        return await orig(self, stmt, *a, **k)
    monkeypatch.setattr(AsyncSession, "execute", hooked)


@pytest.mark.parametrize("values", [
    dict(cultivating_until=time.time() + 3600), dict(gathering_until=time.time() + 3600),
    dict(active_quest='{"id":"q"}'), dict(is_dead=1), dict(spirit_stones=0), dict(lifespan=0),
])
async def test_B58_检查之后状态变了_写入被条件挡住(db, monkeypatch, values):
    await _add(db, techniques=tj((T1, "入门", True)))
    await _race_before_update(db, monkeypatch, **values)
    i = await confirm(confirm_view())
    monkeypatch.undo()
    assert "状态已变化" in i.last and json.loads((await row(db)).techniques)[0]["stage"] == "入门"


async def test_确认修炼_连点只升一阶只收一次钱(db):
    await _add(db, techniques=tj((T1, "入门", True)))
    v = confirm_view()
    a, b = await asyncio.gather(confirm(v), confirm(v))
    p = await row(db)
    assert p.spirit_stones == 9500 and json.loads(p.techniques)[0]["stage"] == "熟练"


@pytest.mark.parametrize("stage", TECHNIQUE_STAGES[:-1])
async def test_确认修炼_每个阶段的费用与升阶(db, stage):
    await _add(db, techniques=tj((T1, stage, True)), stones=1_000_000)
    stones, years = get_technique_cost(T1, stage)
    nxt = TECHNIQUE_STAGES[TECHNIQUE_STAGES.index(stage) + 1]
    await confirm(confirm_view(stage=stage, nxt=nxt, stones=stones, years=years))
    p = await row(db)
    assert p.spirit_stones == 1_000_000 - stones and json.loads(p.techniques)[0]["stage"] == nxt


# --- 学习 ---------------------------------------------------------------------

async def give_book(db, name, qty=1, uid=U):
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        s.add(D.Inventory(discord_id=uid, item_id=name, quantity=qty))
        await s.commit()


async def book_qty(db, name, uid=U):
    return (await db["inventory"].get_inventory(uid)).get(name, 0)


async def test_学习_成功_扣书_自动装备(db):
    await _add(db, techniques="[]")
    await give_book(db, T1, 2)
    i = inter()
    await pick(view(LearnSelectView), i, T1)
    t = json.loads((await row(db)).techniques)
    assert t == [{"name": T1, "grade": "黄级上品", "stage": "入门", "equipped": True}]
    assert await book_qty(db, T1) == 1 and "成功学习" in i.last and "已自动装备" in i.last


async def test_学习_各种拒绝(db):
    v = view(LearnSelectView)
    i = inter("9999")
    await pick(v, i, T1)
    assert "角色不存在" in i.last
    await _add(db, techniques="[]")
    i = inter()
    await pick(v, i, T1)
    assert "已没有这本功法书" in i.last
    await give_book(db, T1)
    await _add(db, "1002", techniques=tj((T1, "入门", True)))
    await give_book(db, T1, 1, "1002")
    i = inter("1002")
    await pick(v, i, T1)
    assert "已习得" in i.last and await book_qty(db, T1, "1002") == 1                 # 学过的不扣书


async def test_学习_连点只学一次只扣一本(db):
    await _add(db, techniques="[]")
    await give_book(db, T1, 1)
    v = view(LearnSelectView)
    a, b = inter(), inter()
    await asyncio.gather(pick(v, a, T1), pick(v, b, T1))
    assert await book_qty(db, T1) == 0 and len(json.loads((await row(db)).techniques)) == 1


async def test_学习_功法列表被改动_整体回滚_书不丢(db, monkeypatch):
    await _add(db, techniques="[]")
    await give_book(db, T1, 1)
    from sqlalchemy import update
    from sqlalchemy.ext.asyncio import AsyncSession
    D = db["db_async"]
    orig, state = AsyncSession.execute, {"done": False}

    async def hooked(self, stmt, *a, **k):
        if not state["done"] and "UPDATE inventory" in str(stmt):               # 扣书之前，列表被别处改了
            state["done"] = True
            async with D.AsyncSessionLocal() as other:
                await other.execute(update(D.Player).values(techniques=tj((T2, "入门", True))))
                await other.commit()
        return await orig(self, stmt, *a, **k)
    monkeypatch.setattr(AsyncSession, "execute", hooked)
    i = inter()
    await pick(view(LearnSelectView), i, T1)
    monkeypatch.undo()
    assert "有变动" in i.last and await book_qty(db, T1) == 1


async def test_B57_学习时自动装备的上限随境界(db):
    names = [n for n in TECHNIQUES if n != T1][:5]
    await _add(db, techniques=tj(*[(n, "入门", True) for n in names]), realm="结丹期初期")      # 栏位 9，已装 5
    await give_book(db, T1)
    i = inter()
    await pick(view(LearnSelectView), i, T1)
    new = json.loads((await row(db)).techniques)[-1]
    assert new["name"] == T1 and new["equipped"] is True and "已自动装备" in i.last


async def test_学习_栏位满了不自动装备(db):
    names = [n for n in TECHNIQUES if n != T1][:5]
    await _add(db, techniques=tj(*[(n, "入门", True) for n in names]))                     # 炼气期栏位 5，已满
    await give_book(db, T1)
    i = inter()
    await pick(view(LearnSelectView), i, T1)
    new = json.loads((await row(db)).techniques)[-1]
    assert new["equipped"] is False and "未装备（已满5本）" in i.last


async def test_B58_检查之后功法列表被改_写入被条件挡住(db, monkeypatch):
    await _add(db, techniques=tj((T1, "入门", True)))
    await _race_before_update(db, monkeypatch, techniques=tj((T1, "入门", True), (T2, "入门", True)))
    i = await confirm(confirm_view())
    monkeypatch.undo()
    p = await row(db)
    assert "状态已变化" in i.last and p.spirit_stones == 10_000 and len(json.loads(p.techniques)) == 2
    assert all(t["stage"] == "入门" for t in json.loads(p.techniques))


async def test_卸下延寿功法_按阶段放大后的加成计算上限(db):
    """大成阶段延寿加成 ×1.8 = 9：有效上限 109，卸下后 100，寿元 101 不能卸；101 在『不放大』的错误算法下会被放行。"""
    await _add(db, techniques=tj((LIFE, "大成", True)), lifespan=101, lifespan_max=100)
    i = inter()
    await pick(view(ToggleEquipView), i, LIFE)
    assert "无法卸下" in i.last and "降至 **100年**" in i.last
