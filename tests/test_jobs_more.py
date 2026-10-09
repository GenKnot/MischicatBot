"""打工（utils/jobs.py、utils/views/jobs.py）：任职条件、数据合法性、面板。结算与冷却见 test_jobs.py。

B40 —— 『码头扛货』的数据里写了 `city_tags`（港口 / 北冥港 / 碧波城），说明只在港口城市开放，
  但没有任何代码读这个字段：任何城市都能扛货。条件改为放进 `req["city_in"]`，和其他任职条件走同一条判断。
"""

import time

import pytest

from tests.conftest import make_player
from tests.discord_fakes import FakeInteraction
from utils import jobs as jm
from utils.jobs import JOBS, _check_req, _req_desc, get_available_jobs, get_job_list, get_locked_jobs
from utils.views.jobs import BackToCityButton, JobButton, JobsView, _jobs_overview_embed

U = "1001"


def by_id(job_id):
    return next(j for j in JOBS if j["id"] == job_id)


def pl(**kw):
    base = dict(discord_id=U, realm="炼气期1层", physique=5, bone=5, comprehension=5, soul=5, fortune=5,
                reputation=0, alchemy_level=0, sect=None, current_city="灵虚城")
    base.update(kw)
    return base


# --- 数据合法性 ---------------------------------------------------------------

def test_打工数据_合法():
    ids = [j["id"] for j in JOBS]
    assert len(ids) == len(set(ids)) and get_job_list() is JOBS
    known = {"realm_min", "physique", "bone", "comprehension", "soul", "fortune", "reputation", "alchemy_level",
             "has_sect", "city", "city_in"}
    for j in JOBS:
        assert 1 <= j["tier"] <= 5 and j["dialogues"] and j["name"] and j["desc"]
        assert set(j["req"]) <= known, (j["id"], set(j["req"]) - known)
        assert "city_tags" not in j, j["id"]                    # 条件统一放 req 里，不再有没人读的旁路字段
        for key, (lo, hi) in ((k, v) for k, v in j["reward"].items() if k != "items"):
            assert 0 <= lo <= hi, (j["id"], key)
        for _, chance in j["reward"].get("items", []):
            assert 0 < chance <= 1
        if "risk" in j:
            lo, hi = j["risk"]["lifespan_loss"]
            assert 0 < lo <= hi and 0 < j["risk"]["chance"] <= 1


def test_高阶工作报酬不低于低阶():
    """档位越高灵石下限越高（防止配置错位）。"""
    floor = {}
    for j in JOBS:
        floor.setdefault(j["tier"], []).append(j["reward"]["spirit_stones"][0])
    mins = {t: min(v) for t, v in floor.items()}
    assert mins[1] < mins[3] < mins[5]


# --- 任职条件 -----------------------------------------------------------------

def test_条件_空要求人人可做():
    assert _check_req(pl(), {}) and _check_req({}, {})


def test_条件_境界():
    req = {"realm_min": "筑基期1层"}
    assert not _check_req(pl(realm="炼气期9层"), req) and _check_req(pl(realm="筑基期1层"), req)
    assert _check_req(pl(realm="结丹期初期"), req) and not _check_req({}, req)


@pytest.mark.parametrize("stat", ["physique", "bone", "comprehension", "soul", "fortune", "reputation", "alchemy_level"])
def test_条件_各项属性是大于等于(stat):
    req = {stat: 7}
    assert not _check_req(pl(**{stat: 6}), req) and _check_req(pl(**{stat: 7}), req) and _check_req(pl(**{stat: 8}), req)
    assert not _check_req({}, req)


def test_条件_宗门与城市():
    assert not _check_req(pl(), {"has_sect": True}) and _check_req(pl(sect="青云宗"), {"has_sect": True})
    assert _check_req(pl(), {"has_sect": False})
    assert _check_req(pl(current_city="丹阁"), {"city": "丹阁"}) and not _check_req(pl(), {"city": "丹阁"})


def test_条件_城市白名单_B40():
    req = {"city_in": ["北冥港", "碧波城"]}
    assert _check_req(pl(current_city="碧波城"), req) and _check_req(pl(current_city="北冥港"), req)
    assert not _check_req(pl(current_city="灵虚城"), req) and not _check_req({}, req)


def test_码头扛货只在港口城市开放_B40():
    porter = by_id("porter")
    assert porter in get_available_jobs(pl(current_city="碧波城"))
    assert porter not in get_available_jobs(pl(current_city="灵虚城"))
    assert porter in get_locked_jobs(pl(current_city="灵虚城"))


def test_条件_多项同时要满足():
    req = {"realm_min": "筑基期1层", "bone": 10}
    assert not _check_req(pl(realm="筑基期1层", bone=9), req) and not _check_req(pl(realm="炼气期1层", bone=10), req)
    assert _check_req(pl(realm="筑基期1层", bone=10), req)


def test_可做与未解锁正好互补():
    for player in (pl(), pl(realm="结丹期初期", bone=10, sect="x", reputation=900, alchemy_level=5, current_city="丹阁")):
        a, l = get_available_jobs(player), get_locked_jobs(player)
        assert len(a) + len(l) == len(JOBS) and not ({j["id"] for j in a} & {j["id"] for j in l})


def test_新人只能做入门工作():
    ids = {j["id"] for j in get_available_jobs(pl())}
    assert {"sweep", "waiter"} <= ids and "escort" not in ids and "storyteller" not in ids


def test_条件文案():
    assert _req_desc({}) == "无"
    d = _req_desc({"realm_min": "筑基期1层", "physique": 5, "bone": 6, "comprehension": 7, "soul": 8, "reputation": 9,
                   "alchemy_level": 2, "has_sect": True, "city": "丹阁", "city_in": ["北冥港", "碧波城"]})
    for part in ("境界≥筑基期1层", "体魄≥5", "根骨≥6", "悟性≥7", "神识≥8", "声望≥9", "炼丹≥2品", "已加入宗门",
                 "需在丹阁", "北冥港", "碧波城"):
        assert part in d, part


# --- 面板 ---------------------------------------------------------------------

async def _add(db, uid=U, **kw):
    D = db["db_async"]
    p = make_player(D, uid, stones=0)
    for k, v in kw.items():
        setattr(p, k, v)
    async with D.AsyncSessionLocal() as s:
        s.add(p)
        await s.commit()


async def _pd(uid=U):
    from sqlalchemy import text
    from utils.db_async import AsyncSessionLocal
    async with AsyncSessionLocal() as s:
        r = await s.execute(text("SELECT * FROM players WHERE discord_id=:u"), {"u": uid})
        return dict(r.fetchone()._mapping)


def inter(uid=U):
    return FakeInteraction(uid)


async def test_总览_状态行与冷却(db):
    await _add(db, job_daily_count=2, job_daily_reset=time.time(), job_cooldown_until=time.time() + 125)
    e = await _jobs_overview_embed(await _pd())
    status = next(f.value for f in e.fields if f.name == "状态")
    assert "2/3" in status and "冷却中" in status and "2 分" in status


async def test_总览_隔天次数按0显示_无冷却(db):
    await _add(db, job_daily_count=3, job_daily_reset=time.time() - 2 * 86400)
    status = next(f.value for f in (await _jobs_overview_embed(await _pd())).fields if f.name == "状态")
    assert "0/3" in status and "冷却中" not in status


async def test_总览_可接与未解锁_最多列5个未解锁(db):
    await _add(db)
    e = await _jobs_overview_embed(await _pd())
    names = {f.name: f.value for f in e.fields}
    assert "街头扫洒" in names["可接工作"] and "灵石" in names["可接工作"]
    locked = names["未解锁"].splitlines()
    assert len(locked) == 6 and "还有" in locked[-1] and all(l.startswith("🔒") for l in locked[:5])


async def test_总览_额外奖励标注(db):
    await _add(db, current_city="丹阁", alchemy_level=5, realm="元婴期初期", bone=10, physique=5, comprehension=5,
               reputation=900)
    text = next(f.value for f in (await _jobs_overview_embed(await _pd())).fields if f.name == "可接工作")
    assert "炼丹经验" in text and "材料" in text and "声望" in text


async def test_总览_没有这个玩家也不崩(db):
    e = await _jobs_overview_embed(pl())
    assert next(f.value for f in e.fields if f.name == "状态").startswith("今日已打工：**0/3**")


async def test_面板_每个可接工作一个按钮加返回(db):
    p = pl()
    v = JobsView(inter().user, p, None)
    assert len(v.children) == len(get_available_jobs(p)) + 1
    assert isinstance(v.children[-1], BackToCityButton)


async def test_面板_只有本人能点(db):
    v = JobsView(inter().user, pl(), None)
    assert await v.interaction_check(inter("2002")) is False


async def click(job, uid=U, cog=None):
    v = JobsView(inter(uid).user, pl(discord_id=uid), cog)
    btn = JobButton(job)                         # 面板可能是旧的：按钮不一定还在当前可做列表里
    btn._view = v
    i = inter(uid)
    await btn.callback(i)
    return i


async def test_点击工作_成功_结算并刷新面板(db, monkeypatch):
    await _add(db)
    monkeypatch.setattr(jm.random, "randint", lambda a, b: a)
    i = await click(by_id("sweep"))
    msg = i.last
    assert i.response.deferred and "街头扫洒 · 完成" in msg.embed.title and isinstance(msg.view, JobsView)
    assert "灵石 +**30**" in next(f.value for f in msg.embed.fields if f.name == "收获")
    assert (await _pd())["spirit_stones"] == 30


async def test_点击工作_奖励卡片带声望_炼丹经验_材料_意外(db, monkeypatch):
    await _add(db, realm="结丹期初期", bone=10)
    monkeypatch.setattr(jm.random, "randint", lambda a, b: b)
    monkeypatch.setattr(jm.random, "random", lambda: 0.0)                   # 材料必掉、风险必中
    i = await click(by_id("escort"))
    f = {x.name: x.value for x in i.last.embed.fields}
    assert "声望 +**5**" in f["收获"]
    assert "损失 **3 年** 寿元" in f["⚠️ 意外"]


async def test_点击工作_材料_炼丹经验行(db, monkeypatch):
    await _add(db, bone=10, physique=5, current_city="丹阁", alchemy_level=1)
    monkeypatch.setattr(jm.random, "randint", lambda a, b: a)
    monkeypatch.setattr(jm.random, "random", lambda: 0.0)
    i = await click(by_id("forge_apprentice"))
    assert "材料：铁矿石、精铁矿" in next(f.value for f in i.last.embed.fields if f.name == "收获")
    i = await click(by_id("dange_assistant"))
    assert "冷却中" in i.last                                                # 刚打过一次，第二份工要等冷却


async def test_点击工作_冷却中被拒(db):
    await _add(db, job_cooldown_until=time.time() + 600)
    i = await click(by_id("sweep"))
    assert "冷却中" in i.last and i.last.ephemeral


async def test_点击工作_不再满足条件_或角色不存在(db):
    await _add(db)
    i = await click(by_id("escort"))                                         # 炼气期做不了镖局
    assert "不满足此工作的要求" in i.last and i.last.ephemeral
    i = await click(by_id("sweep"), uid="9999")
    assert "角色不存在" in i.last


async def test_点击工作_条件已变化时不能靠旧面板绕过_B40(db):
    await _add(db, current_city="灵虚城")
    i = await click(by_id("porter"))
    assert "不满足此工作的要求" in i.last and (await _pd())["spirit_stones"] == 0


async def test_返回城市(db):
    await _add(db)
    v = JobsView(inter().user, pl(), None)
    i = inter()
    await v.children[-1].callback(i)
    assert i.last.embed is not None and not isinstance(i.last.view, JobsView)
