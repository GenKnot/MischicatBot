"""装备 cog（cogs/equipment.py）：背包、装备详情、穿 / 卸 / 丢弃命令、使用道具、出售。

服药的扣药与回滚见 test_cogs_equipment.py，这里补各类效果与其余命令。

B51 —— 突破用的丹药（筑基丹 / 凝丹丹 / 化婴丹 / 破障丹）只有 `breakthrough_bonus` 一个效果，而突破逻辑是在突破时
  自己从背包里取药（面板上的『服用筑基丹冲关』）。`使用 筑基丹` 却会扣掉一颗、回复『下次突破成功率 +40%』，
  实际没有记录任何加成 —— 一颗稀有丹药白白消失。现在直接拒绝并告诉玩家去突破面板用，丹药不扣。
B52 —— `破障丹`（『提升所有境界突破成功率 20%』）在突破逻辑里根本没有接入，哪里都用不上。
  这是游戏内容缺口，不是代码 bug：`使用` 对它给出明确提示，丹药不扣；要不要接入突破请你定。
B53 —— `出售` 先扣物品、再另开事务加灵石：两步之间出错（崩溃、数据库锁）物品就白没了。改成同一个事务。
"""

import json
import time

import discord
import pytest

from cogs.equipment import BackpackPageView, EquipmentCog, _build_backpack_pages
from tests.conftest import make_player
from tests.discord_fakes import FakeContext, FakeInteraction
from utils.alchemy import QUALITY_MULTIPLIERS, QUALITY_NAMES
from utils.items import ITEMS

U = "1001"


class Bot:
    def __init__(self, **cogs):
        self.cogs = cogs


@pytest.fixture
def cog():
    return EquipmentCog(bot=Bot())


async def _add(db, uid=U, stones=0, items=None, **kw):
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        p = make_player(D, uid, stones=stones)
        p.name = f"道友{uid}"
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


async def qty(db, item, uid=U):
    return (await db["inventory"].get_inventory(uid)).get(item, 0)


async def buffs(db, uid=U):
    return json.loads((await row(db, uid)).active_buffs or "{}")


def ctx(uid=U):
    return FakeContext(user_id=uid)


async def run(cog, name, c, *args, **kw):
    return await getattr(cog, name).callback(cog, c, *args, **kw)


async def give_eq(db, equip_id="eq1", slot="武器", uid=U, tier=0, tier_req=0, quality="普通", name=None, stats=None):
    await db["equipment_db"].give_equipment(uid, {
        "equip_id": equip_id, "name": name or f"装备{equip_id}", "slot": slot, "quality": quality, "tier": tier,
        "tier_req": tier_req, "stats": stats or {"physique": 2}, "flavor": "风"})


# --- 背包 ---------------------------------------------------------------------

async def test_背包_没有角色_已坐化(db, cog):
    c = ctx()
    await run(cog, "backpack", c)
    assert c.said("尚未踏入修仙之路")
    await _add(db, is_dead=1)
    c = ctx()
    await run(cog, "backpack", c)
    assert c.said("尚未踏入修仙之路")


async def test_背包_空背包(db, cog):
    await _add(db)
    c = ctx()
    await run(cog, "backpack", c)
    f = {x.name: x.value for x in c.last.embed.fields}
    assert f["丹药 / 道具"] == "空空如也" and f["装备"] == "无装备" and isinstance(c.last.view, BackpackPageView)


async def test_背包_物品与装备分区(db, cog):
    await _add(db, items={"聚灵丹": 3})
    await give_eq(db, "eq1", name="已穿剑")
    await give_eq(db, "eq2", slot="防具", name="备用甲")
    await db["equipment_db"].equip_item(U, "eq1", 0)
    c = ctx()
    await run(cog, "backpack", c)
    f = {x.name: x.value for x in c.last.embed.fields}
    assert "聚灵丹** ×3" in f["丹药 / 道具"] and "已穿剑" in f["装备"] and "（已装备）" in f["装备"]
    assert "---未装备---" in f["装备"] and "`eq2`" in f["装备"]


def make_player_dict():
    return {"name": "甲"}


def test_背包分页_长列表分段_每页最多4栏():
    items = {f"物品{n}": 1 for n in range(120)}
    pages = _build_backpack_pages(make_player_dict(), items, [])
    assert len(pages) > 1 and all(len(p.fields) <= 4 for p in pages)
    assert all(len(f.value) <= 1024 for p in pages for f in p.fields)
    assert pages[0].footer.text.startswith("第 1 / ") and f"/ {len(pages)} 页" in pages[0].footer.text
    assert any("续" in f.name for p in pages for f in p.fields)


def test_背包分页_单页没有页码():
    pages = _build_backpack_pages(make_player_dict(), {"聚灵丹": 1}, [])
    assert len(pages) == 1 and "页" not in pages[0].footer.text


def test_背包分页_装备过多也分段():
    equips = [{"equip_id": f"e{n:04d}", "name": "一把名字很长很长很长的剑" * 2, "quality": "普通", "equipped": False}
              for n in range(60)]
    pages = _build_backpack_pages(make_player_dict(), {}, equips)
    assert all(len(f.value) <= 1024 for p in pages for f in p.fields) and len(pages) >= 1
    assert sum(f.value.count("`e") for p in pages for f in p.fields) == 60


async def test_背包面板_翻页与权限(db):
    pages = [discord.Embed(title=str(n)) for n in range(3)]
    author = FakeInteraction(U).user
    v = BackpackPageView(author, pages, None)
    assert v.prev_btn.disabled and not v.next_btn.disabled
    i = FakeInteraction(U)
    await v.next_btn.callback(i)
    assert i.last.embed.title == "1" and not v.prev_btn.disabled
    await v.next_btn.callback(FakeInteraction(U))
    assert v.next_btn.disabled
    await v.prev_btn.callback(FakeInteraction(U))
    assert v.page == 1
    other = FakeInteraction("2002")
    assert await v.interaction_check(other) is False and other.last.ephemeral


async def test_背包面板_返回主菜单(db, monkeypatch):
    pages = [discord.Embed(title="x")]
    v = BackpackPageView(FakeInteraction(U).user, pages, None)
    i = FakeInteraction(U)
    await v.back_menu.callback(i)
    assert "无法返回" in i.last
    sent = {}

    async def fake_menu(interaction, cog):
        sent["cog"] = cog
    monkeypatch.setattr("utils.views.world._send_main_menu", fake_menu)
    marker = object()
    v = BackpackPageView(FakeInteraction(U).user, pages, marker)
    i = FakeInteraction(U)
    await v.back_menu.callback(i)
    assert i.response.deferred and sent["cog"] is marker


# --- 装备详情 / 穿 / 卸 / 丢 --------------------------------------------------

async def test_装备详情(db, cog):
    c = ctx()
    await run(cog, "equip_details", c)
    assert c.said("尚未踏入修仙之路")
    await _add(db)
    c = ctx()
    await run(cog, "equip_details", c)
    assert c.said("当前未装备任何装备")
    await give_eq(db, "eq1", stats={"physique": 3, "bone": 1})
    await give_eq(db, "eq2", slot="防具", stats={"physique": 2})
    await db["equipment_db"].equip_item(U, "eq1", 0)
    await db["equipment_db"].equip_item(U, "eq2", 0)
    c = ctx()
    await run(cog, "equip_details", c)
    e = c.last.embed
    assert len(e.fields) == 3 and e.fields[-1].name == "总属性加成" and "体魄 +5" in e.fields[-1].value


async def test_穿卸丢_缺参数给用法(db, cog):
    await _add(db)
    for name in ("equip", "unequip", "discard"):
        c = ctx()
        await run(cog, name, c)
        assert c.said("用法"), name


async def test_穿装备_境界不够_没角色(db, cog):
    c = ctx()
    await run(cog, "equip", c, "eq1")
    assert c.said("尚未踏入修仙之路")
    await _add(db)
    await give_eq(db, "eq1", tier_req=2)
    c = ctx()
    await run(cog, "equip", c, "eq1")
    assert c.said("才能装备此物")
    await _add(db, "1002", realm="结丹期初期")
    await give_eq(db, "eq2", uid="1002", tier_req=2)
    c = ctx("1002")
    await run(cog, "equip", c, "eq2")
    assert c.said("已装备")


async def test_穿装备_已坐化(db, cog):
    await _add(db, is_dead=1)
    c = ctx()
    await run(cog, "equip", c, "eq1")
    assert c.said("尚未踏入修仙之路")


async def test_卸下与丢弃命令(db, cog):
    await _add(db)
    await give_eq(db, "eq1")
    c = ctx()
    await run(cog, "equip", c, "eq1")
    await run(cog, "discard", c, "eq1")
    assert c.said("请先卸下装备再丢弃")
    await run(cog, "unequip", c, "eq1")
    assert c.said("已卸下")
    await run(cog, "discard", c, "eq1")
    assert c.said("已丢弃") and await db["equipment_db"].get_equipment_list(U) == []
    await run(cog, "discard", c, "eq1")
    assert c.said("装备不存在")


# --- 使用道具：各类效果 -------------------------------------------------------

async def use(cog, c, name):
    return await cog.use_item.callback(cog, c, item_name=name)


async def test_使用_修为增益按品质倍率(db, cog):
    await _add(db, items={"培元丹": 1, "三纹培元丹": 1}, cultivation=0)
    c = ctx()
    await use(cog, c, "培元丹")
    assert (await row(db)).cultivation == 100 and c.said("修为 **+100**")
    await use(cog, c, "三纹培元丹")
    mult = QUALITY_MULTIPLIERS[QUALITY_NAMES.index("三纹")]
    assert (await row(db)).cultivation == 100 + int(100 * mult)
    assert await qty(db, "三纹培元丹") == 0


async def test_使用_续命丹_补到上限为止(db, cog):
    await _add(db, items={"续命丹": 2}, lifespan=90, lifespan_max=100)
    c = ctx()
    await use(cog, c, "续命丹")
    assert (await row(db)).lifespan == 100 and c.said("+10年") and await qty(db, "续命丹") == 1
    c = ctx()
    await use(cog, c, "续命丹")
    assert c.said("已达上限") and await qty(db, "续命丹") == 1                     # 满了不浪费


async def test_使用_延寿丹_可超过上限(db, cog):
    await _add(db, items={"延寿丹": 1}, lifespan=100, lifespan_max=100)
    c = ctx()
    await use(cog, c, "延寿丹")
    assert (await row(db)).lifespan == 110 and c.said("超出基础上限 10年")


@pytest.mark.parametrize("pill,stat,cap", [("淬骨丹", "bone", 10), ("小淬骨丹", "bone", 5), ("坚骨丹", "bone", 12)])
async def test_使用_永久属性丹_到上限后拒绝_不扣丹(db, cog, pill, stat, cap):
    gain = ITEMS[pill]["effect"]["stat_permanent"][stat]
    await _add(db, items={pill: 2}, **{stat: cap - gain})
    c = ctx()
    await use(cog, c, pill)
    assert getattr(await row(db), stat) == cap and await qty(db, pill) == 1
    c = ctx()
    await use(cog, c, pill)
    assert c.said("已达上限") and await qty(db, pill) == 1 and getattr(await row(db), stat) == cap


async def test_使用_永久属性丹_不会超过上限(db, cog):
    await _add(db, items={"坚骨丹": 1}, bone=11)
    await use(cog, ctx(), "坚骨丹")
    assert (await row(db)).bone == 12                                              # 11 + 2 夹到 12


BUFF_CASES = [
    ("聚灵丹", "cultivation_speed_bonus"), ("战魄丹", "combat_power_bonus"), ("遁形丹", "escape_bonus_once"),
    ("探灵丹", "explore_rare_bonus_once"), ("丰收丹", "gather_bonus_once"), ("速灵丹", "gather_cooldown_reduction"),
    ("回春丹", "combat_lifespan_restore"), ("财运丹", "spirit_stones_bonus_once"), ("声望丹", "reputation_bonus_once"),
    ("五行归元丹", "stat_temp"),
]


@pytest.mark.parametrize("pill,key", BUFF_CASES)
async def test_使用_状态类丹药写入buff_并扣一颗(db, cog, pill, key):
    await _add(db, items={pill: 2})
    c = ctx()
    await use(cog, c, pill)
    assert key in await buffs(db) and await qty(db, pill) == 1 and c.said(f"服用「{pill}」")


async def test_使用_聚灵丹_记录到期时间(db, cog):
    await _add(db, items={"聚灵丹": 1})
    await use(cog, ctx(), "聚灵丹")
    p = await row(db)
    assert p.pill_buff_until == pytest.approx(time.time() + 4 * 3600, abs=30)
    assert (await buffs(db))["cultivation_speed_bonus"]["expires_at"] == pytest.approx(p.pill_buff_until)


async def test_使用_战魄丹_带次数(db, cog):
    await _add(db, items={"战魄丹": 1})
    await use(cog, ctx(), "战魄丹")
    assert (await buffs(db))["combat_power_bonus"] == {"value": 30, "charges": 3}


async def test_使用_复合效果丹药(db, cog):
    await _add(db, items={"天机探宝丹": 1})
    await use(cog, ctx(), "天机探宝丹")
    b = await buffs(db)
    assert "explore_rare_bonus_once" in b and "spirit_stones_bonus_once" in b


async def test_使用_复元丹_恢复探险次数_不会为负(db, cog):
    await _add(db, items={"复元丹": 2}, explore_count=1)
    await use(cog, ctx(), "复元丹")
    assert (await row(db)).explore_count == 0
    await use(cog, ctx(), "复元丹")
    assert (await row(db)).explore_count == 0 and await qty(db, "复元丹") == 0


async def test_使用_情缘丹_缩短双修冷却(db, cog):
    await _add(db, items={"情缘丹": 1}, last_dual_cultivate=1_000_000)
    await use(cog, ctx(), "情缘丹")
    assert (await row(db)).last_dual_cultivate == 1_000_000 - 48 * 3600
    await _add(db, "1002", items={"情缘丹": 1}, last_dual_cultivate=100)
    await use(cog, ctx("1002"), "情缘丹")
    assert (await row(db, "1002")).last_dual_cultivate == 0                        # 夹零


async def test_使用_无效果的物品(db, cog):
    await _add(db, items={"铜矿石": 1})
    c = ctx()
    await use(cog, c, "铜矿石")
    assert c.said("暂时无法直接使用") and await qty(db, "铜矿石") == 1


async def test_使用_品质前缀的未知基础名(db, cog):
    await _add(db)
    c = ctx()
    await use(cog, c, "三纹不存在的药")
    assert c.said("未知道具")


# --- B51/B52：突破丹 ----------------------------------------------------------

@pytest.mark.parametrize("pill", ["筑基丹", "凝丹丹", "化婴丹"])
async def test_B51_使用突破丹_拒绝并指路_不扣丹(db, cog, pill):
    await _add(db, items={pill: 1})
    c = ctx()
    await use(cog, c, pill)
    assert c.said("突破") and await qty(db, pill) == 1 and c.said("冲关")


async def test_B52_破障丹_明确提示暂未接入_不扣丹(db, cog):
    await _add(db, items={"破障丹": 1})
    c = ctx()
    await use(cog, c, "破障丹")
    assert c.said("暂未") and await qty(db, "破障丹") == 1


# --- 出售 ---------------------------------------------------------------------

async def test_出售_用法_没角色(db, cog):
    c = ctx()
    await run(cog, "sell_item", c)
    assert c.said("用法")
    c = ctx()
    await run(cog, "sell_item", c, args="铜矿石 1")
    assert c.said("尚未踏入修仙之路")


async def test_出售_成功_默认数量1(db, cog):
    await _add(db, items={"铜矿石": 5})
    c = ctx()
    await run(cog, "sell_item", c, args="铜矿石")
    assert (await row(db)).spirit_stones == 5 and await qty(db, "铜矿石") == 4 and c.said("获得 **5 灵石**")


async def test_出售_指定数量(db, cog):
    await _add(db, items={"铜矿石": 5})
    c = ctx()
    await run(cog, "sell_item", c, args="铜矿石 3")
    assert (await row(db)).spirit_stones == 15 and await qty(db, "铜矿石") == 2


@pytest.mark.parametrize("args,msg", [("铜矿石 0", "数量需大于 0"), ("铜矿石 -2", "数量需大于 0"),
                                      ("不存在物 1", "未知物品"), ("铜矿石 abc", "未知物品"),
                                      ("铜矿石 9", "背包中只有 **5** 个"), ("聚灵丹 1", "无法出售")])
async def test_出售_拒绝(db, cog, args, msg):
    await _add(db, items={"铜矿石": 5, "聚灵丹": 1})
    c = ctx()
    await run(cog, "sell_item", c, args=args)
    assert c.said(msg) and await qty(db, "铜矿石") == 5 and (await row(db)).spirit_stones == 0


async def test_B53_加灵石失败时物品不丢(db, cog, monkeypatch):
    await _add(db, items={"铜矿石": 5})

    async def boom(*a, **k):
        raise RuntimeError("数据库挂了")
    monkeypatch.setattr("cogs.equipment.grant_stones", boom)
    with pytest.raises(RuntimeError):
        await run(cog, "sell_item", ctx(), args="铜矿石 3")
    assert await qty(db, "铜矿石") == 5 and (await row(db)).spirit_stones == 0


async def test_出售_并发不超卖(db, cog):
    import asyncio
    await _add(db, items={"铜矿石": 5})
    await asyncio.gather(*[run(cog, "sell_item", ctx(), args="铜矿石 2") for _ in range(6)])
    sold = 5 - await qty(db, "铜矿石")
    assert sold in (4,) and (await row(db)).spirit_stones == sold * 5
