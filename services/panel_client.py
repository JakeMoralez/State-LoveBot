"""HTTP-клиент к internal API панели (State-LoveAdmin)."""

from __future__ import annotations

import logging
import os

from dataclasses import dataclass

import aiohttp

from services.http_session import get_http_session
from services.panel_discord import (
    get_discord_link_local,
    get_discord_profile_local,
    normalize_discord_id,
    set_discord_link_local,
)
from services.request_id import REQUEST_ID_HEADER, get_or_create_request_id

logger = logging.getLogger(__name__)

SLED_BOT_SECRET = os.getenv("SLED_BOT_SECRET", "")
PANEL_INTERNAL_URL = os.getenv(
    "PANEL_INTERNAL_URL",
    "http://127.0.0.1:8000",
).rstrip("/")


def panel_api_configured() -> bool:
    return bool(SLED_BOT_SECRET and PANEL_INTERNAL_URL)


def _headers() -> dict[str, str]:
    return {
        "X-Sled-Secret": SLED_BOT_SECRET,
        REQUEST_ID_HEADER: get_or_create_request_id(),
    }


def _panel_detail(data: object, fallback: str = "Ошибка панели") -> str:
    if not isinstance(data, dict):
        return fallback
    detail = data.get("detail")
    if isinstance(detail, str) and detail.strip():
        return detail.strip()
    if isinstance(detail, list) and detail:
        first = detail[0]
        if isinstance(first, dict):
            return str(first.get("msg") or first.get("message") or fallback)
        return str(first)
    if isinstance(detail, dict):
        return str(detail.get("msg") or detail.get("message") or fallback)
    return fallback


def _panel_unreachable() -> str:
    return (
        "Не удалось связаться с панелью. "
        "Проверьте PANEL_INTERNAL_URL (локально панель часто на порту 8013)."
    )


@dataclass(frozen=True)
class DiscordProfile:
    discord_id: str | None
    discord_username: str | None = None
    discord_display_name: str | None = None


async def get_discord_profile(vk_id: int) -> DiscordProfile | None:
    if panel_api_configured():
        url = f"{PANEL_INTERNAL_URL}/internal/discord-link"
        try:
            session = await get_http_session()
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
            session = await get_http_session()
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


async def sync_staff_sphere(
    vk_id: int,
    sphere: str,
    *,
    grant: bool,
    server_id: int | None = None,
) -> tuple[bool, str]:
    """Системный sync одной сферы (беседа следящих) — без actor hierarchy."""
    if not panel_api_configured():
        return True, ""
    url = f"{PANEL_INTERNAL_URL}/internal/staff-spheres/{vk_id}"
    payload: dict = {"grant_sphere": sphere} if grant else {"revoke_sphere": sphere}
    params = {}
    if server_id is not None:
        params["server_id"] = server_id
    try:
        session = await get_http_session()
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
        logger.warning("sync_staff_sphere vk=%s %s: %s", vk_id, sphere, exc)
        return False, "Не удалось связаться с панелью."


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
        session = await get_http_session()
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


async def fetch_staff_spheres(vk_id: int, server_id: int) -> list[str] | None:
    """GET /internal/staff-spheres/{vk_id} — spheres SoT на панели.

    Returns None если панель недоступна / не настроена (caller решает fallback).
    """
    if not panel_api_configured():
        return None
    url = f"{PANEL_INTERNAL_URL}/internal/staff-spheres/{vk_id}"
    try:
        session = await get_http_session()
        async with session.get(
            url,
            params={"server_id": server_id},
            headers=_headers(),
            timeout=aiohttp.ClientTimeout(total=10),
        ) as resp:
            if resp.status != 200:
                logger.warning(
                    "fetch_staff_spheres vk=%s status=%s", vk_id, resp.status
                )
                return None
            data = await resp.json(content_type=None)
            if not isinstance(data, dict):
                return None
            raw = data.get("spheres") or []
            if not isinstance(raw, list):
                return None
            return [str(x).strip() for x in raw if str(x).strip()]
    except Exception as exc:
        logger.warning("fetch_staff_spheres vk=%s: %s", vk_id, exc)
        return None


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
        session = await get_http_session()
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


async def revoke_staff_via_panel(
    *,
    actor_vk_id: int,
    server_id: int,
    vk_id: int,
) -> tuple[bool, str]:
    """POST /internal/staff-revoke/{vk_id} — полное снятие доступа следящего."""
    if not panel_api_configured():
        return False, "Панель не настроена"

    url = f"{PANEL_INTERNAL_URL}/internal/staff-revoke/{vk_id}"
    try:
        session = await get_http_session()
        async with session.post(
            url,
            json={"actor_vk_id": actor_vk_id},
            params={"server_id": server_id},
            headers=_headers(),
            timeout=aiohttp.ClientTimeout(total=10),
        ) as resp:
            data = await resp.json(content_type=None)
            if resp.status == 200 and isinstance(data, dict) and data.get("ok"):
                return True, "ok"
            detail = data.get("detail") if isinstance(data, dict) else None
            if isinstance(detail, list):
                detail = detail[0].get("msg") if detail else None
            return False, str(detail or resp.reason or "Ошибка панели")
    except Exception as exc:
        logger.warning("revoke_staff_via_panel vk=%s: %s", vk_id, exc)
        return False, "Не удалось связаться с панелью."


async def remove_sphere_on_poolkick_via_panel(
    *,
    actor_vk_id: int,
    server_id: int,
    vk_id: int,
    sphere: str,
) -> tuple[bool, dict | str]:
    """POST /internal/staff-sphere-remove/{vk_id} — снять одну сферу после poolkick."""
    if not panel_api_configured():
        return False, "Панель не настроена"

    url = f"{PANEL_INTERNAL_URL}/internal/staff-sphere-remove/{vk_id}"
    try:
        session = await get_http_session()
        async with session.post(
            url,
            json={"actor_vk_id": actor_vk_id, "sphere": sphere},
            params={"server_id": server_id},
            headers=_headers(),
            timeout=aiohttp.ClientTimeout(total=10),
        ) as resp:
            data = await resp.json(content_type=None)
            if resp.status == 200 and isinstance(data, dict) and data.get("ok"):
                return True, data
            detail = data.get("detail") if isinstance(data, dict) else None
            if isinstance(detail, list):
                detail = detail[0].get("msg") if detail else None
            return False, str(detail or resp.reason or "Ошибка панели")
    except Exception as exc:
        logger.warning("remove_sphere_on_poolkick vk=%s: %s", vk_id, exc)
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
        session = await get_http_session()
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


async def academy_me(vk_id: int, server_id: int) -> tuple[bool, dict | str]:
    if not panel_api_configured():
        return False, "Панель не настроена"
    url = f"{PANEL_INTERNAL_URL}/internal/academy/me/{vk_id}"
    try:
        session = await get_http_session()
        async with session.get(
            url,
            params={"server_id": server_id},
            headers=_headers(),
            timeout=aiohttp.ClientTimeout(total=12),
        ) as resp:
            data = await resp.json(content_type=None)
            if resp.status == 200 and isinstance(data, dict):
                return True, data
            return False, _panel_detail(data, resp.reason or "Ошибка панели")
    except Exception as exc:
        logger.warning("academy_me vk=%s: %s", vk_id, exc)
        return False, _panel_unreachable()


async def academy_student(actor_vk_id: int, vk_id: int, server_id: int) -> tuple[bool, dict | str]:
    if not panel_api_configured():
        return False, "Панель не настроена"
    url = f"{PANEL_INTERNAL_URL}/internal/academy/student/{vk_id}"
    try:
        session = await get_http_session()
        async with session.get(
            url,
            params={"actor_vk_id": actor_vk_id, "server_id": server_id},
            headers=_headers(),
            timeout=aiohttp.ClientTimeout(total=12),
        ) as resp:
            data = await resp.json(content_type=None)
            if resp.status == 200 and isinstance(data, dict):
                return True, data
            return False, _panel_detail(data, resp.reason or "Ошибка панели")
    except Exception as exc:
        logger.warning("academy_student vk=%s: %s", vk_id, exc)
        return False, _panel_unreachable()


async def academy_leaderboard(actor_vk_id: int, server_id: int) -> tuple[bool, dict | str]:
    if not panel_api_configured():
        return False, "Панель не настроена"
    url = f"{PANEL_INTERNAL_URL}/internal/academy/leaderboard"
    try:
        session = await get_http_session()
        async with session.get(
            url,
            params={"actor_vk_id": actor_vk_id, "server_id": server_id},
            headers=_headers(),
            timeout=aiohttp.ClientTimeout(total=12),
        ) as resp:
            data = await resp.json(content_type=None)
            if resp.status == 200 and isinstance(data, dict):
                return True, data
            return False, _panel_detail(data, resp.reason or "Ошибка панели")
    except Exception as exc:
        logger.warning("academy_leaderboard actor=%s: %s", actor_vk_id, exc)
        return False, _panel_unreachable()


async def academy_submit_report(
    actor_vk_id: int,
    assignment_id: int,
    server_id: int,
    body: str,
    proof_urls: list[str] | None = None,
) -> tuple[bool, dict | str]:
    if not panel_api_configured():
        return False, "Панель не настроена"
    url = f"{PANEL_INTERNAL_URL}/internal/academy/report"
    try:
        session = await get_http_session()
        async with session.post(
            url,
            json={
                "actor_vk_id": actor_vk_id,
                "assignment_id": assignment_id,
                "body": body,
                "proof_urls": proof_urls or [],
            },
            params={"server_id": server_id},
            headers=_headers(),
            timeout=aiohttp.ClientTimeout(total=15),
        ) as resp:
            data = await resp.json(content_type=None)
            if resp.status == 200 and isinstance(data, dict) and data.get("ok"):
                return True, data
            return False, _panel_detail(data, resp.reason or "Ошибка панели")
    except Exception as exc:
        logger.warning("academy_submit actor=%s: %s", actor_vk_id, exc)
        return False, _panel_unreachable()


async def create_issuance(
    actor_vk_id: int,
    server_id: int,
    *,
    kind: str,
    nickname: str,
    amount: str | int,
    role_title: str,
    reason: str,
    proof_url: str = "",
) -> tuple[bool, dict | str]:
    if not panel_api_configured():
        return False, "Панель не настроена"
    url = f"{PANEL_INTERNAL_URL}/internal/issuance"
    try:
        session = await get_http_session()
        async with session.post(
            url,
            json={
                "actor_vk_id": actor_vk_id,
                "kind": kind,
                "nickname": nickname,
                "amount": amount,
                "role_title": role_title,
                "reason": reason,
                "proof_url": proof_url,
            },
            params={"server_id": server_id},
            headers=_headers(),
            timeout=aiohttp.ClientTimeout(total=15),
        ) as resp:
            data = await resp.json(content_type=None)
            if resp.status == 200 and isinstance(data, dict) and data.get("ok"):
                return True, data
            return False, _panel_detail(data, resp.reason or "Ошибка панели")
    except Exception as exc:
        logger.warning("create_issuance actor=%s: %s", actor_vk_id, exc)
        return False, _panel_unreachable()


async def report_bot_error(
    *,
    message: str,
    stack: str = "",
    level: str = "error",
    user_vk_id: int | None = None,
    url: str = "",
    context: dict | None = None,
) -> None:
    """POST /internal/errors — писать необработанные ошибки бота в DevErrorLog панели."""
    if not panel_api_configured():
        return
    url_path = f"{PANEL_INTERNAL_URL}/internal/errors"
    payload = {
        "level": level,
        "message": (message or "")[:4000] or "(empty)",
        "stack": (stack or "")[:12000],
        "url": (url or "")[:2048],
        "method": "",
        "user_vk_id": user_vk_id,
        "context": context or {},
    }
    try:
        session = await get_http_session()
        async with session.post(
            url_path,
            json=payload,
            headers=_headers(),
            timeout=aiohttp.ClientTimeout(total=8),
        ) as resp:
            if resp.status >= 400:
                logger.debug(
                    "report_bot_error status=%s body=%s",
                    resp.status,
                    (await resp.text())[:200],
                )
    except Exception as exc:
        logger.debug("report_bot_error failed: %s", exc)
