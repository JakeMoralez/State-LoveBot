"""
Точка входа VK-бота (асинхронная архитектура, vkbottle + Tortoise ORM).

Legacy forum-бот: legacy/forum_bot.py
"""

from __future__ import annotations

import asyncio
import logging
import time

from vkbottle import API
from vkbottle.bot import Bot, Message
from vkbottle.exception_factory import VKAPIError
from vkbottle.polling import BotPolling

from config import VK_GROUP_ID, VK_GROUP_TOKEN
from config.settings import BASE_DIR
from config.logging_setup import setup_logging
from database import close_db, init_db
from middlewares.access import AccessChecker, requires_developer
from middlewares.action_logger import ActionLogger
from modules import register_all_modules
from services.chat_admin import ChatAdminService
from services.forum_api import ForumService, _ARIZONA_IMPORT_ERROR, _HAS_ARIZONA
from services.help_menu import build_dev_help_text, build_help_text_for_user
from services.sled_internal_api import start_sled_internal_server, stop_sled_internal_server

logger = logging.getLogger(__name__)

_forum_service = ForumService()
_bot_started_at: float | None = None


def create_bot(token: str, group_id: int) -> tuple[Bot, API, ActionLogger]:
    api = API(token=token)
    polling = BotPolling(api=api, group_id=group_id)
    bot = Bot(token=token, api=api, polling=polling)
    # Не вырезать @бот из текста — иначе ломается [id|никнейм] и команды с @
    bot.labeler.message_view.replace_mention = False
    action_logger = ActionLogger(api)
    register_all_modules(bot, api, action_logger, forum_service=_forum_service)

    @bot.error_handler.register_undefined_error_handler
    async def on_vkbottle_error(error: Exception) -> None:
        logger.exception("Ошибка обработки события VK: %s", error)

    @bot.on.message(text=["/help", "/start", "!help", "!start"])
    async def help_handler(message: Message) -> None:
        user_id = message.from_id or 0
        if user_id <= 0:
            await message.answer("⛔ Команда доступна только пользователям VK.")
            return
        server_id = await AccessChecker.resolve_server_id(message.peer_id, user_id)
        await message.answer(await build_help_text_for_user(user_id, server_id))

    @bot.on.message(text=["/devhelp", "!devhelp"])
    @requires_developer
    async def devhelp_handler(
        message: Message,
        server_id: int = 0,
        access_level: int = 0,
    ) -> None:
        await message.answer(build_dev_help_text())

    @bot.on.message(text=["/ping", "!ping"])
    async def ping_handler(message: Message) -> None:
        if _bot_started_at is None:
            await message.answer("🏓 pong")
            return
        elapsed = int(time.monotonic() - _bot_started_at)
        uptime = ChatAdminService.format_duration(elapsed)
        await message.answer(f"🏓 pong\n⏱ Время работы: {uptime}")

    return bot, api, action_logger


async def run_bot() -> None:
    bot, api, _ = create_bot(VK_GROUP_TOKEN, VK_GROUP_ID)
    sled_runner = None

    try:
        await init_db()
        sled_runner = await start_sled_internal_server(api)
        if _forum_service.available:
            try:
                logger.info("Подключение к форуму...")
                await _forum_service.connect()
            except Exception as exc:
                logger.error(
                    "❌ Не удалось подключиться к форуму: %s. "
                    "!info/!edit не будут работать. "
                    "Проверьте FORUM_XF_* cookies в .env.",
                    exc,
                )
                if not _HAS_ARIZONA:
                    logger.error(
                        "arizona_forum_async не установлен: %s. "
                        "Выполните: pip install -r requirements.txt",
                        _ARIZONA_IMPORT_ERROR,
                    )
        logger.info("Бот запущен (async architecture)")
        global _bot_started_at
        _bot_started_at = time.monotonic()
        try:
            await bot.run_polling()
        except VKAPIError as exc:
            if exc.code == 100 and "longpoll" in str(exc).lower():
                logger.error(
                    "Long Poll API не включён в настройках группы VK.\n"
                    "Включите: Управление сообществом → Работа с API → "
                    "Long Poll API → Включено, типы событий: «Входящие сообщения».\n"
                    "Также проверьте VK_GROUP_ID в .env (числовой ID группы без минуса)."
                )
            raise
    finally:
        await stop_sled_internal_server(sled_runner)
        if _forum_service.available:
            await _forum_service.close()
        await close_db()
        logger.info("Бот остановлен")


def main() -> None:
    setup_logging()
    env_path = BASE_DIR / ".env"
    if not VK_GROUP_TOKEN:
        logger.error(
            "VK_GROUP_TOKEN не задан. Проверьте %s (PM2: cwd должен быть %s)",
            env_path,
            BASE_DIR,
        )
        raise SystemExit(1)
    if not VK_GROUP_ID:
        logger.error("VK_GROUP_ID не задан. Проверьте %s", env_path)
        raise SystemExit(1)
    try:
        asyncio.run(run_bot())
    except KeyboardInterrupt:
        logger.info("Остановка по Ctrl+C")


if __name__ == "__main__":
    main()
