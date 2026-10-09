"""万宝楼竞拍界面测试（utils/views/wanbao.py、utils/views/wanbao_public.py）。

玩家在这里出价、上架、查看拍品。出价按钮背后是 `place_bid`，涉及灵石的托管与退款
（出价即扣、被超越即退，见 ISSUES.md B19），所以每个出价入口都要验证**账上的灵石**，而不只是界面文字。

结构：A 展示函数  B 主面板  C 公开竞价面板  D 私人竞价面板  E 上架表单  F 公共事件里的万宝楼入口
"""

import asyncio
import json
import time
import types

import pytest

from tests.conftest import make_player
from tests.discord_fakes import FakeInteraction
from utils.events.public import wanbao as wb
from utils.views.wanbao import (
    BidView, ListItemModal, PublicBidView, WanbaoMainView, _fmt_stat_bonus, _item_display,
    build_lot_embed, build_lots_list_embed,
)

CITY = "万宝楼"


async def _add_player(db, uid, city=CITY, stones=100_000, **fields):
    D = db["db_async"]
    p = make_player(D, uid, stones=stones)
    p.name = f"道友{uid}"
    p.current_city = city
    for k, v in fields.items():
        setattr(p, k, v)
    async with D.AsyncSessionLocal() as s:
        s.add(p)
        await s.commit()


async def _stones(db, uid):
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        return (await s.get(D.Player, uid)).spirit_stones


async def _sql(db, sql, **params):
    from sqlalchemy import text
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        res = await s.execute(text(sql), params)
        await s.commit()
        return res


async def _auction(db, status="active", start=True):
    a = await wb.get_or_create_auction("2026-10-09")
    if start and status == "active":
        await wb.start_auction(a["auction_id"])
    elif status != "pending":
        await _sql(db, "UPDATE wanbao_auctions SET status=:s WHERE auction_id=:a", s=status, a=a["auction_id"])
    return a["auction_id"]


async def _current_lot(aid):
    return await wb.get_current_lot(aid)


def it(uid="1"):
    return FakeInteraction(user_id=int(uid))


def pe_cog(cultivation_cog=None):
    cogs = {"Cultivation": cultivation_cog} if cultivation_cog else {}
    return types.SimpleNamespace(bot=types.SimpleNamespace(cogs=cogs))


def lot_dict(**over):
    base = {"lot_id": "L1", "auction_id": "A", "lot_index": 0, "seller_id": None, "item_name": "灵芝草",
            "quantity": 1, "item_type": "item", "start_price": 100, "current_bid": 0, "bidder_id": None,
            "status": "pending", "eq_data": None}
    base.update(over)
    return base


# =============================================================================
# A. 展示函数
# =============================================================================

@pytest.mark.parametrize("item_type,tag", [("technique", "📜"), ("equipment", "⚔️"), ("item", "📦")])
def test_拍品名带类型图标(item_type, tag):
    assert _item_display(lot_dict(item_type=item_type)) == f"{tag} 灵芝草"


def test_数量大于一时显示数量():
    assert _item_display(lot_dict(quantity=3)) == "📦 灵芝草 ×3"


def test_属性加成格式_整数加值_小数按百分比_未知键原样():
    s = _fmt_stat_bonus({"comprehension": 3, "cultivation_speed": 0.15, "神秘属性": 2})
    assert "悟性 +3" in s and "修炼速度 +15%" in s and "神秘属性 +2" in s
    assert _fmt_stat_bonus({}) == "无"


def test_拍品卡片_当前出价为零时显示起拍价_有出价者时显示他():
    e = build_lot_embed(lot_dict(start_price=500), time.time() + 125, 0, 8)
    f = {x.name: x.value for x in e.fields}
    assert f["起拍价"] == "500 灵石" and f["当前出价"] == "**500 灵石**" and f["出价者"] == "暂无出价"
    assert f["卖家"] == "万宝楼" and e.title.startswith("✦ 第 1/8 件")
    assert f["剩余时间"].startswith("2分")

    e2 = build_lot_embed(lot_dict(start_price=500, current_bid=900, bidder_id="9", seller_id="7"), time.time() + 10, 2, 8)
    f2 = {x.name: x.value for x in e2.fields}
    assert f2["当前出价"] == "**900 灵石**" and f2["出价者"] == "<@9>" and f2["卖家"] == "<@7>"


def test_拍品卡片_剩余时间不会为负():
    e = build_lot_embed(lot_dict(), time.time() - 999, 0, 1)
    assert {x.name: x.value for x in e.fields}["剩余时间"] == "0分00秒"


def test_拍品卡片_功法():
    from utils.sects import TECHNIQUES
    name, info = next(iter(TECHNIQUES.items()))
    e = build_lot_embed(lot_dict(item_type="technique", item_name=name), time.time() + 60, 0, 1)
    f = {x.name: x.value for x in e.fields}
    assert f["品级"] == info.get("grade", "未知") and "装备加成" in f


def test_拍品卡片_装备():
    eq = {"flavor": "寒光凛冽", "quality": "稀有", "slot": "weapon", "stats": {"comprehension": 2}}
    e = build_lot_embed(lot_dict(item_type="equipment", item_name="寒铁剑", eq_data=json.dumps(eq)), time.time() + 60, 0, 1)
    f = {x.name: x.value for x in e.fields}
    assert e.description == "寒光凛冽" and "稀有" in f["品质"] and "悟性 +2" in f["属性"]


def test_拍品卡片_装备数据缺失也不崩():
    e = build_lot_embed(lot_dict(item_type="equipment", item_name="x", eq_data=None), time.time() + 60, 0, 1)
    assert {x.name: x.value for x in e.fields}["属性"] == "无"


def test_拍品卡片_普通物品带稀有度():
    from utils.items import ITEMS
    name = next(k for k, v in ITEMS.items() if v.get("rarity") == "稀有")
    e = build_lot_embed(lot_dict(item_name=name), time.time() + 60, 0, 1)
    assert "稀有" in {x.name: x.value for x in e.fields}["稀有度"]


def test_拍品一览_各状态的措辞():
    lots = [
        lot_dict(lot_index=0, status="sold", current_bid=700),
        lot_dict(lot_index=1, status="unsold"),
        lot_dict(lot_index=2, status="active", current_bid=0, start_price=300),
        lot_dict(lot_index=3, status="pending", start_price=400, seller_id="9"),
        lot_dict(lot_index=1, status="pending"),                           # 序号小于当前、却还是 pending → 已结束
    ]
    e = build_lots_list_embed({"current_lot": 2}, lots)
    values = [f.value for f in e.fields]
    assert "✅ 已成交 700 灵石" in values[0] and "❌ 流拍" in values[1]
    assert "🔴 竞拍中 · 当前 300 灵石" in values[2]
    assert "起拍 400 灵石" in values[3] and "玩家上架" in values[3]
    assert "已结束" in values[4]


# =============================================================================
# B. 主面板
# =============================================================================

def main_view(cog=None):
    return WanbaoMainView(types.SimpleNamespace(id=1), cog)


async def test_主面板_查看拍品_没有拍卖(db):
    i = it()
    await main_view().view_lots.callback(i)
    assert i.said("当前没有进行中的拍卖") and i.last.ephemeral


async def test_主面板_查看拍品_给出一览(db):
    await _auction(db)
    i = it()
    await main_view().view_lots.callback(i)
    assert "拍品一览" in i.last.embed.title and len(i.last.embed.fields) == 8


async def test_主面板_当前拍品出价_门槛(db):
    i = it()
    await main_view().bid_current.callback(i)
    assert i.said("尚未创建角色")

    await _add_player(db, "1", city="灵虚城")
    i = it()
    await main_view().bid_current.callback(i)
    assert i.said("需在万宝楼城内")

    await _sql(db, "UPDATE players SET current_city='万宝楼' WHERE discord_id='1'")
    i = it()
    await main_view().bid_current.callback(i)
    assert i.said("拍卖尚未开始")                                           # 没有任何拍卖

    await _auction(db, "pending")
    i = it()
    await main_view().bid_current.callback(i)
    assert i.said("拍卖尚未开始")                                           # 有但还没开始


async def test_主面板_当前拍品出价_没有进行中的拍品(db):
    await _add_player(db, "1")
    aid = await _auction(db)
    await _sql(db, "UPDATE wanbao_lots SET status='pending' WHERE auction_id=:a", a=aid)
    i = it()
    await main_view().bid_current.callback(i)
    assert i.said("当前无进行中的拍品")


async def test_主面板_当前拍品出价_给出私人竞价面板(db):
    await _add_player(db, "1")
    aid = await _auction(db)
    i = it()

    await main_view().bid_current.callback(i)

    assert isinstance(i.last.view, BidView) and i.last.ephemeral
    assert i.last.view.auction_id == aid and i.last.view.lot_index == 0 and i.last.view.total == 8
    assert "第 1/8 件" in i.last.embed.title


async def test_主面板_上架_门槛(db):
    i = it()
    await main_view().list_item_btn.callback(i)
    assert i.said("尚未创建角色")

    await _add_player(db, "1", city="灵虚城")
    i = it()
    await main_view().list_item_btn.callback(i)
    assert i.said("需在万宝楼城内")

    await _sql(db, "UPDATE players SET current_city='万宝楼' WHERE discord_id='1'")
    i = it()
    await main_view().list_item_btn.callback(i)
    assert i.said("当前没有拍卖活动")

    await _auction(db)                                                       # 已经开拍
    i = it()
    await main_view().list_item_btn.callback(i)
    assert i.said("拍卖已开始，无法继续上架")


async def test_主面板_上架_已达个人上限被拒_否则弹出表单(db):
    await _add_player(db, "1")
    aid = await _auction(db, "pending")
    i = it()
    await main_view().list_item_btn.callback(i)
    assert isinstance(i.modal, ListItemModal) and i.modal.auction_id == aid

    for n in range(wb.MAX_PLAYER_LOTS):
        await _sql(db, "INSERT INTO wanbao_lots (lot_id, auction_id, lot_index, seller_id, item_name, quantity, item_type, start_price) "
                       "VALUES (:l, :a, :i, '1', 'x', 1, 'item', 1)", l=f"s{n}", a=aid, i=100 + n)
    i = it()
    await main_view().list_item_btn.callback(i)
    assert i.said("最多上架") and i.modal is None


async def test_主面板_返回主菜单(db):
    for cog in (None, pe_cog(None)):
        i = it()
        await main_view(cog).back_menu.callback(i)
        assert i.said("无法返回")


# =============================================================================
# C. 公开竞价面板（拍卖会广播消息上的按钮，人人可出价）
# =============================================================================

async def _public(db, uid="1", stones=100_000, city=CITY):
    await _add_player(db, uid, city=city, stones=stones)
    aid = await _auction(db)
    lot = await _current_lot(aid)
    return aid, lot, PublicBidView(aid, lot["lot_index"], 8)


def bid_button(view, label):
    return next(b for b in view.children if b.label == label)


async def test_公开竞价_是公共面板_超时等于一件拍品的时长(db):
    view = PublicBidView("a", 0, 8)
    assert view.public is True and view.timeout == wb.LOT_DURATION
    assert [b.label for b in view.children] == ["+10", "+100", "+200", "+500", "+1000"]


@pytest.mark.parametrize("label,inc", [("+10", 10), ("+100", 100), ("+200", 200), ("+500", 500), ("+1000", 1000)])
async def test_公开竞价_首次出价是起拍价加增量_灵石当场扣走(db, label, inc):
    aid, lot, view = await _public(db)
    i = it()

    await bid_button(view, label).callback(i)

    after = await _current_lot(aid)
    assert after["current_bid"] == lot["start_price"] + inc and after["bidder_id"] == "1"
    assert await _stones(db, "1") == 100_000 - (lot["start_price"] + inc)           # 托管：出价即扣
    m = i.last
    assert any(f.name == "最新出价" and "道友1" in f.value and str(lot["start_price"] + inc) in f.value for f in m.embed.fields)


async def test_公开竞价_后续出价在当前价上加_被超越者当场退款(db):
    aid, lot, view = await _public(db)
    await _add_player(db, "2")
    p = lot["start_price"]

    await bid_button(view, "+100").callback(it("1"))
    await bid_button(view, "+100").callback(it("2"))                                # 在 p+100 的基础上再加

    after = await _current_lot(aid)
    assert after["current_bid"] == p + 200 and after["bidder_id"] == "2"
    assert await _stones(db, "1") == 100_000, "被超越的人应当立即全额退款"
    assert await _stones(db, "2") == 100_000 - (p + 200)


async def test_公开竞价_自己连续加价只补差额(db):
    aid, lot, view = await _public(db)
    p = lot["start_price"]
    await bid_button(view, "+100").callback(it())
    await bid_button(view, "+500").callback(it())
    assert await _stones(db, "1") == 100_000 - (p + 600)


async def test_公开竞价_没有角色(db):
    aid = await _auction(db)
    view = PublicBidView(aid, 0, 8)
    i = it("9")
    await bid_button(view, "+10").callback(i)
    assert i.said("尚未创建角色")


async def test_公开竞价_不在万宝楼不能出价(db):
    aid, lot, view = await _public(db, city="灵虚城")
    i = it()
    await bid_button(view, "+10").callback(i)
    assert i.said("需在万宝楼城内") and (await _current_lot(aid))["bidder_id"] is None
    assert await _stones(db, "1") == 100_000


async def test_公开竞价_这一件已经结束(db):
    aid, lot, view = await _public(db)
    await _sql(db, "UPDATE wanbao_lots SET status='sold' WHERE lot_id=:l", l=lot["lot_id"])
    i = it()
    await bid_button(view, "+10").callback(i)
    assert i.said("此拍品已结束") and i.last.ephemeral


async def test_公开竞价_灵石不足被拒_账不动(db):
    aid, lot, view = await _public(db, stones=5)
    i = it()
    await bid_button(view, "+10").callback(i)
    assert i.said("灵石不足") and (await _current_lot(aid))["bidder_id"] is None
    assert await _stones(db, "1") == 5


async def test_公开竞价_用的是旧面板_拍卖已经走到下一件(db):
    """广播消息上的按钮是绑定到某一件的：那一件结束后再点，提示已结束，不会去给下一件出价。"""
    aid, lot, view = await _public(db)
    await wb.settle_lot(lot)
    await wb.advance_lot(aid)
    i = it()
    await bid_button(view, "+10").callback(i)
    assert i.said("此拍品已结束")
    assert (await _current_lot(aid))["bidder_id"] is None and await _stones(db, "1") == 100_000


async def test_公开竞价_不能对自己上架的拍品出价(db):
    await _add_player(db, "77")
    aid = await _auction(db, "pending")
    await _sql(db, "DELETE FROM wanbao_lots WHERE auction_id=:a", a=aid)
    await _sql(db, "INSERT INTO wanbao_lots (lot_id, auction_id, lot_index, seller_id, item_name, quantity, item_type, start_price) "
                   "VALUES ('mine', :a, 0, '77', '灵芝草', 1, 'item', 100)", a=aid)
    await wb.start_auction(aid)
    i = it("77")
    await bid_button(PublicBidView(aid, 0, 1), "+10").callback(i)
    assert i.said("不能对自己的拍品出价")


async def test_公开竞价_两人同时点同一个增量_只有一个成功_另一个分文不动(db):
    aid, lot, view = await _public(db)
    await _add_player(db, "2")
    p = lot["start_price"]
    a, b = it("1"), it("2")

    await asyncio.gather(bid_button(view, "+100").callback(a), bid_button(view, "+100").callback(b))

    after = await _current_lot(aid)
    winner, loser = (("1", "2") if after["bidder_id"] == "1" else ("2", "1"))
    assert after["current_bid"] == p + 100
    assert await _stones(db, winner) == 100_000 - (p + 100)
    assert await _stones(db, loser) == 100_000
    # 输家看到的是『已有更高出价』（抢占失败）或『出价不得低于』（读到了赢家刚写入的价），都是正确的拒绝
    refused = [x for x in (a, b) if x.said("更高出价") or x.said("不得低于")]
    assert len(refused) == 1


async def test_公开竞价_出价后把灵石转走也无用_货款早已扣下(db):
    """B19 在界面层的体现：从按钮出价，到结算，得标者实实在在付了钱。"""
    aid, lot, view = await _public(db, stones=100_000)
    await bid_button(view, "+1000").callback(it())
    paid = lot["start_price"] + 1000
    await _sql(db, "UPDATE players SET spirit_stones = 0 WHERE discord_id='1'")     # 剩下的全转走

    result = await wb.settle_lot(await _current_lot(aid))

    assert result["winner_id"] == "1" and result["final_price"] == paid
    assert await _stones(db, "1") == 0                                              # 没有再被扣、也没有凭空多出


# =============================================================================
# D. 私人竞价面板（从主面板进来的、仅自己可见的那个）
# =============================================================================

async def _private(db, uid="1", stones=100_000):
    await _add_player(db, uid, stones=stones)
    aid = await _auction(db)
    lot = await _current_lot(aid)
    auction_ends = (await wb.get_active_auction())["ends_at"]
    return aid, lot, BidView(types.SimpleNamespace(id=int(uid)), aid, lot, auction_ends, lot["lot_index"], 8, None)


async def test_私人竞价_出价成功_刷新拍品卡片_灵石当场扣走(db):
    aid, lot, view = await _private(db)
    i = it()

    await bid_button(view, "+200").callback(i)

    p = lot["start_price"] + 200
    assert (await _current_lot(aid))["current_bid"] == p and await _stones(db, "1") == 100_000 - p
    f = {x.name: x.value for x in i.last.embed.fields}
    assert f["当前出价"] == f"**{p} 灵石**" and f["出价者"] == "<@1>"


async def test_私人竞价_被超越退款_自己加价补差额(db):
    aid, lot, view = await _private(db)
    await _add_player(db, "2")
    p = lot["start_price"]
    await bid_button(view, "+10").callback(it("1"))
    other = BidView(types.SimpleNamespace(id=2), aid, lot, 0, 0, 8, None)
    await bid_button(other, "+100").callback(it("2"))                                # p+10 之上 +100
    assert await _stones(db, "1") == 100_000
    await bid_button(view, "+500").callback(it("1"))                                 # 1 号从 p+110 加到 p+610，全额付一次
    assert await _stones(db, "1") == 100_000 - (p + 610)
    assert await _stones(db, "2") == 100_000                                         # 2 号又被超越，退回


async def test_私人竞价_拍品已结束(db):
    aid, lot, view = await _private(db)
    await _sql(db, "UPDATE wanbao_lots SET status='sold' WHERE lot_id=:l", l=lot["lot_id"])
    i = it()
    await bid_button(view, "+10").callback(i)
    assert i.said("此拍品已结束")


async def test_私人竞价_灵石不足被拒(db):
    aid, lot, view = await _private(db, stones=1)
    i = it()
    await bid_button(view, "+10").callback(i)
    assert i.said("灵石不足") and await _stones(db, "1") == 1


async def test_私人竞价_五个增量按钮(db):
    aid, lot, view = await _private(db)
    assert [b.label for b in view.children] == ["+10", "+100", "+200", "+500", "+1000"]
    assert view.timeout == wb.LOT_DURATION


# =============================================================================
# E. 上架表单
# =============================================================================

def modal(auction_id, name="灵芝草", qty="2", price="500"):
    m = ListItemModal(auction_id)
    m.item_name._value = name
    m.quantity._value = qty
    m.start_price._value = price
    return m


async def test_上架表单_数量或价格不是整数(db):
    for qty, price in [("abc", "500"), ("2", "五百"), ("", "")]:
        i = it()
        await modal("a", qty=qty, price=price).on_submit(i)
        assert i.said("必须是整数")


async def test_上架表单_数量或价格不大于零(db):
    for qty, price in [("0", "500"), ("2", "0"), ("-1", "500")]:
        i = it()
        await modal("a", qty=qty, price=price).on_submit(i)
        assert i.said("必须大于0")


async def test_上架表单_成功_扣手续费扣物品_并提示取回费(db):
    await _add_player(db, "1", stones=1000)
    await db["inventory"].add_item("1", "灵芝草", 5)
    aid = await _auction(db, "pending")
    i = it()

    await modal(aid, name=" 灵芝草 ", qty="2", price="500").on_submit(i)          # 名称两侧的空格会被去掉

    assert i.said("已上架「灵芝草」×2") and i.said(f"{wb.LISTING_FEE}")
    assert await _stones(db, "1") == 1000 - wb.LISTING_FEE
    assert (await db["inventory"].get_inventory("1")).get("灵芝草") == 3


async def test_上架表单_失败时原样告知原因(db):
    await _add_player(db, "1", stones=1000)
    aid = await _auction(db, "pending")
    i = it()
    await modal(aid, name="不存在的东西").on_submit(i)
    assert i.said("未知物品")

    i = it()
    await modal(aid, name="灵芝草").on_submit(i)
    assert i.said("数量不足")


# =============================================================================
# F. 公共事件里的万宝楼入口（utils/views/wanbao_public.py）
# =============================================================================

from utils.views import wanbao_public as wp


def event_button(cog=None):
    return wp._WanbaoEventButton(cog)


async def test_入口_没有拍卖时显示今日举行(db):
    i = it()
    await event_button().callback(i)
    f = {x.name: x.value for x in i.last.embed.fields}
    assert "等待开始" in f["今日状态"] and "拍品数量" not in f and i.last.ephemeral
    assert isinstance(i.last.view, wp._WanbaoDetailView)


async def test_入口_拍卖待开始与进行中(db):
    aid = await _auction(db, "pending")
    i = it()
    await event_button().callback(i)
    f = {x.name: x.value for x in i.last.embed.fields}
    assert "等待开始" in f["今日状态"] and "20:00" in f["今日状态"] and f["拍品数量"] == "**8** 件"

    await wb.start_auction(aid)
    i = it()
    await event_button().callback(i)
    f = {x.name: x.value for x in i.last.embed.fields}
    assert "进行中" in f["今日状态"] and "当前拍品剩余" in f["今日状态"]


def detail_view(cog=None, auction=None):
    return wp._WanbaoDetailView(types.SimpleNamespace(id=1), cog, auction)


@pytest.mark.parametrize("button", ["detail", "travel_button"])
async def test_前往万宝楼_各种拦截与成功(db, button):
    async def click(uid="1"):
        i = it(uid)
        if button == "detail":
            await detail_view().travel.callback(i)
        else:
            await wp._WanbaoTravelButton().callback(i)
        return i

    assert (await click()).said("尚未创建角色")

    await _add_player(db, "1", city=CITY)
    assert (await click()).said("你已在万宝楼")

    now = time.time()
    for field, value, phrase in [("cultivating_until", now + 999, "闭关"), ("gathering_until", now + 999, "采集"),
                                 ("active_quest", "{}", "任务")]:
        await _sql(db, "UPDATE players SET current_city='灵虚城', cultivating_until=NULL, gathering_until=NULL, "
                       "active_quest=NULL WHERE discord_id='1'")
        await _sql(db, f"UPDATE players SET {field}=:v WHERE discord_id='1'", v=value)
        i = await click()
        assert i.said(phrase) and i.said("无法移动")

    await _sql(db, "UPDATE players SET current_city='灵虚城', cultivating_until=NULL, gathering_until=NULL, "
                   "active_quest=NULL WHERE discord_id='1'")
    i = await click()
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        assert (await s.get(D.Player, "1")).current_city == CITY
    assert i.said("已传送至 **万宝楼**")


async def test_进入拍卖_门槛(db):
    i = it()
    await detail_view(pe_cog()).enter_auction.callback(i)
    assert i.said("尚未创建角色")

    await _add_player(db, "1", city="灵虚城")
    i = it()
    await detail_view(pe_cog()).enter_auction.callback(i)
    assert i.said("需先前往 **万宝楼**")

    await _sql(db, "UPDATE players SET current_city='万宝楼' WHERE discord_id='1'")
    i = it()
    await detail_view(None).enter_auction.callback(i)
    assert i.said("系统暂时不可用")


async def test_进入拍卖_没有拍卖时按今天建一场并显示待开始(db):
    await _add_player(db, "1")
    i = it()

    await detail_view(pe_cog()).enter_auction.callback(i)

    assert isinstance(i.last.view, WanbaoMainView)
    assert "等待开始" in i.last.embed.description and "**8** 件" in i.last.embed.description
    assert any(f.name == "开始时间" for f in i.last.embed.fields)
    assert (await _sql(db, "SELECT COUNT(*) FROM wanbao_auctions")).scalar() == 1


async def test_进入拍卖_进行中不显示开始时间(db):
    await _add_player(db, "1")
    await _auction(db)
    i = it()
    await detail_view(pe_cog()).enter_auction.callback(i)
    assert "进行中" in i.last.embed.description and not any(f.name == "开始时间" for f in i.last.embed.fields)


async def test_进入拍卖_今日拍卖已结束_显示上次记录(db):
    await _add_player(db, "1")
    await _add_player(db, "b")
    from utils.views.wanbao_public import WANBAO_TRIGGER_HOUR
    from datetime import datetime
    from zoneinfo import ZoneInfo
    today = datetime.now(ZoneInfo("America/Montreal")).strftime("%Y-%m-%d")
    a = await wb.get_or_create_auction(today)
    lots = await wb.get_lots(a["auction_id"])
    await _sql(db, "UPDATE wanbao_auctions SET status='ended', started_at=:t WHERE auction_id=:a", t=time.time() - 100, a=a["auction_id"])
    await _sql(db, "UPDATE wanbao_lots SET status='sold', bidder_id='b', current_bid=300 WHERE lot_id=:l", l=lots[0]["lot_id"])
    await _sql(db, "UPDATE wanbao_lots SET status='unsold' WHERE auction_id=:a AND lot_id != :l", a=a["auction_id"], l=lots[0]["lot_id"])
    i = it()

    await detail_view(pe_cog()).enter_auction.callback(i)

    rec = next(f for f in i.last.embed.fields if f.name == "上次拍卖记录").value
    assert "道友b · 300 灵石" in rec and rec.count("流拍") == 7
    assert f"{WANBAO_TRIGGER_HOUR}:00" in next(f for f in i.last.embed.fields if f.name == "今日状态").value


async def test_详情面板_返回公共事件总览(db):
    from utils.views.public_event_overview import PublicEventOverviewView
    await _sql(db, "INSERT INTO public_events (event_id, event_type, title, started_at, ends_at, status, data) "
                   "VALUES ('e','spirit_rain','天降灵雨',:t,:t2,'active','{\"city\":\"铁甲城\"}')", t=time.time() - 10, t2=time.time() + 600)
    i = it()
    await detail_view(pe_cog()).back.callback(i)
    assert isinstance(i.last.view, PublicEventOverviewView) and i.last.view.active["event_id"] == "e"


def test_万宝楼说明里公布的规则_与实现一致():
    """说明文字是玩家看到的规则；其中两条曾经与代码不符（B19 出价不冻结、B20 流拍不退物品）。
    这里钉住关键数字，免得改了规则忘了改说明，或反过来。"""
    d = wp.WANBAO_DESC
    assert "出价时灵石自动冻结，被超越后立即解冻" in d
    assert f"**{wb.LISTING_FEE} 灵石** 手续费" in d and f"**{wb.LISTING_FEE} 灵石** 取回费" in d
    assert f"**{int(wb.AUCTION_COMMISSION * 100)}%**" in d and f"最多上架 **{wb.MAX_PLAYER_LOTS} 件**" in d
    assert f"全场上限 **{wb.MAX_LOTS} 件**" in d and f"**{wb.LOT_DURATION // 60} 分钟**" in d
