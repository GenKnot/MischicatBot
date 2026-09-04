"""打工系统功能测试。

冷却和每日次数原本分处两个事务，且计数只加不跨日归零 ——
第二天起每天只剩一次。这里把修好的行为钉住。
"""

import time

import pytest

from tests.conftest import make_player
from utils import jobs as jobs_mod
from utils.jobs import COOLDOWN_SECONDS, JOB_DAILY_LIMIT, JOBS, do_job

SWEEP = next(j for j in JOBS if j["id"] == "sweep")          # 无 req、无 risk、无 items
WITH_ITEMS = next(j for j in JOBS if "items" in j["reward"])
WITH_RISK = next(j for j in JOBS if "risk" in j)
WITH_ALCHEMY = next(j for j in JOBS if "alchemy_exp" in j["reward"])


@pytest.fixture
async def player(db):
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        s.add(make_player(D, "u", stones=0))
        await s.commit()
    return {"discord_id": "u"}


async def _row(db, uid="u"):
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        return await s.get(D.Player, uid)


async def _clear_cooldown(db, uid="u"):
    """把冷却清零，模拟"半小时后再来"。"""
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        p = await s.get(D.Player, uid)
        p.job_cooldown_until = 0
        await s.commit()


# --- 正常流程 --------------------------------------------------------------

async def test_打工成功并结算灵石(db, player):
    result = await do_job(player, SWEEP)

    assert result["ok"]
    assert result["job_name"] == SWEEP["name"]
    low, high = SWEEP["reward"]["spirit_stones"]
    assert low <= result["spirit_stones"] <= high
    assert result["dialogue"] in SWEEP["dialogues"]

    p = await _row(db)
    assert p.spirit_stones == result["spirit_stones"], "返回值与入账金额必须一致"


async def test_打工后进入冷却(db, player):
    await do_job(player, SWEEP)
    p = await _row(db)
    assert p.job_cooldown_until > time.time(), "打完工必须打上冷却"

    again = await do_job(player, SWEEP)
    assert not again["ok"]
    assert "冷却" in again["reason"]


async def test_冷却期间不消耗每日次数(db, player):
    """被冷却挡下时不能扣掉一次名额 —— 否则连点会把当天次数刷光。"""
    await do_job(player, SWEEP)
    used_after_first = (await _row(db)).job_daily_count

    for _ in range(5):
        assert not (await do_job(player, SWEEP))["ok"]

    assert (await _row(db)).job_daily_count == used_after_first


async def test_每日次数用尽后被拒(db, player):
    for i in range(JOB_DAILY_LIMIT):
        await _clear_cooldown(db)
        assert (await do_job(player, SWEEP))["ok"], f"第 {i+1} 次应当成功"

    await _clear_cooldown(db)
    result = await do_job(player, SWEEP)
    assert not result["ok"]
    assert "上限" in result["reason"]


async def test_次数用尽被拒时不打冷却(db, player):
    """回归点：超限分支会 rollback，连带退回刚打上的冷却。

    若没退回，玩家次日第一次打工还要先等 30 分钟。
    """
    for _ in range(JOB_DAILY_LIMIT):
        await _clear_cooldown(db)
        await do_job(player, SWEEP)

    await _clear_cooldown(db)
    await do_job(player, SWEEP)              # 这次会因超限被拒

    assert (await _row(db)).job_cooldown_until == 0, "被拒时不应留下冷却"


# --- 跨日归零 ----------------------------------------------------------------

async def test_跨日后恢复完整次数(db, player):
    """修复前：第二天第一次打工把计数加到 4，随即被判超限 ——
    从第二天起每天只剩 1 次（上限是 3）。"""
    for _ in range(JOB_DAILY_LIMIT):
        await _clear_cooldown(db)
        await do_job(player, SWEEP)

    # 模拟"第二天"：把上次计数时间和冷却都退回一天前
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        p = await s.get(D.Player, "u")
        p.job_daily_reset = time.time() - 86_400
        p.job_cooldown_until = 0
        await s.commit()

    succeeded = 0
    for _ in range(JOB_DAILY_LIMIT + 2):
        await _clear_cooldown(db)
        if (await do_job(player, SWEEP))["ok"]:
            succeeded += 1

    assert succeeded == JOB_DAILY_LIMIT, "次日必须恢复到完整的每日次数"


# --- 各类奖励分支 ----------------------------------------------------------

async def test_声望奖励入账(db, player, monkeypatch):
    job = dict(SWEEP, reward={**SWEEP["reward"], "reputation": [5, 5]})
    result = await do_job(player, job)

    assert result["reputation"] == 5
    assert (await _row(db)).reputation == 5


async def test_炼丹经验奖励入账(db, player):
    result = await do_job(player, WITH_ALCHEMY)
    if result["alchemy_exp"]:
        assert (await _row(db)).alchemy_exp == result["alchemy_exp"]


async def test_物品奖励必定掉落时入背包(db, player, monkeypatch):
    """把掉率拉满，确认物品真的进了背包。"""
    monkeypatch.setattr(jobs_mod.random, "random", lambda: 0.0)
    result = await do_job(player, WITH_ITEMS)

    assert result["items"], "掉率为 100% 时必须有物品"
    inventory = await db["inventory"].get_inventory("u")
    for item in result["items"]:
        assert inventory.get(item, 0) >= 1


async def test_触发风险时扣寿元且不低于_1(db, player, monkeypatch):
    monkeypatch.setattr(jobs_mod.random, "random", lambda: 0.0)      # 必定触发
    before = (await _row(db)).lifespan

    result = await do_job(player, WITH_RISK)

    assert result["risk_triggered"]
    p = await _row(db)
    assert p.lifespan == max(1, before - result["lifespan_loss"])
    assert p.lifespan >= 1, "寿元不能被扣成 0 或负数"


async def test_未触发风险时寿元不变(db, player, monkeypatch):
    monkeypatch.setattr(jobs_mod.random, "random", lambda: 0.999)    # 必定不触发
    before = (await _row(db)).lifespan

    result = await do_job(player, WITH_RISK)

    assert not result["risk_triggered"]
    assert (await _row(db)).lifespan == before
