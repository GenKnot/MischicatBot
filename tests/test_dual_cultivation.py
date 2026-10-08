"""双修逻辑测试（utils/dual_cultivation_logic.py）及其在线上的兑现路径。

双修的数据流（容易看岔）：
1. start_dual_cultivation：把**双方各自**的总收益预先算好，存进 `cultivation_overflow`，
   同时设 1 游戏年的闭关、互指 `dual_partner_id`、扣 1 年寿元、清掉清白身。
2. 闭关结束：线上由 cogs/cultivation.py::_cultivation_notifier（每分钟的定时任务）兑现——
   有 overflow 就直接发 overflow，没有才按公式算。
3. 提前出关：cultivation_logic.stop_cultivation 按已过比例兑现 overflow（见 test_cultivation_logic.py）。

倍率：双方清白 10~20 倍随机；一方清白 5 倍；都不是 1.2 倍。
"""

import json
import random
import time

import pytest

from cogs.cultivation import CultivationCog
from tests.conftest import make_player
from utils import cultivation_logic as cl
from utils import dual_cultivation_logic as dual
from utils.character import (
    CAVE_BONUS, calc_cultivation_gain, years_to_seconds,
)
from utils.realms import cultivation_needed

A, B = "a", "b"
DUAL_TECH = json.dumps(["双修功法"])


async def _add(db, uid, **fields):
    D = db["db_async"]
    p = make_player(D, uid, stones=0)
    p.name = f"道友{uid}"
    p.is_virgin = False                       # 默认都不是清白身，用到时显式指定
    p.current_city = "灵虚城"
    for k, v in fields.items():
        setattr(p, k, v)
    async with D.AsyncSessionLocal() as s:
        s.add(p)
        await s.commit()


async def _row(db, uid):
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        return await s.get(D.Player, uid)


async def _pair(db, a_fields=None, b_fields=None):
    """一对可以双修的玩家：同城、A 会双修功法、都不是清白身。"""
    await _add(db, A, techniques=DUAL_TECH, **(a_fields or {}))
    await _add(db, B, **(b_fields or {}))


def _gain(player_comprehension=5, root="单灵根", bonus=0.0, mult=1.2):
    return int(calc_cultivation_gain(1, player_comprehension, root) * (1 + bonus) * mult)


# --- has_dual_technique -------------------------------------------------------

@pytest.mark.parametrize("techniques,expected", [
    (json.dumps(["双修功法"]), True),                                   # 字符串形式
    (json.dumps([{"name": "双修功法", "stage": 1}]), True),             # 字典形式
    (json.dumps(["别的功法", {"name": "双修功法"}]), True),             # 混着放
    (json.dumps(["别的功法"]), False),
    (json.dumps([]), False),
    (None, False),
])
async def test_是否习得双修功法(db, techniques, expected):
    await _add(db, A, techniques=techniques)
    assert await dual.has_dual_technique(A) is expected


async def test_不存在的玩家没有双修功法(db):
    assert await dual.has_dual_technique("nobody") is False


# --- check_dual_requirements --------------------------------------------------

async def test_条件齐全_返回双方信息(db):
    await _pair(db, b_fields={"is_virgin": True})

    res = await dual.check_dual_requirements(A, B)

    assert res == {
        "success": True, "inviter_virgin": False, "target_virgin": True,
        "inviter_name": f"道友{A}", "target_name": f"道友{B}",
    }


async def test_只要有一方会双修功法就行(db):
    await _add(db, A)
    await _add(db, B, techniques=DUAL_TECH)
    assert (await dual.check_dual_requirements(A, B))["success"] is True


@pytest.mark.parametrize("who,fields,message", [
    (A, {"is_dead": True}, "发起者角色不存在或已坐化"),
    (B, {"is_dead": True}, "对方角色不存在或已坐化"),
    (A, {"lifespan": 0}, "发起者寿元不足"),
    (B, {"lifespan": 0}, "对方寿元不足"),
    (A, {"cultivating_until": time.time() + 999}, "发起者正在闭关"),
    (B, {"cultivating_until": time.time() + 999}, "对方正在闭关"),
    (B, {"current_city": "别的城"}, "双修需在同一城市"),
])
async def test_条件不满足_给出明确原因(db, who, fields, message):
    await _pair(db, **{"a_fields" if who == A else "b_fields": fields})

    res = await dual.check_dual_requirements(A, B)

    assert res["success"] is False and message in res["message"]


async def test_双方都没有双修功法_拒绝(db):
    await _add(db, A)
    await _add(db, B)
    res = await dual.check_dual_requirements(A, B)
    assert res == {"success": False, "message": "双方均未习得「双修功法」"}


async def test_角色不存在_拒绝(db):
    await _add(db, A, techniques=DUAL_TECH)
    assert (await dual.check_dual_requirements(A, "nobody"))["success"] is False
    assert (await dual.check_dual_requirements("nobody", A))["success"] is False


async def test_冷却中_双方各有提示(db):
    recent = time.time() - years_to_seconds(1)                   # 冷却是 2 游戏年
    await _pair(db, a_fields={"last_dual_cultivate": recent})
    assert "发起者冷却中" in (await dual.check_dual_requirements(A, B))["message"]

    await _pair_reset(db)
    await _pair(db, b_fields={"last_dual_cultivate": recent})
    assert "对方冷却中" in (await dual.check_dual_requirements(A, B))["message"]


async def test_冷却过了就能再双修(db):
    long_ago = time.time() - years_to_seconds(2) - 5
    await _pair(db, a_fields={"last_dual_cultivate": long_ago}, b_fields={"last_dual_cultivate": long_ago})
    assert (await dual.check_dual_requirements(A, B))["success"] is True


async def _pair_reset(db):
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        for uid in (A, B):
            row = await s.get(D.Player, uid)
            if row:
                await s.delete(row)
        await s.commit()


# --- calculate_dual_multiplier ------------------------------------------------

def test_倍率_双方清白在十到二十之间(monkeypatch):
    monkeypatch.setattr(random, "uniform", lambda lo, hi: (lo, hi) and 13.7)
    mult, desc = dual.calculate_dual_multiplier(True, True)
    assert mult == 13.7 and "13.7倍" in desc and "双方皆为清白" in desc


def test_倍率_区间边界(monkeypatch):
    seen = {}
    monkeypatch.setattr(random, "uniform", lambda lo, hi: seen.update(lo=lo, hi=hi) or lo)
    dual.calculate_dual_multiplier(True, True)
    assert (seen["lo"], seen["hi"]) == (10, 20)


@pytest.mark.parametrize("inv,tgt", [(True, False), (False, True)])
def test_倍率_一方清白是五倍(inv, tgt):
    mult, desc = dual.calculate_dual_multiplier(inv, tgt)
    assert mult == 5.0 and "5倍" in desc


def test_倍率_都不清白是一点二倍():
    mult, desc = dual.calculate_dual_multiplier(False, False)
    assert mult == 1.2 and "1.2倍" in desc


# --- start_dual_cultivation：成功 ---------------------------------------------

async def test_双修开始_双方进入一年闭关并互相指向(db):
    await _pair(db, a_fields={"lifespan": 50}, b_fields={"lifespan": 60})
    before = time.time()

    res = await dual.start_dual_cultivation(A, B)

    assert res["success"] is True
    a, b = await _row(db, A), await _row(db, B)
    for p, partner, life in ((a, B, 49), (b, A, 59)):
        assert p.lifespan == life                              # 各扣 1 年
        assert p.cultivating_years == 1
        assert before + years_to_seconds(1) <= p.cultivating_until <= time.time() + years_to_seconds(1)
        assert p.dual_partner_id == partner
        assert p.last_dual_cultivate is not None
        assert p.is_virgin is False
    assert a.cultivating_until == b.cultivating_until          # 同一时刻出关


async def test_双修_收益预存进overflow_尚未入账(db):
    await _pair(db)

    res = await dual.start_dual_cultivation(A, B)

    exp = _gain(mult=1.2)
    assert res["inviter_gain"] == res["target_gain"] == exp
    a, b = await _row(db, A), await _row(db, B)
    assert a.cultivation_overflow == b.cultivation_overflow == exp
    assert a.cultivation == b.cultivation == 0                  # 要等出关才入账
    assert res["inviter_cultivation"] == res["target_cultivation"] == 0
    assert res["inviter_needed"] == cultivation_needed("炼气期1层")


async def test_双修_收益按各自悟性和灵根算(db):
    await _pair(db, a_fields={"comprehension": 9, "spirit_root_type": "双灵根"},
                b_fields={"comprehension": 3, "spirit_root_type": "五灵根"})

    res = await dual.start_dual_cultivation(A, B)

    assert res["inviter_gain"] == _gain(9, "双灵根")
    assert res["target_gain"] == _gain(3, "五灵根")


async def test_双修_洞府加成只算在有洞府的那一方(db):
    await _pair(db, a_fields={"cave": "青云洞府"})

    res = await dual.start_dual_cultivation(A, B)

    assert res["inviter_gain"] == _gain(bonus=CAVE_BONUS)
    assert res["target_gain"] == _gain()
    assert res["inviter_gain"] > res["target_gain"]


@pytest.mark.parametrize("a_virgin,b_virgin,mult", [(True, False, 5.0), (False, True, 5.0), (False, False, 1.2)])
async def test_双修_倍率随清白身而定(db, a_virgin, b_virgin, mult):
    await _pair(db, a_fields={"is_virgin": a_virgin}, b_fields={"is_virgin": b_virgin})

    res = await dual.start_dual_cultivation(A, B)

    assert res["inviter_gain"] == res["target_gain"] == _gain(mult=mult)


async def test_双方清白_倍率取随机值且双方共享同一个倍率(db, monkeypatch):
    await _pair(db, a_fields={"is_virgin": True}, b_fields={"is_virgin": True})
    monkeypatch.setattr(random, "uniform", lambda lo, hi: 15.0)

    res = await dual.start_dual_cultivation(A, B)

    assert res["inviter_gain"] == res["target_gain"] == _gain(mult=15.0)
    assert "15.0倍" in res["flavor"]


async def test_清白身只能用一次(db):
    await _pair(db, a_fields={"is_virgin": True}, b_fields={"is_virgin": True})
    await dual.start_dual_cultivation(A, B)
    assert (await _row(db, A)).is_virgin is False
    assert (await _row(db, B)).is_virgin is False


async def test_文案_双方清白_按性别称呼(db):
    await _pair(db, a_fields={"is_virgin": True, "gender": "男"}, b_fields={"is_virgin": True, "gender": "女"})
    flavor = (await dual.start_dual_cultivation(A, B))["flavor"]
    assert f"**道友{A}** 失去了处男状态" in flavor
    assert f"**道友{B}** 失去了处女状态" in flavor


async def test_文案_只有一方清白_只点那一方的名(db):
    await _pair(db, a_fields={"is_virgin": False}, b_fields={"is_virgin": True, "gender": "男"})
    flavor = (await dual.start_dual_cultivation(A, B))["flavor"]
    assert f"**道友{B}** 失去了处男状态" in flavor
    assert f"道友{A}" not in flavor and "5倍" in flavor


async def test_文案_都不清白_没有失去状态的字样(db):
    await _pair(db)
    flavor = (await dual.start_dual_cultivation(A, B))["flavor"]
    assert "失去了" not in flavor and "1.2倍" in flavor


# --- start_dual_cultivation：拒绝时不留半截状态 --------------------------------

async def _snapshot(db):
    out = {}
    for uid in (A, B):
        p = await _row(db, uid)
        out[uid] = (p.lifespan, p.cultivating_until, p.cultivation_overflow, p.dual_partner_id,
                    p.last_dual_cultivate, p.is_virgin)
    return out


@pytest.mark.parametrize("who,fields,keyword", [
    (A, {"lifespan": 0}, "寿元不足"),
    (B, {"lifespan": 0}, "寿元不足"),
    (A, {"last_dual_cultivate": "recent"}, "冷却未结束"),
    (B, {"last_dual_cultivate": "recent"}, "冷却未结束"),
    (A, {"cultivating_until": "soon"}, "正在闭关"),
    (B, {"cultivating_until": "soon"}, "正在闭关"),
])
async def test_拒绝时双方数据一行不动(db, who, fields, keyword):
    fields = {k: (time.time() - years_to_seconds(1) if v == "recent" else
                  time.time() + 999 if v == "soon" else v) for k, v in fields.items()}
    await _pair(db, a_fields={"is_virgin": True}, b_fields={"is_virgin": True})
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        for k, v in fields.items():
            setattr(await s.get(D.Player, who), k, v)
        await s.commit()
    before = await _snapshot(db)

    res = await dual.start_dual_cultivation(A, B)

    assert res["success"] is False and keyword in res["message"]
    assert await _snapshot(db) == before                        # 清白身、寿元、冷却都没被动


async def test_角色不存在(db):
    await _add(db, A)
    assert await dual.start_dual_cultivation(A, "nobody") == {"success": False, "message": "角色数据异常"}


async def test_冷却刚好过完可以再开(db):
    long_ago = time.time() - years_to_seconds(2) - 5
    await _pair(db, a_fields={"last_dual_cultivate": long_ago}, b_fields={"last_dual_cultivate": long_ago})
    assert (await dual.start_dual_cultivation(A, B))["success"] is True


async def test_双修一次后立刻不能再双修_冷却和闭关都拦着(db):
    await _pair(db)
    await dual.start_dual_cultivation(A, B)
    again = await dual.start_dual_cultivation(A, B)
    assert again["success"] is False


# --- 与提前出关衔接 -----------------------------------------------------------

async def test_刚开始就撤_寿元原样退回_不白得修为(db):
    """双修闭关时已预扣 1 年寿元；还没修满就撤，没修的部分退回，收益按已过比例兑现。"""
    await _pair(db, a_fields={"lifespan": 50, "lifespan_max": 100},
                b_fields={"lifespan": 60, "lifespan_max": 100})
    await dual.start_dual_cultivation(A, B)

    res = await cl.stop_cultivation(A)

    assert res["is_dual"] is True and res["actual_years"] == 0
    assert res["gain"] == 0 and res["partner_gain"] == 0
    a, b = await _row(db, A), await _row(db, B)
    assert (a.lifespan, b.lifespan) == (50, 60)
    assert (a.cultivation, b.cultivation) == (0, 0)
    assert a.cultivation_overflow == b.cultivation_overflow == 0
    assert a.dual_partner_id is None and b.dual_partner_id is None


# --- 闭关结束的线上兑现：_cultivation_notifier ---------------------------------

class _FakeUser:
    def __init__(self):
        self.sent = []

    async def send(self, *args, **kwargs):
        self.sent.append({**kwargs, "args": args})


class _FakeBot:
    def __init__(self):
        self.users = {}

    async def fetch_user(self, uid):
        return self.users.setdefault(uid, _FakeUser())


@pytest.fixture
def notifier():
    bot = _FakeBot()
    cog = CultivationCog(bot=bot)

    async def run():
        await cog._cultivation_notifier.coro(cog)
    return cog, bot, run


async def _finish_now(db, *uids):
    """把闭关结束时间拨到过去，模拟时间到了。"""
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        for uid in uids:
            (await s.get(D.Player, uid)).cultivating_until = time.time() - 1
        await s.commit()


async def test_双修结束_按预存的overflow入账并清掉双修状态(db, notifier):
    cog, bot, run = notifier
    await _pair(db)
    res = await dual.start_dual_cultivation(A, B)
    await _finish_now(db, A, B)

    await run()

    for uid in (A, B):
        p = await _row(db, uid)
        assert p.cultivation == res["inviter_gain"]             # 1.2 倍的收益，不是按公式重算
        assert p.cultivation_overflow == 0
        assert p.cultivating_until is None and p.cultivating_years is None
        assert p.dual_partner_id is None


async def test_双修结束_清白倍率没有在入账时丢掉(db, notifier):
    cog, bot, run = notifier
    await _pair(db, a_fields={"is_virgin": True}, b_fields={"is_virgin": True})
    res = await dual.start_dual_cultivation(A, B)
    await _finish_now(db, A, B)
    plain = int(calc_cultivation_gain(1, 5, "单灵根"))

    await run()

    got = (await _row(db, A)).cultivation
    assert got == res["inviter_gain"] and got >= plain * 10


async def test_单人闭关结束_按公式入账(db, notifier):
    cog, bot, run = notifier
    await _add(db, A, cultivating_years=4, cultivating_until=time.time() - 1, cultivation=10)

    await run()

    p = await _row(db, A)
    assert p.cultivation == 10 + int(calc_cultivation_gain(4, 5, "单灵根"))
    assert p.cultivating_until is None


async def test_单人闭关结束_洞府加成与丹药速度buff都算(db, notifier):
    cog, bot, run = notifier
    buffs = json.dumps({"cultivation_speed_bonus": {"value": 50}})
    await _add(db, A, cultivating_years=4, cultivating_until=time.time() - 1,
               cave="青云洞府", active_buffs=buffs)

    await run()

    exp = int(calc_cultivation_gain(4, 5, "单灵根") * (1 + CAVE_BONUS + 0.5))
    assert (await _row(db, A)).cultivation == exp


async def test_还没到时间的不处理(db, notifier):
    cog, bot, run = notifier
    await _add(db, A, cultivating_years=4, cultivating_until=time.time() + 999)
    await run()
    p = await _row(db, A)
    assert p.cultivation == 0 and p.cultivating_until is not None


async def test_已坐化的不处理(db, notifier):
    cog, bot, run = notifier
    await _add(db, A, cultivating_years=4, cultivating_until=time.time() - 1, is_dead=True)
    await run()
    assert (await _row(db, A)).cultivation == 0


async def test_同一个人不会被重复入账(db, notifier):
    """通知过一次就记进 _notified；清掉闭关状态后下一轮也查不到他了。"""
    cog, bot, run = notifier
    await _add(db, A, cultivating_years=4, cultivating_until=time.time() - 1)
    await run()
    first = (await _row(db, A)).cultivation

    await run()

    assert (await _row(db, A)).cultivation == first


async def test_闭关结束会私信玩家(db, notifier):
    """出关通知。收不到私信的玩家只能靠自己去看，等于闭关结束没人知道。

    注意 cog 里会 `int(uid)` 去 fetch_user，所以这里的玩家 ID 必须是数字（真实的 Discord ID 就是）。"""
    cog, bot, run = notifier
    await _add(db, "123456", cultivating_years=4, cultivating_until=time.time() - 1)

    await run()

    gain = int(calc_cultivation_gain(4, 5, "单灵根"))
    assert 123456 in bot.users, "没有给玩家发出任何私信"
    embed = bot.users[123456].sent[0]["embed"]
    assert "闭关结束" in embed.title and "道友123456" in embed.description
    assert any(f"+{gain}" in f.value for f in embed.fields)


# --- 出关通知的异常分级 --------------------------------------------------------

def _forbidden():
    import types
    import discord
    return discord.Forbidden(types.SimpleNamespace(status=403, reason="Forbidden"), "Cannot send messages to this user")


async def test_对方关了私信_是常态_不当错误报(db, notifier, caplog):
    """收不到私信不影响入账，也不该刷 ERROR 日志。"""
    import logging
    cog, bot, run = notifier

    async def _closed_dm(uid):
        raise _forbidden()
    bot.fetch_user = _closed_dm
    await _add(db, "123456", cultivating_years=4, cultivating_until=time.time() - 1)

    with caplog.at_level(logging.DEBUG, logger="cogs.cultivation"):
        await run()

    assert (await _row(db, "123456")).cultivation > 0                     # 修为照常入账
    assert not [r for r in caplog.records if r.levelno >= logging.ERROR]


async def test_通知逻辑自己出错_要报错而不是吞成debug(db, notifier, caplog):
    """B5 回归：曾经 row['name'] 抛 TypeError，被 `except Exception: log.debug` 吞掉，
    所有人的出关通知悄悄丢了很久。出了我们自己的 bug，必须是 ERROR。"""
    import logging
    cog, bot, run = notifier

    async def _boom(uid):
        raise RuntimeError("代码里的 bug")
    bot.fetch_user = _boom
    await _add(db, "123456", cultivating_years=4, cultivating_until=time.time() - 1)

    with caplog.at_level(logging.DEBUG, logger="cogs.cultivation"):
        await run()

    errors = [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert errors and "123456" in errors[0].getMessage()
    assert (await _row(db, "123456")).cultivation > 0                     # 入账不受通知失败影响


async def test_一个人通知失败不影响后面的人(db, notifier):
    cog, bot, run = notifier
    real = bot.fetch_user

    async def _first_fails(uid):
        if uid == 111111:
            raise RuntimeError("boom")
        return await real(uid)
    bot.fetch_user = _first_fails
    await _add(db, "111111", cultivating_years=4, cultivating_until=time.time() - 1)
    await _add(db, "222222", cultivating_years=4, cultivating_until=time.time() - 1)

    await run()

    assert (await _row(db, "111111")).cultivation > 0
    assert (await _row(db, "222222")).cultivation > 0
    assert 222222 in bot.users and bot.users[222222].sent


# --- B8：邀请上展示的倍率，就是实际结算的倍率 ------------------------------------

async def test_传入展示过的倍率_按它结算(db):
    """B8 回归：邀请面板展示了「13.2倍」，结算却在内部另掷一次，二者不一致。"""
    await _pair(db, a_fields={"is_virgin": True}, b_fields={"is_virgin": True})

    res = await dual.start_dual_cultivation(A, B, multiplier=13.2)

    assert res["success"] is True
    assert res["inviter_gain"] == res["target_gain"] == _gain(mult=13.2)
    assert "13.2倍" in res["flavor"]


async def test_展示过的倍率不会被结算时重掷覆盖(db, monkeypatch):
    await _pair(db, a_fields={"is_virgin": True}, b_fields={"is_virgin": True})
    monkeypatch.setattr(random, "uniform", lambda lo, hi: 19.9)     # 若还重掷，会是 19.9

    res = await dual.start_dual_cultivation(A, B, multiplier=11.0)

    assert res["inviter_gain"] == _gain(mult=11.0)


@pytest.mark.parametrize("a_virgin,b_virgin,shown", [(True, False, 5.0), (False, False, 1.2)])
async def test_固定倍率档_展示值照样通过(db, a_virgin, b_virgin, shown):
    await _pair(db, a_fields={"is_virgin": a_virgin}, b_fields={"is_virgin": b_virgin})
    res = await dual.start_dual_cultivation(A, B, multiplier=shown)
    assert res["success"] and res["inviter_gain"] == _gain(mult=shown)


async def test_不传倍率_仍由结算现掷(db, monkeypatch):
    await _pair(db, a_fields={"is_virgin": True}, b_fields={"is_virgin": True})
    monkeypatch.setattr(random, "uniform", lambda lo, hi: 17.0)
    res = await dual.start_dual_cultivation(A, B)
    assert res["inviter_gain"] == _gain(mult=17.0)


async def test_邀请发出后清白身已被用掉_旧的高倍率作废_且不动任何数据(db):
    """防刷：同一份清白身被两张邀请各兑现一次。

    A 同时邀请了 B 和 C，两张邀请都展示「15倍」；B 先接受（A 不再清白），
    C 再接受时若仍按 15 倍结算，清白身就被兑现了两次。"""
    await _pair(db, a_fields={"is_virgin": True}, b_fields={"is_virgin": True})
    await _add(db, "c", is_virgin=True)
    first = await dual.start_dual_cultivation(A, B, multiplier=15.0)
    assert first["success"]
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:                       # 让 A 重新空闲，只剩"清白身已用"这一差别
        a = await s.get(D.Player, A)
        a.cultivating_until = None
        a.last_dual_cultivate = None
        await s.commit()
    before = await _snapshot_of(db, A, "c")

    second = await dual.start_dual_cultivation(A, "c", multiplier=15.0)

    assert second["success"] is False and "重新发起邀请" in second["message"]
    assert await _snapshot_of(db, A, "c") == before


async def test_展示的倍率超出当前档位区间_拒绝(db):
    await _pair(db, a_fields={"is_virgin": True}, b_fields={"is_virgin": True})
    for bad in (9.9, 20.1, 5.0, 1.2):
        res = await dual.start_dual_cultivation(A, B, multiplier=bad)
        assert res["success"] is False, bad
    assert (await _row(db, A)).is_virgin is True                  # 一次都没结算


async def test_区间边界值可以通过(db):
    await _pair(db, a_fields={"is_virgin": True}, b_fields={"is_virgin": True})
    assert (await dual.start_dual_cultivation(A, B, multiplier=20.0))["success"] is True


async def _snapshot_of(db, *uids):
    out = {}
    for uid in uids:
        p = await _row(db, uid)
        out[uid] = (p.lifespan, p.cultivating_until, p.cultivation_overflow, p.dual_partner_id,
                    p.last_dual_cultivate, p.is_virgin)
    return out


# --- 端到端：发邀请 → 对方点接受 ------------------------------------------------

class _Member:
    """够 `双修` 命令用的 discord.Member 替身。"""
    bot = False

    def __init__(self, uid, name):
        self.id = int(uid)
        self.display_name = name
        self.mention = f"<@{uid}>"

    def __eq__(self, other):
        return getattr(other, "id", None) == self.id

    def __hash__(self):
        return hash(self.id)


async def _invite(db, cog, a_virgin, b_virgin):
    """A 发出双修邀请，返回 (邀请消息, 邀请面板, 目标成员)。玩家 ID 取数字，和真实 Discord ID 一样。"""
    from tests.discord_fakes import FakeContext
    await _add(db, "1001", techniques=DUAL_TECH, is_virgin=a_virgin, gender="男")
    await _add(db, "1002", is_virgin=b_virgin, gender="女")
    ctx = FakeContext(user_id=1001)
    ctx.author = _Member(1001, "甲")
    target = _Member(1002, "乙")
    await cog.dual_cultivate.callback(cog, ctx, target)
    msg = ctx.last
    return msg, msg.view, target


async def test_邀请上展示的倍率_就是对方点接受后实际结算的倍率(db):
    """B8 端到端：双方清白时倍率随机。邀请里写了几倍，结算和出关入账就必须是几倍。"""
    from tests.discord_fakes import FakeInteraction
    cog = CultivationCog(bot=None)
    msg, view, target = await _invite(db, cog, True, True)

    import re
    shown = float(re.search(r"（\*\*(\d+\.\d)倍\*\*）", msg.embed.description).group(1))
    assert 10 <= shown <= 20
    assert view.multiplier == pytest.approx(shown, abs=0.05)

    it = FakeInteraction(user_id=1002)
    it.user = target
    await view.accept.callback(it)

    done = it.last
    assert f"{shown:.1f}倍" in done.embed.description                 # 结算文案里还是同一个数
    expected = int(calc_cultivation_gain(1, 5, "单灵根") * view.multiplier)
    assert (await _row(db, "1001")).cultivation_overflow == expected
    assert (await _row(db, "1002")).cultivation_overflow == expected


async def test_邀请到接受之间状态变了_接受时提示重新发起(db):
    from tests.discord_fakes import FakeInteraction
    cog = CultivationCog(bot=None)
    msg, view, target = await _invite(db, cog, True, True)
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:                           # 此时 A 已在别处用掉了清白身
        (await s.get(D.Player, "1001")).is_virgin = False
        await s.commit()

    it = FakeInteraction(user_id=1002)
    it.user = target
    await view.accept.callback(it)

    assert it.said("重新发起邀请")
    assert (await _row(db, "1002")).cultivating_until is None        # 没有开始双修
    assert (await _row(db, "1002")).is_virgin is True


async def test_一方清白的邀请_展示五倍_结算也是五倍(db):
    from tests.discord_fakes import FakeInteraction
    cog = CultivationCog(bot=None)
    msg, view, target = await _invite(db, cog, True, False)
    assert "5倍" in msg.embed.description

    it = FakeInteraction(user_id=1002)
    it.user = target
    await view.accept.callback(it)

    assert (await _row(db, "1001")).cultivation_overflow == int(calc_cultivation_gain(1, 5, "单灵根") * 5.0)
