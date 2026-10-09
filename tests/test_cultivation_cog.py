"""闭关 cog 的命令与面板入口测试（cogs/cultivation.py）。

定时结算任务在 tests/test_notifiers.py，这里测的是玩家直接触碰的那些入口：
死亡 / 轮回判定、角色面板、修炼、停止、突破、主菜单、双修邀请、cog 的启停。

这个文件里有不少「按钮入口」和「命令入口」成对出现的逻辑（角色面板、停止、突破）——
它们是复制粘贴出来的两份，所以每一对都配了「两条路径结果一致」的用例；
`/突破` 命令就曾经因此落后于按钮（绕过化神之壁，ISSUES.md B15）。

玩家 ID 取数字：cog 里会 `int(uid)` 去 fetch_user，真实的 Discord ID 也是数字。
"""

import json
import time

import pytest

from cogs import cultivation as cult
from cogs.cultivation import CultivationCog
from tests.conftest import make_player
from tests.discord_fakes import FakeContext, FakeInteraction
from tests.test_dual_cultivation import _FakeUser, _Member
from utils import breakthrough_logic as bt
from utils.character import CAVE_BONUS, calc_cultivation_gain, years_to_seconds
from utils.realms import cultivation_needed

UID, PARTNER = "1", "2002"
DUAL_TECH = json.dumps(["双修功法"])


class FakeBot:
    def __init__(self):
        self.users = {}
        self.cogs = {}

    async def fetch_user(self, uid):
        return self.users.setdefault(uid, _FakeUser())


@pytest.fixture
def cog():
    return CultivationCog(bot=FakeBot())


async def _add_player(db, uid=UID, **fields):
    D = db["db_async"]
    p = make_player(D, uid, stones=500)
    p.name = f"道友{uid}"
    p.gender = "男"
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


def ctx(uid=UID):
    return FakeContext(user_id=int(uid))


def it(uid=UID):
    return FakeInteraction(user_id=int(uid))


def at_breakthrough(realm, extra=0, **fields):
    """修为刚好够突破的玩家，寿元管够，免得被死亡判定打断。"""
    return dict(realm=realm, cultivation=cultivation_needed(realm) + extra,
                lifespan=99999, lifespan_max=99999, **fields)


def field(message, name):
    return next((f.value for f in message.embed.fields if f.name == name), None)


# =============================================================================
# A. 死亡 / 轮回 / 阴阳奇遇的判定（_check_dead）
# =============================================================================

async def test_活着的人_什么都不发生(db, cog):
    await _add_player(db)
    c = ctx()
    assert await cog._check_dead(c, await cult.get_player(UID)) is False
    assert c.messages == []


async def test_寿元耗尽_没有轮回资格_就是死亡(db, cog):
    await _add_player(db, lifespan=0)
    c = ctx()

    assert await cog._check_dead(c, await cult.get_player(UID)) is True

    assert c.said("魂归天道") and c.said("创建角色")
    assert (await _row(db)).is_dead is True


@pytest.mark.parametrize("fields,reason", [
    ({"sect": "仙葬谷"}, "仙葬谷轮回传承"),
    ({"has_bahongchen": True}, "阴阳奇遇感应"),
])
async def test_寿元耗尽_有轮回资格_重生并继承属性(db, cog, fields, reason):
    await _add_player(db, lifespan=0, comprehension=15, rebirth_count=0, **fields)
    c = ctx()

    assert await cog._check_dead(c, await cult.get_player(UID)) is True

    assert c.said("轮回重生") and c.said(reason) and c.said("第 **1** 次轮回")
    p = await _row(db)
    assert p.is_dead is False and p.realm == "炼气期1层" and p.rebirth_count == 1
    assert p.comprehension == 15 + 3                         # (15-5)*0.3 继承


async def test_已标记死亡但寿元还有_同样走死亡流程(db, cog):
    await _add_player(db, is_dead=True, lifespan=50)
    c = ctx()
    assert await cog._check_dead(c, await cult.get_player(UID)) is True
    assert c.said("魂归天道")


async def test_触发阴阳奇遇_发出奇遇面板_而不是死亡或轮回(db, cog, monkeypatch):
    from utils.views.yinyang import YinYangView
    await _add_player(db, lifespan=0)
    monkeypatch.setattr(cult, "should_trigger_yinyang", lambda player: True)
    c = ctx()

    assert await cog._check_dead(c, await cult.get_player(UID)) is True

    assert isinstance(c.last.view, YinYangView)
    assert (await _row(db)).is_dead is False                 # 奇遇期间人还没死透
    assert not c.said("魂归天道")


# =============================================================================
# B. 角色面板（按钮 send_profile / 命令 查看·我的角色）
# =============================================================================

async def test_面板_没有角色(db, cog):
    i = it()
    await cog.send_profile(i)
    assert i.said("尚未踏入修仙之路")
    c = ctx()
    await cog.view.callback(cog, c)
    assert c.said("尚未踏入修仙之路")


async def test_面板_基本信息与各项属性(db, cog):
    from utils.views import ProfileView
    await _add_player(db, realm="炼气期5层", cultivation=30, spirit_root_type="双灵根", spirit_root="金·木",
                      comprehension=7, physique=8, fortune=9, bone=6, soul=5, spirit_stones=1234,
                      current_city="灵虚城", is_virgin=True)
    i = it()

    await cog.send_profile(i)

    m = i.last
    assert m.embed.title == "✦ 道友1 ✦"
    assert "男修 · 炼气期5层" in m.embed.description and "空闲" in m.embed.description and "灵虚城" in m.embed.description
    assert field(m, "灵根") == "双灵根·金·木（较快）"
    assert field(m, "修为") == f"30 / {cultivation_needed('炼气期5层')}"
    assert field(m, "寿元") == "100 / 100 年"
    assert (field(m, "灵石"), field(m, "悟性"), field(m, "体魄"), field(m, "机缘"), field(m, "根骨"), field(m, "神识")) \
        == ("1234", "7", "8", "9", "6", "5")                   # embed 会把字段值转成字符串
    assert field(m, "身") == "处男"
    assert field(m, "综合战力") and field(m, "逃跑成功率")
    assert isinstance(m.view, ProfileView)


@pytest.mark.parametrize("gender,virgin,label", [
    ("男", True, "处男"), ("男", False, "非处男"), ("女", True, "处女"), ("女", False, "非处女"),
])
async def test_面板_清白身标签(db, cog, gender, virgin, label):
    await _add_player(db, gender=gender, is_virgin=virgin)
    i = it()
    await cog.send_profile(i)
    assert field(i.last, "身") == label


async def test_面板_状态_闭关中_采集中_空闲(db, cog):
    await _add_player(db, cultivating_until=time.time() + years_to_seconds(3), cultivating_years=3)
    i = it()
    await cog.send_profile(i)
    assert "闭关中（还剩 3.0 年）" in i.last.embed.description

    await _set(db, cultivating_until=None, cultivating_years=None,
               gathering_until=time.time() + years_to_seconds(2), gathering_type="采药")
    i = it()
    await cog.send_profile(i)
    assert "采药中（还剩 2.0 年）" in i.last.embed.description


async def test_面板_可选字段_逃跑率_奇遇_炼丹师(db, cog):
    await _add_player(db, escape_rate=50, has_bahongchen=True, alchemy_level=3, alchemy_exp=120)
    i = it()
    await cog.send_profile(i)
    m = i.last
    assert field(m, "奇遇") == "阴阳两界 · 已触发"
    assert any(f.name == "逃跑成功率" and f.value == "+50%" for f in m.embed.fields)
    assert field(m, "炼丹师 3 品") == "经验 120 / 300"


async def test_面板_炼丹师满级(db, cog):
    await _add_player(db, alchemy_level=9, alchemy_exp=3000)
    i = it()
    await cog.send_profile(i)
    assert "满级" in field(i.last, "炼丹师 9 品")


async def test_面板_没有炼丹等级就不显示炼丹师(db, cog):
    await _add_player(db)
    i = it()
    await cog.send_profile(i)
    assert not any(f.name.startswith("炼丹师") for f in i.last.embed.fields)


async def test_面板_功法加寿元时标注含功法(db, cog, monkeypatch):
    await _add_player(db)
    monkeypatch.setattr(cult, "get_effective_lifespan_max", lambda player: 130)
    i = it()
    await cog.send_profile(i)
    assert field(i.last, "寿元") == "100 / 130 年（含功法）"


async def test_面板_同城的其他修士传给面板(db, cog):
    await _add_player(db, current_city="灵虚城")
    await _add_player(db, "3003", current_city="灵虚城")
    await _add_player(db, "4004", current_city="别处")
    await _add_player(db, "5005", current_city="灵虚城", is_dead=True)
    i = it()
    await cog.send_profile(i)
    assert [p["discord_id"] for p in i.last.view.city_players] == ["3003"]


async def test_面板_按钮入口遇到寿元耗尽_只标记死亡(db, cog):
    await _add_player(db, lifespan=0)
    i = it()
    await cog.send_profile(i)
    assert i.said("寿元已尽，魂归天道") and (await _row(db)).is_dead is True


@pytest.mark.parametrize("name", ["view", "my_character"])
async def test_面板_命令入口与按钮入口展示一致(db, cog, name):
    """两份复制粘贴的实现，展示内容必须一致 —— 改了一份忘了另一份会在这里红。"""
    await _add_player(db, escape_rate=20, has_bahongchen=True, alchemy_level=2, alchemy_exp=60)
    i, c = it(), ctx()

    await cog.send_profile(i)
    await getattr(cog, name).callback(cog, c)

    def shape(msg):
        return (msg.embed.title, msg.embed.description,
                [(f.name, str(f.value), f.inline) for f in msg.embed.fields])
    assert shape(i.last) == shape(c.last)


async def test_面板_命令入口遇到死亡_走轮回而不只是标记(db, cog):
    """两条入口在这里有意不同：命令走 _check_dead（可轮回），按钮只标记死亡。记录现状。"""
    await _add_player(db, lifespan=0, sect="仙葬谷")
    c = ctx()
    await cog.view.callback(cog, c)
    assert c.said("轮回重生") and (await _row(db)).rebirth_count == 1


# =============================================================================
# C. 修炼（按钮 send_cultivate / start_cultivate、命令 修炼）
# =============================================================================

async def test_选择时长_给出面板(db, cog):
    from utils.views.cultivation import CultivateView
    await _add_player(db, spirit_root_type="单灵根", cave="洞府")
    i = it()

    await cog.send_cultivate(i)

    m = i.last
    assert isinstance(m.view, CultivateView)
    assert "当前寿元：**100 年**" in m.embed.description
    assert "极快（×2.0）" in m.embed.description
    assert f"+{int(CAVE_BONUS * 100)}%" in m.embed.description


@pytest.mark.parametrize("fields,phrase", [
    ({"lifespan": 0}, "寿元已尽"),
    ({"cultivating_until": time.time() + years_to_seconds(5)}, "正在闭关"),
    ({"gathering_until": time.time() + years_to_seconds(5), "gathering_type": "采药"}, "正在采集中"),
])
async def test_选择时长_被拒绝的情形(db, cog, fields, phrase):
    await _add_player(db, **fields)
    i = it()
    await cog.send_cultivate(i)
    assert i.said(phrase) and i.last.view is None


async def test_选择时长_没有角色与守城(db, cog, monkeypatch):
    i = it()
    await cog.send_cultivate(i)
    assert i.said("尚未踏入修仙之路")

    await _add_player(db)

    async def _defending(uid):
        return True
    monkeypatch.setattr(cult, "is_defending", _defending)
    i = it()
    await cog.send_cultivate(i)
    assert i.said("守城期间无法修炼") and i.last.ephemeral


async def test_开始修炼_按钮入口_成功(db, cog):
    await _add_player(db)
    i = it()

    await cog.start_cultivate(i, 4)

    assert i.said("开始闭关修炼 **4 年**（现实 8 小时）")
    assert i.said(f"出关后将获得约 +{int(calc_cultivation_gain(4, 5, '单灵根'))}")
    assert (await _row(db)).cultivating_years == 4


async def test_开始修炼_按钮入口_速度加成提示(db, cog):
    await _add_player(db, active_buffs=json.dumps({"cultivation_speed_bonus": {"value": 50}}))
    i = it()
    await cog.start_cultivate(i, 1)
    assert i.said("修炼速度加成 +50%")


async def test_开始修炼_按钮入口_失败与守城(db, cog, monkeypatch):
    await _add_player(db, lifespan=2)
    i = it()
    await cog.start_cultivate(i, 8)
    assert i.said("寿元不足")

    async def _defending(uid):
        return True
    monkeypatch.setattr(cult, "is_defending", _defending)
    i = it()
    await cog.start_cultivate(i, 1)
    assert i.said("守城期间无法修炼")


async def test_修炼命令_成功_写入闭关状态(db, cog):
    await _add_player(db)
    c = ctx()
    before = time.time()

    await cog.cultivate.callback(cog, c, 3)

    p = await _row(db)
    assert p.cultivating_years == 3
    assert before + years_to_seconds(3) <= p.cultivating_until <= time.time() + years_to_seconds(3)
    assert c.said("开始闭关修炼 **3 年**") and c.said("预计现实时间 **6 小时**")
    assert c.said(f"出关后将获得约 +{int(calc_cultivation_gain(3, 5, '单灵根'))}")


async def test_修炼命令_默认一年(db, cog):
    await _add_player(db)
    c = ctx()
    await cog.cultivate.callback(cog, c)
    assert (await _row(db)).cultivating_years == 1


async def test_修炼命令_洞府与丹药加成计入预估(db, cog):
    await _add_player(db, cave="洞府", active_buffs=json.dumps({"cultivation_speed_bonus": {"value": 50}}))
    c = ctx()
    await cog.cultivate.callback(cog, c, 2)
    exp = int(calc_cultivation_gain(2, 5, "单灵根") * (1 + CAVE_BONUS + 0.5))
    assert c.said(f"+{exp}") and c.said("修炼速度加成 +50%")


@pytest.mark.parametrize("fields,years,phrase", [
    ({}, 0, "1 至 100"),
    ({}, 101, "1 至 100"),
    ({"lifespan": 3}, 5, "寿元不足"),
    ({"cultivating_until": time.time() + years_to_seconds(5)}, 1, "正在闭关修炼"),
    ({"gathering_until": time.time() + years_to_seconds(5), "gathering_type": "采药"}, 1, "正在采集中"),
])
async def test_修炼命令_被拒绝的情形(db, cog, fields, years, phrase):
    await _add_player(db, **fields)
    c = ctx()
    before = (await _row(db)).cultivating_until

    await cog.cultivate.callback(cog, c, years)

    assert c.said(phrase)
    assert (await _row(db)).cultivating_until == before


async def test_修炼命令_没有角色_死亡_守城(db, cog, monkeypatch):
    c = ctx()
    await cog.cultivate.callback(cog, c)
    assert c.said("尚未踏入修仙之路")

    await _add_player(db, lifespan=0)
    c = ctx()
    await cog.cultivate.callback(cog, c)
    assert c.said("魂归天道") and (await _row(db)).cultivating_until is None

    await _set(db, lifespan=100, is_dead=False)

    async def _defending(uid):
        return True
    monkeypatch.setattr(cult, "is_defending", _defending)
    c = ctx()
    await cog.cultivate.callback(cog, c)
    assert c.said("守城期间无法修炼")


# =============================================================================
# D. 停止闭关（按钮 send_stop / 命令 停止）
# =============================================================================

def _mid(elapsed, total=10, **extra):
    now = time.time()
    return dict(cultivating_until=now + years_to_seconds(total - elapsed), cultivating_years=total,
                last_active=now - years_to_seconds(elapsed), **extra)


async def test_停止_单人_两条入口文案一致(db, cog):
    await _add_player(db, lifespan=50, **_mid(4))
    i = it()
    await cog.send_stop(i)
    first = i.last.content

    await _add_player(db, "9", lifespan=50, **_mid(4))
    c = ctx("9")
    await cog.stop_cultivate.callback(cog, c)

    assert "退出闭关" in first and "实际修炼 **4 年**" in first and "寿元剩余：46 年" in first
    # 两条入口只差最前面的 @提及 与玩家名
    assert first.split("\n", 1)[1] == c.last.content.split("\n", 1)[1]


async def test_停止_没在闭关(db, cog):
    await _add_player(db)
    i, c = it(), ctx()
    await cog.send_stop(i)
    await cog.stop_cultivate.callback(cog, c)
    assert i.said("并未在闭关") and c.said("道友当前并未在闭关")


async def test_停止_没有角色(db, cog):
    c = ctx()
    await cog.stop_cultivate.callback(cog, c)
    assert c.said("尚未踏入修仙之路")


async def _dual_pair(db):
    await _add_player(db, UID, lifespan=50, dual_partner_id=PARTNER, techniques=DUAL_TECH, **_mid(4))
    await _add_player(db, PARTNER, lifespan=60, dual_partner_id=UID, **_mid(4))


@pytest.mark.parametrize("entry", ["button", "command"])
async def test_停止_双修_双方出关_并私信搭档(db, cog, entry):
    await _dual_pair(db)
    if entry == "button":
        i = it()
        await cog.send_stop(i)
        text = i.last.content
    else:
        c = ctx()
        await cog.stop_cultivate.callback(cog, c)
        text = c.last.content

    assert "双修中止" in text and "双方已同时出关" in text and f"道友{PARTNER}" in text
    assert (await _row(db)).cultivating_until is None and (await _row(db, PARTNER)).cultivating_until is None
    dm = cog.bot.users[int(PARTNER)].sent
    assert len(dm) == 1


@pytest.mark.parametrize("entry", ["button", "command"])
async def test_停止_双修_搭档私信失败不影响结算(db, cog, entry):
    await _dual_pair(db)

    async def _closed(uid):
        raise RuntimeError("对方关了私信")
    cog.bot.fetch_user = _closed

    if entry == "button":
        i = it()
        await cog.send_stop(i)
        assert i.said("双修中止")
    else:
        c = ctx()
        await cog.stop_cultivate.callback(cog, c)
        assert c.said("双修中止")
    assert (await _row(db, PARTNER)).cultivating_until is None


# =============================================================================
# E. 突破（按钮 send_breakthrough / 命令 突破）
# =============================================================================

PILL_STAGES = [
    ("炼气期10层", "炼气化液 · 筑基之关", "ZhujiBreakthroughView", "筑基丹"),
    ("筑基期10层", "筑基化液 · 结丹之关", "NingdanBreakthroughView", "凝丹丹"),
    ("结丹期后期", "金丹破碎 · 元婴之关", "HuayingBreakthroughView", "化婴丹"),
]


async def test_突破_没有角色(db, cog):
    i, c = it(), ctx()
    await cog.send_breakthrough(i)
    await cog.breakthrough.callback(cog, c)
    assert i.said("尚未踏入修仙之路") and c.said("尚未踏入修仙之路")


async def test_突破_闭关中要先结束(db, cog):
    await _add_player(db, **at_breakthrough("炼气期1层"), cultivating_until=time.time() + 999, cultivating_years=5)
    i, c = it(), ctx()
    await cog.send_breakthrough(i)
    await cog.breakthrough.callback(cog, c)
    assert i.said("请先结束闭关") and c.said("请先结束闭关")


async def test_突破_修为不够_告诉还差多少(db, cog):
    await _add_player(db, realm="炼气期1层", cultivation=60, lifespan=99999, lifespan_max=99999)
    i, c = it(), ctx()
    await cog.send_breakthrough(i)
    await cog.breakthrough.callback(cog, c)
    assert i.said("还差 **40** 点") and c.said("还差 **40** 点")


@pytest.mark.parametrize("realm,title,view_name,pill", PILL_STAGES)
async def test_突破_三道大关出丹药面板_按钮入口(db, cog, realm, title, view_name, pill):
    await _add_player(db, **at_breakthrough(realm))
    i = it()

    await cog.send_breakthrough(i)

    m = i.last
    assert m.embed.title == f"✦ {title} ✦" and type(m.view).__name__ == view_name
    assert "当前突破成功率" in m.embed.description and f"（背包中无{pill}）" in m.embed.description
    assert [b.label for b in m.view.children] == ["直接冲关"]


@pytest.mark.parametrize("realm,title,view_name,pill", PILL_STAGES)
async def test_突破_有丹药时面板多一个服用选项(db, cog, realm, title, view_name, pill):
    await _add_player(db, **at_breakthrough(realm))
    await db["inventory"].add_item(UID, pill, 1)
    i = it()
    await cog.send_breakthrough(i)
    assert f"服用{pill}后" in i.last.embed.description
    assert [b.label for b in i.last.view.children] == [f"服用{pill}冲关", "直接冲关"]


async def test_突破_筑基大关_悟性机缘够高提示可直接冲关(db, cog):
    await _add_player(db, **at_breakthrough("炼气期10层"), comprehension=12, fortune=9)
    i = it()
    await cog.send_breakthrough(i)
    assert "可直接冲关" in i.last.embed.description


async def test_突破_元婴期后期被化神之壁拦住_按钮入口(db, cog):
    await _add_player(db, **at_breakthrough("元婴期后期"))
    i = it()

    await cog.send_breakthrough(i)

    assert "化神之壁" in i.last.embed.title and i.last.view is None
    assert "尚在封印之中" in i.last.embed.description
    assert (await _row(db)).realm == "元婴期后期"


# --- 命令入口必须与按钮入口一致（B15）-------------------------------------------

@pytest.mark.parametrize("realm,title,view_name,pill", PILL_STAGES)
async def test_突破_命令入口也出丹药面板(db, cog, realm, title, view_name, pill):
    """B15 回归：`/突破` 命令曾只认炼气期10层，筑基期10层 / 结丹期后期 掉进普通连续突破，
    没有丹药面板，成功率也不是大关的那套。"""
    await _add_player(db, **at_breakthrough(realm))
    c = ctx()

    await cog.breakthrough.callback(cog, c)

    m = c.last
    assert m.embed is not None and m.embed.title == f"✦ {title} ✦"
    assert type(m.view).__name__ == view_name
    assert (await _row(db)).realm == realm                   # 面板只是询问，不会自己突破


async def test_突破_命令入口也被化神之壁拦住(db, cog):
    """B15 回归：`/突破` 命令曾直接把元婴期后期的玩家突破到化神期初期，绕过了封印。"""
    await _add_player(db, **at_breakthrough("元婴期后期"))
    c = ctx()

    await cog.breakthrough.callback(cog, c)

    assert c.last.embed is not None and "化神之壁" in c.last.embed.title
    assert (await _row(db)).realm == "元婴期后期"


@pytest.mark.parametrize("realm", [r for r, *_ in PILL_STAGES] + ["元婴期后期"])
async def test_突破_按钮与命令对每个关卡给出同样的东西(db, cog, realm):
    await _add_player(db, **at_breakthrough(realm))
    i, c = it(), ctx()

    await cog.send_breakthrough(i)
    await cog.breakthrough.callback(cog, c)

    assert i.last.embed.title == c.last.embed.title
    assert i.last.embed.description == c.last.embed.description
    assert type(i.last.view) is type(c.last.view)


# --- 普通小境界：走连续突破 ----------------------------------------------------

def _force(monkeypatch, *results):
    seq = iter(results)
    monkeypatch.setattr(bt, "roll_breakthrough", lambda *a, **k: next(seq))


async def test_突破_普通境界_单次成功(db, cog, monkeypatch):
    await _add_player(db, **at_breakthrough("炼气期1层"))
    _force(monkeypatch, (True, None))
    i = it()

    await cog.send_breakthrough(i)

    assert i.said("🎉 突破成功！") and i.said("**炼气期1层** ➜ **炼气期2层**")
    assert (await _row(db)).realm == "炼气期2层"


async def test_突破_普通境界_连续突破汇总(db, cog, monkeypatch):
    await _add_player(db, realm="炼气期1层", cultivation=250, lifespan=99999, lifespan_max=99999)
    _force(monkeypatch, (True, None), (True, None))
    c = ctx()

    await cog.breakthrough.callback(cog, c)

    assert c.said("连续突破 2 次") and c.said("炼气期2层") and c.said("炼气期3层")


async def test_突破_普通境界_失败的提示(db, cog, monkeypatch):
    from utils.realms import FAIL_LIGHT
    await _add_player(db, **at_breakthrough("炼气期1层"))
    _force(monkeypatch, (False, FAIL_LIGHT))
    i = it()

    await cog.send_breakthrough(i)

    assert i.said("突破失败") and not i.said("🎉")


async def test_突破_连续突破中途失败_汇总里带失败行(db, cog, monkeypatch):
    from utils.realms import FAIL_LIGHT
    await _add_player(db, realm="炼气期1层", cultivation=250, lifespan=99999, lifespan_max=99999)
    _force(monkeypatch, (True, None), (False, FAIL_LIGHT))
    c = ctx()

    await cog.breakthrough.callback(cog, c)

    assert c.said("连续突破 1 次") and c.said("突破失败")


async def test_突破命令_死亡走死亡流程_不会拿尸体去突破(db, cog):
    await _add_player(db, lifespan=0, realm="炼气期1层", cultivation=100)
    c = ctx()
    await cog.breakthrough.callback(cog, c)
    assert c.said("魂归天道") and (await _row(db)).realm == "炼气期1层"


# =============================================================================
# F. 主菜单（c / h / 别名）
# =============================================================================

async def test_菜单_有角色_给出主菜单(db, cog):
    from utils.views import MainMenuView
    await _add_player(db, techniques=DUAL_TECH)
    c = ctx()

    await cog.menu_c.callback(cog, c)

    assert isinstance(c.last.view, MainMenuView) and c.last.embed is not None


async def test_菜单_c与h的区别只在是否仅玩法说明(db, cog):
    await _add_player(db)
    c1, c2 = ctx(), ctx()
    await cog.menu_c.callback(cog, c1)
    await cog.menu_h.callback(cog, c2)
    assert c1.last.embed.to_dict() != c2.last.embed.to_dict()


async def test_菜单_修为圆满时主菜单知道可以突破(db, cog):
    await _add_player(db, **at_breakthrough("炼气期1层"))
    c = ctx()
    await cog.menu_c.callback(cog, c)
    labels = [getattr(b, "label", "") for b in c.last.view.children]
    assert any("突破" in (lbl or "") for lbl in labels)


async def test_菜单_没有角色_转去创建角色流程(db, cog):
    called = []

    class FakeCharacterCog:
        async def create_character(self, ctx_):
            called.append(ctx_)
    cog.bot.cogs["Character"] = FakeCharacterCog()
    c = ctx()

    await cog.menu_c.callback(cog, c)

    assert called == [c]


async def test_菜单_已坐化的人也走创建角色流程(db, cog):
    called = []

    class FakeCharacterCog:
        async def create_character(self, ctx_):
            called.append(ctx_)
    cog.bot.cogs["Character"] = FakeCharacterCog()
    await _add_player(db, is_dead=True)
    await cog.menu_h.callback(cog, ctx())
    assert len(called) == 1


async def test_菜单_角色系统不可用时给出提示(db, cog):
    c = ctx()
    await cog.menu_c.callback(cog, c)
    assert c.said("角色系统暂时不可用")


async def test_菜单_同城玩家传给主菜单(db, cog):
    await _add_player(db, current_city="灵虚城")
    await _add_player(db, "3003", current_city="灵虚城")
    await _add_player(db, "4004", current_city="别处")
    c = ctx()
    await cog.menu_c.callback(cog, c)
    assert [p["discord_id"] for p in c.last.view._city_players] == ["3003"]


# =============================================================================
# G. 双修邀请命令的拒绝分支（成功路径在 test_dual_cultivation.py）
# =============================================================================

def _member(uid=PARTNER, bot=False):
    m = _Member(uid, f"成员{uid}")
    m.bot = bot
    return m


async def _dual_ready(db):
    await _add_player(db, UID, techniques=DUAL_TECH, current_city="灵虚城")
    await _add_player(db, PARTNER, current_city="灵虚城")


async def test_双修命令_缺少或非法的对象(db, cog):
    await _add_player(db)
    for target, phrase in [(None, "用法"), (_member(UID), "无法与自己双修"), (_member("9", bot=True), "对方不是修士")]:
        c = ctx()
        await cog.dual_cultivate.callback(cog, c, target)
        assert c.said(phrase), phrase


@pytest.mark.parametrize("who,fields,phrase", [
    (UID, {"is_dead": True}, "尚未踏入修仙之路或已坐化"),
    (PARTNER, {"is_dead": True}, "对方尚未踏入修仙之路或已坐化"),
    (PARTNER, {"current_city": "别处"}, "同一城市"),
    (UID, {"last_dual_cultivate": "recent"}, "双修冷却中"),
    (PARTNER, {"last_dual_cultivate": "recent"}, "双修冷却中"),
    (UID, {"cultivating_until": "soon"}, "正在闭关"),
    (PARTNER, {"cultivating_until": "soon"}, "正在闭关"),
    (UID, {"lifespan": 0}, "寿元不足"),
    (PARTNER, {"lifespan": 0}, "对方寿元不足"),
])
async def test_双修命令_被拒绝的情形(db, cog, who, fields, phrase):
    await _dual_ready(db)
    fields = {k: (time.time() - years_to_seconds(1) if v == "recent" else time.time() + 999 if v == "soon" else v)
              for k, v in fields.items()}
    await _set(db, who, **fields)
    c = ctx()

    await cog.dual_cultivate.callback(cog, c, _member())

    assert c.said(phrase) and c.last.view is None


async def test_双修命令_对象没有角色(db, cog):
    await _add_player(db, techniques=DUAL_TECH)
    c = ctx()
    await cog.dual_cultivate.callback(cog, c, _member("7777"))
    assert c.said("对方尚未踏入修仙之路或已坐化")


async def test_双修命令_双方都没有双修功法(db, cog):
    await _add_player(db, UID)
    await _add_player(db, PARTNER)
    c = ctx()
    await cog.dual_cultivate.callback(cog, c, _member())
    assert c.said("双方均未习得「双修功法」")


async def test_双修命令_只要对方会双修功法也行(db, cog):
    from utils.views.dual import DualCultivateInviteView
    await _add_player(db, UID)
    await _add_player(db, PARTNER, techniques=json.dumps([{"name": "双修功法", "stage": "入门"}]))
    c = ctx()
    await cog.dual_cultivate.callback(cog, c, _member())
    assert isinstance(c.last.view, DualCultivateInviteView)


async def test_双修接受_失败时告知原因(db, cog):
    """对方接受时状态已变（比如已在闭关）：do_dual_cultivate 要把失败原因告诉对方，不是静默。"""
    await _dual_ready(db)
    await _set(db, PARTNER, cultivating_until=time.time() + 999)
    i = it(PARTNER)

    await cog.do_dual_cultivate(i, _member(UID), _member(PARTNER), 1.2, False)

    assert i.said("双修失败")


# =============================================================================
# H. cog 的启停
# =============================================================================

async def test_cog加载时启动两个定时任务_卸载时停止(db):
    import asyncio

    class WaitingBot(FakeBot):
        async def wait_until_ready(self):
            await asyncio.sleep(3600)                       # 一直等着，不让任务真的跑

    cog = CultivationCog(bot=WaitingBot())

    await cog.cog_load()
    try:
        assert cog._cultivation_notifier.is_running() and cog._gathering_notifier.is_running()
    finally:
        await cog.cog_unload()
    await asyncio.sleep(0.05)
    assert not cog._cultivation_notifier.is_running() and not cog._gathering_notifier.is_running()


def test_转发的辅助方法():
    cog = CultivationCog(bot=None)
    assert cog._calc_rebirth_bonus({"comprehension": 15, "rebirth_count": 0})["comprehension"] == 3


# =============================================================================
# I. 合并重复实现之后的保护（S9）
# =============================================================================

async def test_灵雨_停止闭关并前往_走闭关cog的停止逻辑(db, cog):
    """utils/views/spirit_rain.py 会直接调用闭关 cog 的停止方法。
    合并停止逻辑时曾差点把它删掉 —— 那个文件当时零覆盖，测试发现不了。"""
    import types
    from utils.views.spirit_rain import ConfirmStopAndTravelView
    await _add_player(db, lifespan=50, current_city="灵虚城", **_mid(4))
    view = ConfirmStopAndTravelView(UID, "铁甲城", "守城", True, False, await cult.get_player(UID))
    i = it()
    i.client = types.SimpleNamespace(cogs={"Cultivation": cog})

    await view.confirm.callback(i)

    p = await _row(db)
    assert i.said("已停止**守城**，传送至 **铁甲城**")
    assert p.current_city == "铁甲城"
    assert p.cultivating_until is None and p.cultivation > 0 and p.lifespan == 50 - 4     # 闭关已按实际年数结算


async def test_灵雨_别人不能替我确认(db, cog):
    from utils.views.spirit_rain import ConfirmStopAndTravelView
    view = ConfirmStopAndTravelView(UID, "铁甲城", "守城", True, False, {})
    i = it("999")
    await view.confirm.callback(i)
    assert i.said("这不是你的操作")


async def test_停止_双修搭档私信_关私信是常态_自己出错要报错(db, cog, caplog):
    """B5 的同一类问题：以前一份入口把任何异常都吞成 debug、另一份直接 pass。现在统一分级。"""
    import logging
    import types
    import discord

    async def _closed(uid):
        raise discord.Forbidden(types.SimpleNamespace(status=403, reason="Forbidden"), "Cannot send")
    await _dual_pair(db)
    cog.bot.fetch_user = _closed
    with caplog.at_level(logging.DEBUG, logger="cogs.cultivation"):
        ok, text = await cog._stop_cultivation_text(UID)
    assert ok and "双修中止" in text
    assert not [r for r in caplog.records if r.levelno >= logging.ERROR]

    caplog.clear()
    await _dual_pair_again(db)

    async def _boom(uid):
        raise RuntimeError("代码里的 bug")
    cog.bot.fetch_user = _boom
    with caplog.at_level(logging.DEBUG, logger="cogs.cultivation"):
        ok, text = await cog._stop_cultivation_text(UID)
    assert ok and "双修中止" in text                          # 本人的结算不受影响
    assert [r for r in caplog.records if r.levelno >= logging.ERROR]


async def _dual_pair_again(db):
    """上一轮已经把双方出关，重新拨回「双修闭关到一半」。"""
    await _set(db, UID, dual_partner_id=PARTNER, **_mid(4))
    await _set(db, PARTNER, dual_partner_id=UID, **_mid(4))


async def test_停止_失败时返回原因而不是文案(db, cog):
    await _add_player(db)
    ok, text = await cog._stop_cultivation_text(UID)
    assert ok is False and "并未在闭关" in text
    ok, text = await cog._stop_cultivation_text("nobody")
    assert ok is False and "角色不存在" in text


async def test_修炼命令_与按钮入口写入同样的闭关状态(db, cog):
    """命令曾自己写一条 UPDATE，与逻辑层并行存在。现在都走 start_cultivation，写入必须一致。"""
    await _add_player(db, "10", active_buffs=json.dumps({"cultivation_speed_bonus": {"value": 50}}))
    await _add_player(db, "11", active_buffs=json.dumps({"cultivation_speed_bonus": {"value": 50}}))
    i, c = it("10"), ctx("11")

    await cog.start_cultivate(i, 4)
    await cog.cultivate.callback(cog, c, 4)

    a, b = await _row(db, "10"), await _row(db, "11")
    assert (a.cultivating_years, a.lifespan, a.cultivation_overflow) == (b.cultivating_years, b.lifespan, b.cultivation_overflow)
    assert abs(a.cultivating_until - b.cultivating_until) < 5
    # 两边给出的预估收益是同一个数
    gain = int(calc_cultivation_gain(4, 5, "单灵根") * 1.5)
    assert i.said(f"+{gain}") and c.said(f"+{gain}")


async def test_修炼命令_落库被逻辑层拒绝时给出原因(db, cog, monkeypatch):
    """前置检查通过之后、写入之前状态变了：命令要把逻辑层的拒绝原因告诉玩家，不能假装成功。"""
    await _add_player(db)

    async def _refuse(uid, years):
        return {"success": False, "message": "正在闭关，还剩 1.0 年"}
    monkeypatch.setattr(cult, "async_start_cultivation", _refuse)
    c = ctx()

    await cog.cultivate.callback(cog, c, 2)

    assert c.said("正在闭关，还剩 1.0 年") and not c.said("开始闭关修炼")


@pytest.mark.parametrize("entry", ["button", "view", "my_character"])
async def test_面板_视图归属于发起人_别人点不动(db, cog, entry):
    """合并两份面板实现之后，视图的归属人由共用方法传入；传错就会变成人人可点或谁都点不了。"""
    await _add_player(db)
    if entry == "button":
        i = it()
        await cog.send_profile(i)
        msg, owner = i.last, i.user
    else:
        c = ctx()
        await getattr(cog, entry).callback(cog, c)
        msg, owner = c.last, c.author
    view = msg.view

    assert view.author == owner
    assert await view.interaction_check(FakeInteraction(user_id=999)) is False
    assert await view.interaction_check(FakeInteraction(user_id=int(UID))) is True


async def test_停止_按钮入口失败时的文案不带提及(db, cog):
    """失败原因原样返回（没有 @ 前缀），成功才带 @；命令入口的失败是固定提示。"""
    await _add_player(db)
    i = it()
    await cog.send_stop(i)
    assert i.last.content == "当前并未在闭关"

    c = ctx()
    await cog.stop_cultivate.callback(cog, c)
    assert c.last.content == f"<@{UID}> 道友当前并未在闭关。"
