"""Лидеры руководства ЦА: авто-флаг is_leader при входе в беседу."""

from __future__ import annotations

import logging

from vkbottle import API

from database.models.role_chat import ForumRoleKey
from database.repository.forum_role_repo import ForumRoleRepository
from database.repository.user_repo import UserRepository
from services.display_name import DisplayNameService

logger = logging.getLogger(__name__)


async def get_leader_chat_server_id(peer_id: int) -> int | None:
    chat = await ForumRoleRepository.get_role_chat_by_peer(peer_id)
    if chat and chat.role == ForumRoleKey.LEADER:
        return chat.server_id
    return None


async def handle_leader_chat_join(peer_id: int, user_id: int, api: API) -> str | None:
    """Выдаёт is_leader без сообщения в беседу (только лог)."""
    if user_id <= 0 or peer_id < 2_000_000_000:
        return None
    server_id = await get_leader_chat_server_id(peer_id)
    if not server_id:
        return None

    await UserRepository.ensure_user(vk_id=user_id)
    changed, _detail = await UserRepository.grant_leader_from_chat(user_id, server_id)
    if not changed:
        return None

    badge = await DisplayNameService(api, server_id).format_actor_badge(
        user_id,
        server_id,
    )
    logger.info(
        "leader join granted vk_id=%s peer=%s server=%s: 🛡 %s — лидер (беседа руководства ЦА).",
        user_id,
        peer_id,
        server_id,
        badge,
    )
    return None
