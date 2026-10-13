"""机器人对熟人的请求 / 委托（utils/bot_requests.py、utils/views/requests.py、data/bot_requests.json）。

用户 2026-10-13 的想法：机器人缺钱可以向你借（以后同城碰面时隔 1~5 年可能还，有的赖账有的多还）；借物品、托你去某地送信、陪它采集……
各种事都可以，不要卡太死 —— 所以这是个数据驱动的框架：模板 + kind。
"""

import copy
import json
import random
import time
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from tests.conftest import make_player
from tests.discord_fakes import FakeContext, FakeInteraction
from utils import bot_chatter as bc
from utils import bot_grudges as bg
from utils import bot_requests as br
from utils.bot_social import load_archetypes
from utils.character import years_to_seconds
from utils.views import requests as rv

H, CITY = "1001", "灵虚城"
YEAR = years_to_seconds(1)
NOW = 1_800_000_000.0
ARCHES = sorted(load_archetypes())


class Z(random.Random):
    def __init__(self, value=0.0):
        super().__init__(0)
        self.value = value

    def random(self):
        return self.value


def R(seed=0):
    return random.Random(seed)


# ---- 配置与性格决策 ---------------------------------------------------------

def test_配置合法():
    assert br.validate(br.load(), ARCHES) == []


@pytest.mark.parametrize("mutate,expect", [
    (lambda c: c["ask"].update(chance=2), "ask.chance"),
    (lambda c: c["ask"].update(min_tier="至尊"), "min_tier"),
    (lambda c: c["ask"]["chance_by_archetype"].pop("贪财"), "chance_by_archetype"),
    (lambda c: c["templates"]["borrow_stones"].update(kind="魔法"), "kind"),
    (lambda c: c["templates"]["borrow_stones"].update(due_years=[5, 1]), "due_years"),
    (lambda c: c["templates"]["borrow_stones"].update(amounts=[]), "amounts"),
    (lambda c: c["templates"]["gather_together"].update(types=[]), "types"),
    (lambda c: c["templates"]["deliver_letter"].update(reward_stones=[9, 1]), "reward_stones"),
    (lambda c: c["templates"].update(新模板={"kind": "loan_stones", "weight": 1, "amounts": [1], "due_years": [1, 2], "bot_stones_below": 1, "amount_max_player_share": 1}), "缺少开口台词场景"),
    (lambda c: c["repay"]["default_base"].pop("豪爽"), "default_base"),
    (lambda c: c["repay"]["gratitude"].update(bonus=[0.5, 0.1]), "gratitude.bonus"),
])
def test_校验能拦住坏配置(mutate, expect):
    cfg = copy.deepcopy(br.load())
    mutate(cfg)
    assert any(expect in e for e in br.validate(cfg, ARCHES)), br.validate(cfg, ARCHES)


def test_每个模板都有开口台词场景和结算台词场景():
    from utils import bot_chatter_lines as cl
    for name in br.load()["templates"]:
        assert f"request_ask_{name}" in cl.SCENES
    for scene in ("request_thanks", "request_declined", "request_repay", "request_repay_plus", "request_repay_item", "request_short",
                  "request_default", "request_errand_arrive", "request_gather_done", "request_failed"):
        assert scene in cl.SCENES


def test_赖账概率_性格底子_守序善良交情深的更不赖():
    dp = br.default_probability
    assert dp("贪财", 50, 50, 50, "陌生") > dp("豪爽", 50, 50, 50, "陌生") * 3 > 0
    assert dp("贪财", 10, 20, 90, "仇视") > dp("贪财", 90, 90, 10, "至交")
    assert dp("迂腐", 100, 100, 0, "至交") == 0.0
    assert dp("贪财", 0, 0, 100, "仇视") <= 0.9, "封顶"


def test_还钱决策分布():
    def dist(arche, tier="熟识", **kw):
        rng, out = R(1), {"default": 0, "repay": 0, "plus": 0}
        for _ in range(4000):
            out[br.repay_decision(arche, kw.get("lawful", 50), kw.get("kindness", 50), kw.get("greed", 50), tier, rng)] += 1
        return {k: v / 4000 for k, v in out.items()}
    greedy, honest = dist("贪财"), dist("迂腐", kindness=80)
    assert greedy["default"] > 0.2 and honest["default"] < 0.03
    assert honest["plus"] > honest["repay"] * 0.2 and greedy["plus"] < 0.1


# ---- 夹具 -------------------------------------------------------------------

async def mk_human(db, uid=H, city=CITY, stones=2000, **kw):
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        p = make_player(D, uid, stones=stones)
        p.name, p.lifespan, p.current_city, p.last_active = f"人{uid}", 80, city, NOW
        for k, v in kw.items():
            setattr(p, k, v)
        s.add(p)
        await s.commit()


async def mk_bot(db, uid, arche="豪爽", city=CITY, stones=50, kindness=50, greed=50, profile=None, alive=True, likes=None, home=None):
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        p = make_player(D, uid, stones=stones)
        p.name, p.is_bot, p.lifespan, p.current_city, p.is_dead = f"机{uid[-3:]}", True, 80, city, not alive
        s.add(p)
        prof = {"lawful": 50, "impulse": 50, "loyalty": 60, "vengeful": 50, "capacity": 30, "deviance": 0, **(profile or {})}
        s.add(D.BotPersonality(bot_id=uid, archetype=arche, tier="正常", home_city=home or city, kindness=kindness, greed=greed,
                               profile=json.dumps(prof), likes=json.dumps(likes or {"categories": [], "items": []})))
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


async def pin_templates(monkeypatch, only):
    """只留指定的模板（让测试不依赖权重抽签），开口概率拉满。"""
    cfg = copy.deepcopy(br.load())
    cfg["templates"] = {k: v for k, v in cfg["templates"].items() if k in only}
    cfg["ask"]["chance"] = 1.0
    monkeypatch.setattr(br, "load", lambda: cfg)
    return cfg


# ---- 开口 -------------------------------------------------------------------

async def test_熟人缺钱_向你开口借灵石(db, monkeypatch):
    await pin_templates(monkeypatch, ["borrow_stones"])
    await mk_human(db)
    await mk_bot(db, "bot_00001", stones=50)
    await favor(db, "bot_00001", 40)                              # 熟识
    offer = await br.maybe_ask(H, "bot_00001", Z(0.0), NOW)
    assert offer and offer["kind"] == "loan_stones" and offer["params"]["amount"] in (100, 300, 800) and offer["line"]
    assert str(offer["params"]["amount"]) in offer["line"] or "灵石" in offer["line"]
    (r,) = await rows(db)
    assert (r.state, r.player_id, r.bot_id, r.template) == ("offered", H, "bot_00001", "borrow_stones")
    assert r.due_at == NOW + 12 * 3600


async def test_不缺钱的不借(db, monkeypatch):
    await pin_templates(monkeypatch, ["borrow_stones"])
    await mk_human(db)
    await mk_bot(db, "bot_00001", stones=5000)
    await favor(db, "bot_00001", 40)
    assert await br.maybe_ask(H, "bot_00001", Z(0.0), NOW) is None


async def test_借的数目不超过你身家的一半(db, monkeypatch):
    await pin_templates(monkeypatch, ["borrow_stones"])
    await mk_human(db, stones=250)
    await mk_bot(db, "bot_00001", stones=0)
    await favor(db, "bot_00001", 40)
    assert (await br.maybe_ask(H, "bot_00001", Z(0.0), NOW))["params"]["amount"] == 100
    await mk_human(db, "1002", stones=100)
    await favor(db, "bot_00001", 40, "1002")
    assert await br.maybe_ask("1002", "bot_00001", Z(0.0), NOW) is None, "身家的一半不足最小档位"


async def test_不熟的_仇人_陌生人不开口(db, monkeypatch):
    await pin_templates(monkeypatch, ["borrow_stones"])
    await mk_human(db)
    await mk_bot(db, "bot_00001", stones=0)
    assert await br.maybe_ask(H, "bot_00001", Z(0.0), NOW) is None, "陌生人"
    await favor(db, "bot_00001", -50)
    assert await br.maybe_ask(H, "bot_00001", Z(0.0), NOW) is None, "仇视"
    await mk_bot(db, "bot_00002", stones=0)
    await tie(db, H, "bot_00002", "仇敌")
    await favor(db, "bot_00002", 40)
    assert await br.maybe_ask(H, "bot_00002", Z(0.0), NOW) is None, "仇敌"
    await mk_bot(db, "bot_00003", stones=0)
    await tie(db, H, "bot_00003", "朋友")
    assert await br.maybe_ask(H, "bot_00003", Z(0.0), NOW), "关系网上的朋友，哪怕好感记录是空的，也会开口"


async def test_开口按概率_按性格(db, monkeypatch):
    cfg = await pin_templates(monkeypatch, ["borrow_stones"])
    cfg["ask"]["chance"] = 0.3
    await mk_human(db)
    await mk_bot(db, "bot_00001", "贪财", stones=0)
    await mk_bot(db, "bot_00002", "高冷", stones=0)
    for b in ("bot_00001", "bot_00002"):
        await favor(db, b, 40)
    assert await br.maybe_ask(H, "bot_00001", Z(0.4), NOW), "贪财 ×1.5：0.45"
    assert await br.maybe_ask(H, "bot_00002", Z(0.2), NOW) is None, "高冷 ×0.4：0.12"


async def test_同一个机器人同时只有一个请求_有冷却(db, monkeypatch):
    await pin_templates(monkeypatch, ["borrow_stones"])
    await mk_human(db)
    await mk_bot(db, "bot_00001", stones=0)
    await favor(db, "bot_00001", 40)
    first = await br.maybe_ask(H, "bot_00001", Z(0.0), NOW)
    assert first
    assert await br.maybe_ask(H, "bot_00001", Z(0.0), NOW + 5 * 3600) is None, "上一个还没答复"
    await br.decline(first["id"], Z(0.0), NOW + 10)
    assert await br.maybe_ask(H, "bot_00001", Z(0.0), NOW + 20 * 3600) is None, "冷却 24 小时"
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        (await s.get(D.Player, H)).last_active = NOW + 25 * 3600           # 玩家一直在线
        await s.commit()
    assert await br.maybe_ask(H, "bot_00001", Z(0.0), NOW + 25 * 3600)


async def test_玩家手上的请求太多不再开口(db, monkeypatch):
    cfg = await pin_templates(monkeypatch, ["borrow_stones"])
    cfg["ask"]["max_open_per_player"] = 2
    await mk_human(db)
    for i in range(1, 5):
        await mk_bot(db, f"bot_{i:05d}", stones=0)
        await favor(db, f"bot_{i:05d}", 40)
    assert await br.maybe_ask(H, "bot_00001", Z(0.0), NOW) and await br.maybe_ask(H, "bot_00002", Z(0.0), NOW)
    assert await br.maybe_ask(H, "bot_00003", Z(0.0), NOW) is None, "已经有 2 个待处理的请求"
    cfg["ask"]["max_open_per_player"] = 3
    assert await br.maybe_ask(H, "bot_00003", Z(0.0), NOW), "上限放宽就能再开口"


async def test_屏蔽了搭话的玩家_不会被开口(db, monkeypatch):
    await pin_templates(monkeypatch, ["borrow_stones"])
    await mk_human(db)
    await mk_bot(db, "bot_00001", stones=0)
    await favor(db, "bot_00001", 40)
    await bc.set_muted(H, True)
    assert await br.maybe_ask(H, "bot_00001", Z(0.0), NOW) is None


async def test_开口算一次搭话事件_占每日名额_也有冷却(db, monkeypatch):
    await pin_templates(monkeypatch, ["borrow_stones"])
    await mk_human(db)
    await mk_bot(db, "bot_00001", stones=0)
    await favor(db, "bot_00001", 40)
    await br.maybe_ask(H, "bot_00001", Z(0.0), NOW)
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        assert (await s.get(D.ChatterState, H)).count == 1 and (await s.get(D.ChatterPair, (H, "bot_00001"))) is not None


async def test_借物品_挑你有的_便宜的_它喜欢的类别优先(db, monkeypatch):
    from utils.bot_social import category_of
    from utils.items import ITEMS
    await pin_templates(monkeypatch, ["borrow_item"])
    await mk_human(db)
    cheap = next(n for n, v in sorted(ITEMS.items()) if (v.get("sell_price") or 0) and 0 < v["sell_price"] <= 400)
    pricey = next(n for n, v in sorted(ITEMS.items()) if (v.get("sell_price") or 0) > 400)
    await mk_bot(db, "bot_00001", stones=0, likes={"categories": [category_of(cheap)], "items": []})
    await favor(db, "bot_00001", 40)
    await db["inventory"].add_item(H, pricey, 1)
    assert await br.maybe_ask(H, "bot_00001", Z(0.0), NOW) is None, "只有贵重物品：不借"
    await db["inventory"].add_item(H, cheap, 1)
    offer = await br.maybe_ask(H, "bot_00001", Z(0.0), NOW)
    assert offer["kind"] == "loan_item" and offer["params"]["item"] == cheap and cheap in offer["line"]


async def test_送信_收信人是它的熟人_在别的城(db, monkeypatch):
    await pin_templates(monkeypatch, ["deliver_letter"])
    await mk_human(db)
    await mk_bot(db, "bot_00001", city=CITY)
    await mk_bot(db, "bot_00002", city="落云城")
    await mk_bot(db, "bot_00003", city=CITY)
    await favor(db, "bot_00001", 40)
    await tie(db, "bot_00001", "bot_00003", "朋友")
    assert await br.maybe_ask(H, "bot_00001", Z(0.0), NOW) is None, "熟人都在本城：没处可送"
    await tie(db, "bot_00001", "bot_00002", "结拜")
    offer = await br.maybe_ask(H, "bot_00001", Z(0.0), NOW)
    assert offer["kind"] == "errand" and offer["params"] == {"target": "bot_00002", "target_name": "机002", "city": "落云城"}
    assert "落云城" in offer["line"] and "机002" in offer["line"]


async def test_陪采集_它不在秘地就行(db, monkeypatch):
    from utils.world import SPECIAL_REGIONS
    await pin_templates(monkeypatch, ["gather_together"])
    await mk_human(db)
    await mk_bot(db, "bot_00001", city=SPECIAL_REGIONS[0]["name"])
    await mk_bot(db, "bot_00002")
    for b in ("bot_00001", "bot_00002"):
        await favor(db, b, 40)
    assert await br.maybe_ask(H, "bot_00001", Z(0.0), NOW) is None
    offer = await br.maybe_ask(H, "bot_00002", Z(0.0), NOW)
    assert offer["kind"] == "companion_gather" and offer["params"]["what"] in br.load()["templates"]["gather_together"]["types"]


async def test_开口出错只记警告(db, monkeypatch, caplog):
    async def boom(*a, **k):
        raise RuntimeError("库坏了")
    monkeypatch.setattr(bc, "build_context", boom)
    assert await br.maybe_ask(H, "bot_00001") is None
    assert "机器人开口失败" in caplog.text


# ---- 答应 / 婉拒 ------------------------------------------------------------

async def offered(db, monkeypatch, template="borrow_stones", **bot_kw):
    await pin_templates(monkeypatch, [template])
    await mk_human(db)
    bot_kw.setdefault("stones", 0)
    await mk_bot(db, "bot_00001", **bot_kw)
    await favor(db, "bot_00001", 40)
    return await br.maybe_ask(H, "bot_00001", Z(0.0), NOW)


async def test_答应借灵石_当场转钱_约定1到5年后还(db, monkeypatch):
    offer = await offered(db, monkeypatch)
    amount = offer["params"]["amount"]
    res = await br.accept(offer["id"], R(1), NOW + 60)
    assert res["ok"] and res["line"] and res["bot_name"] == "机001"
    assert await stones(db, H) == 2000 - amount and await stones(db, "bot_00001") == amount
    (r,) = await rows(db)
    assert r.state == "active" and NOW + 60 + YEAR <= r.due_at <= NOW + 60 + 5 * YEAR


async def test_答应借灵石_钱不够_不转_请求仍可处理(db, monkeypatch):
    offer = await offered(db, monkeypatch)
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        (await s.get(D.Player, H)).spirit_stones = 5
        await s.commit()
    res = await br.accept(offer["id"], R(1), NOW + 60)
    assert not res["ok"] and "不够" in res["reason"] and await stones(db, "bot_00001") == 0
    assert (await rows(db))[0].state == "offered"


async def test_答应借物品_物品转到对方背包(db, monkeypatch):
    from utils.items import ITEMS
    cheap = next(n for n, v in sorted(ITEMS.items()) if (v.get("sell_price") or 0) and 0 < v["sell_price"] <= 400)
    await mk_human(db)
    await db["inventory"].add_item(H, cheap, 1)
    offer = await offered_item(db, monkeypatch, cheap)
    res = await br.accept(offer["id"], R(1), NOW + 60)
    assert res["ok"]
    assert cheap not in await db["inventory"].get_inventory(H) and (await db["inventory"].get_inventory("bot_00001"))[cheap] == 1


async def offered_item(db, monkeypatch, item):
    await pin_templates(monkeypatch, ["borrow_item"])
    await mk_bot(db, "bot_00001", stones=0)
    await favor(db, "bot_00001", 40)
    return await br.maybe_ask(H, "bot_00001", Z(0.0), NOW)


async def test_答应借物品_你已经把东西用掉了(db, monkeypatch):
    from utils.items import ITEMS
    cheap = next(n for n, v in sorted(ITEMS.items()) if (v.get("sell_price") or 0) and 0 < v["sell_price"] <= 400)
    await mk_human(db)
    await db["inventory"].add_item(H, cheap, 1)
    offer = await offered_item(db, monkeypatch, cheap)
    await db["inventory"].remove_item(H, cheap, 1)
    res = await br.accept(offer["id"], R(1), NOW + 60)
    assert not res["ok"] and cheap in res["reason"]


async def test_答应送信_陪采集_进入active等着办(db, monkeypatch):
    offer = await offered(db, monkeypatch, "gather_together")
    res = await br.accept(offer["id"], R(1), NOW + 60)
    assert res["ok"]
    (r,) = await rows(db)
    lo, hi = br.load()["templates"]["gather_together"]["due_years"]
    assert r.state == "active" and NOW + 60 + lo * YEAR <= r.due_at <= NOW + 60 + hi * YEAR
    assert await stones(db, H) == 2000, "陪采集不转钱"


async def test_婉拒_不扣好感_不转钱_对方回一句(db, monkeypatch):
    from utils import bot_social as bs
    offer = await offered(db, monkeypatch)
    res = await br.decline(offer["id"], R(1), NOW + 5)
    assert res["ok"] and res["line"]
    assert (await rows(db))[0].state == "declined" and await stones(db, H) == 2000 and await bs.get_favor(H, "bot_00001") == 40


async def test_处理过的请求不能再处理_过期的不能答应(db, monkeypatch):
    offer = await offered(db, monkeypatch)
    assert (await br.accept(offer["id"], R(1), NOW + 5))["ok"]
    assert not (await br.accept(offer["id"], R(1), NOW + 6))["ok"] and not (await br.decline(offer["id"]))["ok"]
    assert not (await br.accept("不存在"))["ok"]
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        for r in (await s.execute(select(D.BotRequest))).scalars().all():
            await s.delete(r)
        await s.commit()
    await mk_bot(db, "bot_00002", stones=0)
    await favor(db, "bot_00002", 40)
    o2 = await br.maybe_ask(H, "bot_00002", Z(0.0), NOW)
    res = await br.accept(o2["id"], R(1), NOW + 13 * 3600)
    assert not res["ok"] and "过期" in res["reason"] and (await rows(db))[0].state == "expired"


async def test_对方已经不在了_不能答应(db, monkeypatch):
    offer = await offered(db, monkeypatch)
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        (await s.get(D.Player, "bot_00001")).is_dead = True
        await s.commit()
    assert "不在人世" in (await br.accept(offer["id"], R(1), NOW + 5))["reason"]


# ---- 还钱 -------------------------------------------------------------------

async def lent(db, monkeypatch, arche="迂腐", bot_stones=0, **bot_kw):
    offer = await offered(db, monkeypatch, arche=arche, stones=bot_stones, **bot_kw)
    await br.accept(offer["id"], R(1), NOW + 60)
    (r,) = await rows(db)
    return offer["params"]["amount"], r.due_at


async def meet(present=("bot_00001",), rng=None, now=None):
    return await br.on_meet(H, list(present), rng or Z(0.99), now)


async def test_没到期碰面_什么都不结算(db, monkeypatch):
    amount, due = await lent(db, monkeypatch)
    res = await meet(now=due - 10)
    assert res["events"] == []


async def test_到期碰面_照还_钱回到你手上(db, monkeypatch):
    amount, due = await lent(db, monkeypatch, "迂腐", kindness=50)
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:                         # 它有钱还
        (await s.get(D.Player, "bot_00001")).spirit_stones = 5000
        await s.commit()
    res = await meet(rng=Z(0.99), now=due + 10)
    (ev,) = res["events"]
    assert ev["kind"] == "repay" and ev["amount"] == amount and ev["line"]
    assert await stones(db, H) == 2000 and (await rows(db))[0].state == "done"


async def test_多还的数目在配置的范围里(db, monkeypatch):
    amount, due = await lent(db, monkeypatch, "迂腐")
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        (await s.get(D.Player, "bot_00001")).spirit_stones = 5000
        await s.commit()
    monkeypatch.setattr(br, "repay_decision", lambda *a, **k: "plus")
    (ev,) = (await meet(rng=R(3), now=due + 10))["events"]
    lo, hi = br.load()["repay"]["gratitude"]["bonus"]
    assert ev["kind"] == "repay_plus" and amount * (1 + lo) - 1 <= ev["amount"] <= amount * (1 + hi) + 1
    assert await stones(db, H) == 2000 - amount + ev["amount"]


async def test_赖账_不还_记轻仇_记忆_好感大降(db, monkeypatch):
    from utils import bot_memory
    from utils import bot_social as bs
    amount, due = await lent(db, monkeypatch, "贪财")
    monkeypatch.setattr(br, "repay_decision", lambda *a, **k: "default")
    (ev,) = (await meet(now=due + 10))["events"]
    assert ev["kind"] == "default" and ev["line"]
    assert (await rows(db))[0].state == "defaulted" and await stones(db, H) == 2000 - amount
    (g,) = await bg.grudges_of(H)
    assert g["target"] == "bot_00001" and g["kind"] == "debt" and g["reason"] == "机001欠你的账一直不还"
    assert (await bot_memory.recall(H, "bot_00001"))["debt"][0].count == 1
    assert await bs.get_favor(H, "bot_00001") == 40 + br.load()["default"]["favor"]


async def test_手头不够_先还一部分_宽限几年_宽限用完算赖账(db, monkeypatch):
    amount, due = await lent(db, monkeypatch, "迂腐")
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        (await s.get(D.Player, "bot_00001")).spirit_stones = amount // 2
        await s.commit()
    monkeypatch.setattr(br, "repay_decision", lambda *a, **k: "repay")
    (ev,) = (await meet(now=due + 10))["events"]
    assert ev["kind"] == "short" and ev["amount"] == amount - amount // 2
    (r,) = await rows(db)
    lo, hi = br.load()["repay"]["extend_years"]
    assert r.state == "active" and due + 10 + lo * YEAR <= r.due_at <= due + 10 + hi * YEAR and json.loads(r.params)["owed"] == ev["amount"]
    # 再两次都还不上 → 宽限用完，算赖账
    later = r.due_at + 10
    (ev2,) = (await meet(now=later))["events"]
    assert ev2["kind"] == "short"
    (r,) = await rows(db)
    (ev3,) = (await meet(now=r.due_at + 10))["events"]
    assert ev3["kind"] == "default" and (await rows(db))[0].state == "defaulted"


async def test_一分钱没有_也是先宽限(db, monkeypatch):
    amount, due = await lent(db, monkeypatch, "迂腐")
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        (await s.get(D.Player, "bot_00001")).spirit_stones = 0
        await s.commit()
    monkeypatch.setattr(br, "repay_decision", lambda *a, **k: "repay")
    (ev,) = (await meet(now=due + 10))["events"]
    assert ev["kind"] == "short" and ev["amount"] == amount and await stones(db, H) == 2000 - amount


async def test_借的物品_到期原物奉还_没有了就折成灵石(db, monkeypatch):
    from utils.items import ITEMS
    cheap = next(n for n, v in sorted(ITEMS.items()) if (v.get("sell_price") or 0) and 0 < v["sell_price"] <= 400)
    await mk_human(db)
    await db["inventory"].add_item(H, cheap, 1)
    offer = await offered_item(db, monkeypatch, cheap)
    await br.accept(offer["id"], R(1), NOW + 60)
    due = (await rows(db))[0].due_at
    monkeypatch.setattr(br, "repay_decision", lambda *a, **k: "repay")
    (ev,) = (await meet(now=due + 10))["events"]
    assert ev["kind"] == "repay_item" and ev["item"] == cheap
    assert (await db["inventory"].get_inventory(H))[cheap] == 1 and cheap not in await db["inventory"].get_inventory("bot_00001")


async def test_借的物品_对方用掉了_折成灵石按加价还(db, monkeypatch):
    from utils import bot_economy as be
    from utils.items import ITEMS
    cheap = next(n for n, v in sorted(ITEMS.items()) if (v.get("sell_price") or 0) and 0 < v["sell_price"] <= 400)
    await mk_human(db)
    await db["inventory"].add_item(H, cheap, 1)
    offer = await offered_item(db, monkeypatch, cheap)
    await br.accept(offer["id"], R(1), NOW + 60)
    await db["inventory"].remove_item("bot_00001", cheap, 1)
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        (await s.get(D.Player, "bot_00001")).spirit_stones = 99999
        await s.commit()
    due = (await rows(db))[0].due_at
    monkeypatch.setattr(br, "repay_decision", lambda *a, **k: "repay")
    (ev,) = (await meet(now=due + 10))["events"]
    assert ev["kind"] == "repay" and ev["amount"] == int(be.item_value(cheap) * br.load()["repay"]["item_markup"])


async def test_借款人不在场就不结算(db, monkeypatch):
    amount, due = await lent(db, monkeypatch)
    assert (await meet(present=("bot_00002",), now=due + 10))["events"] == []
    assert (await rows(db))[0].state == "active"


# ---- 送信 / 陪采集 ----------------------------------------------------------

async def errand_accepted(db, monkeypatch, asker_stones=1000):
    await pin_templates(monkeypatch, ["deliver_letter"])
    await mk_human(db)
    await mk_bot(db, "bot_00001", stones=asker_stones, city=CITY, home=CITY)
    await mk_bot(db, "bot_00002", city="落云城", home="落云城")
    await favor(db, "bot_00001", 40)
    await tie(db, "bot_00001", "bot_00002", "朋友")
    offer = await br.maybe_ask(H, "bot_00001", Z(0.0), NOW)
    await br.accept(offer["id"], R(1), NOW + 60)
    return offer


async def test_送信_收信人在场就算送到_酬劳来自托信的人_好感双涨(db, monkeypatch):
    from utils import bot_social as bs
    await errand_accepted(db, monkeypatch)
    assert (await br.on_meet(H, ["bot_00009"], Z(0.99), NOW + 100))["events"] == []
    (ev,) = (await br.on_meet(H, ["bot_00002"], Z(0.99), NOW + 100))["events"]
    lo, hi = br.load()["templates"]["deliver_letter"]["reward_stones"]
    assert ev["kind"] == "errand_done" and ev["bot_id"] == "bot_00002" and lo <= ev["amount"] <= hi and ev["asker"] == "机001"
    assert await stones(db, H) == 2000 + ev["amount"] and await stones(db, "bot_00001") == 1000 - ev["amount"], "钱守恒：托信的人出"
    assert (await rows(db))[0].state == "done"
    assert await bs.get_favor(H, "bot_00001") == 40 + 4 and await bs.get_favor(H, "bot_00002") == 2


async def test_送信_托信的人没钱就有多少给多少(db, monkeypatch):
    await errand_accepted(db, monkeypatch, asker_stones=10)
    (ev,) = (await br.on_meet(H, ["bot_00002"], Z(0.99), NOW + 100))["events"]
    assert ev["amount"] == 10 and await stones(db, "bot_00001") == 0


async def test_送信_收信人不在了就送不到(db, monkeypatch):
    await errand_accepted(db, monkeypatch)
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        (await s.get(D.Player, "bot_00002")).is_dead = True
        await s.commit()
    assert (await br.on_meet(H, ["bot_00002"], Z(0.99), NOW + 100))["events"] == []


async def gather_accepted(db, monkeypatch):
    offer = await offered(db, monkeypatch, "gather_together", stones=500)
    await br.accept(offer["id"], R(1), NOW + 60)


async def test_陪采集_同城开始采集就一起去了_酬劳好感记忆(db, monkeypatch):
    from utils import bot_memory
    from utils import bot_social as bs
    await gather_accepted(db, monkeypatch)
    assert await br.on_gather(H, "落云城", R(1), NOW + 100) == [], "不在同一座城"
    (ev,) = await br.on_gather(H, CITY, R(1), NOW + 100)
    lo, hi = br.load()["templates"]["gather_together"]["reward_stones"]
    assert ev["kind"] == "gather_done" and lo <= ev["amount"] <= hi and ev["line"]
    assert await stones(db, H) == 2000 + ev["amount"] and (await rows(db))[0].state == "done"
    assert await bs.get_favor(H, "bot_00001") == 44 and (await bot_memory.recall(H, "bot_00001"))["gather"][0].extra == "done"
    assert await br.on_gather(H, CITY, R(1), NOW + 200) == [], "只算一次"


# ---- 过期 / 查询 ------------------------------------------------------------

async def test_过期_没答复的作废_没办成的送信陪采集失败扣好感_借款不过期(db, monkeypatch):
    from utils import bot_social as bs
    await errand_accepted(db, monkeypatch)
    (r,) = await rows(db)
    assert await br.expire(r.due_at - 10) == 0
    assert await br.expire(r.due_at + 10) == 1
    assert (await rows(db))[0].state == "failed" and await bs.get_favor(H, "bot_00001") == 40 + br.load()["fail"]["favor"]


async def test_过期_借款到期后一直等着碰面_不会被过期清掉(db, monkeypatch):
    amount, due = await lent(db, monkeypatch)
    assert await br.expire(due + 1000 * YEAR) == 0 and (await rows(db))[0].state == "active"


async def test_过期_提出后没答复的作废(db, monkeypatch):
    await offered(db, monkeypatch)
    assert await br.expire(NOW + 13 * 3600) == 1 and (await rows(db))[0].state == "expired"


async def test_委托列表_文字(db, monkeypatch):
    amount, due = await lent(db, monkeypatch)
    lines = await br.list_for(H, NOW + 100)
    assert len(lines) == 1 and "借给 **机001**" in lines[0] and f"{amount} 灵石" in lines[0] and "年后还" in lines[0]
    assert await br.list_for("9999") == []


async def test_委托列表_各种类型的文字(db, monkeypatch):
    await errand_accepted(db, monkeypatch)
    assert "送信" in (await br.list_for(H, NOW + 100))[0] and "落云城" in (await br.list_for(H, NOW + 100))[0]


# ---- 清理 / 转世 ------------------------------------------------------------

async def test_清理机器人_它名下的请求跟着删(db, monkeypatch):
    from utils import bot_world
    await lent(db, monkeypatch)
    res = await bot_world.remove_bots(["bot_00001"])
    assert res["rows"]["bot_requests"] == 1 and await rows(db) == []


async def test_转世_旧角色的请求作废(db, monkeypatch):
    from utils.character_create_logic import commit_character
    await lent(db, monkeypatch)
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        (await s.get(D.Player, H)).is_dead = True
        await s.commit()
    assert await commit_character(H, "新名字", "男", {})
    assert await rows(db) == []


# ---- 界面 -------------------------------------------------------------------

async def test_开口面板_答应_婉拒(db, monkeypatch):
    offer = await offered(db, monkeypatch)
    me = FakeInteraction(user_id=int(H))
    view = rv.OfferView(offer, me.user)
    assert [c.label for c in view.children] == ["答应", "婉拒"]
    await next(c for c in view.children if c.label == "答应").callback(me)
    assert me.edited[-1].view is None and any("你答应了" in f.name for f in me.edited[-1].embed.fields)
    assert (await rows(db))[0].state == "active"
    j = FakeInteraction(user_id=int(H))
    await next(c for c in view.children if c.label == "婉拒").callback(j)
    assert j.response.said("已经答复过了")


async def test_开口面板_婉拒(db, monkeypatch):
    offer = await offered(db, monkeypatch)
    me = FakeInteraction(user_id=int(H))
    await next(c for c in rv.OfferView(offer, me.user).children if c.label == "婉拒").callback(me)
    assert (await rows(db))[0].state == "declined" and any("你婉拒了" in f.name for f in me.edited[-1].embed.fields)


async def test_开口面板_灵石不够时提示_面板收起(db, monkeypatch):
    offer = await offered(db, monkeypatch)
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        (await s.get(D.Player, H)).spirit_stones = 1
        await s.commit()
    me = FakeInteraction(user_id=int(H))
    await next(c for c in rv.OfferView(offer, me.user).children if c.label == "答应").callback(me)
    assert "不够" in me.edited[-1].embed.description


async def test_开口面板_别人点不动(db, monkeypatch):
    offer = await offered(db, monkeypatch)
    view = rv.OfferView(offer, FakeInteraction(user_id=int(H)).user)
    assert await view.interaction_check(FakeInteraction(user_id=7)) is False


def test_文字摘要():
    assert "借给它 **100** 灵石" in rv.offer_summary({"kind": "loan_stones", "params": {"amount": 100}})
    assert "送一封信" in rv.offer_summary({"kind": "errand", "params": {"city": "落云城", "target_name": "乙"}})
    assert "采药" in rv.offer_summary({"kind": "companion_gather", "params": {"what": "采药"}})
    assert rv.offer_summary({"kind": "未知", "params": {}}) == ""


def test_结算消息样式():
    e = rv.events_embed([{"kind": "repay", "bot_name": "甲", "line": "还你", "amount": 100}])
    assert e.title == "💰 还钱" and "收回 100 灵石" in e.description
    e = rv.events_embed([{"kind": "default", "bot_name": "甲", "line": "不记得了", "amount": 0}, {"kind": "errand_done", "bot_name": "乙", "line": "谢", "amount": 50}])
    assert "2 件事" in e.title and "酬劳 50" in e.description
    assert "仍欠 30" in rv.events_embed([{"kind": "short", "bot_name": "甲", "line": "x", "amount": 30}]).description


async def test_碰面钩子_有结算有开口就发_都没有就不发(db, monkeypatch):
    await pin_templates(monkeypatch, ["borrow_stones"])
    await mk_human(db)
    c = FakeContext(user_id=int(H))
    assert await rv.run_meet(c.send, c.author, ["bot_00001"]) is False and c.messages == []
    await mk_bot(db, "bot_00001", stones=0)
    await favor(db, "bot_00001", 40)

    async def ask(pid, bot, rng=None, now=None):
        return await _real_ask(pid, bot, Z(0.0), NOW)
    monkeypatch.setattr(br, "maybe_ask", ask)
    assert await rv.run_meet(c.send, c.author, ["bot_00001"]) is True
    assert c.last.embed.title.endswith("有事相求") and [b.label for b in c.last.view.children] == ["答应", "婉拒"]


_real_ask = br.maybe_ask


async def test_到城钩子_会结算借款(db, monkeypatch):
    from utils.views import chatter as cv
    amount, due = await lent(db, monkeypatch, "迂腐")
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        (await s.get(D.Player, "bot_00001")).spirit_stones = 5000
        (await s.get(D.Player, H)).last_active = time.time()
        await s.commit()
    monkeypatch.setattr(br, "repay_decision", lambda *a, **k: "repay")
    real = br.on_meet
    monkeypatch.setattr(br, "on_meet", lambda pid, present, rng=None, now=None: real(pid, present, rng, due + 10))
    c = FakeContext(user_id=int(H))
    assert await cv.run_arrive(c.send, c.author, CITY) is True
    assert any(m.embed is not None and m.embed.title == "💰 还钱" for m in c.messages)


async def test_委托命令(db, monkeypatch):
    from cogs.chatter import ChatterCog
    cog = ChatterCog(SimpleNamespace())
    c = FakeContext(user_id=int(H))
    await cog.requests.callback(cog, c)
    assert c.said("没有未了结的委托")
    await lent(db, monkeypatch)
    c = FakeContext(user_id=int(H))
    await cog.requests.callback(cog, c)
    assert c.said("未了结的委托") and c.said("借给")


# ---- 补：变异测试里发现的漏洞 -------------------------------------------------

def test_赖账概率每一项都起作用():
    dp = br.default_probability
    base = dp("豪爽", 50, 50, 50, "陌生")
    assert base == pytest.approx(0.06)
    assert dp("豪爽", 0, 50, 50, "陌生") == pytest.approx(base + 0.2)           # 不守序
    assert dp("豪爽", 50, 50, 100, "陌生") == pytest.approx(base + 0.2)         # 贪婪
    assert dp("贪财", 50, 100, 50, "陌生") == pytest.approx(0.35 - 1 / 6)       # 善良
    assert dp("贪财", 50, 50, 50, "至交") == pytest.approx(0.35 - 0.15)         # 交情深
    assert dp("豪爽", 50, 50, 50, "仇视") == pytest.approx(0.06 + 0.10)         # 仇视更容易赖
    assert dp("贪财", 0, 0, 100, "仇视") == 0.9 and dp("迂腐", 100, 100, 0, "至交") == 0.0


def test_多还的概率每一项都起作用():
    def decide(kindness, tier, second):
        rng = Seq(0.99, second)                                            # 第一个数 0.99：不赖账；第二个数决定要不要多还
        return br.repay_decision("豪爽", 50, kindness, 50, tier, rng)
    base = 0.35                                                            # 豪爽的感念底子
    assert decide(50, "陌生", base - 0.01) == "plus" and decide(50, "陌生", base + 0.01) == "repay"
    assert decide(100, "陌生", base + 0.2) == "plus" and decide(50, "陌生", base + 0.2) == "repay", "善良的更愿意多还"
    assert decide(50, "至交", base + 0.1) == "plus" and decide(50, "陌生", base + 0.1) == "repay", "交情深的更愿意多还"
    assert decide(0, "仇视", base - 0.2) == "repay", "仇视的人不会多还"


class Seq(random.Random):
    def __init__(self, *values):
        super().__init__(0)
        self.values, self.i = list(values), 0

    def random(self):
        v = self.values[min(self.i, len(self.values) - 1)]
        self.i += 1
        return v


async def test_请求冷却和未处理是两道独立的门(db, monkeypatch):
    cfg = await pin_templates(monkeypatch, ["borrow_stones"])
    await mk_human(db)
    D = db["db_async"]
    for b in ("bot_00001", "bot_00002"):
        await mk_bot(db, b, stones=0)
        await favor(db, b, 40)
    # 门一：上一个还在处理中（active 的借款没了结），哪怕过了冷却也不再开口
    o1 = await br.maybe_ask(H, "bot_00001", Z(0.0), NOW)
    await br.accept(o1["id"], R(1), NOW + 10)
    async with D.AsyncSessionLocal() as s:
        (await s.get(D.Player, H)).last_active = NOW + 30 * 3600
        (await s.get(D.Player, H)).spirit_stones = 5000
        await s.commit()
    assert await br.maybe_ask(H, "bot_00001", Z(0.0), NOW + 30 * 3600) is None
    # 门二：处理完了但还在冷却里（24 小时）
    o2 = await br.maybe_ask(H, "bot_00002", Z(0.0), NOW + 30 * 3600)
    await br.decline(o2["id"], R(1), NOW + 30 * 3600 + 5)
    assert await br.maybe_ask(H, "bot_00002", Z(0.0), NOW + 40 * 3600) is None, "刚被拒绝过，冷却中"
    async with D.AsyncSessionLocal() as s:
        (await s.get(D.Player, H)).last_active = NOW + 56 * 3600
        await s.commit()
    assert await br.maybe_ask(H, "bot_00002", Z(0.0), NOW + 56 * 3600), "过了冷却"


async def test_借物品_它喜欢的类别优先(db, monkeypatch):
    from utils.bot_social import category_of
    from utils.items import ITEMS
    await pin_templates(monkeypatch, ["borrow_item"])
    await mk_human(db)
    cheap = [n for n, v in sorted(ITEMS.items()) if (v.get("sell_price") or 0) and 0 < v["sell_price"] <= 400]
    liked = next(n for n in cheap if category_of(n) == "药材")
    other = next(n for n in cheap if category_of(n) != "药材")
    await db["inventory"].add_item(H, liked, 1)
    await db["inventory"].add_item(H, other, 1)
    await mk_bot(db, "bot_00001", stones=0, likes={"categories": ["药材"], "items": []})
    await favor(db, "bot_00001", 40)
    D = db["db_async"]
    tpl = br.load()["templates"]["borrow_item"]
    async with D.AsyncSessionLocal() as s:
        player, bot, persona = await s.get(D.Player, H), await s.get(D.Player, "bot_00001"), await s.get(D.BotPersonality, "bot_00001")
        picks = {(await br._feasible(s, "borrow_item", tpl, player, bot, persona, R(seed)))["item"] for seed in range(30)}
    assert picks == {liked}, "它喜欢药材，就总是挑药材，不会挑别的"


async def test_碰面时只有熟人会开口_陌生人在场不开口(db, monkeypatch):
    await pin_templates(monkeypatch, ["borrow_stones"])
    await mk_human(db)
    await mk_bot(db, "bot_00001", stones=0)                          # 陌生人，和玩家没有任何关系
    res = await br.on_meet(H, ["bot_00001"], Z(0.0), NOW)
    assert res["offer"] is None and await rows(db) == []
    await favor(db, "bot_00001", 40)
    assert (await br.on_meet(H, ["bot_00001"], Z(0.0), NOW))["offer"]


async def test_还钱要记进记忆(db, monkeypatch):
    from utils import bot_memory
    amount, due = await lent(db, monkeypatch, "迂腐")
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        (await s.get(D.Player, "bot_00001")).spirit_stones = 5000
        await s.commit()
    monkeypatch.setattr(br, "repay_decision", lambda *a, **k: "repay")
    await meet(now=due + 10)
    assert (await bot_memory.recall(H, "bot_00001"))["repaid"][0].extra == "repay"


async def test_点搭话按钮_当面聊时该还的还_熟人会开口(db, monkeypatch):
    from utils.views import bot_actions
    amount, due = await lent(db, monkeypatch, "迂腐")
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        (await s.get(D.Player, "bot_00001")).spirit_stones = 5000
        await s.commit()
    monkeypatch.setattr(br, "repay_decision", lambda *a, **k: "repay")
    real = br.on_meet
    monkeypatch.setattr(br, "on_meet", lambda pid, present, rng=None, now=None: real(pid, present, rng, due + 10))
    i = FakeInteraction(user_id=int(H))
    await bot_actions.BotChatButton({"discord_id": "bot_00001", "name": "机001"}).callback(i)
    assert any(m.embed is not None and m.embed.title == "💰 还钱" for m in i.followup.messages)


async def test_开始采集时_约好陪采集的机器人一起去(db, monkeypatch):
    from utils.views.gathering import GatherView
    await gather_accepted(db, monkeypatch)
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        (await s.get(D.Player, H)).current_city = CITY
        await s.commit()
    monkeypatch.setattr(br, "on_gather", lambda pid, city, rng=None, now=None: _gather_now(pid, city))
    i = FakeInteraction(user_id=int(H))
    v = GatherView(i.user, None, {"lifespan": 100, "current_city": CITY}, "采药", "百草谷")
    await next(b for b in v.children if b.years == 1).callback(i)
    assert any(m.embed is not None and m.embed.title == "🌿 一起采集" for m in i.followup.messages)


_real_gather = br.on_gather


async def _gather_now(pid, city):
    return await _real_gather(pid, city, R(1), NOW + 100)
