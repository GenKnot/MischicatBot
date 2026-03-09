import asyncio

from main import main as bot_main


if __name__ == "__main__":
    try:
        asyncio.run(bot_main())
    except KeyboardInterrupt:
        pass

