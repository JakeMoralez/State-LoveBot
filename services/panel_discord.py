"""Discord-привязки в panel (SQLite или PostgreSQL)."""

from __future__ import annotations

from services.panel_db import get_discord_link_row, set_discord_link_row


def normalize_discord_id(raw: str | None) -> str | None:
    if raw is None:
        return None
    value = raw.strip()
    if not value:
        return None
    if not value.isdigit() or not (17 <= len(value) <= 20):
        raise ValueError("Некорректный Discord ID")
    return value


async def get_discord_link_local(vk_id: int) -> str | None:
    discord_id, _, _ = await get_discord_link_row(vk_id)
    return discord_id


async def get_discord_profile_local(
    vk_id: int,
) -> tuple[str | None, str | None, str | None]:
    return await get_discord_link_row(vk_id)


async def set_discord_link_local(
    vk_id: int,
    discord_id: str | None,
    *,
    actor_vk_id: int | None = None,
) -> tuple[bool, str]:
    return await set_discord_link_row(
        vk_id,
        discord_id,
        actor_vk_id=actor_vk_id or vk_id,
    )
