"""Конфигурация проекта из переменных окружения."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

# VK
VK_GROUP_ID: int = int(os.getenv("VK_GROUP_ID", "0"))
VK_GROUP_TOKEN: str = os.getenv("VK_GROUP_TOKEN", "")
VK_USER_TOKEN: str = os.getenv("VK_USER_TOKEN", "")

# Сервер по умолчанию (единственный параметр сервера в .env)
DEFAULT_SERVER_ID: int = int(os.getenv("DEFAULT_SERVER_ID", "30"))
DEFAULT_SERVER_SLUG: str = os.getenv("DEFAULT_SERVER_SLUG", "default")

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

# Панель (должность из staff_notes для {{position}})
def _default_panel_database_url() -> str:
    for path in (
        Path("/opt/State-Love-Admin/data/panel.db"),
        BASE_DIR.parent / "State-LoveAdmin" / "data" / "panel.db",
    ):
        if path.is_file():
            return f"sqlite:///{path.as_posix()}"
    return ""


PANEL_DATABASE_URL: str = os.getenv("PANEL_DATABASE_URL", "") or _default_panel_database_url()

# Форум (cookies из браузера)
FORUM_BASE_URL: str = os.getenv("FORUM_BASE_URL", "https://forum.arizona-rp.com")
FORUM_USER_AGENT: str = os.getenv("FORUM_USER_AGENT", "")
FORUM_COOKIES: dict[str, str | None] = {
    "xf_user": os.getenv("FORUM_XF_USER"),
    "xf_session": os.getenv("FORUM_XF_SESSION"),
    "xf_tfa_trust": os.getenv("FORUM_XF_TFA_TRUST"),
}

ATTORNEY_FORUM_ID: int = 3287
# Жалобы на лидеров → беседа ruk_gos (https://forum.arizona-rp.com/forums/3303/)
LEADER_COMPLAINT_FORUM_ID: int = int(os.getenv("LEADER_COMPLAINT_FORUM_ID", "3303") or "3303")
LEADER_ALLOWED_FORUMS: list[int] = [
    2935, 2936, 2937, 2938, 2939, 2940, 2941, 2942, 2943, 2944, 2945,
    LEADER_COMPLAINT_FORUM_ID,
]
TECH_CHAT_ID: int = 2000000007

# Чёрные списки (Google Sheets, /checkbl)
BLACKLIST_SHEET_ID: str = os.getenv(
    "BLACKLIST_SHEET_ID",
    "1UEqmplxE3caHnCaVs31Duuofv9N6NbXgOJS19bq1FTc",
)
BLACKLIST_CACHE_TTL_SEC: int = int(os.getenv("BLACKLIST_CACHE_TTL_SEC", "300") or "300")

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
                "database.models.court_form",
                "database.models.role_chat",
                "database.models.chat_settings",
                "database.models.judge_forum_list",
                "database.models.court_claim",
                "database.models.leader_complaint",
            ],
            "default_connection": "default",
        },
    },
}
