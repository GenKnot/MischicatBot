"""天骄的一生（U1）：称号与背景、出世（新秀补位）、崛起、陨落、飞升、被击杀。

· 称号 / 背景只有天骄有，按性格原型取，数据合法（可被 AI 扩充，校验器抓格式错误）；
· 天骄离场（死 / 被杀 / 飞升）留一个空缺，补员时优先补新秀天骄并记「出世」传闻；管理员一次性生成不播（会刷屏）；
· 天骄顶在天花板上够了日子每天有几率飞升；正常档不飞升；不再顶着就清零；
· 天骄的突破 / 寿尽 / 被击杀用带称号的专门传闻种类。
"""

import json
import random
import time
from collections import Counter

import pytest
from sqlalchemy import select

from tests.conftest import make_player
from utils import bot_combat as bc
from utils import bot_economy as be
from utils import bot_legends as bl
from utils import bot_settle as bsl
from utils import bot_world
from utils import rumors as rm
from utils.views.bot_actions import profile_lines

TODAY = "2026-10-11"
CITY = "落云城"


@pytest.fixture(autouse=True)
def fixed_day(monkeypatch):
    monkeypatch.setattr(bsl, "today", lambda: TODAY)
    monkeypatch.setattr(bc, "today", lambda: TODAY)


@pytest.fixture
def cfg(monkeypatch):
    c = be.load_config()
    c["income_noise"] = [1.0, 1.0]
    c["daily_cap_per_bot"] = 10**6
    c["wild"]["trip_chance"] = 0
    c["speed"] = {k: 0.0 for k in c["speed"]}
    c["materials"]["jobs_per_day"] = 0
    monkeypatch.setattr(be, "load_config", lambda: json.loads(json.dumps(c)))

    def set_(**kw):
        for k, v in kw.items():
            c[k].update(v) if isinstance(v, dict) and isinstance(c.get(k), dict) else c.__setitem__(k, v)
    set_.cfg = c
    return set_


async def mk(db, uid="bot_00001", tier="天骄", archetype="高冷", realm="炼气期10层", cultivation=200, epithet="寒江雪",
             city=CITY, stones=0, capped_days=0, **kw):
    D = db["db_async"]
    p = make_player(D, uid, stones=stones)
    p.name, p.is_bot, p.realm, p.cultivation, p.current_city = f"道友{uid[-2:]}", True, realm, cultivation, city
    p.lifespan, p.lifespan_max = kw.pop("lifespan", 80), 100
    for k, v in kw.items():
        setattr(p, k, v)
    async with D.AsyncSessionLocal() as s:
        s.add(p)
        s.add(D.BotPersonality(bot_id=uid, archetype=archetype, tier=tier, home_city=city, epithet=epithet,
                               backstory="来历成谜。" if epithet else "", capped_days=capped_days))
        await s.commit()


async def human(db, uid="1001", realm="炼气期1层"):
    D = db["db_async"]
    p = make_player(D, uid)
    p.name, p.realm, p.current_city = f"真人{uid}", realm, CITY
    async with D.AsyncSessionLocal() as s:
        s.add(p)
        await s.commit()


async def pers(db, uid="bot_00001"):
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        return await s.get(D.BotPersonality, uid)


async def vacancy(db):
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        return int(await bot_world.get_state(s, bot_world.VACANCY_KEY, "0") or 0)


async def rumors_of(db, kind=None):
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        q = select(D.Rumor).order_by(D.Rumor.id)
        if kind:
            q = q.where(D.Rumor.kind == kind)
        return list((await s.execute(q)).scalars())


async def run(rng=None, force=False):
    return await bsl.run_settlement(rng=rng or random.Random(0), force=force)


# ---- 称号 / 背景 ------------------------------------------------------------

def test_数据合法():
    assert bl.validate(bl.load()) == []
    data = bl.load()
    assert all(len(v) >= bl.MIN_PER_ARCHETYPE for v in data["epithets"].values())


@pytest.mark.parametrize("edit,words", [
    (lambda d: d["epithets"].pop("豪爽"), "epithets"),
    (lambda d: d["backstories"].pop("豪爽"), "backstories"),
    (lambda d: d["epithets"]["豪爽"].__setitem__(slice(None), ["甲", "乙"]), "至少"),
    (lambda d: d["epithets"]["豪爽"].append(d["epithets"]["豪爽"][0]), "不重复"),
    (lambda d: d["epithets"]["豪爽"].append("太长太长太长太长太长太长"), "称号不合法"),
    (lambda d: d["epithets"]["豪爽"].append("{x}"), "称号不合法"),
    (lambda d: d["backstories"]["豪爽"].append("字" * 100), "超过"),
    (lambda d: d["backstories"]["豪爽"].append("在{place}长大"), "占位符"),
    (lambda d: d["backstories"]["豪爽"].append("在{home"), "花括号"),
    (lambda d: d["backstories"]["豪爽"].__setitem__(slice(None), ["甲", "乙"]), "至少"),
])
def test_校验器抓得住错误(edit, words):
    d = bl.load()
    edit(d)
    errors = bl.validate(d)
    assert errors and any(words in e for e in errors), errors


def test_取称号_背景换成常驻城市_可复现():
    a = bl.make_legend("阴鸷", CITY, random.Random(1))
    assert a == bl.make_legend("阴鸷", CITY, random.Random(1)) and "{" not in a[1]
    assert a[0] in bl.load()["epithets"]["阴鸷"]
    assert "某处" in bl.make_legend("阴鸷", "", random.Random(1))[1], "没有常驻城市时写『某处』，不会留着花括号"


def test_取称号_避开已用的_用完了才重复():
    taken = set()
    got = [bl.make_legend("憨直", CITY, random.Random(i), taken)[0] for i in range(6)]
    assert len(set(got)) == 6 and taken == set(got)                                   # 憨直有 6 个称号
    again = bl.make_legend("憨直", CITY, random.Random(9), taken)[0]
    assert again in got, "用完了就允许重复，不会卡死"


# ---- 生成 -------------------------------------------------------------------

async def test_生成_只有天骄有称号和背景(db):
    await bot_world.generate_bots(120, random.Random(4))
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        rows = list((await s.execute(select(D.BotPersonality))).scalars())
    tj = [r for r in rows if r.tier == "天骄"]
    assert tj and all(r.epithet and r.backstory and "{" not in r.backstory for r in tj)
    assert all(not r.epithet and not r.backstory for r in rows if r.tier != "天骄")
    assert len({r.epithet for r in tj}) == len(tj), "称号尽量不重复"


async def test_生成_背景里的城市是它的常驻城市(db):
    await bot_world.generate_bots(120, random.Random(4))
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        for r in (await s.execute(select(D.BotPersonality).where(D.BotPersonality.tier == "天骄"))).scalars():
            home_tpls = [t for t in bl.load()["backstories"][r.archetype]]
            assert r.backstory in {t.format(home=r.home_city) for t in home_tpls}


async def test_管理员一次性生成不播出世传闻(db):
    await bot_world.generate_bots(120, random.Random(4))
    assert await rumors_of(db, "tianjiao_debut") == []


# ---- 空缺与补位 -------------------------------------------------------------

async def test_天骄离场留空缺_别的档位不留(db):
    await mk(db, "bot_00001", tier="天骄")
    await mk(db, "bot_00002", tier="天骄")
    await mk(db, "bot_00003", tier="正常")
    await bot_world.remove_bots(["bot_00001", "bot_00002", "bot_00003"])
    assert await vacancy(db) == 2


async def test_真人_ID_混进来也不留空缺(db):
    await human(db)
    await bot_world.remove_bots(["1001"])
    assert await vacancy(db) == 0


async def test_补员_先补天骄空缺_并记出世传闻(db):
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        await bot_world.set_state(s, bot_world.VACANCY_KEY, "2")
        await s.commit()
    res = await bot_world.generate_bots(5, random.Random(1), track_target=False, fill_vacancies=True)
    tiers = [c["tier"] for c in res["created"]]
    assert tiers[:2] == ["天骄", "天骄"]
    assert await vacancy(db) == max(0, 2 - res["by_tier"]["天骄"]) == 0
    debuts = await rumors_of(db, "tianjiao_debut")
    assert len(debuts) == res["by_tier"]["天骄"] >= 2
    assert all(r.subject_id.startswith("bot_") and not r.is_human for r in debuts)
    assert any(c["epithet"] in debuts[0].content for c in res["created"] if c["tier"] == "天骄")


async def test_补员_空缺比补员数多就一次补不完_剩下的留着(db):
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        await bot_world.set_state(s, bot_world.VACANCY_KEY, "5")
        await s.commit()
    res = await bot_world.generate_bots(2, random.Random(1), track_target=False, fill_vacancies=True)
    assert res["by_tier"]["天骄"] == 2 and await vacancy(db) == 3


async def test_补员_没有空缺就按档位权重随机(db):
    res = await bot_world.generate_bots(100, random.Random(1), track_target=False, fill_vacancies=True)
    assert res["by_tier"]["天骄"] < 20 and await vacancy(db) == 0


async def test_清除机器人_空缺也清零(db):
    await mk(db)
    await bot_world.remove_bots(["bot_00001"])
    assert await vacancy(db) == 1
    await bot_world.clear_bots()
    assert await vacancy(db) == 0


async def test_天骄寿尽_补员日出现新秀(db, cfg):
    cfg(speed={"天骄": 1.0})
    await mk(db, "bot_00001", lifespan=1, realm="炼气期3层", cultivation=0)
    await mk(db, "bot_00002", tier="正常", epithet="", realm="炼气期3层", cultivation=0)
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        await bot_world.set_state(s, "target", "2")
        await s.commit()
    out = await run()
    assert out["deaths"] == 1 and out["refilled"] == 1
    fall = await rumors_of(db, "tianjiao_fall_old")
    debut = await rumors_of(db, "tianjiao_debut")
    assert len(fall) == 1 and "寒江雪" in fall[0].content
    assert len(debut) == 1 and await vacancy(db) == 0
    async with D.AsyncSessionLocal() as s:
        newcomer = (await s.execute(select(D.BotPersonality).where(D.BotPersonality.bot_id != "bot_00002",
                                                                   D.BotPersonality.bot_id != "bot_00001"))).scalars().one()
    assert newcomer.tier == "天骄" and newcomer.epithet


# ---- 飞升 -------------------------------------------------------------------

async def test_飞升_顶着天花板够日子才飞(db, cfg, monkeypatch):
    cfg(tianjiao={"ascend_after_days": 3, "ascend_chance": 1.0})
    await mk(db)                                               # 炼气期10层，修为够了，没有真人 → 顶着炼气期天花板
    days = []
    for d in range(1, 4):
        monkeypatch.setattr(bsl, "today", lambda d=d: f"2026-10-{10 + d}")
        days.append(await run())
    assert [x["ascended"] for x in days] == [0, 0, 1]
    assert (await pers(db)) is None, "飞升就是离场"
    ascend = await rumors_of(db, "tianjiao_ascend")
    assert len(ascend) == 1 and "寒江雪" in ascend[0].content and ascend[0].score >= 90
    assert await vacancy(db) == 1 and days[2]["deaths"] == 0, "飞升不算死亡"


async def test_飞升_几率为零或没到日子不飞(db, cfg, monkeypatch):
    cfg(tianjiao={"ascend_after_days": 1, "ascend_chance": 0.0001})
    await mk(db)
    for d in range(1, 6):
        monkeypatch.setattr(bsl, "today", lambda d=d: f"2026-10-{10 + d}")
        assert (await run(rng=random.Random(d)))["ascended"] == 0
    assert (await pers(db)).capped_days == 5


async def test_飞升_正常档不飞升(db, cfg, monkeypatch):
    cfg(tianjiao={"ascend_after_days": 1, "ascend_chance": 1.0})
    await mk(db, tier="正常", epithet="")
    for d in range(1, 4):
        monkeypatch.setattr(bsl, "today", lambda d=d: f"2026-10-{10 + d}")
        assert (await run())["ascended"] == 0
    assert (await pers(db)) is not None and (await pers(db)).capped_days == 0


async def test_飞升_天花板升高了就清零(db, cfg, monkeypatch):
    cfg(tianjiao={"ascend_after_days": 5, "ascend_chance": 1.0})
    await mk(db)
    for d in range(1, 3):
        monkeypatch.setattr(bsl, "today", lambda d=d: f"2026-10-{10 + d}")
        await run()
    assert (await pers(db)).capped_days == 2
    await human(db, realm="筑基期3层")                         # 真人到了筑基期：天花板升到筑基期10层
    monkeypatch.setattr(bsl, "today", lambda: "2026-10-20")
    out = await run(rng=random.Random(0))
    assert out["capped"] == 0 and (await pers(db)).capped_days == 0, "不再被天花板顶着，天数清零（这时是买不起筑基丹在等）"


async def test_飞升_修为不够不算顶着(db, cfg, monkeypatch):
    cfg(tianjiao={"ascend_after_days": 1, "ascend_chance": 1.0})
    await mk(db, cultivation=10)
    monkeypatch.setattr(bsl, "today", lambda: "2026-10-12")
    out = await run()
    assert out["ascended"] == 0 and out["capped"] == 0 and (await pers(db)).capped_days == 0


# ---- 传闻 -------------------------------------------------------------------

async def test_天骄突破大境_用专门的种类(db):
    await mk(db, realm="炼气期10层")
    await rm.on_breakthrough({"discord_id": "bot_00001", "name": "甲", "current_city": CITY, "realm": "炼气期10层"},
                             {"breakthrough": True, "old_realm": "炼气期10层", "new_realm": "筑基期1层"})
    r = await rumors_of(db)
    assert [x.kind for x in r] == ["tianjiao_rise"] and "寒江雪" in r[0].content


async def test_天骄小层突破_仍是普通传闻(db):
    await mk(db)
    await rm.on_breakthrough({"discord_id": "bot_00001", "name": "甲", "current_city": CITY, "realm": "炼气期3层"},
                             {"breakthrough": True, "old_realm": "炼气期3层", "new_realm": "炼气期4层"})
    assert [x.kind for x in await rumors_of(db)] == ["breakthrough_minor"]


async def test_天骄突破致死(db):
    await mk(db)
    await rm.on_breakthrough({"discord_id": "bot_00001", "name": "甲", "current_city": CITY, "realm": "筑基期10层"},
                             {"breakthrough": False, "is_dead": True})
    r = await rumors_of(db)
    assert [x.kind for x in r] == ["tianjiao_fall_breakthrough"] and "寒江雪" in r[0].content


async def test_正常档与真人的突破传闻不变(db):
    await mk(db, "bot_00002", tier="正常", epithet="")
    await human(db)
    for uid, name in (("bot_00002", "乙"), ("1001", "丙")):                  # 名字不同：相同的句子十分钟内会去重
        await rm.on_breakthrough({"discord_id": uid, "name": name, "current_city": CITY, "realm": "炼气期10层"},
                                 {"breakthrough": True, "old_realm": "炼气期10层", "new_realm": "筑基期1层"})
    assert [x.kind for x in await rumors_of(db)] == ["breakthrough_major", "breakthrough_major"]


async def test_称号_没有时用道号兜底_真人和非天骄是_None(db):
    await mk(db, "bot_00001", epithet="")
    await mk(db, "bot_00002", tier="正常")
    await human(db)
    assert await rm.tianjiao_epithet("bot_00001") == "道友01"
    assert await rm.tianjiao_epithet("bot_00002") is None and await rm.tianjiao_epithet("1001") is None
    assert await rm.tianjiao_epithet("bot_99999") is None


async def test_寿尽_天骄与普通的种类不同(db):
    await mk(db, "bot_00001")
    await mk(db, "bot_00002", tier="正常", epithet="")
    await rm.on_bot_old_age("bot_00001")
    await rm.on_bot_old_age("bot_00002")
    assert [x.kind for x in await rumors_of(db)] == ["tianjiao_fall_old", "death_old"]


async def test_击杀天骄_是大新闻_并留空缺(db):
    await human(db)
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        h = await s.get(D.Player, "1001")
        h.current_city = "万妖岭"
        await s.commit()
    await mk(db, "bot_00001", city="万妖岭", stones=1000)
    await mk(db, "bot_00002", tier="正常", epithet="", city="万妖岭", stones=1000)
    assert (await bc.kill_bot("1001", "bot_00001"))["ok"]
    assert (await bc.kill_bot("1001", "bot_00002"))["ok"]
    kinds = [x.kind for x in await rumors_of(db)]
    assert kinds == ["tianjiao_killed", "kill_bot"]
    big = (await rumors_of(db, "tianjiao_killed"))[0]
    assert "寒江雪" in big.content and "真人1001" in big.content and big.is_human and big.score >= 90
    assert await vacancy(db) == 1


def test_新种类分值很高_能上广播():
    kinds = rm.load_config()["kinds"]
    floor = rm.load_config()["broadcast"]["min_score"]
    for k in ("tianjiao_debut", "tianjiao_rise", "tianjiao_fall_old", "tianjiao_fall_breakthrough", "tianjiao_ascend", "tianjiao_killed"):
        assert kinds[k]["score"] >= 45 > floor
    assert kinds["tianjiao_ascend"]["score"] > kinds["tianjiao_rise"]["score"] > kinds["tianjiao_debut"]["score"]
    assert kinds["tianjiao_fall_old"]["negative"] and kinds["tianjiao_fall_breakthrough"]["negative"]


# ---- 资料页 / 老数据补称号 --------------------------------------------------

async def test_资料页_天骄显示称号与背景(db):
    await mk(db, "bot_00001")
    await mk(db, "bot_00002", tier="正常", epithet="")
    tj = await profile_lines("1001", "bot_00001")
    plain = await profile_lines("1001", "bot_00002")
    assert tj[0] == "✨ 天骄「寒江雪」" and any("来历成谜" in l for l in tj)
    assert not any("天骄" in l or "来历" in l for l in plain)


async def test_资料页_非天骄即使有称号也不显示(db):
    await mk(db, "bot_00001", tier="正常", epithet="残留的称号")
    lines = await profile_lines("1001", "bot_00001")
    assert not any("残留的称号" in l or "来历" in l for l in lines)


async def test_不再等待飞升的天骄_天数清零(db, cfg):
    """修为掉下来、不再够突破：不算顶着天花板，连续天数清零。"""
    await mk(db, cultivation=10, realm="炼气期3层", capped_days=4)
    await run()
    assert (await pers(db)).capped_days == 0


async def test_站在天花板上但修为不够_天数也清零(db, cfg):
    """突破失败后修为减半，人还在天花板那一层，但已经不够再冲：不算顶着。"""
    await mk(db, cultivation=10, realm="炼气期10层", capped_days=4)
    await run()
    assert (await pers(db)).capped_days == 0


async def test_老天骄没有称号_每日结算补上(db, cfg):
    await mk(db, "bot_00001", epithet="", realm="炼气期3层", cultivation=0, archetype="豪爽")
    await run()
    p = await pers(db)
    assert p.epithet in bl.load()["epithets"]["豪爽"] and p.backstory and "{" not in p.backstory


async def test_已有称号的不会被改(db, cfg):
    await mk(db, "bot_00001", epithet="我的称号", realm="炼气期3层", cultivation=0)
    await run()
    assert (await pers(db)).epithet == "我的称号"


# ---- 迁移 -------------------------------------------------------------------

def test_迁移补上新列(tmp_path):
    import os
    import sqlite3
    import subprocess
    import sys
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    path = tmp_path / "old.db"
    env = dict(os.environ, DB_PATH=str(path))

    def alembic(*a):
        return subprocess.run([sys.executable, "-m", "alembic", "-c", os.path.join(root, "alembic.ini"), *a],
                              cwd=root, env=env, capture_output=True, text=True)

    assert alembic("upgrade", "e4b7a2c91d05").returncode == 0
    conn = sqlite3.connect(path)
    for col in ("epithet", "backstory", "capped_days"):
        conn.execute(f"ALTER TABLE bot_personality DROP COLUMN {col}")
    conn.execute("INSERT INTO bot_personality (bot_id, archetype) VALUES ('bot_00001', '豪爽')")
    conn.commit()
    conn.close()
    assert alembic("upgrade", "head").returncode == 0
    conn = sqlite3.connect(path)
    assert conn.execute("SELECT epithet, backstory, capped_days FROM bot_personality").fetchone() == ("", "", 0)
    conn.close()
    assert alembic("upgrade", "head").returncode == 0
