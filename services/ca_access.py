"""Доступ ЦА: беседа следящих, авто-выдача при входе, снятие при выходе."""

from __future__ import annotations

import logging

from vkbottle import API

from database.models.role_chat import ForumRoleKey
from database.models.user import AccessLevel
from database.repository.forum_role_repo import ForumRoleRepository
from database.repository.user_repo import UserRepository
from middlewares.access import AccessChecker
from services.display_name import DisplayNameService

logger = logging.getLogger(__name__)


async def is_sled_ca_chat(peer_id: int) -> bool:
    chat = await ForumRoleRepository.get_role_chat_by_peer(peer_id)
    return chat is not None and chat.role == ForumRoleKey.SLED_CA


async def get_sled_ca_server_id(peer_id: int) -> int | None:
    chat = await ForumRoleRepository.get_role_chat_by_peer(peer_id)
    if chat and chat.role == ForumRoleKey.SLED_CA:
        return chat.server_id
    return None


def _format_sled_ca_grant_message(
    link: str,
    *,
    detail: str,
    level: int,
) -> str:
    level_name = AccessChecker.level_name(level) if level else AccessLevel.title(
        AccessLevel.PGS
    )
    granted_level = "ур." in detail or "ПГС" in detail
    granted_ca = "доступ ЦА" in detail

    if granted_level and granted_ca:
        return (
            f"🎩 {link} получил уровень {level_name}［D:{level}］ и доступ к ЦА."
        )
    if granted_level:
        return f"🎩 {link} получил уровень {level_name}［D:{level}］."
    if granted_ca:
        return f"🎩 {link} получил доступ к ЦА."
    return f"🎩 {link} получил доступ к ЦА."


async def handle_sled_ca_join(peer_id: int, user_id: int, api: API) -> str | None:
    if user_id <= 0 or peer_id < 2_000_000_000:
        return None
    server_id = await get_sled_ca_server_id(peer_id)
    if not server_id:
        return None

    await UserRepository.ensure_user(vk_id=user_id)
    changed, detail = await UserRepository.grant_sled_ca_from_chat(
        user_id, server_id, peer_id
    )
    if not changed:
        return None

    names = DisplayNameService(api, server_id)
    link = await names.link_user(user_id, server_id)
    level = await UserRepository.get_access_level(user_id, server_id)
    message = _format_sled_ca_grant_message(link, detail=detail, level=level)
    logger.info(
        "sled_ca join granted vk_id=%s peer=%s server=%s: %s",
        user_id,
        peer_id,
        server_id,
        message,
    )
    return message


async def handle_sled_ca_leave(peer_id: int, user_id: int, api: API) -> str | None:
    if user_id <= 0 or peer_id < 2_000_000_000:
        return None
    server_id = await get_sled_ca_server_id(peer_id)
    if not server_id:
        return None

    changed, detail = await UserRepository.revoke_sled_ca_from_chat(
        user_id, server_id, peer_id
    )
    if not changed:
        return None

    link = await DisplayNameService(api, server_id).link_user(user_id, server_id)
    logger.info(
        "sled_ca leave revoked vk_id=%s peer=%s server=%s: %s",
        user_id,
        peer_id,
        server_id,
        detail,
    )
    return f"🔰 {link} — снят {detail} (выход из беседы след. ЦА)."
