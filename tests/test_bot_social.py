"""机器人的性格、偏好与好感度（utils/bot_social.py）。

· 原型数据合法；生成的性格在原型范围内、喜好与厌恶不冲突、物品都真实存在；
· 好感分档、按善意浮动的门槛；
· 送礼：物品转给机器人 + 按偏好加减好感，一个事务；每天份数与涨幅有上限；失败什么都不改；
· 闲聊：每天第一次涨一点；
· 闸门：组队 / 双修要好感，仇视一律拒绝；接入 accept_invite / add_to_party / 双修 / 两个面板。
"""

import asyncio
import json
import random
from types import SimpleNamespace

import pytest

from tests.conftest import make_player
from tests.discord_fakes import FakeInteraction
from utils import bot_social as bs
from utils import dual_cultivation_logic as dual
from utils import party
from utils.bots import BOT_CAPABILITIES
from utils.items import ITEMS

HUMAN, BOT, CITY = "123456", "bot_00001", "灵虚城"

# 固定的一个性格：喜欢 丹药类 + 具体的「筑基丹」，讨厌 矿石类 + 具体的「黄泉铁」
PERSONA = {"archetype": "痴丹", "kindness": 50, "greed": 30, "pride": 40, "talk": 30,
           "likes": {"categories": ["丹药"], "items": ["筑基丹"]},
           "dislikes": {"categories": ["矿石"], "items": ["黄泉铁"]}}


def _item(cat, rarity="普通", exclude=()):
    return next(n for n, v in sorted(ITEMS.items())
                if bs.category_of(n) == cat and v.get("rarity") == rarity and n not in exclude)


@pytest.fixture
def set_day(monkeypatch):
    """换『今天』是几号（monkeypatch 会在测试结束时恢复，不会泄漏到别的测试）。"""
    def _set(day):
        monkeypatch.setattr(bs, "_today", lambda: day)
    return _set


async def _add(db, uid, city=CITY, **kw):
    D = db["db_async"]
    p = make_player(D, uid)
    p.name, p.current_city, p.lifespan = f"道友{uid}", city, 80
    p.is_bot = uid.startswith("bot_")
    for k, v in kw.items():
        setattr(p, k, v)
    async with D.AsyncSessionLocal() as s:
        s.add(p)
        await s.commit()


async def world(db, persona=PERSONA, favor=None, **bot_kw):
    await _add(db, HUMAN)
    await _add(db, BOT, **bot_kw)
    if persona:
        await bs.save_personality(BOT, persona)
    if favor is not None:
        await bs.adjust_favor(HUMAN, BOT, favor)


async def give(db, name, qty=1):
    await db["inventory"].add_item(HUMAN, name, qty)


# ---- 数据 / 生成 ------------------------------------------------------------

def test_原型数据合法():
    archetypes = bs.load_archetypes()
    assert len(archetypes) >= 8
    for name, spec in archetypes.items():
        for k in ("kindness", "greed", "pride", "talk"):
            lo, hi = spec[k]
            assert 0 <= lo <= hi <= 100, (name, k)
        assert spec["likes"] and spec["dislikes"], name
        assert set(spec["likes"]) | set(spec["dislikes"]) <= set(bs.CATEGORIES), name
        assert not set(spec["likes"]) & set(spec["dislikes"]), f"{name} 的喜好与厌恶类别冲突"
        for cat in spec["likes"] + spec["dislikes"]:
            assert any(bs.category_of(n) == cat for n in ITEMS), f"{cat} 类别下没有物品"


def test_生成的性格合法且可复现():
    archetypes = bs.load_archetypes()
    for seed in range(300):
        p = bs.generate_personality(random.Random(seed))
        spec = archetypes[p["archetype"]]
        for k in ("kindness", "greed", "pride", "talk"):
            assert spec[k][0] <= p[k] <= spec[k][1]
        assert 1 <= len(p["likes"]["categories"]) <= 2 and 1 <= len(p["dislikes"]["categories"]) <= 2
        assert 1 <= len(p["likes"]["items"]) <= 2 and 1 <= len(p["dislikes"]["items"]) <= 2
        assert not set(p["likes"]["categories"]) & set(p["dislikes"]["categories"])
        assert not set(p["likes"]["items"]) & set(p["dislikes"]["items"])
        assert all(i in ITEMS and bs.category_of(i) in p["likes"]["categories"] for i in p["likes"]["items"])
        assert all(i in ITEMS and bs.category_of(i) in p["dislikes"]["categories"] for i in p["dislikes"]["items"])
        assert bs.generate_personality(random.Random(seed)) == p


def test_每个原型都能生成():
    for name in bs.load_archetypes():
        assert bs.generate_personality(random.Random(0), archetype=name)["archetype"] == name


def test_不同种子的性格有差别():
    assert len({json.dumps(bs.generate_personality(random.Random(s)), sort_keys=True) for s in range(50)}) > 40


async def test_性格存取往返(db):
    await bs.save_personality(BOT, PERSONA)
    assert await bs.get_personality(BOT) == {**PERSONA, "tier": "正常"}
    assert await bs.get_personality("bot_99999") is None
    await bs.save_personality(BOT, {**PERSONA, "kindness": 7})          # 覆盖而不是重复
    assert (await bs.get_personality(BOT))["kindness"] == 7


# ---- 分档 / 门槛 ------------------------------------------------------------

@pytest.mark.parametrize("favor,tier", [(-100, "仇视"), (-30, "仇视"), (-29, "陌生"), (0, "陌生"), (19, "陌生"),
                                        (20, "熟识"), (49, "熟识"), (50, "至交"), (100, "至交")])
def test_好感分档(favor, tier):
    assert bs.favor_tier(favor) == tier


def test_门槛随善意浮动():
    assert bs.required_favor("party", 50) == 20 and bs.required_favor("dual", 50) == 50
    assert bs.required_favor("party", 0) == 30 and bs.required_favor("dual", 0) == 60
    assert bs.required_favor("party", 100) == 10 and bs.required_favor("dual", 100) == 40


# ---- 送礼 -------------------------------------------------------------------

async def test_送礼_具体喜欢的物品(db):
    await world(db)
    await give(db, "筑基丹")
    res = await bs.give_gift(HUMAN, BOT, "筑基丹")
    bonus = bs.RARITY_BONUS[ITEMS["筑基丹"]["rarity"]]
    assert res["ok"] and res["reaction"] == "love" and res["delta"] == 8 + bonus and res["favor"] == 8 + bonus
    inv = db["inventory"]
    assert await inv.get_inventory(HUMAN) == {} and await inv.get_inventory(BOT) == {"筑基丹": 1}


async def test_送礼_各种反应(db, set_day):
    await world(db)
    pill = _item("丹药", exclude=("筑基丹",))
    ore = _item("矿石", exclude=("黄泉铁",))
    herb = _item("药材")
    cases = [("筑基丹", "love"), (pill, "like"), (herb, "neutral"), (ore, "dislike"), ("黄泉铁", "hate")]
    for name, _ in cases:
        await give(db, name)
    got = []
    for n, (name, _) in enumerate(cases):
        set_day(f"day{n}")                                  # 一天只能 3 份：每份换一天
        got.append((await bs.give_gift(HUMAN, BOT, name))["reaction"])
    assert got == [r for _, r in cases]


def test_gift_reaction_数值():
    r = {"普通": 0, "稀有": 1, "珍贵": 2, "绝世": 3}
    rar = lambda n: r[ITEMS[n]["rarity"]]
    pill, herb, ore = _item("丹药", exclude=("筑基丹",)), _item("药材"), _item("矿石", exclude=("黄泉铁",))
    assert bs.gift_reaction(PERSONA, "筑基丹") == ("love", 8 + rar("筑基丹"))
    assert bs.gift_reaction(PERSONA, pill) == ("like", 4 + rar(pill))
    assert bs.gift_reaction(PERSONA, herb) == ("neutral", 1 + rar(herb))
    assert bs.gift_reaction(PERSONA, ore) == ("dislike", -3)
    assert bs.gift_reaction(PERSONA, "黄泉铁") == ("hate", -8)
    assert bs.gift_reaction(None, herb)[0] == "neutral"
    # 具体厌恶压过类别喜欢
    p = {**PERSONA, "dislikes": {"categories": [], "items": [pill]}}
    assert bs.gift_reaction(p, pill) == ("hate", -8)


async def test_送礼_讨厌的东西扣好感_下限负一百(db):
    await world(db, favor=-95)
    await give(db, "黄泉铁", 3)
    for _ in range(2):
        res = await bs.give_gift(HUMAN, BOT, "黄泉铁")
    assert res["favor"] == -100 == await bs.get_favor(HUMAN, BOT)       # 夹在下限，不会一路跌下去


async def test_送礼_每天最多三份_第四份不扣物品(db, set_day):
    await world(db)
    await give(db, "筑基丹", 4)
    for _ in range(3):
        assert (await bs.give_gift(HUMAN, BOT, "筑基丹"))["ok"]
    res = await bs.give_gift(HUMAN, BOT, "筑基丹")
    assert res["ok"] is False and "3 份" in res["reason"]
    assert await db["inventory"].get_inventory(HUMAN) == {"筑基丹": 1}
    set_day("明天")
    assert (await bs.give_gift(HUMAN, BOT, "筑基丹"))["ok"]            # 隔天又可以


async def test_送礼_每天涨幅封顶_跌不封顶(db, set_day):
    await world(db)
    await give(db, "筑基丹", 3)
    last = None
    for _ in range(3):
        last = await bs.give_gift(HUMAN, BOT, "筑基丹")
    assert last["favor"] == bs.GIFT_GAIN_DAILY_CAP, "三份心头好也只涨到当日上限"
    await give(db, "黄泉铁")
    set_day("明天")
    res = await bs.give_gift(HUMAN, BOT, "黄泉铁")
    assert res["delta"] == -8


async def test_送礼_涨幅封顶后物品仍然送出(db):
    await world(db)
    await give(db, "筑基丹", 3)
    for _ in range(3):
        res = await bs.give_gift(HUMAN, BOT, "筑基丹")
    assert await db["inventory"].get_inventory(BOT) == {"筑基丹": 3}
    assert res["delta"] >= 0


@pytest.mark.parametrize("case", ["no_item", "unknown_item", "far", "bot_dead", "me_dead", "to_human"])
async def test_送礼_失败什么都不改(db, case):
    await world(db, **({"is_dead": True} if case == "bot_dead" else {}))
    await give(db, "筑基丹")
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        if case == "far":
            (await s.get(D.Player, BOT)).current_city = "别处"
        if case == "me_dead":
            (await s.get(D.Player, HUMAN)).is_dead = True
        await s.commit()
    if case == "no_item":
        await db["inventory"].remove_item(HUMAN, "筑基丹")
    item = "不存在的东西" if case == "unknown_item" else "筑基丹"
    target = "654321" if case == "to_human" else BOT
    if case == "to_human":
        await _add(db, target)
    res = await bs.give_gift(HUMAN, target, item)
    assert res["ok"] is False and res["reason"]
    assert await bs.get_favor(HUMAN, BOT) == 0
    assert await db["inventory"].get_inventory(BOT) == {}


async def test_送礼_并发只送出一份(db):
    await world(db)
    await give(db, "筑基丹")
    results = await asyncio.gather(*[bs.give_gift(HUMAN, BOT, "筑基丹") for _ in range(4)])
    assert sum(r["ok"] for r in results) == 1
    assert await db["inventory"].get_inventory(BOT) == {"筑基丹": 1}
    assert await bs.get_favor(HUMAN, BOT) == results[[r["ok"] for r in results].index(True)]["favor"]


async def test_送礼_没有性格行也能送_按中性(db):
    await world(db, persona=None)
    await give(db, "筑基丹")
    res = await bs.give_gift(HUMAN, BOT, "筑基丹")
    assert res["ok"] and res["reaction"] == "neutral"


# ---- 闲聊 -------------------------------------------------------------------

async def test_闲聊_每天第一次涨好感_健谈多涨(db, set_day):
    await world(db, persona={**PERSONA, "talk": 30})
    assert (await bs.chat(HUMAN, BOT))["delta"] == 1
    assert (await bs.chat(HUMAN, BOT))["delta"] == 0
    assert await bs.get_favor(HUMAN, BOT) == 1
    set_day("明天")
    assert (await bs.chat(HUMAN, BOT))["delta"] == 1


async def test_闲聊_健谈的涨两点(db):
    await world(db, persona={**PERSONA, "talk": 60})
    assert (await bs.chat(HUMAN, BOT))["delta"] == 2


async def test_闲聊_不在同城或已坐化被拒(db):
    await world(db, current_city="别处")
    res = await bs.chat(HUMAN, BOT)
    assert res["ok"] is False and "不在此地" in res["reason"]


# ---- 闸门 -------------------------------------------------------------------

async def test_闸门_真人之间不受影响(db):
    assert await bs.bot_gate("party", "1", "2") is None and await bs.bot_gate("dual", "1", "2") is None


async def test_闸门_机器人之间不行(db):
    assert "之间" in await bs.bot_gate("party", "bot_1", "bot_2")


async def test_闸门_组队要熟识_差多少会告诉你(db):
    await world(db, favor=19)
    msg = await bs.bot_gate("party", HUMAN, BOT)
    assert "19/20" in msg and "组队" in msg
    await bs.adjust_favor(HUMAN, BOT, 1)
    assert await bs.bot_gate("party", HUMAN, BOT) is None
    assert await bs.bot_gate("party", BOT, HUMAN) is None, "参数顺序无关"


async def test_闸门_双修要至交(db):
    await world(db, favor=49)
    assert "49/50" in await bs.bot_gate("dual", HUMAN, BOT)
    await bs.adjust_favor(HUMAN, BOT, 1)
    assert await bs.bot_gate("dual", HUMAN, BOT) is None


async def test_闸门_善意高的门槛低_善意低的门槛高(db):
    await world(db, persona={**PERSONA, "kindness": 100}, favor=40)
    assert await bs.bot_gate("dual", HUMAN, BOT) is None                      # 门槛 40
    await bs.save_personality(BOT, {**PERSONA, "kindness": 0})
    assert "40/60" in await bs.bot_gate("dual", HUMAN, BOT)                   # 门槛 60


async def test_闸门_没有性格行按善意50(db):
    await world(db, persona=None, favor=20)
    assert await bs.bot_gate("party", HUMAN, BOT) is None


async def test_闸门_仇视一律拒绝(db):
    await world(db, favor=-30)
    assert "怀恨在心" in await bs.bot_gate("party", HUMAN, BOT)
    assert "怀恨在心" in await bs.bot_gate("dual", HUMAN, BOT)


async def test_闸门_好感是各人各自的(db):
    await world(db, favor=60)
    await _add(db, "654321")
    assert await bs.bot_gate("dual", HUMAN, BOT) is None
    assert "0/" in await bs.bot_gate("dual", "654321", BOT)


async def test_闸门_总开关关掉优先(db, monkeypatch):
    await world(db, favor=100)
    monkeypatch.setitem(BOT_CAPABILITIES, "dual", False)
    assert "双修" in await bs.bot_gate("dual", HUMAN, BOT)


# ---- 接入组队 / 双修 --------------------------------------------------------

async def test_组队_好感够_机器人入队(db):
    await world(db, favor=20)
    res = await party.accept_invite(HUMAN, BOT)
    assert res["ok"]
    members = {m["discord_id"] for m in await party.get_party_members(res["party_id"])}
    assert members == {HUMAN, BOT}


async def test_组队_好感不够_不建队(db):
    await world(db, favor=19)
    res = await party.accept_invite(HUMAN, BOT)
    assert res["ok"] is False and "交情尚浅" in res["reason"]
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        assert (await s.get(D.Player, HUMAN)).party_id is None


async def test_组队_机器人不会主动邀请(db):
    await world(db, favor=100)
    res = await party.accept_invite(BOT, HUMAN)
    assert res["ok"] is False and "主动" in res["reason"]


async def test_add_to_party_按队长的好感判断(db):
    await world(db, favor=20)
    pid = await party.create_party(HUMAN, CITY)
    assert await party.add_to_party(pid, BOT) is True
    assert await party.add_to_party("不存在的队伍", BOT) is False


async def test_add_to_party_好感不够(db):
    await world(db, favor=0)
    pid = await party.create_party(HUMAN, CITY)
    assert await party.add_to_party(pid, BOT) is False


async def test_双修_好感够_双方失去清白身(db):
    await world(db, favor=50, is_virgin=True)
    res = await dual.start_dual_cultivation(HUMAN, BOT)
    assert res["success"] is True
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        h, b = await s.get(D.Player, HUMAN), await s.get(D.Player, BOT)
        assert h.dual_partner_id == BOT and b.dual_partner_id == HUMAN
        assert not h.is_virgin and not b.is_virgin and b.cultivating_until


async def test_双修_好感不够_什么都不改(db):
    await world(db, favor=49)
    res = await dual.start_dual_cultivation(HUMAN, BOT)
    assert res["success"] is False and "49/50" in res["message"]
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        h = await s.get(D.Player, HUMAN)
        assert h.dual_partner_id is None and h.is_virgin and h.lifespan == 80


async def test_双修_机器人冷却中不能连续约(db):
    """清白身用掉后仍受 2 游戏年冷却限制：机器人不能被无限次约。"""
    await world(db, favor=100)
    assert (await dual.start_dual_cultivation(HUMAN, BOT))["success"]
    await _add(db, "654321")
    await bs.adjust_favor("654321", BOT, 100)
    res = await dual.start_dual_cultivation("654321", BOT)
    assert res["success"] is False


# ---- 面板 -------------------------------------------------------------------

def _inter(uid, client=None):
    i = FakeInteraction(uid)
    i.client = client or SimpleNamespace(cogs={}, fetch_user=None)
    return i


async def _as_dict(db, uid):
    from utils.player import get_player
    return await get_player(uid)


async def test_面板_组队邀请机器人_好感够当场入队(db):
    from utils.views.party import PartyInviteButton
    await world(db, favor=20)
    btn = PartyInviteButton(await _as_dict(db, HUMAN), await _as_dict(db, BOT))
    i = _inter(HUMAN)
    await btn.callback(i)
    assert "组队成功" in i.last.embed.title and "欣然应允" in i.last.embed.description


async def test_面板_组队邀请机器人_好感不够给提示(db):
    from utils.views.party import PartyInviteButton
    await world(db, favor=5)
    btn = PartyInviteButton(await _as_dict(db, HUMAN), await _as_dict(db, BOT))
    i = _inter(HUMAN)
    await btn.callback(i)
    assert "5/20" in i.last and i.last.ephemeral


async def test_面板_双修邀请机器人_好感够当场结算(db):
    from utils.views.combat import PlayerActionView
    await world(db, favor=50)
    done = {}

    class Cog:
        async def do_dual_cultivate(self, interaction, inviter, target, multiplier, both_virgin):
            done.update(target=target, multiplier=multiplier, both=both_virgin)

    i = _inter(HUMAN, SimpleNamespace(cogs={"Cultivation": Cog()}, fetch_user=None))
    v = PlayerActionView(i.user, await _as_dict(db, HUMAN), await _as_dict(db, BOT), False)
    v.viewer["techniques"] = json.dumps(["双修功法"])
    await v._dual_cultivate_callback(i)
    assert done["target"].id == BOT and done["target"].display_name == f"道友{BOT}"
    assert done["both"] is True and 10 <= done["multiplier"] <= 20, "和真人一样：双方都清白就是 ×10~20"


async def test_好感上限一百(db):
    await world(db, favor=100)
    await give(db, "筑基丹")
    res = await bs.give_gift(HUMAN, BOT, "筑基丹")
    assert res["favor"] == 100 and await bs.adjust_favor(HUMAN, BOT, 50) == 100
