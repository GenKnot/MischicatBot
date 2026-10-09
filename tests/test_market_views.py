"""交易坊面板（utils/views/market.py）。账务本身见 test_market.py。

B37 —— 筛选里「矿石」的键是 `material`，但物品表里矿石的类型是 `ore`，选了永远是『暂无商品』。
B38 —— 上架表单把价格标成『单价』，实际 `list_item` 把它当整笔挂单的总价、买家付的就是这个数：
  按单价填的卖家，50 个只卖了一个的价钱。
"""

import time

import pytest

from tests.conftest import make_player
from tests.discord_fakes import FakeInteraction
from utils import market
from utils.views import market as mv
from utils.views.market import (BuyModal, ClaimModal, DelistModal, ITEM_TYPE_LABELS, ListEquipModal, ListEquipView,
                                ListItemModal, ListItemView, ListTypeView, MarketBackButton, MarketBuyButton,
                                MarketFilterSelect, MarketListButton, MarketMainView, MarketMyStallButton,
                                MarketPageButton, MyStallView, PAGE_SIZE, _get_listings_with_names, _listing_line,
                                _market_main_embed, _my_listings_embed)

S, B = "1001", "1002"
HERB, ORE, PILL = "灵芝草", "铜矿石", "筑基丹"


async def _add(db, uid, stones=100_000, city="灵虚城"):
    D = db["db_async"]
    p = make_player(D, uid, stones=stones)
    p.name = f"道友{uid}"
    p.current_city = city
    async with D.AsyncSessionLocal() as s:
        s.add(p)
        await s.commit()


async def stones(db, uid):
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        return (await s.get(D.Player, uid)).spirit_stones


@pytest.fixture
async def world(db):
    await _add(db, S)
    await _add(db, B)
    for it in (HERB, ORE, PILL):
        await db["inventory"].add_item(S, it, 20)
    return db


def inter(uid=S):
    return FakeInteraction(uid)


def author(uid=S):
    return inter(uid).user


def filled(modal, **values):
    for k, v in values.items():
        getattr(modal, k)._value = v
    return modal


def footer(i):
    return i.edited[-1].embed.footer.text


async def main_view(uid=S, page=0, ftype="all"):
    player = await mv._get_player(uid)
    listings = await _get_listings_with_names(ftype)
    return MarketMainView(author(uid), player, listings, page, ftype, None)


def row(i, **kw):
    now = time.time()
    base = dict(listing_id=f"id{i:06d}", item_name=f"物{i}", quantity=1, price=100, seller_id="9999999",
                expires_at=now + 5 * 3600 + 60, status="active", item_type="item", item_id=HERB)
    base.update(kw)
    return base


# --- 文案 ---------------------------------------------------------------------

def test_挂单行_数量大于1才显示乘号_过期标记_卖家名():
    assert "×3" in _listing_line(row(1, quantity=3)) and "×" not in _listing_line(row(1))
    assert "⏰已过期" in _listing_line(row(1, expires_at=time.time() - 1))
    assert "5h" in _listing_line(row(1))
    assert " · 999999" in _listing_line(row(1)) and "999999" not in _listing_line(row(1), show_seller=False)
    assert "老张" in _listing_line(row(1, seller_name="老张"))


def test_主界面_分页文案():
    rows = [row(i) for i in range(PAGE_SIZE + 3)]
    e1 = _market_main_embed({"spirit_stones": 1234}, rows, 0, "all")
    e2 = _market_main_embed({"spirit_stones": 1234}, rows, 1, "all")
    assert "1,234" in e1.description and "第1/2页" in e1.fields[0].name and "第2/2页" in e2.fields[0].name
    assert len(e1.fields[0].value.splitlines()) == PAGE_SIZE and len(e2.fields[0].value.splitlines()) == 3


def test_主界面_没有商品():
    e = _market_main_embed({}, [], 0, "herb")
    assert e.fields[0].value == "暂无商品"


def test_我的摊位_只列在售的_过期的单独列出():
    e = _my_listings_embed({"spirit_stones": 5}, [row(1), row(2, status="sold"), row(3, status="expired")],
                           [row(3, status="expired", quantity=2)])
    f = {x.name: x.value for x in e.fields}
    assert "物1" in f["在售中"] and "物2" not in f["在售中"] and "物3" not in f["在售中"]
    assert "待领回" in f["⏰ 已过期（待领回）"] and "×2" in f["⏰ 已过期（待领回）"]
    assert _my_listings_embed({}, [], []).fields[0].value == "暂无"


# --- 筛选 ---------------------------------------------------------------------

async def test_筛选_每个类型都能筛到对应物品(world):
    """B37：矿石以前键是 material，永远筛不到。"""
    for it in (HERB, ORE, PILL):
        assert (await market.list_item(S, it, 1, 100))["ok"]
    from utils.items import ITEMS
    for key in ITEM_TYPE_LABELS:
        if key in ("all", "equipment"):
            continue
        got = [x["item_id"] for x in await _get_listings_with_names(key)]
        assert got == [i for i in (HERB, ORE, PILL) if ITEMS[i]["type"] == key], key


async def test_筛选_全部与装备(world):
    await market.list_item(S, HERB, 1, 100)
    D = world["db_async"]
    async with D.AsyncSessionLocal() as s:
        s.add(D.Equipment(equip_id="eq000001", discord_id=S, name="剑", slot="武器", quality="稀有", tier=1,
                          tier_req=0, stats="{}", flavor="", equipped=False))
        await s.commit()
    await market.list_equipment(S, "eq000001", 100)
    assert len(await _get_listings_with_names("all")) == 2
    assert [x["item_type"] for x in await _get_listings_with_names("equipment")] == ["equipment"]


def test_筛选标签的键都对应真实的物品类型():
    from utils.items import ITEMS
    real = {v.get("type") for v in ITEMS.values()}
    assert set(ITEM_TYPE_LABELS) - {"all", "equipment"} <= real


async def test_筛选下拉_选择后刷新(world):
    await market.list_item(S, ORE, 1, 100)
    v = await main_view()
    sel = next(c for c in v.children if isinstance(c, MarketFilterSelect))
    sel._values = ["ore"]
    i = inter()
    await sel.callback(i)
    assert "矿石" in i.last.embed.fields[0].name and "铜矿石" in i.last.embed.fields[0].value
    assert i.last.view.filter_type == "ore"


# --- 主界面按钮与分页 ---------------------------------------------------------

async def test_只有本人能操作(world):
    v = await main_view()
    i = inter(B)
    assert await v.interaction_check(i) is False and i.last.ephemeral


async def test_分页按钮_首页没有上一页_末页没有下一页(world):
    rows = [row(i) for i in range(PAGE_SIZE + 1)]
    mk = lambda page: MarketMainView(author(), {}, rows, page, "all", None)
    labels = lambda v: [getattr(c, "label", None) for c in v.children]
    assert "◀ 上一页" not in labels(mk(0)) and "下一页 ▶" in labels(mk(0))
    assert "◀ 上一页" in labels(mk(1)) and "下一页 ▶" not in labels(mk(1))


async def test_分页按钮_翻页(world):
    rows = [row(i) for i in range(PAGE_SIZE * 2 + 1)]
    v = MarketMainView(author(), {}, rows, 1, "all", None)
    nxt = next(c for c in v.children if isinstance(c, MarketPageButton) and c.direction == "next")
    prv = next(c for c in v.children if isinstance(c, MarketPageButton) and c.direction == "prev")
    i = inter()
    await nxt.callback(i)
    assert i.last.view.page == 2
    i = inter()
    await prv.callback(i)
    assert i.last.view.page == 0


async def test_翻页不会越界(world):
    v = MarketMainView(author(), {}, [row(1)], 0, "all", None)
    btn = MarketPageButton("下一页", "next")
    btn._view = v
    i = inter()
    await btn.callback(i)
    assert i.last.view.page == 0
    btn = MarketPageButton("上一页", "prev")
    btn._view = v
    await btn.callback(inter())


async def test_购买按钮弹表单_我的摊位_上架_返回(world):
    v = await main_view()
    i = inter()
    await next(c for c in v.children if isinstance(c, MarketBuyButton)).callback(i)
    assert isinstance(i.modal, BuyModal)

    i = inter()
    await next(c for c in v.children if isinstance(c, MarketMyStallButton)).callback(i)
    assert isinstance(i.last.view, MyStallView) and "我的摊位" in i.last.embed.title

    i = inter()
    await next(c for c in v.children if isinstance(c, MarketListButton)).callback(i)
    assert isinstance(i.last.view, ListTypeView)

    i = inter()
    await next(c for c in v.children if isinstance(c, MarketBackButton)).callback(i)
    assert i.last.embed is not None and not isinstance(i.last.view, MarketMainView)


# --- 购买 ---------------------------------------------------------------------

async def test_购买表单_成功(world):
    lid = (await market.list_item(S, HERB, 2, 1000))["listing_id"]
    m = filled(BuyModal(author(B), None), listing_id_input=f" {lid} ")
    i = inter(B)
    await m.on_submit(i)
    assert "购买 **灵芝草** 成功" in footer(i) and "手续费 80" in footer(i) and i.response.deferred
    assert await stones(world, B) == 99_000 and isinstance(i.edited[-1].view, MarketMainView)


async def test_购买表单_失败转述原因(world):
    m = filled(BuyModal(author(B), None), listing_id_input="nope")
    i = inter(B)
    await m.on_submit(i)
    assert "已下架或不存在" in i.last and i.last.ephemeral and not i.edited


# --- 上架 ---------------------------------------------------------------------

async def test_上架类型选择_背包与装备与返回(world):
    v = ListTypeView(author(), None)
    i = inter()
    await v.view_inv_btn.callback(i)
    assert isinstance(i.last.view, ListItemView) and "灵芝草" in i.last.embed.fields[0].value
    i = inter()
    await v.view_eq_btn.callback(i)
    assert isinstance(i.last.view, ListEquipView)
    i = inter()
    await v.back_btn.callback(i)
    assert isinstance(i.last.view, MarketMainView)


async def test_背包列表_空背包与超过30种(db):
    await _add(db, S)
    e = await mv._inventory_embed(S)
    assert e.fields[0].value == "空空如也"
    for n in range(35):
        await db["inventory"].add_item(S, f"item{n}", 1)
    e = await mv._inventory_embed(S)
    assert len(e.fields[0].value.splitlines()) == 30 and "共 35 种" in e.footer.text


async def test_装备列表_未装备可上架_已装备锁定(db):
    await _add(db, S)
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        for eid, eq in (("eq000001", False), ("eq000002", True)):
            s.add(D.Equipment(equip_id=eid, discord_id=S, name=f"剑{eid[-1]}", slot="武器", quality="稀有", tier=1,
                              tier_req=0, stats='{"attack": 3}', flavor="", equipped=eq))
        await s.commit()
    e = await mv._equipment_list_embed(S)
    f = {x.name: x.value for x in e.fields}
    assert "eq000001" in f["可上架（复制ID填入上架表单）"] and "eq000002" not in f["可上架（复制ID填入上架表单）"]
    assert "剑2" in f["已装备（不可上架）"]
    await _add(db, B)
    assert {x.name: x.value for x in (await mv._equipment_list_embed(B)).fields}["可上架"] == "暂无未装备的装备"


async def test_上架子面板按钮(world):
    for cls, modal in ((ListItemView, ListItemModal), (ListEquipView, ListEquipModal)):
        v = cls(author(), None)
        i = inter()
        await v.list_btn.callback(i)
        assert isinstance(i.modal, modal)
        i = inter()
        await v.back_btn.callback(i)
        assert isinstance(i.last.view, ListTypeView)


async def test_上架物品表单_成功(world):
    m = filled(ListItemModal(author(), None), item_id_input=f" {HERB} ", qty_input="4", price_input="1,500")
    i = inter()
    await m.on_submit(i)
    assert "已上架，编号" in footer(i) and (await world["inventory"].get_inventory(S))[HERB] == 16
    [lst] = await market.get_active_listings()
    assert lst["quantity"] == 4 and lst["price"] == 1500


@pytest.mark.parametrize("qty,price", [("x", "100"), ("1", "abc"), ("1.5", "100"), ("", "")])
async def test_上架物品表单_非数字被拒(world, qty, price):
    m = filled(ListItemModal(author(), None), item_id_input=HERB, qty_input=qty, price_input=price)
    i = inter()
    await m.on_submit(i)
    assert "请输入有效数字" in i.last and await market.get_active_listings() == []


async def test_上架物品表单_失败转述原因(world):
    m = filled(ListItemModal(author(), None), item_id_input=HERB, qty_input="99", price_input="100")
    i = inter()
    await m.on_submit(i)
    assert "背包物品不足" in i.last and i.last.ephemeral


async def test_上架物品表单_价格标签是总价而不是单价(world):
    """B38。"""
    assert "总价" in ListItemModal(author(), None).price_input.label
    assert "单价" not in ListItemModal(author(), None).price_input.label


async def test_上架装备表单(world):
    D = world["db_async"]
    async with D.AsyncSessionLocal() as s:
        s.add(D.Equipment(equip_id="eq000001", discord_id=S, name="剑", slot="武器", quality="稀有", tier=1,
                          tier_req=0, stats="{}", flavor="", equipped=False))
        await s.commit()
    m = filled(ListEquipModal(author(), None), equip_id_input="eq000001", price_input="800")
    i = inter()
    await m.on_submit(i)
    assert "装备已上架" in footer(i)

    m = filled(ListEquipModal(author(), None), equip_id_input="eq000001", price_input="x")
    i = inter()
    await m.on_submit(i)
    assert "请输入有效数字" in i.last

    m = filled(ListEquipModal(author(), None), equip_id_input="nope", price_input="5")
    i = inter()
    await m.on_submit(i)
    assert "装备不存在" in i.last and i.last.ephemeral


# --- 我的摊位 -----------------------------------------------------------------

async def stall(uid=S):
    player = await mv._get_player(uid)
    listings = await market.get_my_listings(uid)
    expired = await market.get_expired_unclaimed(uid)
    return MyStallView(author(uid), player, listings, expired, None)


async def test_摊位_下架按钮弹表单_返回交易坊(world):
    v = await stall()
    i = inter()
    await v.delist_btn.callback(i)
    assert isinstance(i.modal, DelistModal)
    i = inter()
    await v.back_btn.callback(i)
    assert isinstance(i.last.view, MarketMainView)


async def test_摊位_领回按钮_没有过期商品时提示(world):
    v = await stall()
    i = inter()
    await v.claim_btn.callback(i)
    assert "没有待领回" in i.last and i.last.ephemeral and i.modal is None


async def test_摊位_有过期商品时弹出领回表单(world):
    lid = (await market.list_item(S, HERB, 2, 100))["listing_id"]
    await market.expire_old_listings()
    D = world["db_async"]
    from sqlalchemy import update
    async with D.AsyncSessionLocal() as s:
        await s.execute(update(D.MarketListing).values(status="expired"))
        await s.commit()
    v = await stall()
    i = inter()
    await v.claim_btn.callback(i)
    assert isinstance(i.modal, ClaimModal)

    m = filled(ClaimModal(author(), None), listing_id_input=lid)
    i = inter()
    await m.on_submit(i)
    assert "已领回 **灵芝草**" in footer(i) and (await world["inventory"].get_inventory(S))[HERB] == 20


async def test_下架表单(world):
    lid = (await market.list_item(S, HERB, 2, 100))["listing_id"]
    m = filled(DelistModal(author(), None), listing_id_input=lid)
    i = inter()
    await m.on_submit(i)
    assert "已下架 **灵芝草**" in footer(i) and isinstance(i.edited[-1].view, MyStallView)
    assert (await world["inventory"].get_inventory(S))[HERB] == 20

    m = filled(DelistModal(author(), None), listing_id_input=lid)
    i = inter()
    await m.on_submit(i)
    assert i.last.ephemeral and not i.edited                      # 再下架一次被拒


async def test_领回表单_失败转述原因(world):
    m = filled(ClaimModal(author(), None), listing_id_input="nope")
    i = inter()
    await m.on_submit(i)
    assert "不存在" in i.last and i.last.ephemeral and not i.edited


async def test_装备列表_最多列20件(db):
    await _add(db, S)
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        for n in range(25):
            s.add(D.Equipment(equip_id=f"eq{n:06d}", discord_id=S, name=f"剑{n}", slot="武器", quality="稀有", tier=1,
                              tier_req=0, stats="{}", flavor="", equipped=False))
        await s.commit()
    e = await mv._equipment_list_embed(S)
    assert len(e.fields[0].value.splitlines()) == 20
