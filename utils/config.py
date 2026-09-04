"""应用配置，在模块加载时从环境变量读取（含 .env）。"""
import os

# 命令前缀，与 .env 中 COMMAND_PREFIX 一致，用于所有面向用户的提示文案
COMMAND_PREFIX = os.getenv("COMMAND_PREFIX", "cat!")

# 数据库路径，三处（db.py / db_async.py / web/main.py）统一从此引用
DB_PATH = os.getenv("DB_PATH", "game.db")

# 管理员（Master）的 Discord ID，逗号分隔。这些人能用 `重置*` 之类的运维命令。
# 默认值是原先散在各处的那个硬编码 ID，保持行为不变；正式的权限体系见
# .gk/ROADMAP.md 的 R1。
MASTER_IDS = frozenset(
    s.strip() for s in os.getenv("MASTER_IDS", "304758476448595970").split(",") if s.strip()
)


def is_master(user_id) -> bool:
    return str(user_id) in MASTER_IDS
