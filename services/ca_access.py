"""Доступ ЦА: беседа следящих, авто-выдача при входе, снятие при выходе."""

from __future__ import annotations

import logging

from vkbottle import API

from database.models.role_chat import ForumRoleKey
from database.repository.forum_role_repo import ForumRoleRepository
from database.repository.user_repo import UserRepository
from middlewares.access import AccessChecker
from services.display_name import DisplayNameService

logger = logging.getLogger(__name__)


async def is_sled_ca_chat(peer_id: int) -> bool:
    role = await ForumRoleRepository.find_role_by_peer(peer_id)
    return role == ForumRoleKey.SLED_CA


async def handle_sled_ca_join(peer_id: int, user_id: int, api: API) -> str | None:
    if user_id <= 0 or peer_id < 2_000_000_000:
        return None
    if not await is_sled_ca_chat(peer_id):
        return None

    server_id = await AccessChecker.resolve_server_id(peer_id)
    await UserRepository.ensure_user(vk_id=user_id)
    changed, detail = await UserRepository.grant_sled_ca_from_chat(
        user_id, server_id, peer_id
    )
    if not changed:
        return None

    link = await DisplayNameService(api).link_user(user_id)
    logger.info("sled_ca join granted vk_id=%s peer=%s: %s", user_id, peer_id, detail)
    return f"✅ {link} — выдан {detail} (беседа след. ЦА)."


async def handle_sled_ca_leave(peer_id: int, user_id: int, api: API) -> str | None:
    if user_id <= 0 or peer_id < 2_000_000_000:
        return None
    if not await is_sled_ca_chat(peer_id):
        return None

    server_id = await AccessChecker.resolve_server_id(peer_id)
    changed, detail = await UserRepository.revoke_sled_ca_from_chat(
        user_id, server_id, peer_id
    )
    if not changed:
        return None

    link = await DisplayNameService(api).link_user(user_id)
    logger.info("sled_ca leave revoked vk_id=%s peer=%s: %s", user_id, peer_id, detail)
    return f"🔰 {link} — снят {detail} (выход из беседы след. ЦА)."
