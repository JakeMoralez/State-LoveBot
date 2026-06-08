"""Регистрация бизнес-модулей бота."""

from __future__ import annotations

from vkbottle import API
from vkbottle.bot import Bot

from middlewares.action_logger import ActionLogger
from modules.administration.handlers import register_administration
from modules.ca.handlers import register_ca
from modules.chat.handlers import register_chat
from modules.chat_admin.handlers import register_chat_admin
from modules.congress.handlers import register_congress
from modules.forum.handlers import register_forum
from modules.forum_roles.handlers import register_forum_roles
from modules.pools.handlers import register_pools
from modules.profile.handlers import register_profile
from modules.system.handlers import register_system
from services.forum_api import ForumService


def register_all_modules(
    bot: Bot,
    api: API,
    action_logger: ActionLogger,
    forum_service: ForumService | None = None,
) -> None:
    register_system(bot, api)
    register_chat(bot, api, action_logger)
    register_chat_admin(bot, api, action_logger)
    register_pools(bot, api, action_logger)
    register_profile(bot, api, action_logger)
    register_administration(bot, api, action_logger)
    register_forum_roles(bot, api, action_logger)
    register_ca(bot, api, action_logger)
    register_congress(bot, api, action_logger)
    register_forum(bot, api, action_logger, forum_service=forum_service)
