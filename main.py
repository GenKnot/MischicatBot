import asyncio
import os

from dotenv import load_dotenv

from bot import MischicatBot

load_dotenv()


async def main():
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        raise ValueError("DISCORD_TOKEN missing")

    async with MischicatBot() as bot:
        await bot.start(token)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
