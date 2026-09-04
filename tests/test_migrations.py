"""数据库迁移测试。

Alembic 接手建表和后续所有 schema 变更。这里守住三件事：
- 全新库能被迁移建出完整 schema
- 已有库上是空操作，不动数据
- 迁移建出来的 schema 和 ORM 模型一致（不一致说明有人改了模型没写迁移）
"""

import os
import shutil
import sqlite3
import subprocess
import sys

import pytest
from sqlalchemy import create_engine

from utils.db_async import Base

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _alembic(db_path, *args):
    env = dict(os.environ, DB_PATH=str(db_path))
    return subprocess.run(
        [sys.executable, "-m", "alembic", "-c", os.path.join(_ROOT, "alembic.ini"), *args],
        cwd=_ROOT, env=env, capture_output=True, text=True,
    )


def _tables(path):
    conn = sqlite3.connect(path)
    return {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}


def _columns(path, table):
    conn = sqlite3.connect(path)
    return {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}


def test_全新库能迁移出完整_schema(tmp_path):
    db = tmp_path / "fresh.db"

    result = _alembic(db, "upgrade", "head")

    assert result.returncode == 0, result.stderr
    tables = _tables(db)
    assert "alembic_version" in tables
    for name in Base.metadata.tables:
        assert name in tables, f"缺表 {name}"


def test_迁移建出的_schema_与_orm_模型一致(tmp_path):
    """模型改了却没写迁移的话，这条会红。"""
    migrated = tmp_path / "migrated.db"
    _alembic(migrated, "upgrade", "head")

    reference = tmp_path / "reference.db"
    Base.metadata.create_all(create_engine(f"sqlite:///{reference}"))

    for table in sorted(Base.metadata.tables):
        assert _columns(migrated, table) == _columns(reference, table), f"{table} 列不一致"


def test_对已有库是空操作(tmp_path):
    """老库已经有全部表，迁移不能动数据。"""
    db = tmp_path / "existing.db"
    Base.metadata.create_all(create_engine(f"sqlite:///{db}"))
    conn = sqlite3.connect(db)
    conn.execute("INSERT INTO inventory (discord_id, item_id, quantity) VALUES ('u','x',3)")
    conn.commit()
    conn.close()

    result = _alembic(db, "upgrade", "head")

    assert result.returncode == 0, result.stderr
    conn = sqlite3.connect(db)
    assert conn.execute("SELECT quantity FROM inventory WHERE discord_id='u'").fetchone()[0] == 3


def test_重复迁移仍然幂等(tmp_path):
    db = tmp_path / "twice.db"
    assert _alembic(db, "upgrade", "head").returncode == 0
    before = _tables(db)

    assert _alembic(db, "upgrade", "head").returncode == 0

    assert _tables(db) == before


def test_迁移脚本没有分叉():
    """多个 head 说明有人并行加了迁移没接上，之后 upgrade head 会失败。"""
    result = _alembic(":memory:", "heads")
    assert result.returncode == 0, result.stderr
    heads = [l for l in result.stdout.splitlines() if l.strip() and "(head)" in l]
    assert len(heads) == 1, f"存在多个 head：{result.stdout}"


def test_遗留的_migrate_不再新增字段():
    """utils/db.py 的 _migrate 已冻结。新字段要写成 alembic revision。

    数字变了就说明有人往里加了东西，该去写迁移。
    """
    import ast
    import inspect

    from utils import db as db_sync

    # 用 AST 解析而不是正则 —— 列表里的对齐方式不统一，正则会漏
    tree = ast.parse(inspect.getsource(db_sync._migrate))
    entries = next(
        node.value.elts
        for node in ast.walk(tree)
        if isinstance(node, ast.Assign)
        and getattr(node.targets[0], "id", None) == "migrations"
    )
    assert len(entries) == 41, (
        f"_migrate 的字段数变成了 {len(entries)}（原为 41）。"
        "它已冻结，新字段请写 alembic revision。")
