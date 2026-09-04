"""Schema 一致性测试。

两条建表路径：utils/db.py 的裸 SQL（老库走这条）和 ORM 的 create_all（新库）。
两者必须等价。ORM 的 default= 不生成 SQL DEFAULT，万宝阁曾因此在新库上开不了拍。
"""

import sqlite3

import pytest
from sqlalchemy import create_engine

from utils import db as db_sync
from utils.db_async import Base


def _orm_schema(tmp_path):
    """用独立的同步 engine 把 ORM schema 建到临时库，不碰全局 engine。"""
    path = tmp_path / "orm.db"
    Base.metadata.create_all(create_engine(f"sqlite:///{path}"))
    return sqlite3.connect(path)


def _legacy_schema(tmp_path, monkeypatch):
    """走 utils/db.py 的遗留建表路径。"""
    path = tmp_path / "legacy.db"
    monkeypatch.setattr(db_sync, "DB_PATH", str(path))
    db_sync.init_db()
    return sqlite3.connect(path)


def _columns(conn, table):
    """{列名: (是否 NOT NULL, 默认值)}"""
    return {r[1]: (r[3], r[4]) for r in conn.execute(f"PRAGMA table_info({table})")}


def _tables(conn):
    return {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
    )}


def test_orm_模型的每个默认值都有对应的_server_default():
    """凡是有 Python 端 default 的列，都必须同时声明 server_default。"""
    missing = []
    for table in Base.metadata.tables.values():
        for col in table.columns:
            if col.default is not None and col.server_default is None:
                missing.append(f"{table.name}.{col.name}")

    assert not missing, (
        "以下列有 Python 端默认值但没有 server_default，"
        f"新库上的裸 INSERT 会撞 NOT NULL：{missing}"
    )


def test_两条建表路径的表集合一致(tmp_path, monkeypatch):
    orm = _orm_schema(tmp_path)
    legacy = _legacy_schema(tmp_path, monkeypatch)
    assert _tables(orm) == _tables(legacy)


def test_两条建表路径的默认值不分叉(tmp_path, monkeypatch):
    """ORM 建的表不能出现「NOT NULL 却没有默认值」而 legacy 有默认值的列。"""
    orm = _orm_schema(tmp_path)
    legacy = _legacy_schema(tmp_path, monkeypatch)

    divergent = {}
    for table in sorted(_tables(orm) & _tables(legacy)):
        o, l = _columns(orm, table), _columns(legacy, table)
        bad = [
            name for name, (not_null, default) in o.items()
            if not_null and default is None
            and name in l and l[name][1] is not None
        ]
        if bad:
            divergent[table] = bad

    assert not divergent, f"两套 schema 的默认值分叉：{divergent}"


@pytest.mark.parametrize("sql", [
    # 这些是代码里真实存在的、没有列全字段的裸 INSERT
    "INSERT INTO wanbao_auctions (auction_id, date_str, status)"
    " VALUES ('a', '2026-01-01', 'pending')",
    "INSERT INTO wanbao_lots (lot_id, auction_id, lot_index, seller_id, item_name,"
    " quantity, item_type, start_price, eq_data)"
    " VALUES ('l', 'a', 0, NULL, 'x', 1, 'item', 100, NULL)",
    "INSERT INTO wanbao_frozen (discord_id, auction_id, amount) VALUES ('1', 'a', 5)",
    "INSERT INTO public_events (event_id, event_type, title, started_at, ends_at,"
    " status, data) VALUES ('e', 't', 'ti', 1, 2, 'active', '{}')",
    "INSERT INTO public_event_participants (event_id, discord_id, joined_at, activity)"
    " VALUES ('e', '1', 1, 'act')",
    "INSERT INTO known_recipes (discord_id, recipe_id) VALUES ('1', 'r')",
    "INSERT INTO adventure_progress (discord_id, progress, updated_at)"
    " VALUES ('1', '{}', 0)",
])
def test_全新库能接受代码里的裸_insert(tmp_path, sql):
    orm = _orm_schema(tmp_path)
    orm.execute(sql)      # 抛异常即失败


# --- 主键完整性 --------------------------------------------------------------

def test_主键列不可为空(tmp_path):
    """SQLite 里 NULL != NULL，可空的主键列挡不住重复行。

    `public_event_participants.activity` 曾是可空主键列，activity 为 NULL 时
    同一个人同一个活动能插进多行。
    """
    orm = _orm_schema(tmp_path)
    nullable_pk = []
    for table in Base.metadata.tables:
        for cid, name, _type, notnull, _default, pk in orm.execute(
                f"PRAGMA table_info({table})"):
            if pk and not notnull:
                nullable_pk.append(f"{table}.{name}")
    assert not nullable_pk, f"这些主键列可为空：{nullable_pk}"


def test_参与记录不能重复(tmp_path):
    orm = _orm_schema(tmp_path)
    orm.execute("INSERT INTO public_event_participants "
                "(event_id, discord_id, activity, joined_at, contribution) "
                "VALUES ('e', 'u', 'defense', 1, 0)")

    with pytest.raises(sqlite3.IntegrityError):
        orm.execute("INSERT INTO public_event_participants "
                    "(event_id, discord_id, activity, joined_at, contribution) "
                    "VALUES ('e', 'u', 'defense', 1, 0)")


def test_省略_activity_时也挡得住重复(tmp_path):
    """不传 activity 会落到默认空串上，仍然受主键约束。"""
    orm = _orm_schema(tmp_path)
    orm.execute("INSERT INTO public_event_participants "
                "(event_id, discord_id, joined_at, contribution) VALUES ('e','u',1,0)")

    with pytest.raises(sqlite3.IntegrityError):
        orm.execute("INSERT INTO public_event_participants "
                    "(event_id, discord_id, joined_at, contribution) VALUES ('e','u',1,0)")
