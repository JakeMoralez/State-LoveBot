"""Чтение/запись panel-данных (discord_links, staff_notes) — SQLite или PostgreSQL."""

from __future__ import annotations

import asyncio
import logging
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from config.settings import BASE_DIR, PANEL_DATABASE_URL
from services.db_utils import is_postgres_url, is_sqlite_url

logger = logging.getLogger(__name__)


def _sqlite_path_from_url(url: str) -> Path | None:
    raw = (url or "").strip()
    if not is_sqlite_url(raw):
        return None
    path = raw.removeprefix("sqlite:///").removeprefix("sqlite://")
    if path.startswith("//"):
        path = path[1:]
    return Path(path)


def panel_db_path() -> Path | None:
    candidates: list[Path] = []
    from_url = _sqlite_path_from_url(PANEL_DATABASE_URL)
    if from_url:
        candidates.append(from_url)
    candidates.extend(
        [
            Path("/opt/State-Love-Admin/data/panel.db"),
            BASE_DIR.parent / "State-LoveAdmin" / "data" / "panel.db",
        ]
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def _postgres_dsn(url: str) -> str:
    """asyncpg DSN from Tortoise postgres URL."""
    raw = (url or "").strip()
    if raw.startswith("postgres://"):
        return "postgresql://" + raw[len("postgres://") :]
    return raw


async def _pg_fetchrow(query: str, *args: Any) -> Any | None:
    import asyncpg

    conn = await asyncpg.connect(_postgres_dsn(PANEL_DATABASE_URL))
    try:
        return await conn.fetchrow(query, *args)
    finally:
        await conn.close()


async def _pg_execute(query: str, *args: Any) -> None:
    import asyncpg

    conn = await asyncpg.connect(_postgres_dsn(PANEL_DATABASE_URL))
    try:
        await conn.execute(query, *args)
    finally:
        await conn.close()


def _read_staff_note_sync(vk_id: int, server_id: int) -> dict[str, str] | None:
    db_path = panel_db_path()
    if not db_path:
        return None
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        try:
            row = conn.execute(
                """
                SELECT leader_position, note, leader_note
                FROM staff_notes
                WHERE vk_id = ? AND server_id = ?
                """,
                (vk_id, server_id),
            ).fetchone()
        finally:
            conn.close()
    except Exception as exc:
        logger.debug("panel staff_notes read failed vk_id=%s: %s", vk_id, exc)
        return None
    if not row:
        return None
    return {
        "leader_position": (row[0] or "").strip(),
        "note": (row[1] or "").strip(),
        "leader_note": (row[2] or "").strip(),
    }


async def read_staff_note(vk_id: int, server_id: int) -> dict[str, str] | None:
    if is_postgres_url(PANEL_DATABASE_URL):
        try:
            row = await _pg_fetchrow(
                """
                SELECT leader_position, note, leader_note
                FROM staff_notes
                WHERE vk_id = $1 AND server_id = $2
                """,
                vk_id,
                server_id,
            )
        except Exception as exc:
            logger.debug("panel staff_notes pg read failed vk_id=%s: %s", vk_id, exc)
            return None
        if not row:
            return None
        return {
            "leader_position": (row["leader_position"] or "").strip(),
            "note": (row["note"] or "").strip(),
            "leader_note": (row["leader_note"] or "").strip(),
        }
    return await asyncio.to_thread(_read_staff_note_sync, vk_id, server_id)


def _get_discord_link_sync(vk_id: int) -> tuple[str | None, str | None, str | None]:
    db_path = panel_db_path()
    if not db_path:
        return None, None, None
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        try:
            row = conn.execute(
                """
                SELECT discord_id, discord_username, discord_display_name
                FROM discord_links WHERE vk_id = ?
                """,
                (vk_id,),
            ).fetchone()
        finally:
            conn.close()
    except Exception as exc:
        logger.debug("panel discord read failed vk=%s: %s", vk_id, exc)
        return None, None, None
    if not row or not row[0]:
        return None, None, None
    return (
        str(row[0]).strip(),
        (str(row[1]).strip() if row[1] else None),
        (str(row[2]).strip() if row[2] else None),
    )


async def get_discord_link_row(
    vk_id: int,
) -> tuple[str | None, str | None, str | None]:
    if is_postgres_url(PANEL_DATABASE_URL):
        try:
            row = await _pg_fetchrow(
                """
                SELECT discord_id, discord_username, discord_display_name
                FROM discord_links WHERE vk_id = $1
                """,
                vk_id,
            )
        except Exception as exc:
            logger.debug("panel discord pg read failed vk=%s: %s", vk_id, exc)
            return None, None, None
        if not row or not row["discord_id"]:
            return None, None, None
        return (
            str(row["discord_id"]).strip(),
            (str(row["discord_username"]).strip() if row["discord_username"] else None),
            (
                str(row["discord_display_name"]).strip()
                if row["discord_display_name"]
                else None
            ),
        )
    return await asyncio.to_thread(_get_discord_link_sync, vk_id)


def _set_discord_link_sync(
    vk_id: int,
    discord_id: str | None,
    actor_vk_id: int,
) -> tuple[bool, str]:
    db_path = panel_db_path()
    if not db_path:
        return False, "Файл panel.db не найден."

    now = datetime.now(UTC).isoformat()
    try:
        conn = sqlite3.connect(str(db_path))
        try:
            if discord_id is None:
                conn.execute("DELETE FROM discord_links WHERE vk_id = ?", (vk_id,))
                conn.commit()
                return True, ""

            other = conn.execute(
                "SELECT vk_id FROM discord_links WHERE discord_id = ? AND vk_id != ?",
                (discord_id, vk_id),
            ).fetchone()
            if other:
                return False, f"Discord ID уже привязан к VK {other[0]}"

            existing = conn.execute(
                "SELECT vk_id FROM discord_links WHERE vk_id = ?",
                (vk_id,),
            ).fetchone()
            if existing:
                conn.execute(
                    """
                    UPDATE discord_links
                    SET discord_id = ?, linked_by = ?, updated_at = ?
                    WHERE vk_id = ?
                    """,
                    (discord_id, actor_vk_id, now, vk_id),
                )
            else:
                conn.execute(
                    """
                    INSERT INTO discord_links (vk_id, discord_id, linked_by, updated_at)
                    VALUES (?, ?, ?, ?)
                    """,
                    (vk_id, discord_id, actor_vk_id, now),
                )
            conn.commit()
            return True, ""
        finally:
            conn.close()
    except Exception as exc:
        logger.warning("panel discord write failed vk=%s: %s", vk_id, exc)
        return False, "Не удалось сохранить Discord ID в panel.db."


async def set_discord_link_row(
    vk_id: int,
    discord_id: str | None,
    *,
    actor_vk_id: int,
) -> tuple[bool, str]:
    if is_postgres_url(PANEL_DATABASE_URL):
        now = datetime.now(UTC)
        try:
            if discord_id is None:
                await _pg_execute("DELETE FROM discord_links WHERE vk_id = $1", vk_id)
                return True, ""

            other = await _pg_fetchrow(
                "SELECT vk_id FROM discord_links WHERE discord_id = $1 AND vk_id != $2",
                discord_id,
                vk_id,
            )
            if other:
                return False, f"Discord ID уже привязан к VK {other['vk_id']}"

            existing = await _pg_fetchrow(
                "SELECT vk_id FROM discord_links WHERE vk_id = $1",
                vk_id,
            )
            if existing:
                await _pg_execute(
                    """
                    UPDATE discord_links
                    SET discord_id = $1, linked_by = $2, updated_at = $3
                    WHERE vk_id = $4
                    """,
                    discord_id,
                    actor_vk_id,
                    now,
                    vk_id,
                )
            else:
                await _pg_execute(
                    """
                    INSERT INTO discord_links (vk_id, discord_id, linked_by, updated_at)
                    VALUES ($1, $2, $3, $4)
                    """,
                    vk_id,
                    discord_id,
                    actor_vk_id,
                    now,
                )
            return True, ""
        except Exception as exc:
            logger.warning("panel discord pg write failed vk=%s: %s", vk_id, exc)
            return False, "Не удалось сохранить Discord ID в PostgreSQL."
    return await asyncio.to_thread(
        _set_discord_link_sync,
        vk_id,
        discord_id,
        actor_vk_id,
    )
