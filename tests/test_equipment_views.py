"""装备管理面板（utils/views/equipment.py）。账务与并发见 test_equipment_db.py。"""

import discord
from tests.conftest import make_player
from tests.discord_fakes import FakeInteraction
from utils.views import equipment as ev
from utils.views.equipment import (EquipmentManageView, _DiscardSelectView, _EquipSelectView, _UnequipSelectView,
                                   _build_equipment_embed)

U = "1001"


async def _add(db, uid=U, **kw):
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        p = make_player(D, uid, stones=0)
        for k, v in kw.items():
            setattr(p, k, v)
        s.add(p)
        await s.commit()


async def give(db, equip_id, slot="武器", uid=U, tier=0, tier_req=0, quality="普通", name=None, stats=None):
    await db["equipment_db"].give_equipment(uid, {
        "equip_id": equip_id, "name": name or f"装备{equip_id}", "slot": slot, "quality": quality, "tier": tier,
        "tier_req": tier_req, "stats": stats or {"physique": 2}, "flavor": "风"})


def inter(uid=U):
    return FakeInteraction(uid)


def view(cog=None):
    return EquipmentManageView(inter().user, cog)


async def equips(uid=U):
    return await ev.get_equipment_list(uid)


# --- 文案 ---------------------------------------------------------------------

def test_装备管理文案_无装备():
    e = _build_equipment_embed({}, [])
    assert e.fields[0].name == "已装备" and e.fields[0].value == "暂无" and len(e.fields) == 1


def test_装备管理文案_已装备带总加成_背包中带境界():
    items = [
        {"equipped": True, "name": "甲", "slot": "武器", "quality": "稀有", "tier": 1, "stats": {"physique": 2, "bone": 1}},
        {"equipped": True, "name": "乙", "slot": "防具", "quality": "普通", "tier": 0, "stats": {"physique": 3}},
        {"equipped": False, "name": "丙", "slot": "饰品", "quality": "史诗", "tier": 99, "stats": {"soul": 5}},
    ]
    e = _build_equipment_embed({}, items)
    f = {x.name: x.value for x in e.fields}
    assert "甲" in f["已装备"] and "乙" in f["已装备"] and "总加成：体魄+5  根骨+1" in f["已装备"]
    assert "丙" in f["背包中"] and "神识+5" in f["背包中"]                      # 境界下标越界也不崩


# --- 装备 / 卸下 / 丢弃 按钮 --------------------------------------------------

async def test_装备按钮_没有可装备的(db):
    await _add(db)
    i = inter()
    await view().equip_btn.callback(i)
    assert "没有可装备" in i.last and i.last.ephemeral


async def test_装备按钮_列出未穿的_最多25件(db):
    await _add(db)
    for n in range(30):
        await give(db, f"e{n:02d}", tier=n % 3)
    await give(db, "worn", slot="防具")
    await db["equipment_db"].equip_item(U, "worn", 0)
    i = inter()
    await view().equip_btn.callback(i)
    sv = i.last.view
    assert isinstance(sv, _EquipSelectView) and i.last.ephemeral
    values = [o.value for o in sv.select.options]
    assert len(values) == 25 and "worn" not in values


async def test_装备选择_成功刷新面板_失败转述(db):
    await _add(db)
    await give(db, "a")
    await give(db, "hi", tier_req=3)
    sv = _EquipSelectView(inter().user, None, [])

    async def pick(i, v):
        sv.select._values = [v]
        await sv.select.callback(i)
    i = inter()
    await pick(i, "a")
    assert i.last.embed.footer.text == "已装备 **装备a**。" and isinstance(i.last.view, EquipmentManageView)
    i = inter()
    await pick(i, "hi")
    assert "才能装备此物" in i.last and i.last.ephemeral


async def test_卸下按钮与选择(db):
    await _add(db)
    i = inter()
    await view().unequip_btn.callback(i)
    assert "没有已装备" in i.last and i.last.ephemeral
    await give(db, "a")
    await db["equipment_db"].equip_item(U, "a", 0)
    i = inter()
    await view().unequip_btn.callback(i)
    sv = i.last.view
    assert isinstance(sv, _UnequipSelectView) and [o.value for o in sv.select.options] == ["a"]

    async def pick(i):
        sv.select._values = ["a"]
        await sv.select.callback(i)
    i = inter()
    await pick(i)
    assert "已卸下" in i.last.embed.footer.text and not (await equips())[0]["equipped"]
    i = inter()
    await pick(i)                                                          # 再卸一次：已经没穿
    assert "未装备" in i.last and i.last.ephemeral


async def test_丢弃按钮与选择(db):
    await _add(db)
    i = inter()
    await view().discard_btn.callback(i)
    assert "没有任何装备可丢弃" in i.last
    await give(db, "a")
    await give(db, "b", slot="防具")
    await db["equipment_db"].equip_item(U, "b", 0)
    i = inter()
    await view().discard_btn.callback(i)
    sv = i.last.view
    assert isinstance(sv, _DiscardSelectView) and "无法找回" in i.last.embed.description
    notes = {o.value: o.description for o in sv.select.options}
    assert "已装备·先卸下" in notes["b"] and "已装备" not in notes["a"]

    async def pick(i, v):
        sv.select._values = [v]
        await sv.select.callback(i)
    i = inter()
    await pick(i, "b")                                                      # 已穿的丢不掉
    assert "请先卸下" in i.last and i.last.ephemeral
    i = inter()
    await pick(i, "a")
    assert "已丢弃" in i.last.embed.footer.text and [e["equip_id"] for e in await equips()] == ["b"]


async def test_选择器里按钮_返回装备面板(db):
    await _add(db)
    await give(db, "a")
    for cls in (_EquipSelectView, _UnequipSelectView, _DiscardSelectView):
        sv = cls(inter().user, None, [])
        i = inter()
        await sv.back_btn.callback(i)
        assert isinstance(i.last.view, EquipmentManageView) and i.last.embed.title == "✦ 装备管理 ✦"


async def test_只有本人能操作(db):
    v = view()
    other = inter("2002")
    assert await v.interaction_check(other) is False and other.last.ephemeral


async def test_返回主菜单(db, monkeypatch):
    sent = {}

    async def fake(interaction, cog):
        sent["cog"] = cog
    monkeypatch.setattr("utils.views.world._send_main_menu", fake)
    marker = object()
    i = inter()
    await view(marker).back_btn.callback(i)
    assert i.response.deferred and sent["cog"] is marker


def test_选项文案不超过Discord限制():
    long_name = "名" * 100
    opts = [discord.SelectOption(label=long_name[:40], value="x", description=("武器 · " + "属" * 200)[:100])]
    assert len(opts[0].label) <= 100 and len(opts[0].description) <= 100
