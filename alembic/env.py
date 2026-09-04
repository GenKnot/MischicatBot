"""Alembic 环境。

用同步引擎跑迁移 —— 迁移只在启动时执行一次，没必要为它引入异步模板。
数据库地址从 utils.config 读，和 bot 用的是同一个库。
"""

import os
import sys

from alembic import context
from sqlalchemy import create_engine, pool

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.config import DB_PATH          # noqa: E402
from utils.db_async import Base           # noqa: E402

target_metadata = Base.metadata


def _url() -> str:
    return f"sqlite:///{DB_PATH}"


def run_migrations_offline() -> None:
    context.configure(url=_url(), target_metadata=target_metadata,
                      literal_binds=True, render_as_batch=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_engine(_url(), poolclass=pool.NullPool)
    with engine.connect() as connection:
        # SQLite 不支持大部分 ALTER，batch 模式会自动改成建新表搬数据
        context.configure(connection=connection, target_metadata=target_metadata,
                          render_as_batch=True)
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
