"""探险奖励结算测试（cogs/explore.py::_apply_rewards）。

这个函数里「发现宗门」和「装备掉落」两支曾经一跑就崩：
它们用 `row["列名"]` 读 SQLAlchemy 2 的 Row（只支持下标和 `row._mapping["列名"]`），
抛 TypeError，既没发宗门/装备，同一事件里排在后面的奖励也一起丢了。
没人发现，是因为这一块此前零测试。
"""

import json


from cogs.explore import _apply_rewards
from tests.conftest import make_player

UID = "u"


async def _add_player(db, **fields):
    D = db["db_async"]
    p = make_player(D, UID, stones=100)
    for k, v in fields.items():
        setattr(p, k, v)
    async with D.AsyncSessionLocal() as s:
        s.add(p)
        await s.commit()


async def _row(db):
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        return await s.get(D.Player, UID)


async def _equipment(db):
    D = db["db_async"]
    from sqlalchemy import select
    async with D.AsyncSessionLocal() as s:
        return (await s.execute(select(D.Equipment).where(D.Equipment.discord_id == UID))).scalars().all()


# --- 属性类奖励 ---------------------------------------------------------------

async def test_属性与灵石奖励逐项入账(db):
    await _add_player(db, physique=5, bone=5, spirit_stones=100)

    await _apply_rewards(UID, {"physique": 2, "bone": 1, "spirit_stones": 600})

    p = await _row(db)
    assert (p.physique, p.bone, p.spirit_stones) == (7, 6, 700)


async def test_负数奖励是扣减_但不会扣成负数(db):
    await _add_player(db, spirit_stones=100, fortune=2)

    await _apply_rewards(UID, {"spirit_stones": -500, "fortune": -1})

    p = await _row(db)
    assert p.spirit_stones == 0                    # MAX(0, 100-500)
    assert p.fortune == 1


async def test_空奖励什么都不做(db):
    await _add_player(db)
    await _apply_rewards(UID, {})
    await _apply_rewards(UID, None)
    assert (await _row(db)).spirit_stones == 100


# --- 发现宗门 -----------------------------------------------------------------

async def test_发现宗门_记入已发现列表_同一事件的其它奖励照发(db):
    """回归：这一支曾因 row["discovered_sects"] 抛 TypeError，宗门没发现、后面的奖励也丢了。"""
    await _add_player(db, soul=5)

    await _apply_rewards(UID, {"discover_sect": "太虚阁", "soul": 1})

    p = await _row(db)
    assert json.loads(p.discovered_sects) == ["太虚阁"]
    assert p.soul == 6


async def test_发现宗门_不重复记录(db):
    await _add_player(db, discovered_sects=json.dumps(["太虚阁"]))

    await _apply_rewards(UID, {"discover_sect": "太虚阁"})

    assert json.loads((await _row(db)).discovered_sects) == ["太虚阁"]


async def test_发现宗门_追加在已有宗门之后(db):
    await _add_player(db, discovered_sects=json.dumps(["甲宗"]))

    await _apply_rewards(UID, {"discover_sect": "太虚阁"})

    assert json.loads((await _row(db)).discovered_sects) == ["甲宗", "太虚阁"]


async def test_发现宗门_角色不存在不报错(db):
    await _apply_rewards("nobody", {"discover_sect": "太虚阁"})


# --- 装备掉落 -----------------------------------------------------------------

async def test_装备掉落_发到背包_并把装备记在奖励里供界面展示(db):
    """回归：这一支曾因 p_row["realm"] 抛 TypeError，玩家看不到装备也看不到事件结果，
    排在装备后面的奖励（下面的根骨）一起丢失。"""
    await _add_player(db, realm="筑基期3层", bone=5)
    rewards = {"physique": 1, "equipment": {"quality": "精良", "chance": 1.0}, "bone": 1}

    await _apply_rewards(UID, rewards)

    owned = await _equipment(db)
    assert len(owned) == 1 and owned[0].quality == "精良"
    assert rewards["_generated_equipment"]["equip_id"] == owned[0].equip_id
    p = await _row(db)
    assert p.physique == 6 and p.bone == 6        # 装备前后的奖励都在


async def test_装备掉落_档位跟随玩家境界(db):
    await _add_player(db, realm="结丹期初期")

    await _apply_rewards(UID, {"equipment": {"quality": "精良", "chance": 1.0}})

    from utils.equipment import get_player_tier
    assert (await _equipment(db))[0].tier == get_player_tier("结丹期初期")
    assert get_player_tier("结丹期初期") > get_player_tier("炼气期1层")        # 前提：档位确实随境界变


async def test_装备掉落_概率为零不掉(db):
    await _add_player(db)
    rewards = {"equipment": {"quality": "精良", "chance": 0.0}}

    await _apply_rewards(UID, rewards)

    assert await _equipment(db) == []
    assert "_generated_equipment" not in rewards


async def test_装备掉落_按品质池和权重抽(db, monkeypatch):
    import random
    await _add_player(db)
    monkeypatch.setattr(random, "choices", lambda pool, weights, k: [pool[-1]])
    spec = {"quality_pool": ["精良", "稀有"], "quality_weights": [60, 40], "chance": 1.0}

    await _apply_rewards(UID, {"equipment": spec})

    assert (await _equipment(db))[0].quality == "稀有"
