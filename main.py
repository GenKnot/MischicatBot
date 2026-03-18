import asyncio
import os
import sys

# PyInstaller onefile: 尽早设置 base 路径，供 web.main 在子进程中使用
if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
    os.environ.setdefault("MISCHICAT_BASE", sys._MEIPASS)

import subprocess

import uvicorn
from dotenv import load_dotenv

ENV_TEMPLATE = """DISCORD_TOKEN=
DISCORD_GUILD_ID=
COMMAND_PREFIX=cat!
# Docker 用 /app/sqlite-data/game.db；本地 Windows 用 sqlite-data/game.db
DB_PATH=/app/sqlite-data/game.db
# 本地 Web 服务端口，不填则默认 8080
WEB_PORT=8080
PUBLIC_EVENT_CHANNEL_ID=
"""


def exit_with_pause(msg: str | None = None, code: int = 0):
    """打印消息后等待回车再退出，防止窗口直接关闭。"""
    if msg:
        print(msg)
    input("按回车键退出...")
    sys.exit(code)



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


def _get_git_root() -> str | None:
    out = _run_git("rev-parse", "--show-toplevel")
    return out if out else None


def _get_current_commit() -> str | None:
    return _run_git("rev-parse", "HEAD") or None


def _resolve_target_commit(channel: str) -> str | None:
    """
    stable: latest tag matching v* (sorted by version)
    alpha: latest remote HEAD (origin/HEAD)
    """
    channel = (channel or "").strip().lower()
    if channel == "stable":
        _run_git("fetch", "origin", "--tags")
        tags = _run_git("tag", "--sort=-v:refname", "v*").splitlines()
        if not tags:
            return None
        tag = tags[0].strip()
        commit = _run_git("rev-list", "-n", "1", tag)
        return commit or None

    _run_git("fetch", "origin")
    origin_head_ref = _run_git("symbolic-ref", "-q", "refs/remotes/origin/HEAD")
    if origin_head_ref:
        commit = _run_git("rev-parse", origin_head_ref.strip())
        return commit or None
    commit = _run_git("rev-parse", "origin/HEAD")
    return commit or None


def maybe_update_repo_once() -> bool:
    """
    Compare local HEAD with configured target commit.
    If different: git reset --hard to target, then return True.
    """
    enabled = os.getenv("AUTO_UPDATE", "").strip().lower()
    if enabled not in {"1", "true", "yes", "on"}:
        return False

    channel = os.getenv("UPDATE_CHANNEL", "stable").strip().lower()

    git_root = _get_git_root()
    if not git_root:
        print("[auto-update] Not a git repository; skip.")
        return False

    current = _get_current_commit()
    if not current:
        print("[auto-update] Cannot resolve current git commit; skip.")
        return False

    target = _resolve_target_commit(channel)
    if not target:
        print(f"[auto-update] Cannot resolve target commit for channel={channel}; skip.")
        return False

    if current == target:
        return False

    print(f"[auto-update] Updating git repo: {current[:7]} -> {target[:7]}")
    _run_git("reset", "--hard", target, cwd=git_root)
    return True


async def auto_update_loop():
    enabled = os.getenv("AUTO_UPDATE", "").strip().lower()
    if enabled not in {"1", "true", "yes", "on"}:
        return

    interval_min = float(os.getenv("UPDATE_INTERVAL_MINUTES", "60").strip() or "60")
    interval_s = max(5.0, interval_min * 60.0)

    try:
        updated = maybe_update_repo_once()
    except Exception as e:
        print(f"[auto-update] Startup check failed: {e!r}")
        updated = False

    if updated:
        print("[auto-update] Restarting after update...")
        os.execv(sys.executable, [sys.executable, *sys.argv])

    while True:
        await asyncio.sleep(interval_s)
        try:
            updated = maybe_update_repo_once()
        except Exception as e:
            print(f"[auto-update] Update check failed: {e!r}")
            continue

        if updated:
            print("[auto-update] Restarting after update...")
            os.execv(sys.executable, [sys.executable, *sys.argv])


async def main():

    token = os.getenv("DISCORD_TOKEN")
    if not token:
        exit_with_pause("请设置 DISCORD_TOKEN 环境变量后重新运行。", 1)

    web_port = int(os.getenv("WEB_PORT", "8080"))
    config = uvicorn.Config("web.main:app", host="0.0.0.0", port=web_port, log_level="warning")
    server = uvicorn.Server(config)

    async with MischicatBot() as bot:
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
