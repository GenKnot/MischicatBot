import asyncio
import os
import sys

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


def ensure_env():
    """若不存在 .env 则从模板生成并提示用户填写后退出。"""
    env_path = os.path.join(os.getcwd(), ".env")
    if not os.path.exists(env_path):
        with open(env_path, "w", encoding="utf-8") as f:
            f.write(ENV_TEMPLATE)
        exit_with_pause("已生成 .env 文件，请填写 DISCORD_TOKEN 等配置后重新运行。", 0)


ensure_env()
load_dotenv()

from bot import MischicatBot


async def main():
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        exit_with_pause("请在 .env 中填写 DISCORD_TOKEN 后重新运行。", 1)

    web_port = int(os.getenv("WEB_PORT", "8080"))
    config = uvicorn.Config("web.main:app", host="0.0.0.0", port=web_port, log_level="warning")
    server = uvicorn.Server(config)

    async with MischicatBot() as bot:
        await asyncio.gather(
            bot.start(token),
            server.serve(),
        )


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        exit_with_pause()
