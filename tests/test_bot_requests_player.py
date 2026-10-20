"""玩家主动向熟人求助（借灵石 / 借物品 / 陪采集）：utils/bot_requests.py 的 player_ask / repay_debt / 催债 / 赖账，以及面板（utils/views/bot_actions.py）。

用户 2026-10-13：『借灵石或者物品……陪他采集灵草或者各种事情都可以』，反过来玩家也能求机器人。借了要还；到期它会催；宽限期过了还不还它就翻脸记仇。
"""

import json
import random
import time

import pytest
from sqlalchemy import select

from tests.conftest import make_player
from tests.discord_fakes import FakeInteraction
from utils import bot_grudges as bg
from utils import bot_requests as br
from utils.character import years_to_seconds
from utils.views import bot_actions as ba

H, CITY = "1001", "灵虚城"
YEAR = years_to_seconds(1)
NOW = 1_800_000_000.0
_real_ask = br.player_ask


class Z(random.Random):
    def __init__(self, value=0.0):
        super().__init__(0)
        self.value = value

    def random(self):
        return self.value


def R(seed=0):
    return random.Random(seed)


# ---- 答应概率（纯函数） -----------------------------------------------------

def test_答应概率_档位底子_关系加成_性格修正_数额占比():
    f = br.lend_chance
    assert f("熟识", "无", 50, 50, 50, 0.0) == pytest.approx(0.45)
    assert f("至交", "无", 50, 50, 50, 0.0) == pytest.approx(0.8)
    assert f("熟识", "结拜", 50, 50, 50, 0.0) == pytest.approx(0.70) and f("熟识", "朋友", 50, 50, 50, 0.0) == pytest.approx(0.60)
    assert f("熟识", "无", 100, 50, 50, 0.0) == pytest.approx(0.45 + 0.2)           # 善良
    assert f("熟识", "无", 50, 100, 50, 0.0) == pytest.approx(0.45 + 0.125)         # 义气
    assert f("熟识", "无", 50, 50, 100, 0.0) == pytest.approx(0.45 - 1 / 6)         # 贪婪
    assert f("熟识", "无", 50, 50, 50, 0.4) == pytest.approx(0.45 - 0.2)            # 借的数目占它身家 40%
    assert f("至交", "无", 50, 50, 50, 9.0) == pytest.approx(0.8 - 0.5), "占比封顶 100%"
    assert f("熟识", "无", 50, 50, 50, 9.0) == 0.02, "概率不会低于下限"
    assert f("熟识", "无", 50, 50, 50, 0.0, gather=True) == pytest.approx(0.55)
    assert f("仇视", "仇敌", 0, 0, 100, 1.0) == 0.02 and f("至交", "结拜", 100, 100, 0, 0.0) == 0.95


# ---- 夹具 -------------------------------------------------------------------

async def mk_human(db, uid=H, city=CITY, stones=1000, **kw):
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        p = make_player(D, uid, stones=stones)
        p.name, p.lifespan, p.current_city, p.last_active = f"人{uid}", 80, city, NOW
        for k, v in kw.items():
            setattr(p, k, v)
        s.add(p)
        await s.commit()


async def mk_bot(db, uid="bot_00001", arche="豪爽", city=CITY, stones=2000, kindness=50, greed=50, profile=None, alive=True):
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        p = make_player(D, uid, stones=stones)
        p.name, p.is_bot, p.lifespan, p.current_city, p.is_dead = f"机{uid[-3:]}", True, 80, city, not alive
        s.add(p)
        prof = {"lawful": 50, "impulse": 50, "loyalty": 50, "vengeful": 50, "capacity": 30, "deviance": 0, **(profile or {})}
        s.add(D.BotPersonality(bot_id=uid, archetype=arche, tier="正常", home_city=city, kindness=kindness, greed=greed, profile=json.dumps(prof)))
        await s.commit()


async def favor(db, bot, value, uid=H):
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        s.add(D.BotRelation(player_id=uid, bot_id=bot, favor=value))
        await s.commit()


async def tie(db, a, b, kind="朋友", strength=70):
    from utils import bot_ties
    D = db["db_async"]
    x, y = bot_ties.pair(a, b)
    async with D.AsyncSessionLocal() as s:
        s.add(D.BotTie(a_id=x, b_id=y, kind=kind, strength=strength))
        await s.commit()


async def rows(db):
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        return list((await s.execute(select(D.BotRequest).order_by(D.BotRequest.created_at))).scalars())


async def stones(db, uid):
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        return (await s.get(D.Player, uid)).spirit_stones


async def world(db, **bot_kw):
    await mk_human(db)
    await mk_bot(db, **bot_kw)
    await favor(db, "bot_00001", 40)                              # 熟识


def cheap_item():
    from utils.items import ITEMS
    return next(n for n, v in sorted(ITEMS.items()) if (v.get("sell_price") or 0) and 0 < v["sell_price"] <= 400)


def fixed_ask(monkeypatch):
    """面板里调 player_ask 时不带 rng / now，这里钉成『一定答应』『当前时间是 NOW』。"""
    monkeypatch.setattr(br, "player_ask", lambda pid, bid, kind, params, rng=None, now=None: _real_ask(pid, bid, kind, params, Z(0.0), NOW))


# ---- 借灵石 -----------------------------------------------------------------

async def test_借灵石_答应_当场转钱_记账_约定年限(db):
    await world(db)
    res = await br.player_ask(H, "bot_00001", "loan_stones", {"amount": 300}, Z(0.0), NOW)
    assert res["ok"] and res["accepted"] and res["line"]
    assert await stones(db, H) == 1300 and await stones(db, "bot_00001") == 1700
    (r,) = await rows(db)
    lo, hi = br.load()["player_ask"]["due_years"]
    assert (r.state, r.template) == ("active", "borrow_stones") and json.loads(r.params)["dir"] == "player"
    assert NOW + lo * YEAR <= r.due_at <= NOW + hi * YEAR and NOW + lo * YEAR <= res["due_at"] <= NOW + hi * YEAR


async def test_借灵石_婉拒_钱不动_记一笔冷却(db):
    await world(db)
    res = await br.player_ask(H, "bot_00001", "loan_stones", {"amount": 300}, Z(0.99), NOW)
    assert res["ok"] and not res["accepted"] and res["line"]
    assert await stones(db, H) == 1000 and (await rows(db))[0].state == "refused"
    again = await br.player_ask(H, "bot_00001", "loan_stones", {"amount": 100}, Z(0.0), NOW + 3600)
    assert not again["ok"] and "刚向" in again["reason"], "婉拒也占冷却，不能连着磨"
    later = await br.player_ask(H, "bot_00001", "loan_stones", {"amount": 100}, Z(0.0), NOW + 25 * 3600)
    assert later["accepted"]


async def test_借灵石_数额必须是配置里的档位(db):
    await world(db)
    res = await br.player_ask(H, "bot_00001", "loan_stones", {"amount": 12345}, Z(0.0), NOW)
    assert not res["ok"] and "不对" in res["reason"] and await rows(db) == []


async def test_借灵石_它自己手头没那么多_直接说手头紧_不掷骰(db):
    await world(db, stones=50)
    res = await br.player_ask(H, "bot_00001", "loan_stones", {"amount": 100}, Z(0.0), NOW)
    assert res["ok"] and not res["accepted"] and "手头也紧" in res["reason"]
    assert (await rows(db))[0].note == "手头紧"


async def test_借灵石_陌生人_仇人_不会借(db):
    await mk_human(db)
    await mk_bot(db)
    res = await br.player_ask(H, "bot_00001", "loan_stones", {"amount": 100}, Z(0.0), NOW)
    assert res["ok"] and not res["accepted"], "陌生人：哪怕掷 0 也不借"
    await mk_bot(db, "bot_00002")
    await favor(db, "bot_00002", 60)
    await tie(db, H, "bot_00002", "仇敌")
    assert not (await br.player_ask(H, "bot_00002", "loan_stones", {"amount": 100}, Z(0.0), NOW))["accepted"]
    await mk_bot(db, "bot_00003")
    await tie(db, H, "bot_00003", "朋友")
    assert (await br.player_ask(H, "bot_00003", "loan_stones", {"amount": 100}, Z(0.0), NOW))["accepted"], "关系网上的朋友，没有好感记录也借"


async def test_借灵石_答应的概率真的按公式(db):
    await world(db, kindness=100, profile={"loyalty": 100})              # 0.45 + 0.2 + 0.125 − 0.5×(300/2000)
    expect = 0.45 + 0.2 + 0.125 - 0.5 * 0.15
    assert (await br.player_ask(H, "bot_00001", "loan_stones", {"amount": 300}, Z(expect - 0.01), NOW))["accepted"]
    await mk_human(db, "1002")
    await favor(db, "bot_00001", 40, "1002")
    assert not (await br.player_ask("1002", "bot_00001", "loan_stones", {"amount": 300}, Z(expect + 0.01), NOW))["accepted"]


async def test_上一笔没还清_不能再借同一种(db):
    await world(db)
    await br.player_ask(H, "bot_00001", "loan_stones", {"amount": 100}, Z(0.0), NOW)
    res = await br.player_ask(H, "bot_00001", "loan_stones", {"amount": 100}, Z(0.0), NOW + 30 * 3600)
    assert not res["ok"] and "没还" in res["reason"]


async def test_不在同城_已死_求不了(db):
    await mk_human(db)
    await mk_bot(db, city="落云城")
    await favor(db, "bot_00001", 40)
    assert "离开此地" in (await br.player_ask(H, "bot_00001", "loan_stones", {"amount": 100}, Z(0.0), NOW))["reason"]
    await mk_bot(db, "bot_00002", alive=False)
    assert "不在人世" in (await br.player_ask(H, "bot_00002", "loan_stones", {"amount": 100}, Z(0.0), NOW))["reason"]
    assert not (await br.player_ask(H, "bot_99999", "loan_stones", {"amount": 100}))["ok"]
    res = await br.player_ask(H, "bot_00001", "跳舞", {})
    assert not res["ok"] and "不知道这种求助" in res["reason"]


# ---- 借物品 -----------------------------------------------------------------

async def test_借物品_答应_物品转到你背包(db):
    await world(db)
    item = cheap_item()
    await db["inventory"].add_item("bot_00001", item, 1)
    res = await br.player_ask(H, "bot_00001", "loan_item", {"item": item}, Z(0.0), NOW)
    assert res["accepted"]
    assert (await db["inventory"].get_inventory(H))[item] == 1 and item not in await db["inventory"].get_inventory("bot_00001")
    (r,) = await rows(db)
    assert r.template == "borrow_item" and json.loads(r.params)["item"] == item


async def test_借物品_它没有_不存在_太贵重_都不行(db):
    from utils.items import ITEMS
    await world(db)
    item = cheap_item()
    assert "手上没有" in (await br.player_ask(H, "bot_00001", "loan_item", {"item": item}, Z(0.0), NOW))["reason"]
    assert "不能借" in (await br.player_ask(H, "bot_00001", "loan_item", {"item": "不存在的东西"}, Z(0.0), NOW))["reason"]
    pricey = next(n for n, v in sorted(ITEMS.items()) if (v.get("sell_price") or 0) > 400)
    await db["inventory"].add_item("bot_00001", pricey, 1)
    assert "不能借" in (await br.player_ask(H, "bot_00001", "loan_item", {"item": pricey}, Z(0.0), NOW))["reason"]
    assert await rows(db) == []


# ---- 陪采集 -----------------------------------------------------------------

async def test_陪采集_答应_同城开始采集就一起去_没有酬劳_好感涨(db):
    from utils import bot_memory
    from utils import bot_social as bs
    await world(db)
    res = await br.player_ask(H, "bot_00001", "companion_gather", {"what": "采药"}, Z(0.0), NOW)
    assert res["accepted"]
    assert await br.on_gather(H, "落云城", R(1), NOW + 100) == [], "不在同一座城"
    (ev,) = await br.on_gather(H, CITY, R(1), NOW + 100)
    assert ev["kind"] == "gather_done" and ev["line"] and ev["amount"] == 0
    assert await stones(db, H) == 1000 and (await rows(db))[0].state == "done"
    assert await bs.get_favor(H, "bot_00001") == 40 + br.load()["player_ask"]["gather_favor"]
    assert (await bot_memory.recall(H, "bot_00001"))["gather"][0].extra == "done"
    assert await br.on_gather(H, CITY, R(1), NOW + 200) == []


class Seq(random.Random):
    def __init__(self, *values):
        super().__init__(0)
        self.values, self.i = list(values), 0

    def random(self):
        v = self.values[min(self.i, len(self.values) - 1)]
        self.i += 1
        return v


async def test_陪采集和借钱的约定期限各用各的配置(db):
    await world(db)
    pa = br.load()["player_ask"]
    g = await br.player_ask(H, "bot_00001", "companion_gather", {"what": "采药"}, Seq(0.0, 0.999), NOW)
    assert g["due_at"] == pytest.approx(NOW + pa["gather_due_years"][1] * YEAR, abs=100)
    assert pa["gather_due_years"][1] < pa["due_years"][1]
    l = await br.player_ask(H, "bot_00001", "loan_stones", {"amount": 100}, Seq(0.0, 0.999), NOW + 3 * 86400)
    assert l["due_at"] == pytest.approx(NOW + 3 * 86400 + pa["due_years"][1] * YEAR, abs=100)


async def test_陪采集_类型不对_机器人在秘地_不行(db):
    from utils.world import SPECIAL_REGIONS
    await world(db)
    assert not (await br.player_ask(H, "bot_00001", "companion_gather", {"what": "跳舞"}, Z(0.0), NOW))["ok"]
    wild = SPECIAL_REGIONS[0]["name"]
    await mk_human(db, "1002", city=wild)
    await mk_bot(db, "bot_00002", city=wild)
    await favor(db, "bot_00002", 40, "1002")
    assert not (await br.player_ask("1002", "bot_00002", "companion_gather", {"what": "采药"}, Z(0.0), NOW))["ok"]


async def test_陪采集_过期不扣好感(db):
    from utils import bot_social as bs
    await world(db)
    res = await br.player_ask(H, "bot_00001", "companion_gather", {"what": "采药"}, Z(0.0), NOW)
    assert await br.expire(res["due_at"] + 10) == 1
    assert (await rows(db))[0].state == "expired" and await bs.get_favor(H, "bot_00001") == 40


# ---- 还钱 -------------------------------------------------------------------

async def borrowed(db, amount=300):
    await world(db)
    res = await br.player_ask(H, "bot_00001", "loan_stones", {"amount": amount}, Z(0.0), NOW)
    return res["due_at"]


async def test_还钱_全还_账清_好感涨_记忆_台词(db):
    from utils import bot_memory
    from utils import bot_social as bs
    await borrowed(db)
    res = await br.repay_debt(H, "bot_00001", NOW + 10)
    assert res["ok"] and res["cleared"] == 1 and res["paid"] == 300 and res["left"] == 0 and res["line"]
    assert await stones(db, H) == 1000 and await stones(db, "bot_00001") == 2000 and (await rows(db))[0].state == "done"
    assert await bs.get_favor(H, "bot_00001") == 40 + br.load()["player_ask"]["cleared_favor"]
    assert (await bot_memory.recall(H, "bot_00001"))["repaid_by_player"][0].count == 1


async def test_还钱_钱不够_有多少还多少_剩下的继续欠(db):
    await borrowed(db)
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        (await s.get(D.Player, H)).spirit_stones = 100
        await s.commit()
    res = await br.repay_debt(H, "bot_00001", NOW + 10)
    assert res["ok"] and res["cleared"] == 0 and res["paid"] == 100 and res["left"] == 200 and res["line"] == ""
    (r,) = await rows(db)
    assert r.state == "active" and json.loads(r.params)["owed"] == 200
    async with D.AsyncSessionLocal() as s:
        (await s.get(D.Player, H)).spirit_stones = 0
        await s.commit()
    res = await br.repay_debt(H, "bot_00001", NOW + 20)
    assert not res["ok"] and "一分钱也还不了" in res["reason"]


async def test_还钱_没有欠账(db):
    await world(db)
    res = await br.repay_debt(H, "bot_00001", NOW)
    assert not res["ok"] and "没有欠" in res["reason"]


async def test_还物品_有就还原物_没有就折成灵石加价(db):
    from utils import bot_economy as be
    item = cheap_item()
    await world(db)
    await db["inventory"].add_item("bot_00001", item, 1)
    await br.player_ask(H, "bot_00001", "loan_item", {"item": item}, Z(0.0), NOW)
    res = await br.repay_debt(H, "bot_00001", NOW + 10)
    assert res["ok"] and res["items"] == [item] and item not in await db["inventory"].get_inventory(H)
    assert (await db["inventory"].get_inventory("bot_00001"))[item] == 1
    # 第二轮：东西已经用掉了
    await mk_human(db, "1002")
    await favor(db, "bot_00001", 40, "1002")
    await br.player_ask("1002", "bot_00001", "loan_item", {"item": item}, Z(0.0), NOW + 100)
    await db["inventory"].remove_item("1002", item, 1)
    res = await br.repay_debt("1002", "bot_00001", NOW + 200)
    assert res["ok"] and res["paid"] == int(be.item_value(item) * br.load()["repay"]["item_markup"]) and res["cleared"] == 1


# ---- 催债 / 翻脸 ------------------------------------------------------------

async def test_没到期碰面_不催(db):
    due = await borrowed(db)
    assert (await br.on_meet(H, ["bot_00001"], Z(0.99), due - 10))["events"] == []


async def test_到期后碰面_它来催_好感小降_隔一阵才再催(db):
    from utils import bot_social as bs
    due = await borrowed(db)
    (ev,) = (await br.on_meet(H, ["bot_00001"], Z(0.99), due + 10))["events"]
    pa = br.load()["player_ask"]
    assert ev["kind"] == "dun" and ev["line"] and ev["amount"] == 300
    assert await bs.get_favor(H, "bot_00001") == 40 + pa["dun_favor"]
    assert (await br.on_meet(H, ["bot_00001"], Z(0.99), due + 20))["events"] == [], "刚催过"
    (ev2,) = (await br.on_meet(H, ["bot_00001"], Z(0.99), due + pa["dun_interval_years"] * YEAR + 100))["events"]
    assert ev2["kind"] == "dun"


async def test_债主不在场就不催(db):
    due = await borrowed(db)
    assert (await br.on_meet(H, ["bot_00009"], Z(0.99), due + 10))["events"] == []


async def test_宽限期过了还不还_翻脸_记它的仇恨账_好感大降_记忆(db):
    from utils import bot_memory
    from utils import bot_social as bs
    due = await borrowed(db)
    pa = br.load()["player_ask"]
    (ev,) = (await br.on_meet(H, ["bot_00001"], Z(0.99), due + pa["grace_years"] * YEAR + 10))["events"]
    assert ev["kind"] == "player_default" and ev["line"]
    assert (await rows(db))[0].state == "defaulted" and (await rows(db))[0].note == "玩家赖账"
    assert await bs.get_favor(H, "bot_00001") == 40 + pa["default_favor"]
    (g,) = await bg.grudges_against(H)
    assert g["holder"] == "bot_00001" and g["kind"] == "debt" and g["reason"] == f"人{H}欠你的账一直不还"
    assert (await bot_memory.recall(H, "bot_00001"))["debt_by_player"][0].count == 1


async def test_翻脸后不会重复翻脸(db):
    due = await borrowed(db)
    pa = br.load()["player_ask"]
    await br.on_meet(H, ["bot_00001"], Z(0.99), due + pa["grace_years"] * YEAR + 10)
    assert (await br.on_meet(H, ["bot_00001"], Z(0.99), due + pa["grace_years"] * YEAR + 20))["events"] == []


async def test_宽限期内还清_就不会翻脸(db):
    due = await borrowed(db)
    await br.on_meet(H, ["bot_00001"], Z(0.99), due + 10)
    assert (await br.repay_debt(H, "bot_00001", due + 20))["cleared"] == 1
    assert (await br.on_meet(H, ["bot_00001"], Z(0.99), due + 100 * YEAR))["events"] == []


async def test_玩家欠的账_不会被当成机器人欠玩家去还钱(db):
    due = await borrowed(db)
    res = await br.on_meet(H, ["bot_00001"], Z(0.99), due + 10)
    assert all(e["kind"] in ("dun", "player_default") for e in res["events"])
    assert await stones(db, H) == 1300, "借来的还在手上，催债没有替你还"


# ---- 委托列表 ---------------------------------------------------------------

async def test_委托列表_区分机器人欠你和你欠机器人(db):
    await borrowed(db)
    (line,) = await br.list_for(H, NOW + 100)
    assert line.startswith("你欠 **机001** 300 灵石") and "年后还" in line
    await br.player_ask(H, "bot_00001", "companion_gather", {"what": "采矿"}, Z(0.0), NOW + 100000)
    assert any("答应陪你采矿" in l for l in await br.list_for(H, NOW + 100))


# ---- 面板 -------------------------------------------------------------------

def target():
    return {"discord_id": "bot_00001", "name": "机001"}


def test_机器人面板有求助和还钱按钮():
    import discord
    view = discord.ui.View()
    ba.add_bot_buttons(view, target())
    assert [c.label for c in view.children][-2:] == ["🙏 求助", "💰 还钱"]


async def test_求助面板_三档灵石_借物品_四种采集(db):
    view = ba.AskView(target(), FakeInteraction(user_id=int(H)).user)
    assert [c.label for c in view.children] == ["借 100 灵石", "借 300 灵石", "借 800 灵石", "借物品…", "陪我采药", "陪我采矿", "陪我伐木", "陪我钓鱼"]


async def test_点求助_出面板_点借灵石_得到答复_按钮收起(db, monkeypatch):
    await world(db)
    me = FakeInteraction(user_id=int(H))
    await ba.BotAskButton(target()).callback(me)
    assert isinstance(me.response.last.view, ba.AskView) and me.response.last.ephemeral
    view = me.response.last.view
    fixed_ask(monkeypatch)
    j = FakeInteraction(user_id=int(H))
    await next(c for c in view.children if c.label == "借 100 灵石").callback(j)
    assert j.edited[-1].view is None and j.edited[-1].embed.title == "🙏 答应了"
    k = FakeInteraction(user_id=int(H))
    await next(c for c in view.children if c.label == "借 300 灵石").callback(k)
    assert k.response.said("已经开过口")


async def test_求助面板_别人点不动(db):
    view = ba.AskView(target(), FakeInteraction(user_id=int(H)).user)
    assert await view.interaction_check(FakeInteraction(user_id=7)) is False


async def test_借物品表单_提交走借物品流程(db, monkeypatch):
    await world(db)
    item = cheap_item()
    await db["inventory"].add_item("bot_00001", item, 1)
    fixed_ask(monkeypatch)
    modal = ba.ItemAskModal(target())
    modal.item._value = item
    i = FakeInteraction(user_id=int(H))
    await modal.on_submit(i)
    assert i.followup.last.embed.title == "🙏 答应了" and item in await db["inventory"].get_inventory(H)


async def test_点借物品_弹出表单(db):
    i = FakeInteraction(user_id=int(H))
    await next(c for c in ba.AskView(target(), i.user).children if c.label == "借物品…").callback(i)
    assert isinstance(i.response.modal, ba.ItemAskModal)


async def test_点还钱按钮(db):
    await world(db)
    me = FakeInteraction(user_id=int(H))
    await ba.BotRepayButton(target()).callback(me)
    assert me.response.said("没有欠它的账")
    await br.player_ask(H, "bot_00001", "loan_stones", {"amount": 100}, Z(0.0), NOW)
    j = FakeInteraction(user_id=int(H))
    await ba.BotRepayButton(target()).callback(j)
    assert j.response.said("还了 **100** 灵石") and j.response.said("账清了")


def test_求助结果文字():
    e = ba._ask_result_embed({"ok": False, "reason": "刚求过"}, "甲")
    assert e.title == "🙏 没能开口" and "刚求过" in e.description
    e = ba._ask_result_embed({"ok": True, "accepted": False, "reason": "手头也紧", "line": "抱歉", "bot_name": "甲"}, "甲")
    assert e.title == "🙏 婉拒了" and "手头也紧" in e.description and "抱歉" in e.description
    e = ba._ask_result_embed({"ok": True, "accepted": True, "reason": "", "line": "好", "bot_name": "甲", "due_at": time.time() + 3 * YEAR}, "甲")
    assert e.title == "🙏 答应了" and "年内了结" in e.description
