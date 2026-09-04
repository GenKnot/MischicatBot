"""测试夹具。

DB_PATH 必须在导入任何 utils 模块之前定好。别改成运行时 reload —— 很多模块
导入时就把 engine 绑成了全局，漏掉一个那个模块就还在读写旧库，测试会空跑通过。

每个测试之间清空所有表。
"""

import os
import sys
import tempfile

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

# 必须先于任何 utils 导入。
#
# 只建一次：pytest 会以 `conftest` 导入本文件，而测试里的
# `from tests.conftest import ...` 又会以 `tests.conftest` 再导入一次。
# 不加这个判断的话 mkdtemp 会跑两遍、DB_PATH 被后一次覆盖，
# 而 utils.db_async 的 engine 绑的是先前那个路径 —— 两边对不上，
# 表建在 A 文件、查询打到 B 文件，症状是莫名其妙的 "no such table"。
if not os.environ.get("MISCHICAT_TEST_DB"):
    _TMPDIR = tempfile.mkdtemp(prefix="mischicat-tests-")
    os.environ["MISCHICAT_TEST_DB"] = os.path.join(_TMPDIR, "test.db")
os.environ["DB_PATH"] = os.environ["MISCHICAT_TEST_DB"]

from utils import db_async as _db_async  # noqa: E402


@pytest.fixture(scope="session")
def anyio_backend():
    return "asyncio"


@pytest.fixture(autouse=True)
async def db():
    """建表（首次）+ 清空所有表，返回常用模块的引用。"""
    async with _db_async.engine.begin() as conn:
        await conn.run_sync(_db_async.Base.metadata.create_all)
        for table in reversed(_db_async.Base.metadata.sorted_tables):
            await conn.execute(table.delete())

    from utils import (alchemy, atomic, bank, checkin, equipment_db, forging,
                       gamble, inventory, market, roulette)
    from utils.views import alchemy as views_alchemy

    yield {
        "db_async": _db_async, "atomic": atomic, "inventory": inventory,
        "market": market, "bank": bank, "gamble": gamble, "roulette": roulette,
        "forging": forging, "alchemy": alchemy, "checkin": checkin,
        "equipment_db": equipment_db, "views_alchemy": views_alchemy,
    }


def make_player(db_async, uid: str, stones: int = 10_000):
    """构造一个最小可用的玩家对象。"""
    import time
    now = time.time()
    return db_async.Player(
        discord_id=uid, name=uid, gender="男",
        spirit_root="金", spirit_root_type="单灵根",
        comprehension=5, physique=5, fortune=5, bone=5, soul=5,
        lifespan=100, lifespan_max=100,
        spirit_stones=stones, created_at=now, last_active=now,
    )
