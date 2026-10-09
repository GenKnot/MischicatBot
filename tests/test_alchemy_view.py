"""炼丹面板（utils/views/alchemy.py）：丹方匹配、自由配药、确认开炉、结果卡片。炼丹结算本身见 test_alchemy.py。

B59 —— 自由配药的 `_ConfirmFreeMixButton.callback` 缺了 `except Exception as e:`（第一版就丢了）：
  · 每一次自由配药（成功也一样）结尾都会跑到 `log.exception("炼丹出错")`，日志里到处是假的 ERROR，
    之后 `f"炼丹出错：{e}"` 因为 `e` 未定义抛 NameError，被里层的 `except` 悄悄吞掉；
  · 真正出错时（数据库挂了、结算抛异常）没人接，玩家只看到『交互失败』，也没有任何错误提示。
B60 —— 炼丹失败的『损失寿元』（炉毁 / 丹毒反噬）在面板里是读 → 改 → 写回，开炉的两条路径各抄了一份：
  并发时会丢更新。抽成一个原子 UPDATE（寿元降到 0 同时置为坐化）。
B61 —— 结果卡片里『今日剩余次数』写死成 6，不是 `DAILY_LIMIT`。
"""

import asyncio
import logging
import time

import discord
import pytest

from tests.conftest import make_player
from tests.discord_fakes import FakeInteraction
from utils import alchemy as al
from utils.alchemy import DAILY_LIMIT, QUALITY_NAMES, RECIPES, get_recipe_by_id
from utils.views import alchemy as av
from utils.views.alchemy import (AlchemyMainView, _AshView, _AuxSelect, _AuxSelectView, _BackToMainButton,
                                 _ConfirmFreeMixButton, _ConfirmView, _FailView, _FreeMixHerbSelect, _FreeMixQtyView,
                                 _FreeMixSelectView, _KnownRecipeSelect, _KnownRecipeSelectView, _PlusOneButton,
                                 _all_herb_names_owned, _auto_match_recipe, _confirm_embed, _consume_all,
                                 _give_pill, _pill_tier_label, _qty_content, _quality_cap_label,
                                 _recipe_embed, _result_embed)

U = "1001"
EXAM = get_recipe_by_id("juqiwan_exam")
JL1 = get_recipe_by_id("juling_1")               # 灵芝草×1 + (碧灵花 | 九节菖蒲)
JL2 = get_recipe_by_id("juling_2")               # 灵芝草×2 + (碧灵花|九节菖蒲) + (甘草灵根|茯苓灵块)


async def _add(db, uid=U, items=None, level=1, **kw):
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        p = make_player(D, uid, stones=0)
        p.name = f"道友{uid}"
        p.alchemy_level, p.lifespan = level, 100
        for k, v in kw.items():
            setattr(p, k, v)
        s.add(p)
        for name, qty in (items or {}).items():
            s.add(D.Inventory(discord_id=uid, item_id=name, quantity=qty))
        await s.commit()


async def row(db, uid=U):
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        return await s.get(D.Player, uid)


async def inv(db, uid=U):
    return await db["inventory"].get_inventory(uid)


def inter(uid=U):
    return FakeInteraction(uid)


def player(**kw):
    base = dict(discord_id=U, alchemy_level=1, soul=5)
    base.update(kw)
    return base


def win(monkeypatch):
    monkeypatch.setattr(al.random, "randint", lambda a, b: a)


def lose(monkeypatch, consequence=("炉毁", 3)):
    monkeypatch.setattr(al.random, "randint", lambda a, b: 100)
    monkeypatch.setattr(al, "roll_failure_consequence", lambda: consequence)


# --- 纯函数 -------------------------------------------------------------------

def test_阶数与品质上限文案():
    assert _pill_tier_label(1) == "一阶" and _pill_tier_label(9) == "九阶" and _pill_tier_label(12) == "12阶"
    assert _quality_cap_label(11, True) == QUALITY_NAMES[11]
    assert _quality_cap_label(11, False) == QUALITY_NAMES[al.NO_YANHUO_CAP]
    assert _quality_cap_label(3, False) == QUALITY_NAMES[3]


def test_自动匹配_材料够的第一个丹方(monkeypatch):
    monkeypatch.setattr(av, "RECIPES", [JL1, JL2, EXAM])
    r, choices = _auto_match_recipe({"灵芝草": 2, "甘草灵根": 1}, 0)
    assert r["recipe_id"] == "juqiwan_exam" and choices == [0]
    r, choices = _auto_match_recipe({"灵芝草": 1, "九节菖蒲": 2}, 1)
    assert r["recipe_id"] == "juling_1" and choices == [1]            # 辅药取第一个够数的选项（碧灵花没有，九节菖蒲 ×2 够）


def test_自动匹配_品级不够_材料不够(monkeypatch):
    monkeypatch.setattr(av, "RECIPES", [JL1, JL2])
    r, _ = _auto_match_recipe({"灵芝草": 1, "碧灵花": 1}, 0)
    assert r is None                                                  # juling_1 需要 1 品
    assert _auto_match_recipe({"灵芝草": 1}, 5) == (None, [])
    assert _auto_match_recipe({}, 9) == (None, [])


def test_自动匹配_多余材料也能匹配_辅药不会重复占用主药(monkeypatch):
    monkeypatch.setattr(av, "RECIPES", [JL1, JL2])
    r, choices = _auto_match_recipe({"灵芝草": 2, "碧灵花": 1}, 1)
    assert r["recipe_id"] == "juling_1"                               # 靠前的丹方先中
    r, choices = _auto_match_recipe({"灵芝草": 1}, 1)
    assert r is None                                                  # 灵芝草已被主药用掉，辅药没有可选


def test_可投入药材_只列有持有的_按名字排序():
    names = _all_herb_names_owned({"灵芝草": 3, "碧灵花": 0, "九节菖蒲": 1, "无关物": 9}, 1)
    assert names == sorted(["灵芝草", "九节菖蒲"])
    assert _all_herb_names_owned({"灵芝草": 3}, 0) == ["灵芝草"]


def test_数量文案():
    text = _qty_content({"灵芝草": 2}, {"灵芝草": 5})
    assert "灵芝草 ×2" in text and "持有 5" in text and text.startswith("**已选药材")


def test_丹方卡片_标出材料够不够():
    e = _recipe_embed(JL1, player(), {"灵芝草": 1, "碧灵花": 0, "九节菖蒲": 2}, False)
    f = {x.name: x.value for x in e.fields}
    assert "（无异火）" in f["基本信息"] and "需要品级：1 品" in f["基本信息"] and "基础成功率：70%" in f["基本信息"]
    assert "✅ 灵芝草 ×1（持有 1）" in f["主药"]
    aux = next(v for k, v in f.items() if k.startswith("辅药组 1"))
    assert "❌ [1] 碧灵花" in aux and "✅ [2] 九节菖蒲 ×2" in aux


def test_丹方卡片_有异火不写无异火():
    e = _recipe_embed(JL1, player(), {}, True)
    assert "无异火" not in e.fields[0].value


async def test_确认卡片(db):
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        s.add(D.AlchemyMastery(discord_id=U, pill_name="聚灵丹", count=12))
        await s.commit()
    e = await _confirm_embed(JL1, player(), {}, [1], False)
    f = {x.name: x.value for x in e.fields}
    assert f["丹方"] == JL1["name"]
    assert f["熟练度"] == "熟悉（12次）" and "九节菖蒲 ×2（辅药组 1）" in f["消耗材料"] and f["成功率"].endswith("%")


def success_result(**kw):
    base = {"ok": True, "success": True, "pill": "聚灵丹", "quality_name": "常规", "daily_count": 2, "consumed": {"灵芝草": 1},
            "mastery_label": "生疏", "mastery_count": 1}
    base.update(kw)
    return base


def test_结果卡片_成功():
    e = _result_embed(success_result(first_unlock=True, leveled_up=True, alchemy_level=2), JL1, {"灵芝草": 5})
    assert e.title == "炼丹成功！" and "首次炼成" in e.description and "「常规聚灵丹」" in e.description
    f = {x.name: x.value for x in e.fields}
    assert f["今日剩余次数"] == f"{DAILY_LIMIT - 2}/{DAILY_LIMIT}" and "灵芝草 ×1（剩余 4）" in f["消耗材料"]
    assert "晋升为 2 品" in f["品级提升"]


@pytest.mark.parametrize("quality,color", [("无暇", 0xFFD700), ("三纹", 0x9B59B6), ("常规", 0x2ECC71)])
def test_结果卡片_品质颜色(quality, color):
    e = _result_embed(success_result(quality_name=quality), JL1, None)
    assert e.color.value == color and f"「{quality}聚灵丹」" in e.description
    assert not any(f.name == "消耗材料" and "剩余" in f.value for f in e.fields)           # 没给库存就不写剩余


def test_结果卡片_失败():
    e = _result_embed({"success": False, "consequence": "丹毒反噬", "lifespan_loss": 8, "daily_count": 6, "consumed": {"灵芝草": 2}},
                      JL1, {"灵芝草": 1})
    assert "丹毒反噬" in e.title and "寿元损失 8 年" in e.description and e.color.value == 0x8B0000
    assert next(f.value for f in e.fields if f.name == "今日剩余次数") == f"0/{DAILY_LIMIT}"
    assert "剩余 0" in next(f.value for f in e.fields if f.name == "消耗材料")             # 不会出现负数
    plain = _result_embed({"success": False, "daily_count": 1, "consumed": {}}, JL1, None)
    assert "普通失败" in plain.title and "寿元" not in plain.description


def test_B61_剩余次数用上限常量(monkeypatch):
    monkeypatch.setattr(av, "DAILY_LIMIT", 10)
    e = _result_embed(success_result(daily_count=3), JL1, None)
    assert next(f.value for f in e.fields if f.name == "今日剩余次数") == "7/10"


# --- 扣料 / 发丹 --------------------------------------------------------------

async def test_成组扣料_任一不足整体不扣(db):
    await _add(db, items={"灵芝草": 3, "碧灵花": 1})
    assert await _consume_all(U, {"灵芝草": 2, "碧灵花": 2}) is False
    assert await inv(db) == {"灵芝草": 3, "碧灵花": 1}
    assert await _consume_all(U, {"灵芝草": 2, "碧灵花": 1}) is True
    assert (await inv(db)).get("灵芝草") == 1


async def test_发丹_常规与带品质前缀(db):
    await _add(db)
    await _give_pill(U, "聚灵丹", "常规")
    await _give_pill(U, "聚灵丹", "常规")
    await _give_pill(U, "聚灵丹", "三纹")
    assert await inv(db) == {"聚灵丹": 2, "三纹聚灵丹": 1}


# --- 主面板 -------------------------------------------------------------------

def main_view(known=None, level=1, choices=None, **kw):
    return AlchemyMainView(inter().user, player(alchemy_level=level), False, set(known or []), cog=None,
                           known_choices=choices, **kw)


async def test_主面板_只有本人能点():
    assert await main_view().interaction_check(inter("2002")) is False


async def test_主面板_已知丹方按钮分支():
    i = inter()
    await main_view().known_recipes_btn.callback(i)
    assert "还没有掌握任何丹方" in i.last and i.last.ephemeral
    high = max(RECIPES, key=lambda r: r["alchemy_level_req"])
    i = inter()
    await main_view(known=[high["recipe_id"]], level=1).known_recipes_btn.callback(i)           # 高品丹方，玩家 1 品
    assert "没有符合当前品级" in i.last
    i = inter()
    await main_view(known=["juling_1"]).known_recipes_btn.callback(i)
    sv = i.last.view
    assert isinstance(sv, _KnownRecipeSelectView) and i.last.content == "选择已知丹方："
    assert [o.value for o in next(c for c in sv.children if isinstance(c, _KnownRecipeSelect)).options] == ["juling_1"]


async def test_主面板_自由配药按钮(db):
    await _add(db, items={"灵芝草": 3})
    i = inter()
    await main_view().free_mix_btn.callback(i)
    assert isinstance(i.last.view, _FreeMixSelectView) and "自由配药" in i.last.content


async def test_主面板_返回技艺():
    i = inter()
    await main_view().back_crafting_btn.callback(i)
    assert i.last.embed is not None and i.last.view is not None


# --- 已知丹方 -----------------------------------------------------------------

async def pick_known(db, recipe_id, saved=None, items=None, uid=U):
    sv = _KnownRecipeSelectView(inter().user, player(), False, [get_recipe_by_id(recipe_id)], saved or {}, cog=None)
    sel = next(c for c in sv.children if isinstance(c, _KnownRecipeSelect))
    sel._values = [recipe_id]
    i = inter(uid)
    await sel.callback(i)
    return i


async def test_已知丹方_材料不足(db):
    await _add(db, items={"灵芝草": 1})
    i = await pick_known(db, "juling_1", {"juling_1": [0]})
    assert "材料不足" in i.last and "碧灵花 ×1" in i.last and i.last.ephemeral


async def test_已知丹方_材料够进入确认_用保存的辅药选择(db):
    await _add(db, items={"灵芝草": 1, "九节菖蒲": 2})
    i = await pick_known(db, "juling_1", {"juling_1": [1]})
    assert isinstance(i.last.view, _ConfirmView) and "九节菖蒲 ×2" in i.last.content and "碧灵花" not in i.last.content


async def test_已知丹方_保存的选择不全时补0(db):
    await _add(db, items={"灵芝草": 2, "碧灵花": 1, "甘草灵根": 1})
    i = await pick_known(db, "juling_2", {"juling_2": []})
    assert isinstance(i.last.view, _ConfirmView) and i.last.view.choices == [0, 0]


# --- 辅药选择 -----------------------------------------------------------------

async def test_辅药逐组选择_最后一组后进入确认(db):
    await _add(db, items={"灵芝草": 2, "碧灵花": 1, "甘草灵根": 1})
    v = _AuxSelectView(inter().user, player(discord_id=U), False, JL2, {"灵芝草": 2, "碧灵花": 1, "甘草灵根": 1}, [])
    sel = next(c for c in v.children if isinstance(c, _AuxSelect))
    assert sel.group_idx == 0 and [o.value for o in sel.options] == ["0", "1"] and "持有 1" in sel.options[0].description
    sel._values = ["0"]
    i = inter()
    await sel.callback(i)
    nxt = i.last.view
    assert isinstance(nxt, _AuxSelectView) and nxt.choices_so_far == [0]
    sel2 = next(c for c in nxt.children if isinstance(c, _AuxSelect))
    assert sel2.group_idx == 1
    sel2._values = ["1"]
    i = inter()
    await sel2.callback(i)
    assert isinstance(i.last.view, _ConfirmView) and i.last.view.choices == [0, 1] and "确认开炉" in i.last.embed.title


def test_辅药选择_已选完时不再有下拉():
    v = _AuxSelectView(inter().user, player(), False, JL1, {}, [0])
    assert not [c for c in v.children if isinstance(c, _AuxSelect)]


# --- 确认开炉 -----------------------------------------------------------------

def confirm_view(recipe=JL1, choices=(0,), inventory=None, lv=1, soul=5):
    return _ConfirmView(inter().user, player(alchemy_level=lv, soul=soul), False, recipe, inventory or {"灵芝草": 5, "碧灵花": 5},
                        list(choices), cog=None)


async def brew(v, uid=U):
    i = inter(uid)
    await v.confirm.callback(i)
    return i


async def test_开炉_成功_给丹_扣料_记录丹方(db, monkeypatch):
    await _add(db, items={"灵芝草": 3, "碧灵花": 3})
    win(monkeypatch)
    i = await brew(confirm_view())
    assert i.response.deferred and "炼丹成功" in i.edited[-1].embed.title and i.edited[-1].view is None
    items = await inv(db)
    assert items["灵芝草"] == 2 and items["碧灵花"] == 2 and any("聚灵丹" in k for k in items)
    assert "juling_1" in await al.get_known_recipes(U)


async def test_开炉_失败_有失败面板_损失寿元(db, monkeypatch):
    await _add(db, items={"灵芝草": 3, "碧灵花": 3})
    lose(monkeypatch, ("炉毁", 3))
    i = await brew(confirm_view())
    assert "炼丹失败" in i.edited[-1].embed.title and isinstance(i.edited[-1].view, _FailView)
    assert (await row(db)).lifespan == 97 and not (await row(db)).is_dead


async def test_开炉_失败到寿元耗尽_坐化(db, monkeypatch):
    await _add(db, items={"灵芝草": 3, "碧灵花": 3}, lifespan=3)
    lose(monkeypatch, ("丹毒反噬", 8))
    await brew(confirm_view())
    p = await row(db)
    assert p.lifespan == 0 and p.is_dead


async def test_开炉_材料不足_如实提示(db):
    await _add(db, items={"灵芝草": 0})
    i = await brew(confirm_view(inventory={"灵芝草": 0}))
    assert "主药不足" in i.last and i.last.ephemeral


async def test_开炉_次数用尽_材料退回(db):
    await _add(db, items={"灵芝草": 3, "碧灵花": 3}, alchemy_daily_count=DAILY_LIMIT, alchemy_daily_reset=time.time())
    i = await brew(confirm_view())
    assert "已达上限" in i.last and (await inv(db))["灵芝草"] == 3


async def test_开炉_一次点击一炉(db, monkeypatch):
    await _add(db, items={"灵芝草": 5, "碧灵花": 5})
    win(monkeypatch)
    v = confirm_view()
    a, b = await asyncio.gather(brew(v), brew(v))
    assert (await inv(db))["灵芝草"] == 4
    assert len([i for i in (a, b) if "已经开了" in (i.last.content or "")]) == 1


async def test_开炉_取消():
    v = confirm_view()
    i = inter()
    await v.cancel.callback(i)
    assert "已取消炼丹" in i.last and v.is_finished()


async def test_B60_并发失败扣寿元不丢更新(db, monkeypatch):
    await _add(db, items={"灵芝草": 9, "碧灵花": 9})
    lose(monkeypatch, ("炉毁", 2))
    await asyncio.gather(*[brew(confirm_view()) for _ in range(5)])
    assert (await row(db)).lifespan == 100 - 2 * 5


# --- 失败 / 灰烬面板 ----------------------------------------------------------

async def test_失败面板_继续与返回(db):
    await _add(db, items={"灵芝草": 1})
    v = _FailView(inter().user, player(), False, cog=None)
    i = inter()
    await v.continue_btn.callback(i)
    assert isinstance(i.last.view, AlchemyMainView) and i.last.content == "炼丹台："
    i = inter()
    await v.back_btn.callback(i)
    assert i.last.embed is not None


async def test_灰烬面板_继续与返回(db):
    await _add(db, items={"灵芝草": 1})
    v = _AshView(inter().user, player(), False, {}, cog=None)
    i = inter()
    await v.continue_btn.callback(i)
    assert isinstance(i.last.view, _FreeMixSelectView) and "自由配药" in i.last.content
    i = inter()
    await v.back_btn.callback(i)
    assert isinstance(i.last.view, AlchemyMainView)


async def test_返回炼丹台按钮(db):
    await _add(db)
    v = _FreeMixSelectView(inter().user, player(), False, {}, cog=None)
    btn = next(c for c in v.children if isinstance(c, _BackToMainButton))
    i = inter()
    await btn.callback(i)
    assert isinstance(i.last.view, AlchemyMainView)


# --- 自由配药 -----------------------------------------------------------------

def test_自由配药_没有药材时没有下拉():
    v = _FreeMixSelectView(inter().user, player(), False, {}, cog=None)
    assert not [c for c in v.children if isinstance(c, _FreeMixHerbSelect)]


def test_自由配药_下拉最多5种_25个选项():
    inventory = {h: 1 for h in _all_herb_names_owned({r["main_ingredients"][0]["item"]: 1 for r in RECIPES}, 9)}
    v = _FreeMixSelectView(inter().user, player(alchemy_level=9), False, inventory, cog=None)
    sel = next(c for c in v.children if isinstance(c, _FreeMixHerbSelect))
    assert len(sel.options) <= 25 and sel.max_values <= 5


async def test_自由配药_选药后进入数量面板_加一不超过持有(db):
    inventory = {"灵芝草": 2, "碧灵花": 1}
    v = _FreeMixSelectView(inter().user, player(), False, inventory, cog=None)
    sel = next(c for c in v.children if isinstance(c, _FreeMixHerbSelect))
    sel._values = ["灵芝草", "碧灵花"]
    i = inter()
    await sel.callback(i)
    qv = i.last.view
    assert isinstance(qv, _FreeMixQtyView) and qv.qty_map == {"灵芝草": 1, "碧灵花": 1}
    plus = {c.item: c for c in qv.children if isinstance(c, _PlusOneButton)}
    i = inter()
    await plus["灵芝草"].callback(i)
    assert qv.qty_map["灵芝草"] == 2 and "灵芝草 ×2" in i.last.content
    i = inter()
    await plus["灵芝草"].callback(i)
    assert qv.qty_map["灵芝草"] == 2 and "已达上限" in i.last and i.last.ephemeral
    i = inter()
    await plus["碧灵花"].callback(i)
    assert "已达上限" in i.last


def qty_view(qty_map, inventory=None, lv=1):
    return _FreeMixQtyView(inter().user, player(alchemy_level=lv), False, inventory or dict(qty_map), qty_map, cog=None)


async def fire(v, uid=U):
    btn = next(c for c in v.children if isinstance(c, _ConfirmFreeMixButton))
    i = inter(uid)
    await btn.callback(i)
    return i


async def test_自由配药_没有匹配丹方_变成灰烬_材料照扣(db):
    await _add(db, items={"灵芝草": 1, "金丝草": 1})
    i = await fire(qty_view({"灵芝草": 1, "金丝草": 1}))
    assert "灰烬" in i.edited[-1].content and isinstance(i.edited[-1].view, _AshView)
    assert await inv(db) == {"灵芝草": 0, "金丝草": 0} or not any((await inv(db)).values())


async def test_自由配药_灰烬时药材不足(db):
    await _add(db, items={"灵芝草": 1})
    i = await fire(qty_view({"灵芝草": 1, "金丝草": 1}, {"灵芝草": 1, "金丝草": 1}))
    assert "药材不足" in i.edited[-1].content and (await inv(db))["灵芝草"] == 1


async def test_自由配药_匹配丹方并成功(db, monkeypatch):
    await _add(db, items={"灵芝草": 2, "甘草灵根": 1})
    win(monkeypatch)
    i = await fire(qty_view({"灵芝草": 2, "甘草灵根": 1}, lv=1))
    assert "炼丹成功" in i.edited[-1].embed.title
    items = await inv(db)
    assert items.get("灵芝草", 0) == 0 and items.get("甘草灵根", 0) == 0 and any("聚气丸" in k for k in items)


async def test_自由配药_匹配丹方失败_损失寿元(db, monkeypatch):
    await _add(db, items={"灵芝草": 2, "甘草灵根": 1})
    lose(monkeypatch, ("炉毁", 4))
    i = await fire(qty_view({"灵芝草": 2, "甘草灵根": 1}))
    assert isinstance(i.edited[-1].view, _FailView) and (await row(db)).lifespan == 96


async def test_自由配药_结算被拒_转述原因(db):
    await _add(db, items={"灵芝草": 2, "甘草灵根": 1}, alchemy_daily_count=DAILY_LIMIT, alchemy_daily_reset=time.time())
    i = await fire(qty_view({"灵芝草": 2, "甘草灵根": 1}))
    assert "已达上限" in i.edited[-1].content and i.edited[-1].view is None


async def test_自由配药_运转中再点_被拒(db):
    v = qty_view({"灵芝草": 1})
    v._firing = True
    i = await fire(v)
    assert "丹炉运转中" in i.last and i.last.ephemeral


async def test_B59_成功的自由配药不该留下假的错误日志(db, monkeypatch, caplog):
    await _add(db, items={"灵芝草": 2, "甘草灵根": 1})
    win(monkeypatch)
    with caplog.at_level(logging.DEBUG, logger="utils.views.alchemy"):
        await fire(qty_view({"灵芝草": 2, "甘草灵根": 1}))
    assert not [r for r in caplog.records if r.levelno >= logging.ERROR], [r.getMessage() for r in caplog.records]
    assert not [r for r in caplog.records if "炼丹报错消息发送失败" in r.getMessage()]


async def test_B59_结算抛异常_玩家看到错误提示并可再试(db, monkeypatch, caplog):
    await _add(db, items={"灵芝草": 2, "甘草灵根": 1})

    async def boom(**kw):
        raise RuntimeError("数据库挂了")
    monkeypatch.setattr(al, "attempt_alchemy", boom)
    v = qty_view({"灵芝草": 2, "甘草灵根": 1})
    with caplog.at_level(logging.ERROR, logger="utils.views.alchemy"):
        i = await fire(v)
    assert "炼丹出错：数据库挂了" in i.edited[-1].content and v._firing is False
    assert [r for r in caplog.records if r.levelno >= logging.ERROR and "炼丹出错" in r.getMessage()]


async def test_B59_出错提示发不出去也不抛(db, monkeypatch):
    await _add(db, items={"灵芝草": 2, "甘草灵根": 1})

    async def boom(**kw):
        raise RuntimeError("x")
    monkeypatch.setattr(al, "attempt_alchemy", boom)
    v = qty_view({"灵芝草": 2, "甘草灵根": 1})
    btn = next(c for c in v.children if isinstance(c, _ConfirmFreeMixButton))
    i = inter()

    async def expired(**kw):
        raise discord.HTTPException(type("R", (), {"status": 404, "reason": "x"})(), "interaction expired")
    i.edit_original_response = expired
    await btn.callback(i)
    assert v._firing is False


def test_自动匹配_主药占用后辅药只能用剩下的(monkeypatch):
    recipe = {"recipe_id": "x", "alchemy_level_req": 0, "main_ingredients": [{"item": "甲", "qty": 2}],
              "aux_groups": [{"desc": "d", "options": [{"item": "甲", "qty": 1}, {"item": "乙", "qty": 1}]}]}
    monkeypatch.setattr(av, "RECIPES", [recipe])
    assert _auto_match_recipe({"甲": 2}, 0) == (None, [])                 # 主药已经用掉 2 个甲，辅药没得选
    assert _auto_match_recipe({"甲": 3}, 0)[1] == [0]
    assert _auto_match_recipe({"甲": 2, "乙": 1}, 0)[1] == [1]
