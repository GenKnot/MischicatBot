import asyncio
import os

import uvicorn
from dotenv import load_dotenv

load_dotenv()

from bot import MischicatBot


async def main():
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        raise ValueError("DISCORD_TOKEN missing")

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
        pass
