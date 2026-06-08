"""Конфигурация проекта из переменных окружения."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent

# VK
VK_GROUP_ID: int = int(os.getenv("VK_GROUP_ID", "0"))
VK_GROUP_TOKEN: str = os.getenv("VK_GROUP_TOKEN", "")
VK_USER_TOKEN: str = os.getenv("VK_USER_TOKEN", "")

# Сервер по умолчанию (для односерверных инсталляций)
DEFAULT_SERVER_SLUG: str = os.getenv("DEFAULT_SERVER_SLUG", "default")
DEFAULT_SERVER_NAME: str = os.getenv("DEFAULT_SERVER_NAME", "Основной сервер")
SERVER_NUMBER: int = int(os.getenv("SERVER_NUMBER", "0"))

# Администратор / разработчик
MAIN_ADMIN_ID: int = int(os.getenv("MAIN_ADMIN_ID", "0"))
MAIN_ADMIN_USERNAME: str = os.getenv("MAIN_ADMIN_USERNAME", "")

# Логирование
LOG_CHAT_ID: int = int(os.getenv("LOG_CHAT_ID", "0"))
LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")

# База данных (Tortoise ORM / aiosqlite)
DATABASE_URL: str = os.getenv(
    "DATABASE_URL",
    f"sqlite://{BASE_DIR / 'bot.db'}",
)

# Форум (cookies из браузера)
FORUM_BASE_URL: str = os.getenv("FORUM_BASE_URL", "https://forum.arizona-rp.com")
FORUM_USER_AGENT: str = os.getenv("FORUM_USER_AGENT", "")
FORUM_COOKIES: dict[str, str | None] = {
    "xf_user": os.getenv("FORUM_XF_USER"),
    "xf_session": os.getenv("FORUM_XF_SESSION"),
    "xf_tfa_trust": os.getenv("FORUM_XF_TFA_TRUST"),
}

ATTORNEY_FORUM_ID: int = 3287
JUDGE_FORUM_ID: int = 3423
LEADER_ALLOWED_FORUMS: list[int] = [
    2935, 2936, 2937, 2938, 2939, 2940, 2941, 2942, 2943, 2944, 2945,
]
TECH_CHAT_ID: int = 2000000007

TORTOISE_ORM: dict = {
    "connections": {"default": DATABASE_URL},
    "apps": {
        "models": {
            "models": [
                "database.models.server",
                "database.models.user",
                "database.models.pool",
                "database.models.chat",
                "database.models.moderation",
                "database.models.notification",
                "database.models.role_chat",
            ],
            "default_connection": "default",
        },
    },
}
