"""Пересчёт тега в никнейме следящего после смены уровня (/setlvl)."""

from __future__ import annotations

import logging

from database.models.user import AccessLevel
from database.repository.user_repo import UserRepository
from services.panel_db import read_staff_spheres
from services.staff_nickname import (
    extract_leading_nickname_tag,
    format_staff_nickname,
    normalize_custom_tag,
    rewrite_legacy_nickname_tags,
    strip_nickname_tags,
)

logger = logging.getLogger(__name__)


async def sync_staff_nickname_tag(
    vk_id: int,
    server_id: int,
    access_level: int,
) -> str | None:
    """
    Обновить [тег] в user_server_access.nickname — как на сайте при смене уровня.
    Возвращает новый ник или None, если обновление не требовалось / не удалось.
    """
    if access_level < AccessLevel.PGS:
        return None

    current = await UserRepository.get_nickname(vk_id, server_id)
    if not current:
        return None

    clean = strip_nickname_tags(current)
    if not clean:
        return None

    spheres = await read_staff_spheres(vk_id, server_id)
    access = await UserRepository.get_server_access(vk_id, server_id)
    is_senior = bool(access and getattr(access, "is_senior", False))
    senior_spheres = list(getattr(access, "senior_spheres", []) or []) if access else []

    custom_tag: str | None = None
    if access_level >= AccessLevel.DEVELOPER:
        custom_tag = normalize_custom_tag(extract_leading_nickname_tag(current))

    try:
        formatted = format_staff_nickname(
            clean,
            access_level,
            spheres,
            custom_tag=custom_tag,
            is_senior=is_senior,
            senior_spheres=senior_spheres if is_senior else None,
        )
    except ValueError as exc:
        logger.warning("sync_staff_nickname_tag vk=%s: %s", vk_id, exc)
        return None

    formatted = rewrite_legacy_nickname_tags(formatted)
    if formatted == current:
        return formatted

    if await UserRepository.is_nickname_taken(
        server_id,
        formatted,
        exclude_vk_id=vk_id,
    ):
        logger.warning(
            "sync_staff_nickname_tag vk=%s: nick taken: %s",
            vk_id,
            formatted,
        )
        return None

    await UserRepository.set_nickname(vk_id, server_id, formatted)
    return formatted
