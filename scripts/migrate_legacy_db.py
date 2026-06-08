"""
Миграция данных из legacy users.db в новую схему Tortoise (bot.db).

Запуск (после pip install -r requirements.txt):
    python scripts/migrate_legacy_db.py
"""

from __future__ import annotations

import asyncio
import logging
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from config.settings import DEFAULT_SERVER_NAME, DEFAULT_SERVER_SLUG  # noqa: E402
from database.connection import init_db, close_db  # noqa: E402
from database.models.user import AccessLevel, User, UserServerAccess  # noqa: E402
from database.repository.server_repo import ServerRepository  # noqa: E402

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

LEGACY_DB = ROOT / "users.db"


def _map_access_level(row: sqlite3.Row) -> int | None:
    """Только is_admin (legacy) → ГА. Судьи/адвокаты — только флаги, без уровня."""
    if row["is_admin"]:
        return AccessLevel.GA
    return None


async def migrate() -> None:
    if not LEGACY_DB.exists():
        logger.error("Файл %s не найден", LEGACY_DB)
        return

    await init_db()
    server = await ServerRepository.get_or_create_default(
        slug=DEFAULT_SERVER_SLUG,
        name=DEFAULT_SERVER_NAME,
    )

    conn = sqlite3.connect(LEGACY_DB)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users")
    users = cursor.fetchall()
    conn.close()

    migrated = 0
    for row in users:
        user, created = await User.get_or_create(
            vk_id=row["vk_id"],
            defaults={
                "username": row["username"],
                "added_by": row["added_by"],
                "note": row["note"],
                "is_admin": bool(row["is_admin"]),
                "is_judge": bool(row["is_judge"]),
                "is_attorney": bool(row["is_attorney"]),
                "is_leader": bool(row["is_leader"]),
            },
        )
        if not created:
            user.username = row["username"]
            user.note = row["note"]
            user.is_admin = bool(row["is_admin"])
            user.is_judge = bool(row["is_judge"])
            user.is_attorney = bool(row["is_attorney"])
            user.is_leader = bool(row["is_leader"])
            await user.save()

        level = _map_access_level(row)
        if level is not None:
            access, _ = await UserServerAccess.get_or_create(
                user=user,
                server=server,
                defaults={"access_level": level},
            )
            if access.access_level != level:
                access.access_level = level
                await access.save()

        migrated += 1
        roles = []
        if user.is_judge:
            roles.append("judge")
        if user.is_attorney:
            roles.append("attorney")
        if user.is_leader:
            roles.append("leader")
        logger.info(
            "Мигрирован vk_id=%s access=%s forum_roles=%s",
            row["vk_id"],
            level or "—",
            ",".join(roles) or "—",
        )

    logger.info("Готово: %s пользователей", migrated)
    await close_db()


if __name__ == "__main__":
    asyncio.run(migrate())
