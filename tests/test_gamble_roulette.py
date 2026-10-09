"""赌坊（utils/gamble.py）与轮转赌坊（utils/roulette.py）：账务、每日次数、概率配置，以及两个面板。

B39 —— 轮转赌坊的期望收益是 +87.5%：12 格里 × 0 占 4 格，但 ×5、×10 各占 1 格、×2 占 2 格，
  每转一次（押 500）平均净赚 437 灵石，每天 5 次就是凭空印钱。赌坊（gamble）的期望是 0.78，
  这个是明显的数值失衡。需要定数值（见 ISSUES.md），这里先用测试把现状钉住，改配置时必须同步改这条断言。
"""

import asyncio
import time

import pytest

from tests.conftest import make_player
from tests.discord_fakes import FakeInteraction
from utils import gamble, roulette
from utils.views import gamble as gv
from utils.views import roulette as rv

U = "1001"
DAY = 86400


async def _add(db, uid=U, stones=100_000, **kw):
    D = db["db_async"]
    p = make_player(D, uid, stones=stones)
    for k, v in kw.items():
        setattr(p, k, v)
    async with D.AsyncSessionLocal() as s:
        s.add(p)
        await s.commit()


async def row(db, uid=U):
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        return await s.get(D.Player, uid)


def force_gamble(monkeypatch, label):
    outcome = next(o for o in gamble.CONFIG["outcomes"] if o["label"] == label)
    monkeypatch.setattr(gamble.random, "choices", lambda pop, weights=None, k=1: [outcome])


def force_slot(monkeypatch, multiplier):
    slot = next(s for s in roulette.SLOTS if s["multiplier"] == multiplier)
    monkeypatch.setattr(roulette, "spin_wheel", lambda: slot)


# --- 配置 ---------------------------------------------------------------------

def test_赌坊_概率合计100():
    assert sum(p for _, p in gamble.OUTCOME_PROBS) == pytest.approx(100, abs=0.2)
    assert [l for l, _ in gamble.OUTCOME_PROBS] == [o["label"] for o in gamble.CONFIG["outcomes"]]


def test_赌坊_期望收益小于1_庄家有优势():
    total = sum(o["weight"] for o in gamble.CONFIG["outcomes"])
    ev = sum(o["weight"] * o["multiplier"] for o in gamble.CONFIG["outcomes"]) / total
    assert ev < 1, ev


def test_赌坊_每个结局都有文案_倍率非负():
    for o in gamble.CONFIG["outcomes"]:
        assert o["messages"] and o["multiplier"] >= 0 and o["weight"] > 0


def test_赌坊_面板上写死的倍率文案与配置一致():
    """面板里『大赢 ×3 · 赢 ×2 · 小赢 ×1.5 · 输 ×0』是手写的，配置一改就和真实结算对不上。"""
    desc = gv._gamble_overview_embed({"spirit_stones": 0}).description
    for o in gamble.CONFIG["outcomes"]:
        m = o["multiplier"]
        mult = f"{m:g}"
        assert f"{o['label']} ×{mult}" in desc, o


def test_轮转_转盘12格_与文案一致():
    assert len(roulette.WHEEL) == 12 and sum(s["count"] for s in roulette.SLOTS) == 12


def test_轮转_期望收益钉住现状_B39():
    """BALANCE：+87.5%/次，明显失衡，等数值定了再改这里（见 ISSUES.md B39）。"""
    ev = sum(s["count"] * s["multiplier"] for s in roulette.SLOTS) / len(roulette.WHEEL)
    assert ev == pytest.approx(1.875)


def test_轮转_落点展示恰好一个括号():
    for slot in roulette.SLOTS:
        text = roulette.build_wheel_display(slot)
        assert text.count("[") == 1 and f"[{slot['emoji']}]" in text and len(text.split()) == 12


# --- 赌坊账务 -----------------------------------------------------------------

async def test_赌坊_没有角色(db):
    assert (await gamble.do_gamble(U, 100))["reason"] == "角色不存在。"


@pytest.mark.parametrize("bet", [0, -100])
async def test_赌坊_押注必须为正(db, bet):
    await _add(db)
    r = await gamble.do_gamble(U, bet)
    assert not r["ok"] and (await row(db)).spirit_stones == 100_000 and (await row(db)).gamble_daily_count in (0, None)


async def test_赌坊_灵石不足_不扣钱_也不占次数(db):
    await _add(db, stones=50)
    r = await gamble.do_gamble(U, 100)
    assert "灵石不足" in r["reason"]
    p = await row(db)
    assert p.spirit_stones == 50 and not p.gamble_daily_count


@pytest.mark.parametrize("label,mult", [("大赢", 3.0), ("赢", 2.0), ("小赢", 1.5), ("输", 0.0)])
async def test_赌坊_各结局结算(db, monkeypatch, label, mult):
    await _add(db, stones=10_000)
    force_gamble(monkeypatch, label)
    r = await gamble.do_gamble(U, 1000)
    assert r["ok"] and r["label"] == label and r["payout"] == int(1000 * mult) and r["net"] == int(1000 * mult) - 1000
    assert (await row(db)).spirit_stones == 10_000 - 1000 + int(1000 * mult)
    assert r["message"] in next(o for o in gamble.CONFIG["outcomes"] if o["label"] == label)["messages"]


async def test_赌坊_小数倍率向下取整(db, monkeypatch):
    await _add(db)
    force_gamble(monkeypatch, "小赢")
    r = await gamble.do_gamble(U, 101)
    assert r["payout"] == 151                                                     # int(151.5)


async def test_赌坊_每日次数上限(db, monkeypatch):
    await _add(db)
    force_gamble(monkeypatch, "输")
    for n in range(1, gamble.DAILY_LIMIT + 1):
        r = await gamble.do_gamble(U, 100)
        assert r["ok"] and r["daily_count"] == n
    stones = (await row(db)).spirit_stones
    r = await gamble.do_gamble(U, 100)
    assert "已达上限" in r["reason"] and (await row(db)).spirit_stones == stones


async def test_赌坊_隔天次数归零(db, monkeypatch):
    await _add(db, gamble_daily_count=gamble.DAILY_LIMIT, gamble_daily_reset=time.time() - 2 * DAY)
    force_gamble(monkeypatch, "输")
    r = await gamble.do_gamble(U, 100)
    assert r["ok"] and r["daily_count"] == 1


async def test_赌坊_并发不超次数也不多扣(db, monkeypatch):
    await _add(db)
    force_gamble(monkeypatch, "输")
    results = await asyncio.gather(*[gamble.do_gamble(U, 100) for _ in range(gamble.DAILY_LIMIT + 6)])
    ok = [r for r in results if r["ok"]]
    assert len(ok) == gamble.DAILY_LIMIT and (await row(db)).spirit_stones == 100_000 - 100 * len(ok)


async def test_赌坊_长期统计_庄家占优(db):
    """不固定随机数：跑一批看平均回报确实低于押注（防止配置被改成亏庄家）。"""
    await _add(db, stones=10**9)
    D = db["db_async"]
    from sqlalchemy import update
    net = 0
    for _ in range(300):
        async with D.AsyncSessionLocal() as s:
            await s.execute(update(D.Player).values(gamble_daily_count=0))
            await s.commit()
        net += (await gamble.do_gamble(U, 1000))["net"]
    assert net < 0, net                                                           # 期望每次 -220，300 次几乎不可能为正


# --- 轮转账务 -----------------------------------------------------------------

async def test_轮转_没有角色_灵石不足(db):
    assert (await roulette.do_roulette(U))["reason"] == "角色不存在。"
    await _add(db, stones=roulette.BET - 1)
    r = await roulette.do_roulette(U)
    assert "灵石不足" in r["reason"]
    p = await row(db)
    assert p.spirit_stones == roulette.BET - 1 and not p.roulette_daily_count


@pytest.mark.parametrize("mult", [s["multiplier"] for s in roulette.SLOTS])
async def test_轮转_各格结算(db, monkeypatch, mult):
    await _add(db, stones=10_000)
    force_slot(monkeypatch, mult)
    r = await roulette.do_roulette(U)
    payout = int(roulette.BET * mult)
    assert r["ok"] and r["payout"] == payout and r["net"] == payout - roulette.BET and r["bet"] == roulette.BET
    assert (await row(db)).spirit_stones == 10_000 - roulette.BET + payout


async def test_轮转_每日次数与隔天归零(db, monkeypatch):
    await _add(db)
    force_slot(monkeypatch, 0.0)
    for n in range(1, roulette.DAILY_LIMIT + 1):
        assert (await roulette.do_roulette(U))["daily_count"] == n
    assert "已达上限" in (await roulette.do_roulette(U))["reason"]
    from sqlalchemy import update
    async with _sess(db) as s:
        await s.execute(update(db["db_async"].Player).values(roulette_daily_reset=time.time() - 2 * DAY))
        await s.commit()
    assert (await roulette.do_roulette(U))["daily_count"] == 1


def _sess(db):
    return db["db_async"].AsyncSessionLocal()


async def test_轮转_并发不超次数(db, monkeypatch):
    await _add(db)
    force_slot(monkeypatch, 0.0)
    results = await asyncio.gather(*[roulette.do_roulette(U) for _ in range(roulette.DAILY_LIMIT + 5)])
    assert len([r for r in results if r["ok"]]) == roulette.DAILY_LIMIT
    assert (await row(db)).spirit_stones == 100_000 - roulette.BET * roulette.DAILY_LIMIT


# --- 面板：赌坊 ---------------------------------------------------------------

def inter(uid=U):
    return FakeInteraction(uid)


def player(**kw):
    base = dict(spirit_stones=100_000, gamble_daily_count=0, gamble_daily_reset=time.time(),
                roulette_daily_count=0, roulette_daily_reset=time.time())
    base.update(kw)
    return base


def test_赌坊面板_剩余次数_隔天按满额显示():
    e = gv._gamble_overview_embed(player(gamble_daily_count=3))
    assert f"{gamble.DAILY_LIMIT - 3} / {gamble.DAILY_LIMIT}" in e.description
    e = gv._gamble_overview_embed(player(gamble_daily_count=3, gamble_daily_reset=time.time() - 2 * DAY))
    assert f"{gamble.DAILY_LIMIT} / {gamble.DAILY_LIMIT}" in e.description
    assert "100,000" in e.description and "输 " in e.description
    assert gv._gamble_overview_embed({}).description


def test_赌坊面板_按钮按灵石和次数禁用():
    v = gv.GambleView(inter().user, player(spirit_stones=600), None)
    bets = [b for b in v.children if b.custom_id in ("100", "500", "1000", "5000")]
    assert [(b.custom_id, b.disabled) for b in bets] == [("100", False), ("500", False), ("1000", True), ("5000", True)]
    v = gv.GambleView(inter().user, player(gamble_daily_count=gamble.DAILY_LIMIT), None)
    assert all(b.disabled for b in v.children if b.custom_id in ("100", "500", "1000", "5000"))
    v = gv.GambleView(inter().user, player(gamble_daily_count=gamble.DAILY_LIMIT, gamble_daily_reset=time.time() - 2 * DAY), None)
    assert not any(b.disabled for b in v.children if b.custom_id in ("100", "500", "1000", "5000"))


async def test_赌坊面板_只有本人能点(db):
    v = gv.GambleView(inter().user, player(), None)
    other = inter("2002")
    assert await v.interaction_check(other) is False


async def click_bet(view, bet):
    btn = next(b for b in view.children if b.custom_id == str(bet))
    i = inter()
    await btn.callback(i)
    return i


async def test_赌坊面板_押注成功后展示结果(db, monkeypatch):
    await _add(db, stones=10_000)
    force_gamble(monkeypatch, "赢")
    v = gv.GambleView(inter().user, player(spirit_stones=10_000), None)
    i = await click_bet(v, 1000)
    e = i.edited[-1].embed
    assert e.title == "✦ 赢 ✦" and "+1,000" in e.description and "押注：**1,000**" in e.description
    assert (await row(db)).spirit_stones == 11_000
    assert all(b.disabled for b in v.children)                                    # 点击后原面板被禁用，防连点


async def test_赌坊面板_输的时候显示负数(db, monkeypatch):
    await _add(db, stones=10_000)
    force_gamble(monkeypatch, "输")
    i = await click_bet(gv.GambleView(inter().user, player(spirit_stones=10_000), None), 500)
    assert "结算：**-500**" in i.edited[-1].embed.description


async def test_赌坊面板_失败时转述原因(db):
    await _add(db, stones=10)
    i = await click_bet(gv.GambleView(inter().user, player(spirit_stones=10_000), None), 100)   # 面板数据过期
    assert "灵石不足" in i.edited[-1].embed.description


async def test_赌坊面板_返回城市(db):
    await _add(db)
    i = inter()
    await gv._go_back(i, i.user, {}, None)
    assert i.last.embed is not None and i.last.view is not None
    v = gv._back_only_view(i.user, {}, None)
    i2 = inter()
    await v.children[0].callback(i2)
    assert i2.last.view is not None
    v = gv.GambleView(i.user, player(), None)
    i3 = inter()
    await v.children[-1].callback(i3)
    assert i3.last.view is not None


# --- 面板：轮转 ---------------------------------------------------------------

def test_轮转面板_文案与禁用():
    e = rv._wheel_overview_embed(player(roulette_daily_count=2))
    assert f"{roulette.DAILY_LIMIT - 2} / {roulette.DAILY_LIMIT}" in e.description and "12 格" in e.description
    assert "33%" in e.description and "17%" in e.description                      # × 0 占 4/12，× 2 占 2/12
    e = rv._wheel_overview_embed(player(roulette_daily_count=2, roulette_daily_reset=time.time() - 2 * DAY))
    assert f"{roulette.DAILY_LIMIT} / {roulette.DAILY_LIMIT}" in e.description
    assert rv.RouletteView(inter().user, player(spirit_stones=499), None).spin_btn.disabled
    assert rv.RouletteView(inter().user, player(roulette_daily_count=roulette.DAILY_LIMIT), None).spin_btn.disabled
    assert not rv.RouletteView(inter().user, player(), None).spin_btn.disabled
    assert not rv.RouletteView(inter().user, player(roulette_daily_count=99, roulette_daily_reset=0), None).spin_btn.disabled


@pytest.mark.parametrize("mult,title,color_name", [
    (10.0, "💎 大吉！× 10", "gold"), (5.0, "🔥 走运！× 5", "gold"), (2.0, "🟡 小赚 × 2", "green"),
    (1.0, "⚪ 回本 × 1", "greyple"), (0.5, "🌑 小亏 × 0.5", "red"), (0.0, "💀 全输 × 0", "red"),
])
async def test_轮转面板_转动结果(db, monkeypatch, mult, title, color_name):
    import discord
    await _add(db, stones=10_000)
    force_slot(monkeypatch, mult)
    v = rv.RouletteView(inter().user, player(spirit_stones=10_000), None)
    i = inter()
    await v.spin_btn.callback(i)
    result = i.last
    assert title in result.embed.title and result.embed.color == getattr(discord.Color, color_name)()
    assert isinstance(result.view, rv.RouletteResultView)
    assert result.embed.description.count("**[") == 1                              # 同样的格子有好几个，也只高亮一个
    assert (await row(db)).spirit_stones == 10_000 - 500 + int(500 * mult)
    assert isinstance(i.messages[0].view, rv.RouletteView)                        # 原消息刷新成新状态的转盘


async def test_轮转面板_失败时私下提示(db):
    await _add(db, stones=10)
    v = rv.RouletteView(inter().user, player(spirit_stones=10_000), None)
    i = inter()
    await v.spin_btn.callback(i)
    assert "灵石不足" in i.last and i.last.ephemeral


async def test_轮转面板_再来一次与返回(db):
    await _add(db)
    rvw = rv.RouletteResultView(inter().user, player(), None)
    i = inter()
    await rvw.again_btn.callback(i)
    assert isinstance(i.last.view, rv.RouletteView) and "轮转赌坊" in i.last.embed.title
    i = inter()
    await rvw.back_btn.callback(i)
    assert i.last.view is not None
    i = inter()
    await rv.RouletteView(inter().user, player(), None).back_btn.callback(i)
    assert i.last.view is not None
