"""茶馆的命令与面板（cogs/tavern.py）：茶馆、交任务、签到、四个管理员重置命令、接任务按钮。

通知循环另见 test_tavern_notifier.py。

B27 —— `QuestConfirmView.accept` 一进来就 `try_claim()`（永久作废），而 `start_quest` 会因为
  「闭关中 / 采集中 / 守城期间 / 队员有任务」拒绝。被拒绝之后按钮已经死了：玩家处理完原因想再点一次，
  只会看到「这个任务已经接取过了」，必须重新打开茶馆。应该先占位、被拒绝就放回（CONVENTIONS #11）。
"""

import json
import time

import pytest

from cogs import tavern as tavern_mod
from cogs.tavern import QuestButton, QuestConfirmView, TavernCog, TavernView, _reward_lines
from tests.conftest import make_player
from tests.discord_fakes import FakeContext, FakeInteraction
from tests.test_dual_cultivation import _FakeBot
from utils import quest_logic

UID = "1001"
MASTER = "304758476448595970"
GATHER = {"id": "g1", "title": "采集百草", "type": "gather", "location": "百草谷",
          "desc": "去山谷里采一些药草回来交差用的描述", "rewards": {"spirit_stones": 500, "reputation": 3}}
COMBAT = {"id": "c1", "title": "剿灭山贼", "type": "combat", "desc": "山贼盘踞山头，劫掠往来客商的描述",
          "enemy": {"name": "山贼", "power": 5}, "rewards": {"spirit_stones": 100}}


@pytest.fixture
def cog():
    return TavernCog(bot=_FakeBot())


async def _add(db, uid=UID, **fields):
    D = db["db_async"]
    p = make_player(D, uid, stones=0)
    p.name = f"道友{uid}"
    for k, v in fields.items():
        setattr(p, k, v)
    async with D.AsyncSessionLocal() as s:
        s.add(p)
        await s.commit()


async def _row(db, uid=UID):
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        return await s.get(D.Player, uid)


def ctx(uid=UID):
    return FakeContext(user_id=uid)


async def run(cog, name, c, *args):
    return await getattr(cog, name).callback(cog, c, *args)


# --- _reward_lines ------------------------------------------------------------

def test_奖励文案_各类奖励():
    lines = _reward_lines({
        "spirit_stones": 10, "reputation": 2, "cultivation": 5, "lifespan": 3,
        "stat_bonus": {"comprehension": 1, "bone": 2},
        "equipment": {"chance": 0.3, "quality": "稀有"},
    })
    text = "\n".join(lines)
    for part in ("灵石 +10", "声望 +2", "修为 +5", "寿元 +3 年", "悟性 永久 +1", "根骨 永久 +2", "30% 概率"):
        assert part in text, part


def test_奖励文案_必得装备与功法():
    from utils.sects import TECHNIQUES
    name = next(iter(TECHNIQUES))
    text = "\n".join(_reward_lines({"technique": name, "equipment": {"quality": "史诗"}}))
    assert f"**{name}**" in text and "必得" in text


def test_奖励文案_空奖励():
    assert _reward_lines({}) == []


# --- 茶馆 ---------------------------------------------------------------------

async def test_茶馆_没有角色(db, cog):
    c = ctx()
    await run(cog, "tavern", c)
    assert c.said("尚未踏入修仙之路")


async def test_茶馆_已坐化(db, cog):
    await _add(db, is_dead=1)
    c = ctx()
    await run(cog, "tavern", c)
    assert c.said("已坐化")


async def test_茶馆_在秘地没有茶馆(db, cog):
    await _add(db, current_city="百草谷")
    c = ctx()
    await run(cog, "tavern", c)
    assert c.said("没有茶馆") and c.last.view is None


async def test_茶馆_万宝楼拍卖进行中暂停营业(db, cog, monkeypatch):
    await _add(db, current_city="万宝楼")

    async def active():
        return {"status": "active"}
    monkeypatch.setattr("utils.events.public.wanbao.get_active_auction", active)
    c = ctx()
    await run(cog, "tavern", c)
    assert c.said("暂停营业")


async def test_茶馆_万宝楼没有拍卖时照常营业(db, cog, monkeypatch):
    await _add(db, current_city="万宝楼")

    async def none():
        return None
    monkeypatch.setattr("utils.events.public.wanbao.get_active_auction", none)
    c = ctx()
    await run(cog, "tavern", c)
    assert not c.said("暂停营业")


async def test_茶馆_有进行中任务_提示剩余时间(db, cog):
    await _add(db, active_quest=json.dumps(GATHER, ensure_ascii=False), quest_due=time.time() + 3600)
    c = ctx()
    await run(cog, "tavern", c)
    assert c.said("采集百草") and c.said("交任务") and c.last.view is None


async def test_茶馆_正常展示任务栏_每个任务一个按钮(db, cog):
    await _add(db)
    c = ctx()
    await run(cog, "tavern", c)
    msg = c.last
    assert msg.embed is not None and isinstance(msg.view, TavernView)
    assert "茶馆任务栏" in msg.embed.title
    buttons = [i for i in msg.view.children if isinstance(i, QuestButton)]
    assert buttons and all(b.quest["id"] for b in buttons)


async def test_茶馆_没有适合境界的任务(db, cog, monkeypatch):
    await _add(db)
    monkeypatch.setattr(tavern_mod, "get_tavern_quests", lambda p: {})
    c = ctx()
    await run(cog, "tavern", c)
    assert c.said("没有适合你境界的任务")


async def test_茶馆_只有锁定提示也算没有任务(db, cog, monkeypatch):
    await _add(db)
    monkeypatch.setattr(tavern_mod, "get_tavern_quests", lambda p: {"_locked": ["精英任务需声望 ≥ 50"]})
    c = ctx()
    await run(cog, "tavern", c)
    assert c.said("没有适合你境界的任务")


async def test_茶馆_锁定提示与任务并存时都展示(db, cog, monkeypatch):
    await _add(db)
    monkeypatch.setattr(tavern_mod, "get_tavern_quests",
                        lambda p: {"普通": [GATHER], "_locked": ["精英任务需声望 ≥ 50（当前 0）"]})
    c = ctx()
    await run(cog, "tavern", c)
    names = [f.name for f in c.last.embed.fields]
    assert "🔒 未解锁" in names and "── 普通任务 ──" in names
    assert len(c.last.view.children) == 1                      # 锁定提示不生成按钮


# --- 交任务 -------------------------------------------------------------------

async def test_交任务_各种前置拒绝(db, cog):
    c = ctx()
    await run(cog, "submit_quest", c)
    assert c.said("尚未踏入修仙之路")

    await _add(db, "1002", is_dead=1)
    c = ctx("1002")
    await run(cog, "submit_quest", c)
    assert c.said("已坐化")

    await _add(db)
    c = ctx()
    await run(cog, "submit_quest", c)
    assert c.said("没有进行中的任务")


async def test_交任务_未到期不结算(db, cog):
    await _add(db, active_quest=json.dumps(GATHER, ensure_ascii=False), quest_due=time.time() + 3600)
    c = ctx()
    await run(cog, "submit_quest", c)
    assert c.said("尚未完成")
    assert (await _row(db)).active_quest is not None and (await _row(db)).spirit_stones == 0


async def test_交任务_到期结算并发奖励(db, cog, monkeypatch):
    monkeypatch.setattr(quest_logic.random, "choice", lambda seq: seq[0])
    await _add(db, active_quest=json.dumps(GATHER, ensure_ascii=False), quest_due=time.time() - 1)
    c = ctx()
    await run(cog, "submit_quest", c)
    row = await _row(db)
    assert row.active_quest is None and row.spirit_stones > 0
    assert c.last.embed is not None and "采集百草" in c.last.embed.title


async def test_交任务_结算失败时转述原因(db, cog, monkeypatch):
    await _add(db, active_quest=json.dumps(GATHER, ensure_ascii=False), quest_due=time.time() - 1)

    async def fail(uid):
        return {"success": False, "message": "出了点问题"}
    monkeypatch.setattr(quest_logic, "resolve_quest", fail)
    c = ctx()
    await run(cog, "submit_quest", c)
    assert c.said("出了点问题")


# --- 结果卡片 -----------------------------------------------------------------

def test_结果卡片_五种结局(cog):
    e = cog._build_result_embed({"victory": True, "quest_name": "Q", "rewards": {"spirit_stones": 9},
                                 "equipment": {"name": "青锋剑", "quality": "稀有", "slot": "武器"}})
    assert "任务完成" in e.title and "青锋剑" in e.fields[0].value and "灵石 +9" in e.fields[0].value

    e = cog._build_result_embed({"victory": True, "quest_name": "Q", "is_party": True,
                                 "rewards": {"_equip_roll_result": "甲掷出 88"}})
    assert any(f.name == "🎲 装备 Roll 点" for f in e.fields)

    e = cog._build_result_embed({"quest_name": "Q", "event_desc": "采到了灵草", "rewards": {"reputation": 1}})
    assert e.description == "采到了灵草" and "声望 +1" in e.fields[0].value

    e = cog._build_result_embed({"quest_name": "Q", "fatal": True})
    assert "魂归天道" in e.title

    e = cog._build_result_embed({"quest_name": "Q", "escaped": True})
    assert "成功逃脱" in e.description

    e = cog._build_result_embed({"quest_name": "Q", "lifespan_loss": 7})
    assert "7 年" in e.description


def test_结果卡片_胜利无奖励时不加奖励栏(cog):
    e = cog._build_result_embed({"victory": True, "quest_name": "Q", "rewards": {}})
    assert not e.fields


# --- 签到 ---------------------------------------------------------------------

async def test_签到_没有角色(db, cog):
    c = ctx()
    await run(cog, "checkin", c)
    assert c.said("请先创建角色")


async def test_签到_今日已签(db, cog):
    await _add(db, checkin_last_date=time.strftime("%Y-%m-%d", time.gmtime()))
    c = ctx()
    await run(cog, "checkin", c)
    assert c.said("今日已签到") and c.last.view is None


async def test_签到_未签时给出按钮面板(db, cog):
    await _add(db, checkin_last_date="2000-01-01")
    c = ctx()
    await run(cog, "checkin", c)
    assert c.last.view is not None and "每日签到" in c.last.embed.title


# --- 管理员重置命令 -----------------------------------------------------------

RESETS = [
    ("reset_job", dict(job_cooldown_until=99, job_daily_count=5, job_daily_reset=99),
     dict(job_cooldown_until=0, job_daily_count=0, job_daily_reset=0)),
    ("reset_checkin", dict(checkin_last_date="2026-01-01"), dict(checkin_last_date=None)),
    ("reset_gamble", dict(gamble_daily_count=5, gamble_daily_reset=99), dict(gamble_daily_count=0, gamble_daily_reset=0)),
    ("reset_roulette", dict(roulette_daily_count=5, roulette_daily_reset=99), dict(roulette_daily_count=0, roulette_daily_reset=0)),
]


@pytest.mark.parametrize("name,dirty,clean", RESETS)
async def test_重置命令_非管理员什么都不做(db, cog, name, dirty, clean):
    await _add(db, **dirty)
    c = ctx(UID)
    await run(cog, name, c)
    row = await _row(db)
    assert not c.messages and all(getattr(row, k) == v for k, v in dirty.items())


@pytest.mark.parametrize("name,dirty,clean", RESETS)
async def test_重置命令_管理员重置自己(db, cog, name, dirty, clean):
    await _add(db, MASTER, **dirty)
    c = ctx(MASTER)
    await run(cog, name, c)
    row = await _row(db, MASTER)
    assert all(getattr(row, k) == v for k, v in clean.items())
    assert c.said(f"道友{MASTER}")


@pytest.mark.parametrize("name,dirty,clean", RESETS)
async def test_重置命令_管理员重置别人_只动目标(db, cog, name, dirty, clean):
    await _add(db, UID, **dirty)
    await _add(db, "1002", **dirty)
    c = ctx(MASTER)
    await run(cog, name, c, UID)
    target, other = await _row(db, UID), await _row(db, "1002")
    assert all(getattr(target, k) == v for k, v in clean.items())
    assert all(getattr(other, k) == v for k, v in dirty.items())


@pytest.mark.parametrize("name,dirty,clean", RESETS)
async def test_重置命令_目标不存在也不报错(db, cog, name, dirty, clean):
    c = ctx(MASTER)
    await run(cog, name, c, "999999")
    assert c.said("999999")


@pytest.mark.parametrize("name,dirty,clean", RESETS)
async def test_重置命令_留审计日志(db, cog, name, dirty, clean, caplog):
    await _add(db, UID, **dirty)
    with caplog.at_level("WARNING", logger="mischicat.audit"):
        await run(cog, name, ctx(MASTER), UID)
    assert any(name in r.getMessage() and UID in r.getMessage() for r in caplog.records)


# --- 任务栏面板 ---------------------------------------------------------------

def test_任务栏_每个任务一个按钮_锁定提示不生成(cog):
    view = TavernView(object(), {"普通": [GATHER, COMBAT], "_locked": ["x"]}, cog)
    assert len(view.children) == 2


async def test_任务栏_只有本人能点(db, cog):
    owner = ctx().author
    view = TavernView(owner, {"普通": [GATHER]}, cog)
    ok = FakeInteraction(UID)
    ok.user = owner
    assert await view.interaction_check(ok) is True
    other = FakeInteraction("2002")
    assert await view.interaction_check(other) is False
    assert other.messages[-1].ephemeral and "不是你的" in other.messages[-1]


async def _click(db, cog, quest, tier="普通", uid=UID):
    view = TavernView(FakeInteraction(uid).user, {tier: [quest]}, cog)
    btn = view.children[0]
    i = FakeInteraction(uid)
    await btn.callback(i)
    return i


async def test_点任务_战斗任务展示战力评估(db, cog):
    await _add(db)
    i = await _click(db, cog, COMBAT)
    msg = i.last
    assert isinstance(msg.view, QuestConfirmView)
    assert "剿灭山贼" in msg.embed.title
    target = next(f for f in msg.embed.fields if f.name == "目标")
    assert "山贼" in target.value and "你的战力" in target.value
    assert any(s in target.value for s in ("胜算较大", "势均力敌", "凶多吉少"))


@pytest.mark.parametrize("enemy_power,expected", [(0, "胜算较大"), (10**9, "凶多吉少")])
async def test_点任务_战力评估三档(db, cog, enemy_power, expected):
    await _add(db)
    q = {**COMBAT, "enemy": {"name": "敌", "power": enemy_power}}
    i = await _click(db, cog, q)
    assert expected in next(f for f in i.last.embed.fields if f.name == "目标").value


async def test_点任务_势均力敌(db, cog, monkeypatch):
    await _add(db)

    async def power(d):
        return 50.0
    monkeypatch.setattr(tavern_mod, "calc_power", power)
    q = {**COMBAT, "enemy": {"name": "敌", "power": 55}}
    i = await _click(db, cog, q)
    assert "势均力敌" in next(f for f in i.last.embed.fields if f.name == "目标").value


async def test_点任务_显示的战力与结算用的战力同口径(db, cog):
    """B28：展示用的战力少传了 discord_id（装备加成取不到）、fortune 等字段，评估和实际结算对不上。"""
    from utils.combat import calc_power
    await _add(db, fortune=60, comprehension=40)
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        p = await s.get(D.Player, UID)
        full = {c.key: getattr(p, c.key) for c in p.__table__.columns}
    expected = await calc_power(full)
    i = await _click(db, cog, COMBAT)
    target = next(f for f in i.last.embed.fields if f.name == "目标")
    assert f"你的战力：{expected:.1f}" in target.value


async def test_点任务_采集任务展示地点与耗时(db, cog):
    await _add(db)
    i = await _click(db, cog, GATHER)
    fields = {f.name: f.value for f in i.last.embed.fields}
    assert "百草谷" in fields["目标"] and "2 游戏年" in fields["耗时"] and "灵石 +500" in fields["奖励预览"]


async def test_点任务_角色异常(db, cog):
    i = await _click(db, cog, GATHER)
    assert "角色状态异常" in i.last and i.last.ephemeral

    await _add(db, is_dead=1)
    i = await _click(db, cog, GATHER)
    assert "角色状态异常" in i.last


# --- 接取任务按钮 -------------------------------------------------------------

def confirm(cog, quest=GATHER, uid=UID):
    return QuestConfirmView(FakeInteraction(uid).user, quest, "普通", cog)


async def accept(view, uid=UID):
    i = FakeInteraction(uid)
    await view.accept.callback(i)
    return i


async def test_接取任务_成功_写入任务与到期时间(db, cog):
    await _add(db)
    i = await accept(confirm(cog))
    row = await _row(db)
    assert json.loads(row.active_quest)["id"] == "g1" and row.quest_due > time.time()
    assert "已接取任务" in i.last and "采集百草" in i.last


async def test_接取任务_只能点一次(db, cog):
    await _add(db)
    view = confirm(cog)
    await accept(view)
    i = await accept(view)
    assert "已经接取过了" in i.last and i.last.ephemeral


async def test_接取任务_并发点击只接取一次(db, cog):
    import asyncio
    await _add(db)
    view = confirm(cog)
    a, b = await asyncio.gather(accept(view), accept(view))
    texts = [m for i in (a, b) for m in i.messages]
    assert sum("已接取任务" in m for m in texts) == 1


async def test_接取任务_组队提示人数(db, cog):
    await _add(db, party_id="P1")
    await _add(db, "1002", party_id="P1")
    i = await accept(confirm(cog))
    assert "队伍（2人）" in i.last
    assert (await _row(db, "1002")).active_quest is not None


async def test_接取任务_放弃按钮(db, cog):
    view = confirm(cog)
    i = FakeInteraction(UID)
    await view.decline.callback(i)
    assert "已放弃" in i.last and i.last.ephemeral and view.is_finished()


@pytest.mark.parametrize("fields,reason", [
    (dict(cultivating_until=time.time() + 3600), "闭关中"),
    (dict(gathering_until=time.time() + 3600), "采集中"),
    (dict(active_quest=json.dumps(COMBAT, ensure_ascii=False)), "已有进行中的任务"),
])
async def test_接取任务_被拒绝时转述原因_且不留下任务(db, cog, fields, reason):
    await _add(db, **fields)
    i = await accept(confirm(cog))
    assert reason in i.last and i.last.ephemeral


@pytest.mark.parametrize("fields", [
    dict(cultivating_until=time.time() + 3600),
    dict(gathering_until=time.time() + 3600),
])
async def test_接取任务_被拒绝后按钮还能再点(db, cog, fields):
    """B27：以前被拒绝（闭关中等）之后按钮已经作废，处理完原因再点只会看到『已经接取过了』。"""
    await _add(db, **fields)
    view = confirm(cog)
    await accept(view)
    assert not view.is_finished()

    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:                                     # 玩家结束了闭关 / 采集
        p = await s.get(D.Player, UID)
        p.cultivating_until = None
        p.gathering_until = None
        await s.commit()

    i = await accept(view)
    assert "已接取任务" in i.last
    assert (await _row(db)).active_quest is not None


async def test_接取任务_成功后面板作废(db, cog):
    await _add(db)
    view = confirm(cog)
    await accept(view)
    assert view.is_finished()


async def test_接取任务_守城期间被拒绝(db, cog):
    from sqlalchemy import text
    await _add(db)
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        await s.execute(text("INSERT INTO public_events (event_id, event_type, title, started_at, ends_at, status, data) "
                             "VALUES ('E1', 'spirit_rain', 't', 0, 9e12, 'active', '{}')"))
        await s.execute(text("INSERT INTO public_event_participants (event_id, discord_id, activity, joined_at) "
                             "VALUES ('E1', :u, 'defense', 0)"), {"u": UID})
        await s.commit()
    view = confirm(cog)
    i = await accept(view)
    assert "守城期间" in i.last and not view.is_finished()


async def test_接取任务_结算途中抛异常_占位放回(db, cog, monkeypatch):
    await _add(db)

    async def boom(*a):
        raise RuntimeError("库挂了")
    monkeypatch.setattr(quest_logic, "start_quest", boom)
    view = confirm(cog)
    with pytest.raises(RuntimeError):
        await accept(view)
    assert not view.is_finished()

    monkeypatch.undo()
    i = await accept(view)
    assert "已接取任务" in i.last


@pytest.mark.parametrize("diff,expected", [
    (21, "胜算较大"), (20, "势均力敌"), (-19, "势均力敌"), (-20, "凶多吉少"),
])
async def test_点任务_战力评估档位边界(db, cog, monkeypatch, diff, expected):
    await _add(db)

    async def power(d):
        return 100.0
    monkeypatch.setattr(tavern_mod, "calc_power", power)
    q = {**COMBAT, "enemy": {"name": "敌", "power": 100 - diff}}
    i = await _click(db, cog, q)
    assert expected in next(f for f in i.last.embed.fields if f.name == "目标").value
