"""Discord-привязки в panel.db (fallback, если internal API недоступен)."""

from __future__ import annotations

import asyncio
import logging
import sqlite3
from datetime import UTC, datetime

from services.judge_display import _panel_db_path

logger = logging.getLogger(__name__)


def normalize_discord_id(raw: str | None) -> str | None:
    if raw is None:
        return None
    value = raw.strip()
    if not value:
        return None
    if not value.isdigit() or not (17 <= len(value) <= 20):
        raise ValueError("Некорректный Discord ID")
    return value


def _get_discord_link_sync(vk_id: int) -> tuple[str | None, str | None, str | None]:
    db_path = _panel_db_path()
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


def _get_discord_id_sync(vk_id: int) -> str | None:
    discord_id, _, _ = _get_discord_link_sync(vk_id)
    return discord_id


def _set_discord_link_sync(
    vk_id: int,
    discord_id: str | None,
    actor_vk_id: int,
) -> tuple[bool, str]:
    db_path = _panel_db_path()
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


async def get_discord_link_local(vk_id: int) -> str | None:
    return await asyncio.to_thread(_get_discord_id_sync, vk_id)


async def get_discord_profile_local(
    vk_id: int,
) -> tuple[str | None, str | None, str | None]:
    return await asyncio.to_thread(_get_discord_link_sync, vk_id)


async def set_discord_link_local(
    vk_id: int,
    discord_id: str | None,
    *,
    actor_vk_id: int | None = None,
) -> tuple[bool, str]:
    return await asyncio.to_thread(
        _set_discord_link_sync,
        vk_id,
        discord_id,
        actor_vk_id or vk_id,
    )
