import asyncio
import os
import sys

# PyInstaller onefile: 尽早设置 base 路径，供 web.main 在子进程中使用
if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
    os.environ.setdefault("MISCHICAT_BASE", sys._MEIPASS)

import subprocess

import uvicorn
from dotenv import load_dotenv

from utils.logging_setup import configure_logging

configure_logging()

ENV_TEMPLATE = """DISCORD_TOKEN=
DISCORD_GUILD_ID=
COMMAND_PREFIX=cat!
# Docker 用 /app/sqlite-data/game.db；本地 Windows 用 sqlite-data/game.db
DB_PATH=/app/sqlite-data/game.db
# 本地 Web 服务端口，不填则默认 8080
WEB_PORT=8080
PUBLIC_EVENT_CHANNEL_ID=
# Web 面板鉴权：留空则本地不鉴权、在 Kubernetes 里则停用面板
WEB_USER=admin
WEB_PASS=
"""


def exit_with_pause(msg: str | None = None, code: int = 0):
    """打印消息后等待回车再退出，防止窗口直接关闭。"""
    if msg:
        print(msg)
    input("按回车键退出...")
    sys.exit(code)


def _update_log_path() -> str:
    # Default log file: repository root next to main.py
    return os.getenv("UPDATE_LOG_PATH", "auto_update.log").strip() or "auto_update.log"


def _log_update(msg: str):
    line = f"[auto-update] {msg}"
    print(line)
    # Avoid writing log files when running inside Kubernetes pods.
    if os.getenv("KUBERNETES_SERVICE_HOST") is not None:
        return

    try:
        with open(_update_log_path(), "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        # Logging should never break the bot.
        pass



# Optionally load .env if present, but do not require it
try:
    load_dotenv()
except Exception:
    pass

from bot import MischicatBot

# test commit 1
def _run_git(*args: str, cwd: str | None = None) -> str:
    """Run git command and return stdout (trimmed)."""
    res = subprocess.run(
        ["git", *args],
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
    )
    return (res.stdout or "").strip()


# 仓库根目录。git 命令统一带上它，免得进程 cwd 不是仓库时行为不一致。
_REPO_DIR = os.path.dirname(os.path.abspath(__file__))


def _get_git_root() -> str | None:
    out = _run_git("rev-parse", "--show-toplevel", cwd=_REPO_DIR)
    return out if out else None


def _get_current_commit() -> str | None:
    return _run_git("rev-parse", "HEAD", cwd=_REPO_DIR) or None


def _resolve_target_commit(channel: str) -> str | None:
    """
    stable: latest tag matching v* (sorted by version)
    alpha: latest remote HEAD (origin/HEAD)
    """
    channel = (channel or "").strip().lower()
    if channel == "stable":
        _run_git("fetch", "origin", "--tags", cwd=_REPO_DIR)
        tags = _run_git("tag", "--sort=-v:refname", "--list", "v*", cwd=_REPO_DIR).splitlines()
        if not tags:
            return None
        tag = tags[0].strip()
        commit = _run_git("rev-list", "-n", "1", tag, cwd=_REPO_DIR)
        return commit or None

    _run_git("fetch", "origin", cwd=_REPO_DIR)
    origin_head_ref = _run_git("symbolic-ref", "-q", "refs/remotes/origin/HEAD", cwd=_REPO_DIR)
    if origin_head_ref:
        commit = _run_git("rev-parse", origin_head_ref.strip(), cwd=_REPO_DIR)
        return commit or None
    commit = _run_git("rev-parse", "origin/HEAD", cwd=_REPO_DIR)
    return commit or None


def maybe_update_repo_once() -> bool:
    """
    Compare local HEAD with configured target commit.
    If different: git reset --hard to target, then return True.
    """

    # Disable autoupdate if running in Kubernetes
    if os.getenv("KUBERNETES_SERVICE_HOST") is not None:
        _log_update("Kubernetes detected, auto-update disabled.")
        return False

    enabled = os.getenv("AUTO_UPDATE", "").strip().lower()
    if enabled not in {"1", "true", "yes", "on"}:
        return False

    channel = os.getenv("UPDATE_CHANNEL", "stable").strip().lower()

    git_root = _get_git_root()
    if not git_root:
        _log_update("Not a git repository; skip.")
        return False

    current = _get_current_commit()
    if not current:
        _log_update("Cannot resolve current git commit; skip.")
        return False

    target = _resolve_target_commit(channel)
    if not target:
        _log_update(f"Cannot resolve target commit for channel={channel}; skip.")
        return False

    if current == target:
        return False

    _log_update(f"Resolved current={current[:7]} target={target[:7]} channel={channel}")
    _log_update(f"Updating git repo: {current[:7]} -> {target[:7]}")
    _run_git("reset", "--hard", target, cwd=git_root)
    return True


def _restart():
    """原地重启。frozen 下 sys.argv[0] 就是 exe 本身，不能再传一次。"""
    args = sys.argv[1:] if getattr(sys, "frozen", False) else sys.argv
    os.execv(sys.executable, [sys.executable, *args])


async def auto_update_loop():

    # Disable autoupdate if running in Kubernetes
    if os.getenv("KUBERNETES_SERVICE_HOST") is not None:
        _log_update("Kubernetes detected, auto-update loop disabled.")
        return

    enabled = os.getenv("AUTO_UPDATE", "").strip().lower()
    if enabled not in {"1", "true", "yes", "on"}:
        return

    interval_min = float(os.getenv("UPDATE_INTERVAL_MINUTES", "60").strip() or "60")
    interval_s = max(5.0, interval_min * 60.0)

    try:
        git_root = _get_git_root()
        current = _get_current_commit()
        channel = os.getenv("UPDATE_CHANNEL", "stable").strip().lower()
        log_path = _update_log_path()
        if git_root and current:
            _log_update(
                f"Startup: log={log_path} current HEAD={current[:7]} channel={channel}"
            )
        else:
            _log_update(f"Startup: log={log_path} current HEAD unavailable channel={channel}")
    except Exception as e:
        _log_update(f"Startup: cannot read git info: {e!r}")

    try:
        # git fetch 是同步阻塞的，网络慢会卡住整个 bot，丢到线程里跑
        updated = await asyncio.to_thread(maybe_update_repo_once)
    except Exception as e:
        _log_update(f"Startup check failed: {e!r}")
        updated = False

    if updated:
        _log_update("Restarting after update...")
        _restart()

    while True:
        await asyncio.sleep(interval_s)
        try:
            updated = await asyncio.to_thread(maybe_update_repo_once)
        except Exception as e:
            _log_update(f"Update check failed: {e!r}")
            continue

        if updated:
            _log_update("Restarting after update...")
            _restart()


async def main():

    token = os.getenv("DISCORD_TOKEN")
    if not token:
        exit_with_pause("请设置 DISCORD_TOKEN 环境变量后重新运行。", 1)

    web_port = int(os.getenv("WEB_PORT", "8080"))
    config = uvicorn.Config("web.main:app", host="0.0.0.0", port=web_port, log_level="warning")
    server = uvicorn.Server(config)

    async with MischicatBot() as bot:
        # 让 /ready 探针能看到 bot 的真实状态（uvicorn 以 "web.main:app"
        # 字符串加载，与这里 import 的是同一个模块对象）
        from web.main import set_bot
        set_bot(bot)

        await asyncio.gather(
            bot.start(token),
            server.serve(),
            auto_update_loop(),
        )


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        exit_with_pause()
