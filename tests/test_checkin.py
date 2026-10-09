"""每日签到（utils/checkin.py、utils/views/checkin.py）。

B54 —— `data/checkin_config.json` 里灵石奖励的档位区间重叠：二档 501–2500，三档却从 1501 开始。
  档位按顺序是 1–500 / 501–1500 / 1501–3000 / 3001–6000，二档的上限明显写成了 2500（应为 1500），
  结果二档的平均奖励是 1500 而不是 1000，整体灵石期望被抬高。改为 501–1500，并加测试保证档位首尾相接。
"""

import asyncio
import json
import time

import pytest

from tests.conftest import make_player
from tests.discord_fakes import FakeInteraction
from utils import checkin as ck
from utils.checkin import CONFIG, do_checkin
from utils.items import ITEMS
from utils.sects import TECHNIQUES
from utils.views.checkin import CheckinView, _checkin_result_embed

U = "1001"
TODAY = lambda: time.strftime("%Y-%m-%d", time.gmtime())  # noqa: E731


async def _add(db, uid=U, **kw):
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        p = make_player(D, uid, stones=0)
        p.name = f"道友{uid}"
        for k, v in kw.items():
            setattr(p, k, v)
        s.add(p)
        await s.commit()


async def row(db, uid=U):
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        return await s.get(D.Player, uid)


def force(monkeypatch, category, **picks):
    """固定奖励类别（以及档位 / 条目）。"""
    monkeypatch.setattr(ck.random, "choices",
                        lambda pop, weights=None, k=1: [category] if pop == list(CONFIG["category_weights"]) else [pop[picks.get("tier", 0)]])


# --- 配置合法性 ---------------------------------------------------------------

def test_配置_类别权重齐全():
    assert set(CONFIG["category_weights"]) == {"spirit_stones", "material", "technique", "equipment"}
    assert all(w > 0 for w in CONFIG["category_weights"].values())


def test_B54_灵石档位首尾相接不重叠():
    tiers = CONFIG["spirit_stones"]["tiers"]
    for a, b in zip(tiers, tiers[1:]):
        assert a["max"] + 1 == b["min"], f"{a['label']} 与 {b['label']} 区间重叠或有空隙：{a['min']}-{a['max']} / {b['min']}-{b['max']}"
    assert tiers[0]["min"] >= 1 and all(t["min"] <= t["max"] and t["weight"] > 0 for t in tiers)


def test_配置_材料池里的物品都存在():
    for tier in CONFIG["material"]["tiers"]:
        assert tier["pool"] and tier["weight"] > 0
        for name in tier["pool"]:
            assert name in ITEMS, f"签到材料「{name}」不在物品表里"


def test_配置_功法档位都有候选():
    grades = {t.get("grade") for t in TECHNIQUES.values()}
    for tier in CONFIG["technique"]["tiers"]:
        assert set(tier["grades"]) <= grades, tier
        assert any(t.get("grade") in tier["grades"] for t in TECHNIQUES.values())


def test_配置_装备品质合法():
    from utils.equipment import QUALITY_ORDER
    assert {t["quality"] for t in CONFIG["equipment"]["tiers"]} <= set(QUALITY_ORDER)


def test_配置_灵石期望在合理范围():
    tiers = CONFIG["spirit_stones"]["tiers"]
    ev = sum(t["weight"] * (t["min"] + t["max"]) / 2 for t in tiers) / sum(t["weight"] for t in tiers)
    assert 300 < ev < 2000, ev


# --- 签到逻辑 -----------------------------------------------------------------

async def test_签到_没有角色(db):
    assert await do_checkin(U) == {"ok": False, "reason": "角色不存在。"}


async def test_签到_灵石(db, monkeypatch):
    await _add(db)
    force(monkeypatch, "spirit_stones", tier=1)
    monkeypatch.setattr(ck.random, "randint", lambda a, b: b)
    r = await do_checkin(U)
    tier = CONFIG["spirit_stones"]["tiers"][1]
    assert r["ok"] and r["category"] == "spirit_stones" and r["spirit_stones"] == tier["max"] and r["tier_label"] == tier["label"]
    p = await row(db)
    assert p.spirit_stones == tier["max"] and p.checkin_last_date == TODAY()


async def test_签到_材料入背包(db, monkeypatch):
    await _add(db)
    force(monkeypatch, "material", tier=2)
    monkeypatch.setattr(ck.random, "choice", lambda pool: pool[0])
    r = await do_checkin(U)
    name = CONFIG["material"]["tiers"][2]["pool"][0]
    assert r["item_name"] == name and (await db["inventory"].get_inventory(U)) == {name: 1}


async def test_签到_新功法加入列表(db, monkeypatch):
    await _add(db, techniques=json.dumps(["旧功法"], ensure_ascii=False))
    force(monkeypatch, "technique", tier=0)
    monkeypatch.setattr(ck.random, "choice", lambda pool: pool[0])
    r = await do_checkin(U)
    assert r["already_known"] is False
    assert json.loads((await row(db)).techniques) == ["旧功法", r["technique"]]
    grade = TECHNIQUES[r["technique"]]["grade"]
    assert grade in CONFIG["technique"]["tiers"][0]["grades"]


async def test_签到_已会的功法不重复加入(db, monkeypatch):
    tier_grades = CONFIG["technique"]["tiers"][0]["grades"]
    only = [n for n, t in TECHNIQUES.items() if t.get("grade") in tier_grades]
    await _add(db, techniques=json.dumps(only, ensure_ascii=False))             # 该档位的全会了
    force(monkeypatch, "technique", tier=0)
    r = await do_checkin(U)
    assert r["already_known"] is True and json.loads((await row(db)).techniques) == only


async def test_签到_装备入库(db, monkeypatch):
    await _add(db)
    force(monkeypatch, "equipment", tier=3)
    r = await do_checkin(U)
    [e] = await db["equipment_db"].get_equipment_list(U)
    assert r["equipment"]["quality"] == "史诗" and e["equip_id"] == r["equipment"]["equip_id"] and e["equipped"] is False


async def test_签到_每天只能一次(db, monkeypatch):
    await _add(db)
    force(monkeypatch, "spirit_stones")
    monkeypatch.setattr(ck.random, "randint", lambda a, b: 100)
    assert (await do_checkin(U))["ok"]
    r = await do_checkin(U)
    assert not r["ok"] and "今日已签到" in r["reason"] and (await row(db)).spirit_stones == 100


async def test_签到_昨天签过今天可以再签(db, monkeypatch):
    await _add(db, checkin_last_date="2000-01-01")
    force(monkeypatch, "spirit_stones")
    assert (await do_checkin(U))["ok"] and (await row(db)).checkin_last_date == TODAY()


async def test_签到_并发连点只发一次奖(db, monkeypatch):
    await _add(db)
    force(monkeypatch, "spirit_stones")
    monkeypatch.setattr(ck.random, "randint", lambda a, b: 100)
    results = await asyncio.gather(*[do_checkin(U) for _ in range(8)])
    assert len([r for r in results if r["ok"]]) == 1 and (await row(db)).spirit_stones == 100


async def test_签到_每个类别真实跑一遍不报错(db):
    for n, cat in enumerate(CONFIG["category_weights"]):
        uid = f"u{n}"
        await _add(db, uid)
        import utils.checkin as m
        orig = m.random.choices

        def pick(pop, weights=None, k=1, _cat=cat, _orig=orig):
            return [_cat] if pop == list(CONFIG["category_weights"]) else _orig(pop, weights=weights, k=k)
        m.random.choices = pick
        try:
            r = await do_checkin(uid)
        finally:
            m.random.choices = orig
        assert r["ok"] and r["category"] == cat


# --- 结果卡片 / 面板 ----------------------------------------------------------

def test_卡片_失败():
    e = _checkin_result_embed({"ok": False, "reason": "今日已签到，明日再来。"}, {})
    assert e.description == "今日已签到，明日再来。" and not e.fields


@pytest.mark.parametrize("result,title,text", [
    ({"ok": True, "category": "spirit_stones", "spirit_stones": 321}, "灵石", "+321"),
    ({"ok": True, "category": "material", "item_name": "铜矿石"}, "材料", "铜矿石"),
    ({"ok": True, "category": "technique", "technique": "某功法", "already_known": False}, "功法", "已自动加入功法列表"),
    ({"ok": True, "category": "technique", "technique": "某功法", "already_known": True}, "功法", "化为感悟"),
    ({"ok": True, "category": "equipment", "equipment": {"name": "剑", "slot": "武器", "quality": "普通", "tier": 0,
                                                         "tier_req": 0, "stats": {"physique": 1}, "flavor": ""}}, "装备", "剑"),
    ({"ok": True, "category": "mystery"}, "mystery", None),
])
def test_卡片_各类别(result, title, text):
    e = _checkin_result_embed(result, {})
    assert title in e.title and e.footer.text == "明日可再次签到"
    if text:
        assert text in e.description


def inter(uid=U):
    return FakeInteraction(uid)


async def test_面板_签到按钮_成功后换成返回按钮(db, monkeypatch):
    await _add(db)
    force(monkeypatch, "spirit_stones")
    monkeypatch.setattr(ck.random, "randint", lambda a, b: 100)
    v = CheckinView(inter().user, {"discord_id": U}, None)
    i = inter()
    await v.checkin_btn.callback(i)
    assert all(c.disabled for c in v.children)                                  # 先禁用，防连点
    msg = i.edited[-1]
    assert "灵石" in msg.embed.title and len(msg.view.children) == 1 and msg.view.children[0].label == "返回城市"
    assert (await row(db)).spirit_stones == 100


async def test_面板_今日已签_显示原因(db):
    await _add(db, checkin_last_date=TODAY())
    v = CheckinView(inter().user, {}, None)
    i = inter()
    await v.checkin_btn.callback(i)
    assert "今日已签到" in i.edited[-1].embed.description


async def test_面板_返回城市(db):
    await _add(db)
    v = CheckinView(inter().user, {}, None)
    i = inter()
    await v.checkin_btn.callback(i)
    back = i.edited[-1].view.children[0]
    i2 = inter()
    await back.callback(i2)
    assert i2.last.embed is not None and i2.last.view is not None


async def test_面板_只有本人能点(db):
    v = CheckinView(inter().user, {}, None)
    other = inter("2002")
    assert await v.interaction_check(other) is False


async def test_面板_连点两次只发一次奖(db, monkeypatch):
    await _add(db)
    force(monkeypatch, "spirit_stones")
    monkeypatch.setattr(ck.random, "randint", lambda a, b: 100)
    v = CheckinView(inter().user, {}, None)
    a, b = inter(), inter()
    await asyncio.gather(v.checkin_btn.callback(a), v.checkin_btn.callback(b))
    assert (await row(db)).spirit_stones == 100


async def test_签到_功法优先发没学过的(db, monkeypatch):
    tier_grades = CONFIG["technique"]["tiers"][0]["grades"]
    names = [n for n, t in TECHNIQUES.items() if t.get("grade") in tier_grades]
    await _add(db, techniques=json.dumps(names[:-1], ensure_ascii=False))       # 只剩最后一本没学
    force(monkeypatch, "technique", tier=0)
    monkeypatch.setattr(ck.random, "choice", lambda pool: pool[0])
    r = await do_checkin(U)
    assert r["technique"] == names[-1] and r["already_known"] is False


async def test_签到_档位没有候选功法时退回全部功法(db, monkeypatch):
    await _add(db)
    monkeypatch.setitem(CONFIG["technique"]["tiers"][0], "grades", ["不存在的品级"])
    force(monkeypatch, "technique", tier=0)
    r = await do_checkin(U)
    assert r["ok"] and r["technique"] in TECHNIQUES
