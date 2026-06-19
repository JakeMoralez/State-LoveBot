"""HTTP-клиент к internal API панели (State-LoveAdmin)."""

from __future__ import annotations

import logging
import os

import aiohttp

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


async def get_discord_link(vk_id: int) -> str | None:
    if not panel_api_configured():
        return None
    url = f"{PANEL_INTERNAL_URL}/internal/discord-link"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                url,
                params={"vk_id": vk_id},
                headers=_headers(),
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json()
                return data.get("discord_id")
    except Exception as exc:
        logger.warning("get_discord_link vk=%s: %s", vk_id, exc)
        return None


async def set_discord_link(vk_id: int, discord_id: str | None) -> tuple[bool, str]:
    if not panel_api_configured():
        return False, "Панель не настроена (PANEL_INTERNAL_URL / SLED_BOT_SECRET)."
    url = f"{PANEL_INTERNAL_URL}/internal/discord-link"
    payload = {"vk_id": vk_id, "discord_id": discord_id}
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
                return False, str(detail or resp.reason or "Ошибка панели")
    except Exception as exc:
        logger.warning("set_discord_link vk=%s: %s", vk_id, exc)
        return False, "Не удалось связаться с панелью."
