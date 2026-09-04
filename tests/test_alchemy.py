"""炼丹系统功能测试。

每日次数改成了一条原子 UPDATE（顺带处理跨日归零）。
扣料的顺序也调过：校验 → 扣料 → 占次数 → 掷骰，原先材料不足会白丢一次机会。
"""

import time

import pytest

from tests.conftest import make_player
from utils import alchemy as alchemy_mod
from utils.alchemy import (DAILY_LIMIT, QUALITY_NAMES, attempt_alchemy,
                           calc_quality, calc_success_rate,
                           check_and_consume_daily, get_known_recipes,
                           get_mastery_count, increment_mastery,
                           unlock_recipe)

# 字段与 data/recipes.json 的真实结构保持一致 —— 用自造结构会漏掉
# pill_tier / base_success_rate / max_quality 这些参与计算的字段。
RECIPE = {
    "recipe_id": "test_pill",
    "pill": "测试丹",
    "pill_tier": 1,
    "name": "测试丹方",
    "alchemy_level_req": 0,
    "base_success_rate": 80,
    "max_quality": 5,
    "main_ingredients": [{"item": "灵芝草", "qty": 2}],
    "aux_groups": [
        {"desc": "调和辅药（选一）", "options": [
            {"item": "茯苓灵块", "qty": 1, "quality_bonus": 0},
            {"item": "朱果", "qty": 1, "quality_bonus": 3},
        ]}
    ],
}


@pytest.fixture
async def alchemist(db):
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        p = make_player(D, "u", stones=10_000)
        p.alchemy_level = 3
        s.add(p)
        for item in ("灵芝草", "茯苓灵块", "朱果"):
            s.add(D.Inventory(discord_id="u", item_id=item, quantity=50))
        await s.commit()
    return "u"


async def _inv(db, uid="u"):
    return await db["inventory"].get_inventory(uid)


async def _player(db, uid="u"):
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        return await s.get(D.Player, uid)


# --- 每日次数 ----------------------------------------------------------------

async def test_每日次数逐次递增(db, alchemist):
    for expected in range(1, DAILY_LIMIT + 1):
        ok, used = await check_and_consume_daily(alchemist)
        assert ok and used == expected


async def test_超出上限后被拒并回报已用次数(db, alchemist):
    for _ in range(DAILY_LIMIT):
        await check_and_consume_daily(alchemist)

    ok, used = await check_and_consume_daily(alchemist)

    assert not ok and used == DAILY_LIMIT


async def test_每日次数跨日归零(db, alchemist):
    for _ in range(DAILY_LIMIT):
        await check_and_consume_daily(alchemist)

    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        p = await s.get(D.Player, alchemist)
        p.alchemy_daily_reset = time.time() - 86_400
        await s.commit()

    ok, used = await check_and_consume_daily(alchemist)
    assert ok and used == 1


# --- 熟练度与丹方 ------------------------------------------------------------

async def test_熟练度累加(db, alchemist):
    assert await get_mastery_count(alchemist, "测试丹") == 0

    for expected in (1, 2, 3):
        assert await increment_mastery(alchemist, "测试丹") == expected

    assert await get_mastery_count(alchemist, "测试丹") == 3


async def test_丹方解锁并记录辅药组合(db, alchemist):
    assert await get_known_recipes(alchemist) == set()

    await unlock_recipe(alchemist, "test_pill", [1])

    assert "test_pill" in await get_known_recipes(alchemist)
    known = await alchemy_mod.get_known_recipes_with_choices(alchemist)
    assert known["test_pill"] == [1], "应当记住当次用的辅药组合"


async def test_重复解锁不会覆盖已记录的组合(db, alchemist):
    await unlock_recipe(alchemist, "test_pill", [1])
    await unlock_recipe(alchemist, "test_pill", [0])

    known = await alchemy_mod.get_known_recipes_with_choices(alchemist)
    assert known["test_pill"] == [1], "on_conflict_do_nothing：首次记录为准"


# --- 开炉 --------------------------------------------------------------------

async def test_炼制成功产出丹药并累计熟练度(db, alchemist, monkeypatch):
    monkeypatch.setattr(alchemy_mod.random, "randint", lambda a, b: 1)   # 必定成功
    inventory = await _inv(db)

    result = await attempt_alchemy(alchemist, RECIPE, player_soul=10,
                                   alchemy_level=3, aux_choices=[0],
                                   inventory=inventory)

    assert result["ok"] and result["success"]
    assert result["pill"] == "测试丹"
    assert result["quality_name"] in QUALITY_NAMES
    assert await get_mastery_count(alchemist, "测试丹") == 1
    assert "test_pill" in await get_known_recipes(alchemist)


async def test_炼制失败不产出丹药(db, alchemist, monkeypatch):
    monkeypatch.setattr(alchemy_mod.random, "randint", lambda a, b: 100)  # 必定失败
    inventory = await _inv(db)

    result = await attempt_alchemy(alchemist, RECIPE, player_soul=10,
                                   alchemy_level=3, aux_choices=[0],
                                   inventory=inventory)

    assert result["ok"] is False and result["success"] is False
    assert "consequence" in result
    assert await get_mastery_count(alchemist, "测试丹") == 0


async def test_主药不足直接被拒(db, alchemist):
    result = await attempt_alchemy(alchemist, RECIPE, player_soul=10,
                                   alchemy_level=3, aux_choices=[0],
                                   inventory={"茯苓灵块": 5})

    assert result["ok"] is False and "主药不足" in result["reason"]


async def test_辅药不足直接被拒(db, alchemist):
    result = await attempt_alchemy(alchemist, RECIPE, player_soul=10,
                                   alchemy_level=3, aux_choices=[0],
                                   inventory={"灵芝草": 5})

    assert result["ok"] is False and "辅药不足" in result["reason"]


async def test_主药不足时不消耗每日次数(db, alchemist):
    """材料不足不该白丢一次机会。

    历史：这条原本钉的是相反的行为（配额在掷骰前就被占掉），
    对应 .gk/ISSUES.md C2。C2 修复后按当初的约定翻了过来。
    """
    before = (await _player(db)).alchemy_daily_count

    result = await attempt_alchemy(alchemist, RECIPE, player_soul=10, alchemy_level=3,
                                   aux_choices=[0], inventory={"茯苓灵块": 5})

    assert result["ok"] is False
    assert (await _player(db)).alchemy_daily_count == before, "被拒时不应扣次数"


async def test_开炉必定扣掉材料(db, alchemist, monkeypatch):
    """成败都要扣药 —— 失败时"药材全损"是设计。"""
    monkeypatch.setattr(alchemy_mod.random, "randint", lambda a, b: 100)   # 必定失败
    before = await _inv(db)

    await attempt_alchemy(alchemist, RECIPE, player_soul=10, alchemy_level=3,
                          aux_choices=[0], inventory=before)

    after = await _inv(db)
    assert after["灵芝草"] == before["灵芝草"] - 2
    assert after["茯苓灵块"] == before["茯苓灵块"] - 1


async def test_材料只扣一次(db, alchemist, monkeypatch):
    """回归：扣料原先在 view 里、掷骰之后。把它挪进 attempt_alchemy 时，
    view 里那份必须同步删掉，否则一次开炉扣两份药。"""
    monkeypatch.setattr(alchemy_mod.random, "randint", lambda a, b: 1)
    before = await _inv(db)

    await attempt_alchemy(alchemist, RECIPE, player_soul=10, alchemy_level=3,
                          aux_choices=[0], inventory=before)

    after = await _inv(db)
    assert after["灵芝草"] == before["灵芝草"] - 2, "主药只应扣一份用量"


async def test_次数用尽时材料原样退回(db, alchemist):
    """扣料与占次数在同一事务：次数用尽则药材必须退回。"""
    for _ in range(DAILY_LIMIT):
        await check_and_consume_daily(alchemist)
    before = await _inv(db)

    result = await attempt_alchemy(alchemist, RECIPE, player_soul=10, alchemy_level=3,
                                   aux_choices=[0], inventory=before)

    assert result["ok"] is False and "上限" in result["reason"]
    assert await _inv(db) == before, "被拒时药材必须原样保留"


async def test_超出每日上限时不做任何校验直接返回(db, alchemist):
    for _ in range(DAILY_LIMIT):
        await check_and_consume_daily(alchemist)
    inventory = await _inv(db)

    result = await attempt_alchemy(alchemist, RECIPE, player_soul=10,
                                   alchemy_level=3, aux_choices=[0],
                                   inventory=inventory)

    assert result["ok"] is False and "上限" in result["reason"]


async def test_辅药选择影响品质加成(db, alchemist, monkeypatch):
    """朱果带 quality_bonus=3，应当比茯苓灵块炼出更好的品质。"""
    monkeypatch.setattr(alchemy_mod.random, "randint", lambda a, b: 1)
    monkeypatch.setattr(alchemy_mod.random, "random", lambda: 0.5)

    plain = calc_quality(RECIPE, player_soul=10, alchemy_level=3,
                         aux_quality_bonus=0, mastery_count=0)
    boosted = calc_quality(RECIPE, player_soul=10, alchemy_level=3,
                           aux_quality_bonus=3, mastery_count=0)

    assert boosted >= plain


# --- 纯函数 ------------------------------------------------------------------

def test_成功率在合理区间():
    rate = calc_success_rate(RECIPE, alchemy_level=3, mastery_count=0)
    assert 0 <= rate <= 100


def test_自由配药的成功率不高于按方炼制():
    by_recipe = calc_success_rate(RECIPE, alchemy_level=3, mastery_count=0, free_mix=False)
    free = calc_success_rate(RECIPE, alchemy_level=3, mastery_count=0, free_mix=True)
    assert free <= by_recipe


def test_熟练度越高成功率越高():
    low = calc_success_rate(RECIPE, alchemy_level=3, mastery_count=0)
    high = calc_success_rate(RECIPE, alchemy_level=3, mastery_count=100)
    assert high >= low


def test_品质索引不越界():
    for soul in (0, 10, 999):
        for level in (0, 5, 9):
            idx = calc_quality(RECIPE, soul, level, aux_quality_bonus=99,
                               mastery_count=999, has_yanhuo=True)
            assert 0 <= idx < len(QUALITY_NAMES)


# --- 走 view 的路径（直接调 attempt_alchemy 覆盖不到）-----------------------

async def test_通过面板开炉材料也只扣一次(db, alchemist, monkeypatch):
    """回归重点：扣料从 view 挪进 attempt_alchemy 后，view 里那份必须删掉。

    直接调 `attempt_alchemy` 测不出这个 —— 重复扣料发生在 view 里。
    这条走 `_ConfirmView.confirm` 的完整路径。
    """
    from tests.discord_fakes import FakeInteraction, FakeUser
    from utils.views.alchemy import _ConfirmView

    monkeypatch.setattr(alchemy_mod.random, "randint", lambda a, b: 1)   # 必定成功
    before = await _inv(db)

    view = _ConfirmView(
        author=FakeUser(id=int(alchemist) if alchemist.isdigit() else 1),
        player={"discord_id": alchemist, "soul": 10, "alchemy_level": 3},
        has_yanhuo=False, recipe=RECIPE, inventory=dict(before), choices=[0],
    )
    interaction = FakeInteraction(user_id=alchemist if alchemist.isdigit() else 1)
    interaction.user.id = alchemist          # uid 取自 interaction.user.id

    await view.confirm.callback(interaction)

    after = await _inv(db)
    assert after["灵芝草"] == before["灵芝草"] - 2, (
        f"主药应只扣 2，实际扣了 {before['灵芝草'] - after['灵芝草']}")
    assert after["茯苓灵块"] == before["茯苓灵块"] - 1
