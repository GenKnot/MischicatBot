"""在 bot 启动时把数据库迁到最新。

同步执行，调用方负责丢到线程里（见 bot.py）。
"""

import logging
import os

from alembic import command
from alembic.config import Config

log = logging.getLogger("mischicat.migrate")

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _config() -> Config:
    cfg = Config(os.path.join(_ROOT, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(_ROOT, "alembic"))
    return cfg


def run_migrations() -> None:
    command.upgrade(_config(), "head")
    log.info("数据库已迁移到最新")
