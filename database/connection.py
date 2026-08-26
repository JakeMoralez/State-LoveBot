"""Инициализация Tortoise ORM."""

from __future__ import annotations

import logging

from tortoise import Tortoise

from config import TORTOISE_ORM
from config.settings import (
    DATABASE_URL,
    DEFAULT_SERVER_ID,
    DEFAULT_SERVER_SLUG,
    MAIN_ADMIN_ID,
    MAIN_ADMIN_USERNAME,
)
from services.db_utils import is_sqlite_url
from database.models.user import AccessLevel, User, UserServerAccess
from database.repository.server_repo import ServerRepository

logger = logging.getLogger(__name__)

# Старые server_id односерверных инсталляций → DEFAULT_SERVER_ID при старте
LEGACY_SERVER_IDS: tuple[int, ...] = (1,)


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


async def _ensure_server_forum_columns() -> None:
    conn = Tortoise.get_connection("default")
    for ddl in (
        "ALTER TABLE servers ADD COLUMN tag VARCHAR(64) NULL",
        "ALTER TABLE servers ADD COLUMN judge_forum_id INT NULL",
    ):
        try:
            await conn.execute_query(ddl)
            logger.info("Миграция servers: %s", ddl.split("ADD COLUMN ")[1].split()[0])
        except Exception:
            pass


async def _ensure_server_log_peer_column() -> None:
    conn = Tortoise.get_connection("default")
    try:
        await conn.execute_query(
            "ALTER TABLE servers ADD COLUMN log_peer_id BIGINT NULL"
        )
        logger.info("Добавлена колонка servers.log_peer_id")
    except Exception:
        pass


async def _ensure_server_nickname_column() -> None:
    conn = Tortoise.get_connection("default")
    try:
        await conn.execute_query(
            "ALTER TABLE user_server_access ADD COLUMN nickname VARCHAR(64) NULL"
        )
        logger.info("Добавлена колонка user_server_access.nickname")
    except Exception:
        pass


async def _migrate_global_nicknames_to_servers() -> None:
    users = await User.filter(nickname__not_isnull=True).exclude(nickname="")
    if not users:
        return

    migrated = 0
    for user in users:
        nick = (user.nickname or "").strip()
        if not nick:
            continue

        accesses = await UserServerAccess.filter(user_id=user.vk_id)
        if accesses:
            for access in accesses:
                if not (access.nickname and access.nickname.strip()):
                    access.nickname = nick
                    await access.save()
                    migrated += 1
        else:
            await UserServerAccess.get_or_create(
                user_id=user.vk_id,
                server_id=DEFAULT_SERVER_ID,
                defaults={"access_level": 0, "nickname": nick},
            )
            migrated += 1

        user.nickname = None
        await user.save()

    if migrated:
        logger.info(
            "Никнеймы перенесены в user_server_access: %s записей",
            migrated,
        )


async def _ensure_server_role_columns() -> None:
    conn = Tortoise.get_connection("default")
    for column in (
        "is_judge",
        "is_attorney",
        "is_leader",
        "is_congress_speaker",
        "is_congress_vice",
    ):
        try:
            await conn.execute_query(
                f"ALTER TABLE user_server_access ADD COLUMN {column} "
                "INTEGER NOT NULL DEFAULT 0"
            )
            logger.info("Добавлена колонка user_server_access.%s", column)
        except Exception:
            pass


async def _migrate_global_roles_to_servers() -> None:
    from tortoise.expressions import Q

    role_fields = (
        "is_judge",
        "is_attorney",
        "is_leader",
        "is_congress_speaker",
        "is_congress_vice",
    )
    users = await User.filter(
        Q(is_judge=True)
        | Q(is_attorney=True)
        | Q(is_leader=True)
        | Q(is_congress_speaker=True)
        | Q(is_congress_vice=True)
    )
    migrated = 0
    for user in users:
        access, _ = await UserServerAccess.get_or_create(
            user_id=user.vk_id,
            server_id=DEFAULT_SERVER_ID,
            defaults={"access_level": 0},
        )
        for field in role_fields:
            if getattr(user, field, False):
                setattr(access, field, True)
        await access.save()
        for field in role_fields:
            setattr(user, field, False)
        await user.save()
        migrated += 1

    if migrated:
        logger.info(
            "Роли перенесены в user_server_access (server_id=%s): %s пользователей",
            DEFAULT_SERVER_ID,
            migrated,
        )


async def _migrate_role_chats_per_server() -> None:
    conn = Tortoise.get_connection("default")
    rows = await conn.execute_query_dict("PRAGMA table_info(role_chats)")
    columns = {row["name"] for row in rows}
    if not columns:
        return
    if "id" in columns:
        null_server = await conn.execute_query_dict(
            "SELECT id FROM role_chats WHERE server_id IS NULL"
        )
        for row in null_server:
            await conn.execute_query(
                "UPDATE role_chats SET server_id = ? WHERE id = ?",
                [DEFAULT_SERVER_ID, row["id"]],
            )
        return

    old_rows = await conn.execute_query_dict(
        "SELECT role, peer_id, server_id, registered_by, registered_at FROM role_chats"
    )
    if not old_rows:
        return

    await conn.execute_query("ALTER TABLE role_chats RENAME TO role_chats_legacy")
    await conn.execute_query(
        """
        CREATE TABLE role_chats (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            role VARCHAR(32) NOT NULL,
            server_id INT NOT NULL REFERENCES servers(id) ON DELETE CASCADE,
            peer_id BIGINT NOT NULL,
            registered_by BIGINT,
            registered_at TIMESTAMP,
            UNIQUE(server_id, role)
        )
        """
    )
    for row in old_rows:
        server_id = row.get("server_id") or DEFAULT_SERVER_ID
        await conn.execute_query(
            """
            INSERT INTO role_chats (role, server_id, peer_id, registered_by, registered_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            [
                row["role"],
                server_id,
                row["peer_id"],
                row.get("registered_by"),
                row.get("registered_at"),
            ],
        )
    await conn.execute_query("DROP TABLE role_chats_legacy")
    logger.info(
        "role_chats мигрированы на схему per-server (%s записей)",
        len(old_rows),
    )


async def _migrate_legacy_data_to_default_server() -> None:
    """Перенос остатков старой односерверной БД на DEFAULT_SERVER_ID при старте."""
    from database.models.chat import Chat
    from database.models.moderation import ModerationLog
    from database.models.pool import Pool
    from database.models.role_chat import RoleChat
    from database.models.server import Server

    for old_id in LEGACY_SERVER_IDS:
        if old_id == DEFAULT_SERVER_ID:
            continue

        has_legacy = (
            await Server.filter(id=old_id).exists()
            or await Chat.filter(server_id=old_id).exists()
            or await Pool.filter(server_id=old_id).exists()
            or await RoleChat.filter(server_id=old_id).exists()
            or await ModerationLog.filter(server_id=old_id).exists()
            or await UserServerAccess.filter(server_id=old_id).exists()
        )
        if not has_legacy:
            continue

        merged = await ServerRepository.merge_user_server_access(
            old_id,
            DEFAULT_SERVER_ID,
        )
        await Chat.filter(server_id=old_id).update(server_id=DEFAULT_SERVER_ID)
        await Pool.filter(server_id=old_id).update(server_id=DEFAULT_SERVER_ID)
        await ModerationLog.filter(server_id=old_id).update(
            server_id=DEFAULT_SERVER_ID
        )
        await ServerRepository.remap_role_chats(old_id, DEFAULT_SERVER_ID)
        await Server.filter(id=old_id).delete()

        logger.info(
            "Legacy server_id=%s → %s (доступов слито: %s)",
            old_id,
            DEFAULT_SERVER_ID,
            merged,
        )


async def _ensure_pool_number_column() -> None:
    conn = Tortoise.get_connection("default")
    try:
        await conn.execute_query("ALTER TABLE pools ADD COLUMN number INTEGER NULL")
        logger.info("Добавлена колонка pools.number")
    except Exception:
        pass


async def _migrate_pool_numbers() -> None:
    from database.models.pool import Pool

    pools = await Pool.all().order_by("server_id", "created_at", "id")
    if not pools:
        return

    counters: dict[int, int] = {}
    migrated = 0
    for pool in pools:
        counters[pool.server_id] = counters.get(pool.server_id, 0) + 1
        expected = counters[pool.server_id]
        if pool.number != expected:
            pool.number = expected
            await pool.save()
            migrated += 1

    if migrated:
        logger.info(
            "Нумерация пулов per-server: обновлено %s из %s",
            migrated,
            len(pools),
        )


async def _ensure_ca_access_columns() -> None:
    conn = Tortoise.get_connection("default")
    for ddl in (
        "ALTER TABLE user_server_access ADD COLUMN has_ca_access INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE user_server_access ADD COLUMN ca_auto_peer_id BIGINT NULL",
    ):
        try:
            await conn.execute_query(ddl)
            logger.info("Миграция CA: %s", ddl.split("ADD COLUMN ")[1].split()[0])
        except Exception:
            pass


async def _ensure_court_form_batch_column() -> None:
    conn = Tortoise.get_connection("default")
    try:
        await conn.execute_query(
            "ALTER TABLE court_forms ADD COLUMN batch_id VARCHAR(32) NULL"
        )
        logger.info("Добавлена колонка court_forms.batch_id")
    except Exception:
        pass


async def _ensure_chat_settings_columns() -> None:
    conn = Tortoise.get_connection("default")
    for ddl in (
        "ALTER TABLE chat_peer_settings ADD COLUMN kick_on_leave VARCHAR(8) NOT NULL DEFAULT 'off'",
        "ALTER TABLE chat_peer_settings ADD COLUMN kick_on_rejoin VARCHAR(8) NOT NULL DEFAULT 'off'",
        "ALTER TABLE chat_peer_settings ADD COLUMN auto_mute_on_join VARCHAR(8) NOT NULL DEFAULT 'off'",
    ):
        try:
            await conn.execute_query(ddl)
            logger.info("Миграция chat_peer_settings: %s", ddl.split("ADD COLUMN ")[1].split()[0])
        except Exception:
            pass
    try:
        await conn.execute_query(
            """
            UPDATE chat_peer_settings
            SET kick_on_leave = rejoin_kick
            WHERE (kick_on_leave IS NULL OR kick_on_leave = 'off')
              AND rejoin_kick IS NOT NULL AND rejoin_kick != 'off'
            """
        )
        await conn.execute_query(
            """
            UPDATE chat_peer_settings
            SET kick_on_rejoin = CASE
                WHEN rejoin_kick = 'ask' THEN 'on'
                ELSE rejoin_kick
            END
            WHERE (kick_on_rejoin IS NULL OR kick_on_rejoin = 'off')
              AND rejoin_kick IS NOT NULL AND rejoin_kick != 'off'
            """
        )
    except Exception:
        pass


async def init_db() -> None:
    await Tortoise.init(config=TORTOISE_ORM)
    await Tortoise.generate_schemas(safe=True)
    await _ensure_chat_settings_columns()
    sqlite = is_sqlite_url(DATABASE_URL)
    if sqlite:
        await _ensure_chat_alias_column()
        await _ensure_congress_columns()
        await _ensure_ca_access_columns()
        await _ensure_server_nickname_column()
        await _ensure_server_role_columns()
        await _ensure_server_forum_columns()
        await _ensure_server_log_peer_column()
        await _ensure_pool_number_column()
        await _ensure_court_form_batch_column()
    await _migrate_structure_supervisor_level()
    await _bootstrap_defaults()
    if sqlite:
        await _migrate_legacy_data_to_default_server()
        await _migrate_role_chats_per_server()
    await _migrate_global_nicknames_to_servers()
    await _migrate_pool_numbers()
    await _migrate_global_roles_to_servers()
    logger.info("База данных инициализирована (%s)", "sqlite" if sqlite else "postgresql")


async def close_db() -> None:
    await Tortoise.close_connections()


async def _migrate_structure_supervisor_level() -> None:
    """Insert STRUCTURE_SUPERVISOR=5: shift old levels >=5 up by 1 (once).

    Old: 5=ЗГС ГОС … 10=Разработчик
    New: 5=Следящий структуры, 6=ЗГС ГОС … 11=Разработчик
    """
    top = await UserServerAccess.all().order_by("-access_level").first()
    if top is None:
        return
    max_level = int(top.access_level)
    if max_level >= AccessLevel.DEVELOPER:
        return
    if AccessLevel.DEVELOPER != 11:
        return

    shifted = 0
    for lvl in range(10, 4, -1):
        updated = await UserServerAccess.filter(access_level=lvl).update(access_level=lvl + 1)
        shifted += updated
    if shifted:
        logger.info(
            "Миграция уровней: +1 для access_level>=5 (вставлена «Следящий структуры»), строк=%s",
            shifted,
        )

async def _bootstrap_defaults() -> None:
    server = await ServerRepository.ensure_primary_server(
        DEFAULT_SERVER_ID,
        DEFAULT_SERVER_SLUG,
        f"Arizona №{DEFAULT_SERVER_ID}",
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
    logger.info(
        "Разработчик vk_id=%s → уровень %s на сервере %s",
        MAIN_ADMIN_ID,
        AccessLevel.DEVELOPER,
        server.slug,
    )
