"""Инициализация Tortoise ORM."""

from __future__ import annotations

import logging

from tortoise import Tortoise

from config import TORTOISE_ORM
from config.settings import DEFAULT_SERVER_NAME, DEFAULT_SERVER_SLUG, MAIN_ADMIN_ID, MAIN_ADMIN_USERNAME
from database.models.user import AccessLevel, User, UserServerAccess
from database.repository.server_repo import ServerRepository

logger = logging.getLogger(__name__)


async def _ensure_chat_alias_column() -> None:
    conn = Tortoise.get_connection("default")
    try:
        await conn.execute_query("ALTER TABLE chats ADD COLUMN alias VARCHAR(64) NULL")
        logger.info("Добавлена колонка chats.alias")
    except Exception:
        pass


async def _ensure_congress_columns() -> None:
    conn = Tortoise.get_connection("default")
    for column in ("is_congress_speaker", "is_congress_vice"):
        try:
            await conn.execute_query(
                f"ALTER TABLE users ADD COLUMN {column} INTEGER NOT NULL DEFAULT 0"
            )
            logger.info("Добавлена колонка users.%s", column)
        except Exception:
            pass


async def init_db() -> None:
    await Tortoise.init(config=TORTOISE_ORM)
    await Tortoise.generate_schemas(safe=True)
    await _ensure_chat_alias_column()
    await _ensure_congress_columns()
    await _bootstrap_defaults()
    logger.info("База данных инициализирована")


async def close_db() -> None:
    await Tortoise.close_connections()


async def _bootstrap_defaults() -> None:
    server = await ServerRepository.get_or_create_default(
        slug=DEFAULT_SERVER_SLUG,
        name=DEFAULT_SERVER_NAME,
    )
    if not MAIN_ADMIN_ID:
        return

    user, _ = await User.get_or_create(
        vk_id=MAIN_ADMIN_ID,
        defaults={"username": MAIN_ADMIN_USERNAME or None},
    )
    if MAIN_ADMIN_USERNAME and user.username != MAIN_ADMIN_USERNAME:
        await User.filter(vk_id=MAIN_ADMIN_ID).update(username=MAIN_ADMIN_USERNAME)

    await UserServerAccess.update_or_create(
        user_id=MAIN_ADMIN_ID,
        server_id=server.id,
        defaults={"access_level": AccessLevel.DEVELOPER},
    )
    logger.info("Разработчик vk_id=%s → уровень 10 на сервере %s", MAIN_ADMIN_ID, server.slug)
