"""江湖传闻（utils/rumors.py、cogs/rumors.py、data/rumors.json 与各处埋点）。

· 配置与模板校验（会在 CI 里拦住 AI 批量生成的模板格式问题）；
· 记录：渲染 / 分值 / 机器人档位权重 / 真人开关 / 十分钟去重 / 出错只记 warning 绝不抛；
· 挑选广播：分值门槛、时间窗口、真人加权、真人保底名额、同一人每天最多 1 条负面、每人每天上限、认领；
· 埋点：突破、坐化、任务陨落、炼丹、锻造、探险奇遇、轮回、真人互相击杀、劫杀机器人、机器人处置真人；
· 广播循环与命令；静态棘轮：配置里的每个种类都有地方在记，代码里记的每个种类都在配置里。
"""

import json
import logging
import random
import re
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from cogs import rumors as rumors_cog
from cogs.rumors import RumorsCog
from tests.conftest import make_player
from tests.discord_fakes import FakeContext
from utils import rumors as rm

ROOT = Path(__file__).resolve().parent.parent
H, B = "1001", "bot_00001"
CFG = rm.load_config()


async def player(db, uid=H, name=None, city="灵虚城", **kw):
    D = db["db_async"]
    p = make_player(D, uid)
    p.name, p.current_city = name or f"道友{uid}", city
    p.is_bot = uid.startswith("bot_")
    for k, v in kw.items():
        setattr(p, k, v)
    async with D.AsyncSessionLocal() as s:
        s.add(p)
        await s.commit()
    if p.is_bot:
        async with D.AsyncSessionLocal() as s:
            s.add(D.BotPersonality(bot_id=uid, archetype="豪爽", tier=kw.pop("tier", "正常") if False else "正常"))
            await s.commit()


async def all_rumors(db):
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        return list((await s.execute(select(D.Rumor).order_by(D.Rumor.id))).scalars())


async def add(db, kind="breakthrough_major", subject="x", human=False, score=40, negative=False, created=None,
              broadcast=0.0, text=None):
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        r = D.Rumor(created_at=created or time.time(), kind=kind, score=score, subject_id=subject, subject_name=subject,
                    is_human=human, negative=negative, content=text or f"{kind}-{subject}-{score}", city="", broadcast_at=broadcast)
        s.add(r)
        await s.commit()
        return r.id


# ---- 配置 / 模板 ------------------------------------------------------------

def test_配置合法():
    assert rm.validate_config(CFG) == []


def test_每个种类都有足够的模板_并且都带道号():
    for name, k in CFG["kinds"].items():
        assert len(k["templates"]) >= rm.MIN_TEMPLATES, name
        assert all("{name}" in t for t in k["templates"]), name


@pytest.mark.parametrize("edit,words", [
    (lambda c: c["kinds"].clear(), "kinds"),
    (lambda c: c["kinds"]["rebirth"].update(score=-1), "score"),
    (lambda c: c["kinds"]["rebirth"].update(negative="是"), "negative"),
    (lambda c: c["kinds"]["rebirth"].update(vars=["city"]), "vars"),
    (lambda c: c["kinds"]["rebirth"].update(vars=["name", "怪"]), "vars"),
    (lambda c: c["kinds"]["rebirth"].update(templates=["{name}重入轮回"]), "至少"),
    (lambda c: c["kinds"]["rebirth"]["templates"].append("  "), "空模板"),
    (lambda c: c["kinds"]["rebirth"]["templates"].append("{name}" + "字" * 100), "超过"),
    (lambda c: c["kinds"]["rebirth"]["templates"].append("重入轮回"), "必须出现"),
    (lambda c: c["kinds"]["rebirth"]["templates"].append("{name}遇见{city}"), "没声明"),
    (lambda c: c["kinds"]["rebirth"]["templates"].append("{name"), "花括号"),
    (lambda c: c["broadcast"].update(interval_hours=0), "broadcast"),
    (lambda c: c["broadcast"].update(human_weight=0.5), "human_weight"),
    (lambda c: c["broadcast"].update(human_quota=99), "human_quota"),
    (lambda c: c["broadcast"].update(max_per_subject_per_day=0), "max_per_subject"),
    (lambda c: c["broadcast"]["bot_tier_weight"].pop("天骄"), "bot_tier_weight"),
    (lambda c: c["thresholds"].update(forge_great_qualities=[]), "thresholds"),
    (lambda c: c.update(retention_days=0), "retention_days"),
])
def test_校验器抓得住错误(edit, words):
    cfg = rm.load_config()
    edit(cfg)
    errors = rm.validate_config(cfg)
    assert errors and any(words in e for e in errors), errors


def test_配置是拷贝():
    a = rm.load_config()
    a["kinds"].clear()
    assert rm.load_config()["kinds"]


def test_用户定的广播参数():
    b = CFG["broadcast"]
    assert (b["interval_hours"], b["slots_per_day"], b["human_quota"], b["negative_per_human_per_day"]) == (2, 12, 3, 1)
    assert CFG["retention_days"] == 7


def test_静态棘轮_配置里的种类和代码里记的种类一一对应():
    configured = set(CFG["kinds"])
    used = set()
    for sub in ("utils", "cogs"):
        for f in (ROOT / sub).rglob("*.py"):
            if f.name == "rumors.py" and f.parent.name in ("utils", "cogs"):
                src = f.read_text()
                if f.parent.name == "cogs":
                    continue
            else:
                src = f.read_text()
            used |= set(re.findall(r'record_(?:player_)?rumor(?:_soon)?\(\s*"(\w+)"', src))
    # on_breakthrough 里按条件选的种类
    used |= {"breakthrough_major", "breakthrough_minor", "breakthrough_fail", "death_breakthrough"}
    assert used <= configured, f"代码里记了配置里没有的种类：{used - configured}"
    assert configured <= used, f"配置里的种类没有任何地方在记：{configured - used}"


# ---- 记录 -------------------------------------------------------------------

async def test_记录_渲染入库(db):
    rid = await rm.record_rumor("breakthrough_major", H, "王铁柱", city="落云城", realm="筑基期1层", rng=random.Random(1))
    r = (await all_rumors(db))[0]
    assert rid == r.id and "王铁柱" in r.content and "落云城" in r.content and "筑基期1层" in r.content
    assert (r.kind, r.score, r.is_human, r.negative, r.city, r.broadcast_at) == ("breakthrough_major", 40, True, False, "落云城", 0)


async def test_记录_负面种类标记(db):
    await rm.record_rumor("alchemy_fail", H, "甲", city="x")
    r = (await all_rumors(db))[0]
    assert r.negative is True


async def test_记录_机器人按档位权重(db):
    D = db["db_async"]
    for i, tier in enumerate(("炮灰", "正常", "天骄"), 1):
        uid = f"bot_{i:05d}"
        await player(db, uid)
        async with D.AsyncSessionLocal() as s:
            (await s.get(D.BotPersonality, uid)).tier = tier
            await s.commit()
        await rm.record_rumor("death_old", uid, f"机器人{i}", city="c", realm="r")
    scores = [r.score for r in await all_rumors(db)]
    assert scores == [15, 30, 45] and all(not r.is_human for r in await all_rumors(db))


async def test_记录_真人关了开关就不记(db):
    await player(db, H)
    assert await rm.toggle_optout(H) is True
    assert await rm.record_rumor("rebirth", H, "甲") is None
    assert await all_rumors(db) == []
    assert await rm.toggle_optout(H) is False
    assert await rm.record_rumor("rebirth", H, "甲") is not None


async def test_记录_对方关了开关也不记(db):
    """真人打劫机器人不受影响；机器人劫了关了开关的真人，这条事迹的另一方是真人，也不能记。"""
    await rm.toggle_optout("2002")
    assert await rm.record_rumor("kill_human", "2002", "乙", target_id=H, target="甲", city="x") is None
    assert await rm.record_rumor("kill_human", H, "甲", target_id="2002", target="乙", city="x") is None
    assert await rm.record_rumor("kill_human", H, "甲", target_id="bot_00001", target="机器人", city="x") is not None


async def test_记录_十分钟内同一句不记两遍(db):
    a = await rm.record_rumor("rebirth", H, "甲", rng=random.Random(1))
    b = await rm.record_rumor("rebirth", H, "甲", rng=random.Random(1))
    c = await rm.record_rumor("rebirth", "1002", "乙", rng=random.Random(1))
    assert a is not None and b is None and c is not None


async def test_记录_缺变量_未知种类_只记警告不抛(db, caplog):
    with caplog.at_level(logging.WARNING):
        assert await rm.record_rumor("breakthrough_major", H, "甲", city="x") is None       # 缺 realm
        assert await rm.record_rumor("不存在的种类", H, "甲") is None
    assert caplog.text.count("记录传闻失败") == 2 and await all_rumors(db) == []


async def test_记录_库出错也不抛(db, monkeypatch, caplog):
    class Boom:
        def __call__(self):
            raise RuntimeError("库挂了")
    monkeypatch.setattr(rm, "AsyncSessionLocal", Boom())
    with caplog.at_level(logging.WARNING):
        assert await rm.record_rumor("rebirth", H, "甲") is None
        assert await rm.record_player_rumor("rebirth", H) is None


async def test_按玩家记_自己查名字和所在地(db, monkeypatch):
    seen = []
    monkeypatch.setattr(rm, "render", lambda kind, values, rng=random: seen.append(values) or f"{values['name']}的事")
    await player(db, H, name="李逍遥", city="落云城", realm="筑基期2层")
    await rm.record_player_rumor("alchemy_fail", H)
    r = (await all_rumors(db))[0]
    assert seen == [{"name": "李逍遥", "city": "落云城", "realm": "筑基期2层"}] and r.city == "落云城"
    assert await rm.record_player_rumor("alchemy_fail", "不存在") is None


async def test_按玩家记_调用方给的变量优先(db, monkeypatch):
    seen = []
    monkeypatch.setattr(rm, "render", lambda kind, values, rng=random: seen.append(values) or f"{values['name']}的事")
    await player(db, H, name="李逍遥", city="落云城", realm="结丹期初期")
    await rm.record_player_rumor("death_old", H, realm="元婴期初期")
    assert seen[0]["realm"] == "元婴期初期" and seen[0]["city"] == "落云城"


async def test_soon_版本发出去就不管(db):
    import asyncio
    rm.record_rumor_soon("rebirth", H, "甲")
    for _ in range(20):
        await asyncio.sleep(0.01)
        if await all_rumors(db):
            break
    assert len(await all_rumors(db)) == 1


def test_soon_没有事件循环不抛():
    rm.record_rumor_soon("rebirth", H, "甲")


# ---- 场景封装 ---------------------------------------------------------------

@pytest.mark.parametrize("result,kind", [
    ({"breakthrough": True, "old_realm": "炼气期3层", "new_realm": "炼气期4层"}, "breakthrough_minor"),
    ({"breakthrough": True, "old_realm": "炼气期10层", "new_realm": "筑基期1层"}, "breakthrough_major"),
    ({"breakthrough": False, "is_dead": False}, "breakthrough_fail"),
    ({"breakthrough": False, "is_dead": True}, "death_breakthrough"),
])
async def test_突破封装(db, result, kind):
    await rm.on_breakthrough({"discord_id": H, "name": "甲", "current_city": "c", "realm": "炼气期3层"}, result)
    assert [r.kind for r in await all_rumors(db)] == [kind]


async def test_突破封装_没有突破字段不记(db):
    await rm.on_breakthrough({"discord_id": H, "name": "甲", "realm": "r"}, {"success": False, "message": "x"})
    assert await all_rumors(db) == []


async def test_炼丹封装(db, monkeypatch):
    counter = iter(range(100))
    monkeypatch.setattr(rm, "render", lambda kind, values, rng=random: f"{values['name']}-{kind}-{next(counter)}")   # 避免撞十分钟去重
    await player(db, H)
    await rm.on_alchemy(H, {"success": False, "consequence": "普通失败"})
    await rm.on_alchemy(H, {"success": False, "consequence": "炉毁"})
    await rm.on_alchemy(H, {"success": False, "consequence": "丹毒反噬"})
    await rm.on_alchemy(H, {"success": True, "pill": "聚气丸", "quality_idx": 8, "quality_name": "八纹", "leveled_up": False})
    await rm.on_alchemy(H, {"success": True, "pill": "聚气丸", "quality_idx": 9, "quality_name": "九纹", "leveled_up": True, "alchemy_level": 3})
    await rm.on_alchemy(H, {"ok": False, "reason": "x"})
    assert [r.kind for r in await all_rumors(db)] == ["alchemy_fail", "alchemy_fail", "alchemy_great", "alchemy_levelup"]


async def test_锻造封装(db):
    await player(db, H)
    await rm.on_forge(H, {"success": False, "consequence": "普通失败"})
    await rm.on_forge(H, {"success": True, "equipment": {"name": "凡品长剑", "quality": "稀有"}})
    await rm.on_forge(H, {"success": True, "equipment": {"name": "传说·青霜剑", "quality": "传说"}})
    await rm.on_forge(H, {"ok": False, "reason": "x"})
    assert [r.kind for r in await all_rumors(db)] == ["forge_fail", "forge_great"]
    assert "传说·青霜剑" in (await all_rumors(db))[1].content


# ---- 挑选广播 ---------------------------------------------------------------

async def test_挑选_分值门槛_只进茶馆(db):
    await add(db, subject="a", score=9)                                  # 机器人 9 < 10
    assert await rm.pick_broadcast() is None
    await add(db, subject="h", human=True, score=5)                      # 真人 5 × 2 = 10，刚到线
    assert (await rm.pick_broadcast()).subject_id == "h"


async def test_挑选_时间窗口(db):
    await add(db, subject="old", score=80, created=time.time() - 7 * 3600)
    assert await rm.pick_broadcast() is None
    await add(db, subject="new", score=20)
    assert (await rm.pick_broadcast()).subject_id == "new"


async def test_挑选_播过的不再播(db):
    await add(db, subject="a", score=80, broadcast=time.time() - 60)
    assert await rm.pick_broadcast() is None


async def test_挑选_真人加权(db):
    await add(db, subject="bot", score=40)
    await add(db, subject="human", human=True, score=25)                 # 25 × 2 = 50 > 40
    assert (await rm.pick_broadcast()).subject_id == "human"
    await add(db, subject="bot2", score=60)
    assert (await rm.pick_broadcast()).subject_id == "bot2"


async def test_挑选_同分取最新(db):
    await add(db, subject="a", score=40, created=time.time() - 100)
    await add(db, subject="b", score=40, created=time.time() - 10)
    assert (await rm.pick_broadcast()).subject_id == "b"


async def _fill_today(db, bots, humans):
    now = time.time()
    for i in range(bots):
        await add(db, subject=f"done_b{i}", score=50, broadcast=rm.day_start(now) + 10 + i)
    for i in range(humans):
        await add(db, subject=f"done_h{i}", human=True, score=50, broadcast=rm.day_start(now) + 100 + i)


async def test_保底_名额快用完了就必须播真人(db):
    now = time.time()
    if now - rm.day_start(now) < 1000:
        pytest.skip("刚过零点，造数据的时间戳会落到昨天")
    await _fill_today(db, bots=9, humans=0)                              # 今天播了 9 条，剩 3 个名额，真人一条没有
    await add(db, subject="bigbot", score=90)
    await add(db, subject="human", human=True, score=6)                  # 6 × 2 = 12，远低于 bigbot
    assert (await rm.pick_broadcast()).subject_id == "human"


async def test_保底_名额还够就按分值(db):
    now = time.time()
    if now - rm.day_start(now) < 1000:
        pytest.skip("刚过零点，造数据的时间戳会落到昨天")
    await _fill_today(db, bots=8, humans=0)                              # 剩 4 个名额 > 还缺的 3 个
    await add(db, subject="bigbot", score=90)
    await add(db, subject="human", human=True, score=6)
    assert (await rm.pick_broadcast()).subject_id == "bigbot"


async def test_保底_已经播够真人就不再强制(db):
    now = time.time()
    if now - rm.day_start(now) < 1000:
        pytest.skip("刚过零点，造数据的时间戳会落到昨天")
    await _fill_today(db, bots=6, humans=3)                              # 真人 3 条已满足
    await add(db, subject="bigbot", score=90)
    await add(db, subject="human", human=True, score=6)
    assert (await rm.pick_broadcast()).subject_id == "bigbot"


async def test_保底_没有真人传闻时不卡住(db):
    now = time.time()
    if now - rm.day_start(now) < 1000:
        pytest.skip("刚过零点，造数据的时间戳会落到昨天")
    await _fill_today(db, bots=9, humans=0)
    await add(db, subject="bigbot", score=90)
    assert (await rm.pick_broadcast()).subject_id == "bigbot"


async def test_同一个真人每天最多一条负面广播(db):
    now = time.time()
    if now - rm.day_start(now) < 1000:
        pytest.skip("刚过零点，造数据的时间戳会落到昨天")
    await add(db, kind="alchemy_fail", subject="倒霉蛋", human=True, negative=True, score=14, broadcast=rm.day_start(now) + 50)
    await add(db, kind="death_old", subject="倒霉蛋", human=True, negative=True, score=90)
    await add(db, subject="别人", score=20)
    assert (await rm.pick_broadcast()).subject_id == "别人", "倒霉蛋今天已经被播过一条负面了"
    await add(db, kind="breakthrough_major", subject="倒霉蛋", human=True, negative=False, score=40)
    assert (await rm.pick_broadcast()).kind == "breakthrough_major", "好事不受限"


async def test_机器人的负面不受每日一条限制(db):
    now = time.time()
    if now - rm.day_start(now) < 1000:
        pytest.skip("刚过零点，造数据的时间戳会落到昨天")
    await add(db, kind="death_old", subject="bot_9", negative=True, score=30, broadcast=rm.day_start(now) + 50)
    await add(db, kind="death_old", subject="bot_9", negative=True, score=30)
    assert await rm.pick_broadcast() is not None


async def test_每人每天最多两条(db):
    now = time.time()
    if now - rm.day_start(now) < 1000:
        pytest.skip("刚过零点，造数据的时间戳会落到昨天")
    for i in range(2):
        await add(db, subject="话题人物", score=50, broadcast=rm.day_start(now) + 10 + i)
    await add(db, subject="话题人物", score=90)
    await add(db, subject="路人", score=20)
    assert (await rm.pick_broadcast()).subject_id == "路人"


async def test_认领_只有一个循环能播这一条(db):
    rid = await add(db, subject="a", score=50)
    assert await rm.claim_broadcast(rid) is True and await rm.claim_broadcast(rid) is False


async def test_到点才播(db):
    assert await rm.broadcast_due() is True                              # 从没播过
    await add(db, subject="a", broadcast=time.time() - 3600)
    assert await rm.broadcast_due() is False                             # 1 小时前播过，间隔 2 小时
    assert await rm.broadcast_due(time.time() + 3600 + 1) is True


async def test_清理过期传闻(db):
    await add(db, subject="old", created=time.time() - 8 * 86400)
    await add(db, subject="new")
    assert await rm.prune() == 1
    assert [r.subject_id for r in await all_rumors(db)] == ["new"]


async def test_茶馆列表_真人和机器人分开_最新在前(db):
    now = time.time()
    for i in range(10):
        await add(db, subject=f"h{i}", human=True, created=now - 100 + i)
        await add(db, subject=f"b{i}", created=now - 100 + i)
    await add(db, subject="过期", human=True, created=now - 9 * 86400)
    data = await rm.recent()
    assert [r.subject_id for r in data["human"]] == [f"h{i}" for i in range(9, 1, -1)]
    assert len(data["bot"]) == 8 and "过期" not in {r.subject_id for r in data["human"]}


# ---- 埋点（真实逻辑里会留下传闻）-------------------------------------------

@pytest.fixture
def roll(monkeypatch):
    def set_(value, outcome="light"):
        monkeypatch.setattr(random, "random", lambda: value)
        monkeypatch.setattr(random, "choices", lambda pop, weights=None, k=1: [outcome])
    return set_


async def test_埋点_突破成功(db, roll):
    from utils.breakthrough_logic import do_single_breakthrough
    await player(db, H, name="王铁柱", realm="炼气期3层", cultivation=150, lifespan=80, lifespan_max=100)
    roll(0.0)
    res = await do_single_breakthrough(H, (await _dict(db, H)))
    assert res["breakthrough"] and [r.kind for r in await all_rumors(db)] == ["breakthrough_minor"]


async def test_埋点_大境突破用的是大关逻辑(db, roll):
    from utils.breakthrough_logic import handle_zhuji_breakthrough
    await player(db, H, name="王铁柱", realm="炼气期10层", cultivation=200, lifespan=80, lifespan_max=100)
    await db["inventory"].add_item(H, "筑基丹", 1)
    roll(0.0)
    res = await handle_zhuji_breakthrough(H, True)
    assert res["breakthrough"] and [r.kind for r in await all_rumors(db)] == ["breakthrough_major"]


async def test_埋点_突破失败与致死(db, roll):
    from utils.breakthrough_logic import do_single_breakthrough
    await player(db, H, name="王铁柱", realm="炼气期3层", cultivation=150, lifespan=60, lifespan_max=100)
    roll(0.999, "light")
    await do_single_breakthrough(H, (await _dict(db, H)))
    await player(db, "1002", name="李四", realm="炼气期3层", cultivation=150, lifespan=1, lifespan_max=100)
    roll(0.999, "deviate")
    await do_single_breakthrough("1002", (await _dict(db, "1002")))
    assert [r.kind for r in await all_rumors(db)] == ["breakthrough_fail", "death_breakthrough"]


async def test_埋点_机器人的突破也进传闻(db, roll):
    from utils.breakthrough_logic import do_single_breakthrough
    await player(db, B, name="散修甲", realm="炼气期3层", cultivation=150, lifespan=80, lifespan_max=100)
    roll(0.0)
    await do_single_breakthrough(B, (await _dict(db, B)))
    r = (await all_rumors(db))[0]
    assert r.is_human is False and "散修甲" in r.content


async def _dict(db, uid):
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        p = await s.get(D.Player, uid)
        return {c.key: getattr(p, c.key) for c in p.__table__.columns}


async def test_埋点_真人互相击杀(db):
    from tests.discord_fakes import FakeInteraction
    from utils.views.combat import VictoryActionView
    await player(db, H, name="胜者")
    await player(db, "1002", name="败者")
    v = VictoryActionView(FakeInteraction(H).user, await _dict(db, H), await _dict(db, "1002"))
    i = FakeInteraction(H)
    i.client = SimpleNamespace(cogs={}, fetch_user=None)
    await next(c for c in v.children if c.label == "☠️ 击杀").callback(i)
    r = (await all_rumors(db))[0]
    assert r.kind == "kill_human" and r.subject_id == "1002" and "败者" in r.content and "胜者" in r.content and r.negative


async def test_埋点_劫杀机器人(db):
    from utils import bot_combat as bc
    await player(db, H, name="胜者", city="万妖岭")
    await player(db, B, name="散修甲", city="万妖岭", spirit_stones=1000)
    await player(db, "bot_00002", name="散修乙", city="万妖岭", spirit_stones=1000)
    await player(db, "bot_00003", name="散修丙", city="万妖岭", spirit_stones=1000)
    await bc.rob_bot(H, B)
    await bc.cripple_bot(H, "bot_00002")
    await bc.kill_bot(H, "bot_00003")
    rs = await all_rumors(db)
    assert [r.kind for r in rs] == ["rob_bot", "cripple_bot", "kill_bot"]
    assert all(r.subject_id == H and r.is_human for r in rs) and "散修甲" in rs[0].content and "散修丙" in rs[2].content


async def test_埋点_机器人处置真人(db, monkeypatch):
    from utils import bot_combat as bc
    from utils import bot_economy as be
    cfg = be.load_config()
    cfg["combat"]["can_kill_humans"] = True
    cfg["combat"]["reaction"]["阴鸷"] = {"kill": 100}
    monkeypatch.setattr(be, "load_config", lambda: json.loads(json.dumps(cfg)))
    await player(db, H, name="败者", city="万妖岭", realm="筑基期5层", spirit_stones=1000)
    await player(db, B, name="散修甲", city="万妖岭")
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        (await s.get(D.BotPersonality, B)).archetype = "阴鸷"
        await s.commit()
    await bc.handle_captive(B, H, random.Random(0))
    r = (await all_rumors(db))[0]
    assert r.kind == "bot_kills_human" and r.subject_id == H and r.negative and "散修甲" in r.content


async def test_埋点_机器人劫真人(db, monkeypatch):
    from utils import bot_combat as bc
    from utils import bot_economy as be
    cfg = be.load_config()
    cfg["combat"]["reaction"]["贪财"] = {"rob": 100}
    monkeypatch.setattr(be, "load_config", lambda: json.loads(json.dumps(cfg)))
    await player(db, H, name="败者", city="万妖岭", spirit_stones=1000)
    await player(db, B, name="散修甲", city="万妖岭")
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        (await s.get(D.BotPersonality, B)).archetype = "贪财"
        await s.commit()
    await bc.handle_captive(B, H, random.Random(0))
    assert [r.kind for r in await all_rumors(db)] == ["bot_robs_human"]


async def test_埋点_放走不记(db):
    from utils import bot_combat as bc
    await player(db, H, city="万妖岭")
    await player(db, B, city="万妖岭")
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        (await s.get(D.BotPersonality, B)).archetype = "憨直"
        await s.commit()
    await bc.handle_captive(B, H, random.Random(0))
    assert await all_rumors(db) == []


async def test_埋点_机器人寿尽(db):
    from utils import bot_economy as be
    from utils import bot_settle as bsl
    await player(db, B, name="散修甲", lifespan=1, realm="炼气期3层")
    cfg = be.load_config()
    cfg["speed"]["正常"] = 1.0
    orig = be.load_config
    be.load_config = lambda: json.loads(json.dumps(cfg))
    try:
        await bsl.run_settlement(rng=random.Random(0))
    finally:
        be.load_config = orig
    r = [x for x in await all_rumors(db) if x.kind == "death_old"]
    assert len(r) == 1 and "散修甲" in r[0].content and r[0].subject_id == B and not r[0].is_human


async def test_埋点_坐化后重入轮回(db):
    from utils.character_create_logic import commit_character
    await player(db, H, is_dead=True)
    res = await commit_character(H, "新道号", "男", {})
    assert res is not None
    r = (await all_rumors(db))[0]
    assert r.kind == "rebirth" and "新道号" in r.content
    await commit_character("1002", "全新玩家", "男", {})
    assert len(await all_rumors(db)) == 1, "第一次入道不是轮回"


async def test_埋点_个人查看发现寿尽只记一次(db):
    """死亡的传闻只在『真的坐化的那一下』记，重复查看不再记。"""
    from cogs.cultivation import CultivationCog
    await player(db, H, name="甲", lifespan=0, realm="炼气期3层")
    cog = CultivationCog(bot=SimpleNamespace())
    for _ in range(2):
        await cog.send_profile(SimpleNamespace(user=SimpleNamespace(id=int(H)),
                                               followup=SimpleNamespace(send=_async_noop)))
    assert [r.kind for r in await all_rumors(db)] == ["death_old"]


async def _async_noop(*a, **k):
    return None


async def test_埋点_任务陨落(db, monkeypatch):
    """真走一遍任务结算：战败、没逃掉、掷中死亡 —— 记一条 death_quest；只是逃脱不记。"""
    from utils import quest_logic
    from utils.quest_logic import resolve_quest, start_quest
    strong = {"id": "t", "title": "测试", "type": "combat", "enemy": {"name": "大能", "power": 10**9}, "rewards": {}}
    D = db["db_async"]
    for uid in ("1001", "1002"):
        await player(db, uid, name=f"道友{uid}", lifespan=80)
        await start_quest(uid, strong, "普通")
        async with D.AsyncSessionLocal() as s:
            (await s.get(D.Player, uid)).quest_due = time.time() - 1
            await s.commit()
    monkeypatch.setattr(quest_logic.random, "uniform", lambda a, b: 1.0)

    async def no_escape(p):
        return False, 10
    monkeypatch.setattr("utils.combat.roll_escape", no_escape)
    monkeypatch.setattr(quest_logic.random, "random", lambda: 0.0)               # 掷中死亡
    res = await resolve_quest("1001")
    assert res["fatal"] and (await _dict(db, "1001"))["is_dead"]
    async def escape(p):
        return True, 90
    monkeypatch.setattr("utils.combat.roll_escape", escape)
    await resolve_quest("1002")
    rs = await all_rumors(db)
    assert [r.kind for r in rs] == ["death_quest"] and rs[0].subject_id == "1001"


async def test_埋点_逃脱时寿元耗尽也算陨落(db, monkeypatch):
    from utils import quest_logic
    from utils.quest_logic import resolve_quest, start_quest
    strong = {"id": "t", "title": "测试", "type": "combat", "enemy": {"name": "大能", "power": 10**9}, "rewards": {}}
    D = db["db_async"]
    await player(db, H, name="甲", lifespan=1)
    await start_quest(H, strong, "普通")
    async with D.AsyncSessionLocal() as s:
        (await s.get(D.Player, H)).quest_due = time.time() - 1
        await s.commit()
    monkeypatch.setattr(quest_logic.random, "uniform", lambda a, b: 1.0)

    async def escape(p):
        return True, 90
    monkeypatch.setattr("utils.combat.roll_escape", escape)
    res = await resolve_quest(H)
    assert res["escaped"] and (await _dict(db, H))["is_dead"]
    assert [r.kind for r in await all_rumors(db)] == ["death_quest"]


async def test_埋点_锻造(db, monkeypatch):
    from utils import forging as fm
    D = db["db_async"]
    await player(db, H, name="铁匠", lifespan=80, spirit_stones=100_000)
    async with D.AsyncSessionLocal() as s:
        s.add(D.Inventory(discord_id=H, item_id="铜矿石", quantity=99))
        await s.commit()
    inventory = await db["inventory"].get_inventory(H)
    monkeypatch.setattr(fm.random, "randint", lambda a, b: 100)                   # 必败
    monkeypatch.setattr(fm, "roll_forge_failure", lambda: ("普通失败", 0))
    await fm.attempt_forge(H, "饰品", "铜矿石", "普通", None, None, inventory, 10, 1)
    monkeypatch.setattr(fm.random, "randint", lambda a, b: 1)                     # 必成，且是传说
    real = fm.generate_equipment
    monkeypatch.setattr(fm, "generate_equipment", lambda **kw: {**real(**{**kw, "quality": "传说"}), "quality": "传说"})
    await fm.attempt_forge(H, "饰品", "铜矿石", "普通", None, None, await db["inventory"].get_inventory(H), 10, 1)
    assert [r.kind for r in await all_rumors(db)] == ["forge_fail", "forge_great"]


async def test_埋点_探险奇遇(db, monkeypatch):
    from cogs import explore
    from utils.events import RARE_EVENTS
    assert explore.rumors is rm and RARE_EVENTS
    await player(db, H, name="甲")
    await rm.record_player_rumor("rare_event", H, title=RARE_EVENTS[0]["title"])
    assert RARE_EVENTS[0]["title"] in (await all_rumors(db))[0].content


# ---- 广播与命令 -------------------------------------------------------------

class FakeChannel:
    def __init__(self, active=True, fail=False):
        self.sent, self.active, self.fail = [], active, fail

    async def history(self, limit=50, after=None):
        if self.fail:
            raise RuntimeError("没有权限")
        yield SimpleNamespace(author=SimpleNamespace(bot=True))
        if self.active:
            yield SimpleNamespace(author=SimpleNamespace(bot=False))

    async def send(self, **kw):
        self.sent.append(kw)


def make_cog(channel=None):
    bot = SimpleNamespace(get_channel=lambda cid: channel, wait_until_ready=_async_noop)
    return RumorsCog(bot)


@pytest.fixture
def channel_env(monkeypatch):
    monkeypatch.setenv(rumors_cog.RUMOR_CHANNEL_ENV, "42")
    monkeypatch.delenv(rumors_cog.PUBLIC_EVENT_CHANNEL_ENV, raising=False)


async def test_广播_播出最精彩的一条并认领(db, channel_env):
    ch = FakeChannel()
    await add(db, subject="a", score=30, text="小事一桩-a")
    await add(db, subject="b", score=70, text="惊天大事-b")
    assert await make_cog(ch).broadcast_once() is True
    assert len(ch.sent) == 1 and "惊天大事-b" in ch.sent[0]["embed"].description and ch.sent[0]["embed"].title == "📜 江湖传闻"
    assert await make_cog(ch).broadcast_once() is False, "刚播过，没到下一个游戏年"
    assert len(ch.sent) == 1


async def test_广播_真人事迹带星标(db, channel_env):
    ch = FakeChannel()
    await add(db, subject="h", human=True, score=40, text="真人事迹")
    await make_cog(ch).broadcast_once()
    assert "⭐" in ch.sent[0]["embed"].description


async def test_广播_没配频道就不播(db, monkeypatch):
    monkeypatch.delenv(rumors_cog.RUMOR_CHANNEL_ENV, raising=False)
    monkeypatch.delenv(rumors_cog.PUBLIC_EVENT_CHANNEL_ENV, raising=False)
    await add(db, subject="a", score=70)
    assert await make_cog(FakeChannel()).broadcast_once() is False


async def test_广播_回退到公共事件频道(db, monkeypatch):
    monkeypatch.delenv(rumors_cog.RUMOR_CHANNEL_ENV, raising=False)
    monkeypatch.setenv(rumors_cog.PUBLIC_EVENT_CHANNEL_ENV, "7")
    ch = FakeChannel()
    await add(db, subject="a", score=70)
    assert await make_cog(ch).broadcast_once() is True and len(ch.sent) == 1


async def test_广播_频道里没有这个频道对象就不播(db, channel_env):
    await add(db, subject="a", score=70)
    assert await make_cog(None).broadcast_once() is False


async def test_广播_频道冷清不播_不认领(db, channel_env):
    ch = FakeChannel(active=False)
    await add(db, subject="a", score=70)
    assert await make_cog(ch).broadcast_once() is False and ch.sent == []
    assert len([r for r in await all_rumors(db) if r.broadcast_at == 0]) == 1, "没播就不能标成播过"


async def test_广播_读频道历史失败也不播(db, channel_env, caplog):
    ch = FakeChannel(fail=True)
    await add(db, subject="a", score=70)
    with caplog.at_level(logging.WARNING):
        assert await make_cog(ch).broadcast_once() is False
    assert "读取频道历史失败" in caplog.text


async def test_广播_没有合适的传闻不播(db, channel_env):
    ch = FakeChannel()
    await add(db, subject="a", score=3)
    assert await make_cog(ch).broadcast_once() is False


async def test_广播_总开关(db, channel_env, monkeypatch):
    cfg = rm.load_config()
    cfg["broadcast"]["enabled"] = False
    monkeypatch.setattr(rm, "load_config", lambda: json.loads(json.dumps(cfg)))
    ch = FakeChannel()
    await add(db, subject="a", score=70)
    assert await make_cog(ch).broadcast_once() is False


async def test_广播_顺手清理过期(db, channel_env):
    await add(db, subject="old", created=time.time() - 9 * 86400)
    await make_cog(FakeChannel()).broadcast_once()
    assert await all_rumors(db) == []


async def test_广播_两个循环不会重复播同一条(db, channel_env):
    import asyncio
    ch = FakeChannel()
    await add(db, subject="a", score=70)
    results = await asyncio.gather(make_cog(ch).broadcast_once(), make_cog(ch).broadcast_once())
    assert len(ch.sent) == 1 and sorted(results) == [False, True]


async def test_后台任务调用并且随_cog_启停(db, monkeypatch):
    import asyncio
    calls = []
    cog = make_cog()

    async def fake(now=None):
        calls.append(1)
        return False
    monkeypatch.setattr(cog, "broadcast_once", fake)
    await cog._broadcast_loop.coro(cog)
    assert calls == [1]
    await cog._before_loop()

    class Waiting:
        async def wait_until_ready(self):
            await asyncio.sleep(3600)
    cog2 = RumorsCog(Waiting())
    await cog2.cog_load()
    assert cog2._broadcast_loop.is_running()
    await cog2.cog_unload()
    await asyncio.sleep(0.05)
    assert not cog2._broadcast_loop.is_running()


async def test_后台任务出错不让循环停(db, monkeypatch, caplog):
    cog = make_cog()

    async def boom(now=None):
        raise RuntimeError("x")
    monkeypatch.setattr(cog, "broadcast_once", boom)
    with caplog.at_level(logging.ERROR):
        await cog._broadcast_loop.coro(cog)
    assert "传闻广播 本轮出错" in caplog.text


async def test_命令_茶馆听闻(db):
    now = time.time()
    await add(db, subject="h", human=True, text="真人事迹一条", created=now)
    await add(db, subject="b", text="机器人闲谈一条", created=now - 10)
    cog, c = make_cog(), FakeContext(user_id=1)
    await cog.listen.callback(cog, c)
    e = c.last.embed
    assert "真人事迹一条" in e.fields[0].value and "⭐" in e.fields[0].value and "机器人闲谈一条" in e.fields[1].value
    assert "7 天" in e.footer.text


async def test_命令_茶馆听闻_空的时候有提示(db):
    cog, c = make_cog(), FakeContext(user_id=1)
    await cog.listen.callback(cog, c)
    e = c.last.embed
    assert "还没有修士的事迹" in e.fields[0].value and "风平浪静" in e.fields[1].value


async def test_命令_开关(db):
    await player(db, "1")
    cog = make_cog()
    c = FakeContext(user_id=1)
    await cog.toggle.callback(cog, c)
    assert c.said("已关闭") and await rm.record_rumor("rebirth", "1", "甲") is None
    c2 = FakeContext(user_id=1)
    await cog.toggle.callback(cog, c2)
    assert c2.said("已重新打开")


async def test_命令_没有角色不能开关(db):
    cog, c = make_cog(), FakeContext(user_id=9)
    await cog.toggle.callback(cog, c)
    assert c.said("请先创建角色")


async def test_setup与bot加载():
    added = []

    class Bot:
        async def add_cog(self, c):
            added.append(c)
    await rumors_cog.setup(Bot())
    assert isinstance(added[0], RumorsCog)
    assert 'load_extension("cogs.rumors")' in (ROOT / "bot.py").read_text(encoding="utf-8")


# ---- 迁移 -------------------------------------------------------------------

def test_迁移补上新表(tmp_path):
    import os
    import sqlite3
    import subprocess
    import sys
    path = tmp_path / "old.db"
    env = dict(os.environ, DB_PATH=str(path))

    def alembic(*a):
        return subprocess.run([sys.executable, "-m", "alembic", "-c", str(ROOT / "alembic.ini"), *a],
                              cwd=ROOT, env=env, capture_output=True, text=True)

    assert alembic("upgrade", "d1a8c5e30f72").returncode == 0
    conn = sqlite3.connect(path)
    conn.execute("DROP TABLE rumors")
    conn.execute("DROP TABLE rumor_optout")
    conn.commit()
    conn.close()
    assert alembic("upgrade", "head").returncode == 0
    conn = sqlite3.connect(path)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(rumors)")}
    assert {"id", "created_at", "kind", "score", "subject_id", "subject_name", "is_human", "negative", "content", "city",
            "broadcast_at"} == cols
    assert {r[1] for r in conn.execute("PRAGMA table_info(rumor_optout)")} == {"player_id"}
    conn.close()
    assert alembic("upgrade", "head").returncode == 0
