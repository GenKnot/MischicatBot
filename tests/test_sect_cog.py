"""宗门 / 功法命令测试（cogs/sect.py）。

重点是**写入的并发安全**：这个文件里改功法列表、灵石、寿元的地方，原本都是
「读出来 → 判断 → 把整份结果写成绝对值」，没有任何条件：
- 修炼功法：灵石、寿元、功法列表一起写绝对值 —— 读和写之间别处的收入被覆盖、别处的花销被「写回去」（凭空造钱）；
- 装备 / 领取门派功法 / 加入宗门：整份功法列表覆盖，会把别的入口（面板里的 CAS 写入）刚做的改动冲掉。
这与 ISSUES.md C1 / B19 是同一种形态。

竞态的模拟：把 `get_player` 换成「返回读到的快照，然后立刻执行 mutate」—— 等价于别的入口
在这条命令读完、写入之前改了数据。这样不依赖调度运气，结果是确定的。

结构：A 查询类命令  B 加入 / 退出宗门  C 门派功法  D 装备 / 卸下  E 修炼功法  F 并发
"""

import asyncio
import json
import time

import pytest

from cogs import sect as sect_mod
from cogs.sect import SectCog
from tests.conftest import make_player
from tests.discord_fakes import FakeContext
from utils.character import years_to_seconds
from utils.sects import SECTS, TECHNIQUES, get_technique_cost

UID = "1"
TECH = "青云心法"                               # 黄级上品：入门 → 熟练 需要 500 灵石 + 1 年
STRONG = dict(realm="结丹期初期", comprehension=20, physique=20, fortune=20, bone=20, soul=20,
              spirit_root="金·木·水·火·土", spirit_root_type="单灵根")


def tech(name=TECH, stage="入门", equipped=True):
    return {"name": name, "grade": TECHNIQUES.get(name, {}).get("grade", "黄级上品"), "stage": stage, "equipped": equipped}


async def _add_player(db, techniques=None, uid=UID, **fields):
    D = db["db_async"]
    p = make_player(D, uid, stones=5000)
    p.name = f"道友{uid}"
    p.techniques = json.dumps(techniques if techniques is not None else [], ensure_ascii=False)
    for k, v in fields.items():
        setattr(p, k, v)
    async with D.AsyncSessionLocal() as s:
        s.add(p)
        await s.commit()


async def _row(db, uid=UID):
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        return await s.get(D.Player, uid)


async def _set(db, uid=UID, **fields):
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        p = await s.get(D.Player, uid)
        for k, v in fields.items():
            setattr(p, k, v)
        await s.commit()


async def _techs(db, uid=UID):
    return json.loads((await _row(db, uid)).techniques or "[]")


@pytest.fixture
def cog():
    return SectCog(bot=types_bot())


def types_bot():
    import types
    return types.SimpleNamespace(cogs={})


def ctx(uid=UID):
    return FakeContext(user_id=int(uid))


def race(monkeypatch, mutate):
    """get_player 返回读到的快照后，立刻执行一次 mutate（模拟别的入口在读与写之间改了数据）。"""
    real = sect_mod.get_player
    state = {"done": False}

    async def _gp(uid):
        snap = await real(uid)
        if not state["done"]:
            state["done"] = True
            await mutate()
        return snap
    monkeypatch.setattr(sect_mod, "get_player", _gp)


STALE = "状态已变化"


# =============================================================================
# A. 查询类命令
# =============================================================================

async def test_宗门列表_分正邪两道_不含隐世(db, cog):
    c = ctx()
    await cog.sect_list.callback(cog, c)
    names = [f.name for f in c.last.embed.fields]
    assert names == ["── 正道 ──", "── 邪道 ──"]
    text = " ".join(f.value for f in c.last.embed.fields)
    assert "青云宗" in text and "太虚阁" not in text and "隐世" in c.last.embed.footer.text


async def test_宗门详情_要求与功法(db, cog):
    c = ctx()
    await cog.sect_detail.callback(cog, c, name="青云宗")
    f = {x.name: x.value for x in c.last.embed.fields}
    assert "炼气期5层" in f["入门要求"] and "单灵根" in f["入门要求"] and "悟性" in f["入门要求"]
    assert "青云心法" in f["传承功法"] and f["阵营"] == "正道"


async def test_宗门详情_未知宗门与隐世宗门(db, cog):
    c = ctx()
    await cog.sect_detail.callback(cog, c, name="不存在的宗门")
    assert c.said("未找到宗门")
    c = ctx()
    await cog.sect_detail.callback(cog, c, name="太虚阁")
    assert c.said("行踪隐秘")


async def test_我的功法_没有角色_没有功法_有功法给面板(db, cog):
    from utils.views.techniques import TechniquesView
    c = ctx()
    await cog.my_techniques.callback(cog, c)
    assert c.said("尚未踏入修仙之路")
    await _add_player(db)
    c = ctx()
    await cog.my_techniques.callback(cog, c)
    assert c.said("尚未习得任何功法")
    await _set(db, techniques=json.dumps([tech()]))
    c = ctx()
    await cog.my_techniques.callback(cog, c)
    assert isinstance(c.last.view, TechniquesView) and c.last.embed is not None


async def test_功法属性_没有角色与有角色(db, cog):
    c = ctx()
    await cog.technique_stats.callback(cog, c)
    assert c.said("尚未踏入修仙之路")
    await _add_player(db, [tech()])
    c = ctx()
    await cog.technique_stats.callback(cog, c)
    assert c.last.embed is not None


def test_解析功法列表_兼容字符串与字典():
    got = sect_mod._parse_techniques(json.dumps(["青云心法", {"name": "x", "stage": "熟练", "equipped": False}]))
    assert got[0] == {"name": "青云心法", "grade": "黄级上品", "stage": "入门", "equipped": True}
    assert got[1]["stage"] == "熟练" and sect_mod._parse_techniques(None) == []


# =============================================================================
# B. 加入 / 退出宗门
# =============================================================================

async def test_加入宗门_门槛(db, cog):
    c = ctx()
    await cog.join_sect.callback(cog, c, name="天玄门")
    assert c.said("尚未踏入修仙之路")

    await _add_player(db, is_dead=True)
    c = ctx()
    await cog.join_sect.callback(cog, c, name="天玄门")
    assert c.said("已坐化")

    await _set(db, is_dead=False, sect="御剑阁")
    c = ctx()
    await cog.join_sect.callback(cog, c, name="天玄门")
    assert c.said("已在 **御剑阁** 门下")

    await _set(db, sect=None)
    c = ctx()
    await cog.join_sect.callback(cog, c, name="不存在")
    assert c.said("未找到宗门")

    c = ctx()
    await cog.join_sect.callback(cog, c, name="天玄门")                      # 默认玩家境界不足
    assert c.said("无法加入 **天玄门**") and c.said("境界不足")
    assert (await _row(db)).sect is None


async def test_加入宗门_成功_拿到传承功法_最多装备五本(db, cog):
    existing = [tech(f"旧功法{i}", equipped=True) for i in range(4)]       # 已装备 4 本
    await _add_player(db, existing, **STRONG)
    c = ctx()

    await cog.join_sect.callback(cog, c, name="天玄门")

    p = await _row(db)
    assert p.sect == "天玄门" and p.sect_rank == "外门弟子"
    techs = await _techs(db)
    names = [t["name"] for t in techs]
    for t in SECTS["天玄门"]["techniques"]:
        assert t in names
    assert sum(1 for t in techs if t["equipped"]) == 5                       # 装备上限 5 本，多出来的不自动装备
    assert c.said("成功加入 **天玄门**") and c.said("获得功法")


async def test_加入宗门_已有的功法不重复发(db, cog):
    first = SECTS["天玄门"]["techniques"][0]
    await _add_player(db, [tech(first, stage="精通")], **STRONG)
    c = ctx()
    await cog.join_sect.callback(cog, c, name="天玄门")
    techs = await _techs(db)
    assert [t["name"] for t in techs].count(first) == 1
    assert next(t for t in techs if t["name"] == first)["stage"] == "精通"       # 已有功法的阶段不被重置


async def test_退出宗门(db, cog):
    c = ctx()
    await cog.leave_sect.callback(cog, c)
    assert c.said("尚未踏入修仙之路")
    await _add_player(db)
    c = ctx()
    await cog.leave_sect.callback(cog, c)
    assert c.said("并未加入任何宗门")
    await _set(db, sect="天玄门", sect_rank="外门弟子")
    c = ctx()
    await cog.leave_sect.callback(cog, c)
    p = await _row(db)
    assert p.sect is None and p.sect_rank is None and c.said("功法仍在")


# =============================================================================
# C. 门派功法
# =============================================================================

async def test_门派功法_门槛(db, cog):
    c = ctx()
    await cog.sect_techniques.callback(cog, c)
    assert c.said("尚未踏入修仙之路")
    await _add_player(db)
    c = ctx()
    await cog.sect_techniques.callback(cog, c)
    assert c.said("尚未加入任何宗门")


async def test_门派功法_领取新功法(db, cog):
    await _add_player(db, [], sect="天玄门")
    c = ctx()
    await cog.sect_techniques.callback(cog, c)
    names = [t["name"] for t in await _techs(db)]
    assert set(SECTS["天玄门"]["techniques"]) <= set(names) and c.said("领悟了新功法")


async def test_门派功法_已全部习得时只展示(db, cog):
    await _add_player(db, [tech(t) for t in SECTS["天玄门"]["techniques"]], sect="天玄门")
    c = ctx()
    await cog.sect_techniques.callback(cog, c)
    assert c.last.embed is not None and "传承功法" in c.last.embed.title and "已全部习得" in c.last.embed.footer.text


# =============================================================================
# D. 装备 / 卸下
# =============================================================================

async def test_装备_门槛(db, cog):
    c = ctx()
    await cog.equip_technique.callback(cog, c, name=TECH)
    assert c.said("尚未踏入修仙之路")
    await _add_player(db, [tech()])
    c = ctx()
    await cog.equip_technique.callback(cog, c, name="没学过的")
    assert c.said("未习得功法")


async def test_装备与卸下_来回切换(db, cog):
    await _add_player(db, [tech(equipped=False)])
    c = ctx()
    await cog.equip_technique.callback(cog, c, name=TECH)
    assert c.said("已装备功法") and (await _techs(db))[0]["equipped"] is True
    c = ctx()
    await cog.equip_technique.callback(cog, c, name=TECH)
    assert c.said("已卸下功法") and (await _techs(db))[0]["equipped"] is False


async def test_装备_最多五本(db, cog):
    await _add_player(db, [tech(f"功法{i}", equipped=True) for i in range(5)] + [tech(equipped=False)])
    c = ctx()
    await cog.equip_technique.callback(cog, c, name=TECH)
    assert c.said("已装备5本功法")
    assert [t["equipped"] for t in await _techs(db)][-1] is False


async def test_卸下增寿功法时_寿元超出新上限就拒绝(db, cog):
    name = next((k for k, v in TECHNIQUES.items() if v.get("stat_bonus", {}).get("lifespan_bonus", 0) > 0), None)
    if name is None:
        pytest.skip("没有带寿元加成的功法")
    bonus = TECHNIQUES[name]["stat_bonus"]["lifespan_bonus"]
    await _add_player(db, [tech(name, equipped=True)], lifespan=100 + bonus, lifespan_max=100)
    c = ctx()
    await cog.equip_technique.callback(cog, c, name=name)
    assert c.said("无法卸下") and (await _techs(db))[0]["equipped"] is True


# =============================================================================
# E. 修炼功法
# =============================================================================

COST, YEARS = get_technique_cost(TECH, "入门")


async def test_修炼功法_门槛(db, cog):
    c = ctx()
    await cog.train_technique.callback(cog, c, name=TECH)
    assert c.said("尚未踏入修仙之路")

    await _add_player(db, [tech()], is_dead=True)
    c = ctx()
    await cog.train_technique.callback(cog, c, name=TECH)
    assert c.said("已坐化")

    await _set(db, is_dead=False, cultivating_until=time.time() + 999)
    c = ctx()
    await cog.train_technique.callback(cog, c, name=TECH)
    assert c.said("正在闭关")

    await _set(db, cultivating_until=None)
    c = ctx()
    await cog.train_technique.callback(cog, c, name="没学过的")
    assert c.said("未习得功法")


async def test_修炼功法_已是最高阶段(db, cog):
    await _add_player(db, [tech(stage="破限")])
    c = ctx()
    await cog.train_technique.callback(cog, c, name=TECH)
    assert c.said("已达最高阶段")


async def test_修炼功法_灵石不足与寿元不足_不扣任何东西(db, cog):
    await _add_player(db, [tech()], spirit_stones=COST - 1)
    c = ctx()
    await cog.train_technique.callback(cog, c, name=TECH)
    assert c.said("灵石不足") and c.said(str(COST))

    await _set(db, spirit_stones=5000, lifespan=YEARS - 1)
    c = ctx()
    await cog.train_technique.callback(cog, c, name=TECH)
    assert c.said("寿元不足")
    p = await _row(db)
    assert (p.spirit_stones, p.lifespan) == (5000, YEARS - 1) and (await _techs(db))[0]["stage"] == "入门"


async def test_修炼功法_成功_升阶段_扣灵石寿元_进入闭关(db, cog):
    await _add_player(db, [tech()], spirit_stones=5000, lifespan=100)
    before = time.time()
    c = ctx()

    await cog.train_technique.callback(cog, c, name=TECH)

    p = await _row(db)
    assert (await _techs(db))[0]["stage"] == "熟练"
    assert (p.spirit_stones, p.lifespan) == (5000 - COST, 100 - YEARS)
    assert p.cultivating_years == YEARS
    assert before + years_to_seconds(YEARS) <= p.cultivating_until <= time.time() + years_to_seconds(YEARS)
    e = c.last.embed
    assert "入门 ➜ **熟练**" in e.description and f"消耗灵石：**{COST}**" in e.description
    assert f"剩余：{5000 - COST}" in e.description


async def test_修炼功法_一步步升到最高(db, cog):
    await _add_player(db, [tech()], spirit_stones=10 ** 7, lifespan=10 ** 5)
    stages = ["熟练", "精通", "小成", "大成", "圆满", "破限"]
    for want in stages:
        await _set(db, cultivating_until=None)
        await cog.train_technique.callback(cog, ctx(), name=TECH)
        assert (await _techs(db))[0]["stage"] == want


# =============================================================================
# F. 并发：丢更新
# =============================================================================

async def test_修炼功法_读写之间别处的收入不会被覆盖(db, cog, monkeypatch):
    """原本把『读到的余额 - 花费』写成绝对值：读完到写入之间到账的 +1000（任务奖励、打工……）被抹掉。"""
    await _add_player(db, [tech()], spirit_stones=5000)

    async def income():
        await _set(db, spirit_stones=6000)                                   # 读完之后到账 +1000
    race(monkeypatch, income)
    c = ctx()

    await cog.train_technique.callback(cog, c, name=TECH)

    assert (await _row(db)).spirit_stones == 6000 - COST, "别处的收入不能被覆盖"
    assert (await _techs(db))[0]["stage"] == "熟练"


async def test_修炼功法_读写之间别处花掉了灵石_不能凭空把它们写回来(db, cog, monkeypatch):
    """原本的绝对值写入会把已经花掉的灵石『写回去』—— 凭空造钱；现在条件写入会拒绝。"""
    await _add_player(db, [tech()], spirit_stones=5000)

    async def spend():
        await _set(db, spirit_stones=100)                                    # 读完之后被花到只剩 100
    race(monkeypatch, spend)
    c = ctx()

    await cog.train_technique.callback(cog, c, name=TECH)

    p = await _row(db)
    assert p.spirit_stones == 100, "灵石不足以支付时不能写入，更不能把花掉的灵石写回来"
    assert (await _techs(db))[0]["stage"] == "入门" and c.said(STALE)


async def test_修炼功法_读写之间功法列表被别处改了_整次作废(db, cog, monkeypatch):
    """别的入口（比如面板里的 CAS 写入）刚给了一本新功法：命令的整份覆盖会把它冲掉。"""
    await _add_player(db, [tech()], spirit_stones=5000)

    async def other_writer():
        await _set(db, techniques=json.dumps([tech(), tech("新学的功法", equipped=False)], ensure_ascii=False))
    race(monkeypatch, other_writer)
    c = ctx()

    await cog.train_technique.callback(cog, c, name=TECH)

    names = [t["name"] for t in await _techs(db)]
    assert "新学的功法" in names, "别处刚加的功法不能被冲掉"
    p = await _row(db)
    assert p.spirit_stones == 5000 and (await _techs(db))[0]["stage"] == "入门" and c.said(STALE)


async def test_修炼功法_同时发两条命令_只升一阶_只扣一次(db, cog):
    await _add_player(db, [tech()], spirit_stones=5000, lifespan=100)
    c1, c2 = ctx(), ctx()

    await asyncio.gather(cog.train_technique.callback(cog, c1, name=TECH),
                         cog.train_technique.callback(cog, c2, name=TECH))

    p = await _row(db)
    assert (await _techs(db))[0]["stage"] == "熟练"                          # 只升了一阶
    assert (p.spirit_stones, p.lifespan) == (5000 - COST, 100 - YEARS)        # 只扣了一次
    succeeded = [c for c in (c1, c2) if c.last.embed is not None and "功法修炼" in (c.last.embed.title or "")]
    assert len(succeeded) == 1                                               # 只有一条命令得到『修炼成功』


async def test_装备_读写之间功法列表被别处改了_不会冲掉(db, cog, monkeypatch):
    await _add_player(db, [tech(equipped=False)])

    async def other_writer():
        await _set(db, techniques=json.dumps([tech(equipped=False), tech("新学的功法", equipped=False)], ensure_ascii=False))
    race(monkeypatch, other_writer)
    c = ctx()

    await cog.equip_technique.callback(cog, c, name=TECH)

    assert "新学的功法" in [t["name"] for t in await _techs(db)]
    assert c.said(STALE) and not c.said("已装备功法")


async def test_领取门派功法_读写之间功法列表被别处改了_不会冲掉(db, cog, monkeypatch):
    await _add_player(db, [], sect="天玄门")

    async def other_writer():
        await _set(db, techniques=json.dumps([tech("别处学的功法", equipped=False)], ensure_ascii=False))
    race(monkeypatch, other_writer)
    c = ctx()

    await cog.sect_techniques.callback(cog, c)

    assert "别处学的功法" in [t["name"] for t in await _techs(db)]
    assert c.said(STALE) and not c.said("领悟了新功法")


async def test_加入宗门_同时加入两个不同宗门_只有一个成功(db, cog):
    await _add_player(db, [], **STRONG)
    c1, c2 = ctx(), ctx()

    await asyncio.gather(cog.join_sect.callback(cog, c1, name="天玄门"),
                         cog.join_sect.callback(cog, c2, name="御剑阁"))

    p = await _row(db)
    assert p.sect in ("天玄门", "御剑阁")
    won = p.sect
    others = set(SECTS["天玄门"]["techniques"] + SECTS["御剑阁"]["techniques"]) - set(SECTS[won]["techniques"])
    assert not (others & {t["name"] for t in await _techs(db)}), "不能同时拿到两个宗门的传承"
    assert len([c for c in (c1, c2) if c.said("成功加入")]) == 1


async def test_加入宗门_读写之间已经在别处加入了宗门_作废(db, cog, monkeypatch):
    await _add_player(db, [], **STRONG)

    async def joined_elsewhere():
        await _set(db, sect="御剑阁", sect_rank="外门弟子")
    race(monkeypatch, joined_elsewhere)
    c = ctx()

    await cog.join_sect.callback(cog, c, name="天玄门")

    assert (await _row(db)).sect == "御剑阁" and c.said(STALE)


async def test_修炼功法_读写之间寿元被花掉了_整次作废(db, cog, monkeypatch):
    await _add_player(db, [tech()], spirit_stones=5000, lifespan=100)

    async def spend_lifespan():
        await _set(db, lifespan=YEARS - 1)                                   # 读完之后被别处花到不够
    race(monkeypatch, spend_lifespan)
    c = ctx()

    await cog.train_technique.callback(cog, c, name=TECH)

    p = await _row(db)
    assert p.lifespan == YEARS - 1 and p.spirit_stones == 5000, "寿元不够时不能写入，也不能扣灵石"
    assert (await _techs(db))[0]["stage"] == "入门" and c.said(STALE)


async def test_修炼功法_读写之间已经在别处开始闭关_整次作废(db, cog, monkeypatch):
    """前置检查通过之后，玩家在另一个入口开始了闭关：这里不能再把闭关状态覆盖掉、也不能再扣一遍费。"""
    await _add_player(db, [tech()], spirit_stones=5000, lifespan=100)
    until = time.time() + years_to_seconds(8)

    async def start_cultivating():
        await _set(db, cultivating_until=until, cultivating_years=8)
    race(monkeypatch, start_cultivating)
    c = ctx()

    await cog.train_technique.callback(cog, c, name=TECH)

    p = await _row(db)
    assert p.cultivating_years == 8 and abs(p.cultivating_until - until) < 1, "别处开始的闭关不能被覆盖"
    assert (p.spirit_stones, p.lifespan) == (5000, 100) and c.said(STALE)


async def test_加入宗门_读写之间功法列表被别处改了_整次作废(db, cog, monkeypatch):
    await _add_player(db, [], **STRONG)

    async def other_writer():
        await _set(db, techniques=json.dumps([tech("别处学的功法", equipped=False)], ensure_ascii=False))
    race(monkeypatch, other_writer)
    c = ctx()

    await cog.join_sect.callback(cog, c, name="天玄门")

    assert (await _row(db)).sect is None, "功法列表被改过，这次加入应当作废"
    assert [t["name"] for t in await _techs(db)] == ["别处学的功法"] and c.said(STALE)


async def test_卸下_读写之间功法列表被别处改了_不会冲掉(db, cog, monkeypatch):
    await _add_player(db, [tech(equipped=True)])

    async def other_writer():
        await _set(db, techniques=json.dumps([tech(equipped=True), tech("新学的功法", equipped=False)], ensure_ascii=False))
    race(monkeypatch, other_writer)
    c = ctx()

    await cog.equip_technique.callback(cog, c, name=TECH)

    assert "新学的功法" in [t["name"] for t in await _techs(db)]
    assert c.said(STALE) and not c.said("已卸下功法")
