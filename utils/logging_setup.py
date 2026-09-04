"""日志配置。在 main.py 最早处调用一次。

输出到 stdout —— 容器和 k8s 都是从那里收日志，写文件反而要额外挂卷。
级别用 LOG_LEVEL 环境变量控制，默认 INFO。
"""

import logging
import os
import sys

_NOISY = (
    "alembic.runtime.plugins",     # 启动时刷 8 行插件加载，没用
    "discord.gateway",
    "discord.client",
    "discord.voice_state",
    "discord.player",
    "aiosqlite",
)


def configure_logging() -> None:
    level = os.getenv("LOG_LEVEL", "INFO").upper()
    logging.basicConfig(
        level=getattr(logging, level, logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        stream=sys.stdout,
        force=True,          # 覆盖掉库可能已经装上的 handler
    )
    # 这几个库在 INFO 级别很吵，调高一档
    for name in _NOISY:
        logging.getLogger(name).setLevel(max(logging.WARNING,
                                             getattr(logging, level, logging.INFO)))


def audit(action: str, actor, **fields) -> None:
    """记录管理员操作。谁、做了什么、影响了谁，一行一条。

    改变玩家资产的操作都要留痕，出问题时才追得回来。
    """
    log = logging.getLogger("mischicat.audit")
    detail = " ".join(f"{k}={v}" for k, v in fields.items())
    log.warning("ADMIN %s by %s(%s) %s", action, actor, getattr(actor, "id", "?"), detail)
