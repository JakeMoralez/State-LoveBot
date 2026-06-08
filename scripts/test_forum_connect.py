"""Проверка подключения к форуму через arizona_forum_async."""
import asyncio
import sys
from pathlib import Path

root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(root))

from services.forum_api import ForumService


async def main() -> None:
    forum = ForumService()
    print("cookies ok:", forum.available)
    await forum.connect()
    print("backend:", forum.backend)
    info = await forum.get_thread_info(10015588)
    print("thread:", info)
    await forum.close()


if __name__ == "__main__":
    asyncio.run(main())
