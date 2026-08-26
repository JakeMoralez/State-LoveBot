"""HTTP-клиент к internal API панели (State-LoveAdmin)."""

from __future__ import annotations

import logging
import os

from dataclasses import dataclass

import aiohttp

from services.panel_discord import (
    get_discord_link_local,
    get_discord_profile_local,
    normalize_discord_id,
    set_discord_link_local,
)

logger = logging.getLogger(__name__)

SLED_BOT_SECRET = os.getenv("SLED_BOT_SECRET", "")
PANEL_INTERNAL_URL = os.getenv(
    "PANEL_INTERNAL_URL",
    "http://127.0.0.1:8000",
).rstrip("/")


def panel_api_configured() -> bool:
    return bool(SLED_BOT_SECRET and PANEL_INTERNAL_URL)


def _headers() -> dict[str, str]:
    return {"X-Sled-Secret": SLED_BOT_SECRET}


@dataclass(frozen=True)
class DiscordProfile:
    discord_id: str | None
    discord_username: str | None = None
    discord_display_name: str | None = None


async def get_discord_profile(vk_id: int) -> DiscordProfile | None:
    if panel_api_configured():
        url = f"{PANEL_INTERNAL_URL}/internal/discord-link"
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    url,
                    params={"vk_id": vk_id},
                    headers=_headers(),
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        discord_id = data.get("discord_id")
                        if not discord_id:
                            return None
                        return DiscordProfile(
                            discord_id=str(discord_id).strip(),
                            discord_username=data.get("discord_username"),
                            discord_display_name=data.get("discord_display_name"),
                        )
        except Exception as exc:
            logger.warning("get_discord_profile API vk=%s: %s", vk_id, exc)

    discord_id, username, display_name = await get_discord_profile_local(vk_id)
    if not discord_id:
        return None
    return DiscordProfile(
        discord_id=discord_id,
        discord_username=username,
        discord_display_name=display_name,
    )


async def get_discord_link(vk_id: int) -> str | None:
    profile = await get_discord_profile(vk_id)
    return profile.discord_id if profile else None


async def set_discord_link(vk_id: int, discord_id: str | None) -> tuple[bool, str]:
    try:
        normalized = normalize_discord_id(discord_id)
    except ValueError as exc:
        return False, str(exc)

    if panel_api_configured():
        url = f"{PANEL_INTERNAL_URL}/internal/discord-link"
        payload = {"vk_id": vk_id, "discord_id": normalized}
        try:
            async with aiohttp.ClientSession() as session:
                async with session.put(
                    url,
                    json=payload,
                    headers=_headers(),
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    data = await resp.json(content_type=None)
                    if resp.status == 200:
                        return True, ""
                    detail = data.get("detail") if isinstance(data, dict) else None
                    if isinstance(detail, list):
                        detail = detail[0].get("msg") if detail else None
                    api_err = str(detail or resp.reason or "Ошибка панели")
                    logger.warning(
                        "set_discord_link API vk=%s status=%s: %s",
                        vk_id,
                        resp.status,
                        api_err,
                    )
        except Exception as exc:
            logger.warning("set_discord_link API vk=%s: %s", vk_id, exc)

    return await set_discord_link_local(vk_id, normalized, actor_vk_id=vk_id)


async def sync_staff_spheres(
    vk_id: int,
    *,
    grant_central_apparatus: bool,
    server_id: int | None = None,
) -> tuple[bool, str]:
    if not panel_api_configured():
        return True, ""
    url = f"{PANEL_INTERNAL_URL}/internal/staff-spheres/{vk_id}"
    payload: dict = {"grant_central_apparatus": grant_central_apparatus}
    params = {}
    if server_id is not None:
        params["server_id"] = server_id
    try:
        async with aiohttp.ClientSession() as session:
            async with session.put(
                url,
                json=payload,
                params=params,
                headers=_headers(),
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status == 200:
                    return True, ""
                data = await resp.json(content_type=None)
                detail = data.get("detail") if isinstance(data, dict) else None
                return False, str(detail or resp.reason or "Ошибка панели")
    except Exception as exc:
        logger.warning("sync_staff_spheres vk=%s: %s", vk_id, exc)
        return False, "Не удалось связаться с панелью."


async def set_staff_spheres_via_panel(
    *,
    actor_vk_id: int,
    server_id: int,
    vk_id: int,
    spheres: list[str],
    is_senior: bool | None = None,
    senior_spheres: list[str] | None = None,
) -> tuple[bool, dict | str]:
    """PUT /internal/staff-spheres/{vk_id} — обновление сфер и старшего статуса."""
    if not panel_api_configured():
        return False, "Панель не настроена"

    url = f"{PANEL_INTERNAL_URL}/internal/staff-spheres/{vk_id}"
    payload: dict[str, object] = {
        "actor_vk_id": actor_vk_id,
        "spheres": spheres,
    }
    if is_senior is not None:
        payload["is_senior"] = is_senior
    if senior_spheres is not None:
        payload["senior_spheres"] = senior_spheres
    try:
        async with aiohttp.ClientSession() as session:
            async with session.put(
                url,
                json=payload,
                params={"server_id": server_id},
                headers=_headers(),
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                data = await resp.json(content_type=None)
                if resp.status == 200 and isinstance(data, dict):
                    return True, data
                detail = data.get("detail") if isinstance(data, dict) else None
                if isinstance(detail, list):
                    detail = detail[0].get("msg") if detail else None
                return False, str(detail or resp.reason or "Ошибка панели")
    except Exception as exc:
        logger.warning("set_staff_spheres_via_panel vk=%s: %s", vk_id, exc)
        return False, "Не удалось связаться с панелью."


async def assign_staff_via_panel(
    *,
    actor_vk_id: int,
    server_id: int,
    vk_id: int,
    nickname: str,
    access_level: int,
    spheres: list[str],
    forum_account: str,
    discord_id: str,
) -> tuple[bool, dict | str]:
    """POST /internal/staff-assign — назначение следящего с сайта."""
    if not panel_api_configured():
        return False, "Панель не настроена"

    url = f"{PANEL_INTERNAL_URL}/internal/staff-assign"
    payload = {
        "actor_vk_id": actor_vk_id,
        "vk_id": vk_id,
        "nickname": nickname.strip(),
        "access_level": access_level,
        "spheres": spheres,
        "forum_account": forum_account.strip(),
        "discord_id": discord_id.strip(),
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                url,
                json=payload,
                params={"server_id": server_id},
                headers=_headers(),
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                data = await resp.json(content_type=None)
                if resp.status == 200 and isinstance(data, dict):
                    return True, data
                detail = data.get("detail") if isinstance(data, dict) else None
                if isinstance(detail, list):
                    detail = detail[0].get("msg") if detail else None
                return False, str(detail or resp.reason or "Ошибка панели")
    except Exception as exc:
        logger.warning("assign_staff_via_panel vk=%s: %s", vk_id, exc)
        return False, "Не удалось связаться с панелью."
